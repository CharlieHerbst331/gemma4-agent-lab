import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from gemma_lab.metrics import load_results, summary
from gemma_lab.operations import check_evaluation
from gemma_lab.paired import (
    abort_code,
    build_projection,
    build_schedule,
    clean_stray_sandboxes,
    collect_live_sandbox_names,
    early_stop_loser,
    execute_session,
    kill_process_group,
    projection_for_arm,
    release_server_after_stop,
    repeat_is_valid,
    round2_scenario_seconds,
    start_model_server,
    summarize_pair_run,
    timing_from_context,
    timing_from_trace,
    token_fields,
    trace_artifact_stem,
    write_trace_artifact,
)


class Task:
    def __init__(self, instance_id, repo="example/repo"):
        self.instance_id = instance_id
        self.repo = repo


class Result:
    def __init__(
        self, resolved=False, error_message=None, test_output="", patch="diff\n", trace=None
    ):
        self.resolved = resolved
        self.error_message = error_message
        self.test_output = test_output
        self.agent_patch = patch
        self.test_exit_code = 0
        self.tool_calls = 2
        self.duration_seconds = 3.0
        self.trace = trace

    def model_dump(self):
        return {
            "resolved": self.resolved,
            "agent_patch": self.agent_patch,
            "error_message": self.error_message,
            "test_output": self.test_output,
        }


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value


def arm_meta(tmp_path, label, sha):
    root = tmp_path / label
    root.mkdir()
    (root / "agent.yaml").write_text(f"name: {label}\n")
    digest = hashlib.sha256((root / "agent.yaml").read_bytes()).hexdigest()
    return {"sha256": sha, "root": root, "files": {"agent.yaml": digest}}


def run_session(tmp_path, ids, run_evaluate, **kwargs):
    schedule = build_schedule(ids, repeats=kwargs.pop("repeats", 1))
    session_repeats = kwargs.pop("session_repeats", (1,))
    arms = {
        "A": arm_meta(tmp_path, "A", "a" * 64),
        "B": arm_meta(tmp_path, "B", "b" * 64),
    }
    built = []

    def rebuild(label, repeat):
        built.append((label, repeat))
        return label

    result = execute_session(
        schedule=[entry for entry in schedule["entries"] if entry["repeat"] in session_repeats],
        tasks={task_id: Task(task_id) for task_id in ids},
        rebuild=rebuild,
        run_evaluate=run_evaluate,
        output_dir=tmp_path / "run",
        arms=arms,
        schedule_sha256=schedule["sha256"],
        cap_seconds=kwargs.pop("cap_seconds", 60),
        session_budget_seconds=kwargs.pop("session_budget_seconds", 10**9),
        clock=kwargs.pop("clock", Clock()),
        session_start=0,
        **kwargs,
    )
    result["built"] = built
    result["arms"] = arms
    result["schedule"] = schedule
    return result


def test_crash_isolates_the_arm_and_drops_the_pair(tmp_path):
    def run_evaluate(evaluator, task, dashboard, position, total):
        if evaluator == "A" and task.instance_id == "t3":
            raise RuntimeError("boom")
        return Result(resolved=True, patch="patch\n")

    outcome = run_session(tmp_path, ["t1", "t2", "t3"], run_evaluate)
    rows = outcome["rows"]
    crashed = [row for row in rows if row["task_id"] == "t3" and row["arm"] == "A"]
    other = [row for row in rows if row["task_id"] == "t3" and row["arm"] == "B"]
    assert crashed and crashed[0]["failure_class"] == "infrastructure_or_harness"
    assert crashed[0]["crashed"] is True
    assert other and other[0]["resolved"] is True
    assert outcome["built"].count(("A", 1)) >= 2
    dropped = outcome["report"]["paired"]["dropped_for_infra"]
    assert {"repeat": 1, "task_id": "t3"} in dropped
    raw = outcome["report"]["raw_totals"]["A"]["rows"]
    assert raw == 3
    text = (tmp_path / "run" / "pair_results.jsonl").read_text()
    assert "boom" in text


def test_kernel_death_keeps_fsynced_rows(tmp_path):
    def run_evaluate(evaluator, task, dashboard, position, total):
        return Result(resolved=False, patch="p\n")

    def after(row):
        if row["task_id"] == "t5" and row["arm"] == "A":
            raise SystemExit(1)

    ids = [f"t{index}" for index in range(1, 6)]
    with pytest.raises(SystemExit):
        run_session(tmp_path, ids, run_evaluate, after_row=after)
    lines = (tmp_path / "run" / "pair_results.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    done = {(row["task_id"], row["arm"]) for row in rows}
    assert all((f"t{index}", arm) in done for index in range(1, 5) for arm in ("A", "B"))
    assert ("t5", "A") in done
    assert ("t5", "B") not in done
    assert not (tmp_path / "run" / "projection.json").exists()


def test_one_server_restart_then_abort(tmp_path):
    checks = {"n": 0}
    restarts = []

    def health():
        checks["n"] += 1
        if checks["n"] == 1:
            return False
        if checks["n"] == 2:
            return True
        return False

    def restart():
        restarts.append(1)
        return 4.0

    def run_evaluate(evaluator, task, dashboard, position, total):
        return Result(resolved=True)

    outcome = run_session(
        tmp_path,
        ["t1", "t2"],
        run_evaluate,
        health=health,
        restart_server=restart,
    )
    assert restarts == [1]
    assert outcome["status"] == "aborted:model_server"
    unhealthy = [row for row in outcome["rows"] if row["error"] == "model_server_unhealthy"]
    assert len(unhealthy) == 2
    assert unhealthy[0]["post_restart"] is True
    assert all(row["post_restart"] for row in outcome["rows"])


def test_abort_rules_validity_and_early_stop(tmp_path):
    cap = 60
    assert abort_code([{"wall_seconds": cap + 121}], cap, "A") == "aborted:budget_anomaly"
    infra = {"failure_class": "infrastructure_or_harness", "wall_seconds": 1}
    assert abort_code([infra, infra], cap, "A") == "aborted:infra"
    schema = [
        {"patch_chars": 0, "error": "invalid tool schema", "wall_seconds": 1} for _ in range(4)
    ]
    assert abort_code(schema, cap, "B") == "aborted_arm:B"
    window = [
        {"patch_chars": 3, "test_output": "Context window exceeded", "wall_seconds": 1}
        for _ in range(4)
    ]
    window[2]["test_output"] = "ok"
    window[3]["test_output"] = "maximum context"
    assert abort_code(window, cap, "A") == "aborted_arm:A"
    assert repeat_is_valid(12, 13) is True
    assert repeat_is_valid(11, 13) is False

    ids = [f"t{index:02d}" for index in range(13)]

    def run_evaluate(evaluator, task, dashboard, position, total):
        resolved = evaluator == "B" and task.instance_id in {"t00", "t01", "t02"}
        return Result(resolved=resolved, patch="p\n")

    outcome = run_session(
        tmp_path,
        ids,
        run_evaluate,
        early_stop="round2",
        repeats=2,
        session_repeats=(1, 2),
    )
    assert outcome["status"] == "early_stopped:A"
    assert outcome["validity"]["A"]["1"]["valid"] is True
    later = [row for row in outcome["rows"] if row["repeat"] == 2]
    assert later and all(row["arm"] == "B" for row in later)
    loser_rows = {
        "A": [{"resolved": False}] * 13,
        "B": [{"resolved": True}] * 3 + [{"resolved": False}] * 10,
    }
    assert early_stop_loser(loser_rows, 13) == "A"


def test_budget_guard_lists_unrun_pairs(tmp_path):
    clock = Clock(0)

    def run_evaluate(evaluator, task, dashboard, position, total):
        return Result(resolved=False, patch="p\n")

    def after(row):
        if row["task_id"] == "t1" and row["arm"] == "B":
            clock.value = 100000

    outcome = run_session(
        tmp_path,
        ["t1", "t2", "t3"],
        run_evaluate,
        clock=clock,
        cap_seconds=100,
        session_budget_seconds=1000,
        pair_pad_seconds=60,
        after_row=after,
    )
    assert outcome["status"] == "truncated_by_budget"
    unrun = [(item["task_id"], item["repeat"]) for item in outcome["unrun"]]
    assert unrun == [("t2", 1), ("t3", 1)]
    manifest = json.loads((tmp_path / "run" / "pair_manifest.json").read_text())
    assert manifest["unrun_pairs"][0]["task_id"] == "t2"


def test_timing_tiers_and_projection_math():
    class Context:
        task_start_time = 10.0
        agent_start_time = 12.0
        agent_end_time = 40.0
        agent_elapsed_seconds = 28.0
        llm_calls_used = 4

    timing = timing_from_context(Context(), wall_seconds=50, cap_seconds=30, pre_call_overhead=1)
    assert timing["timing_tier"] == 2
    assert timing["setup_seconds"] == 2
    assert timing["agent_seconds"] == 28
    assert timing["grading_seconds"] == 50 - (40 - 10) - 1

    class Entry:
        def __init__(self, timestamp):
            self.timestamp = timestamp

    class Trace:
        entries = [Entry(100.0), Entry(130.0)]

        def summarize(self):
            return {"total_prompt_tokens": 5, "total_tokens": 9}

    traced = timing_from_trace(40, 90, 150, Trace(), 30)
    assert traced["timing_source"] == "trace"
    assert traced["setup_seconds"] == 10
    assert traced["agent_seconds"] == 30
    assert token_fields(Trace())["total_completion_tokens"] is None
    assert token_fields(None)["total_tokens"] is None
    assert token_fields(Trace())["total_prompt_tokens"] == 5

    heavy = round2_scenario_seconds(900, 129, 0.8, 270, 30)
    assert abs(heavy / 3600 - 10.2) < 0.05
    quiet = projection_for_arm(
        [{"wall_seconds": 10, "hit_cap": {"wall": False, "marker": False}}] * 3
        + [{"wall_seconds": 800, "hit_cap": {"wall": True, "marker": False}}],
        arm_sha256="a" * 64,
        cap_seconds=10,
        model_load_seconds=900,
        session_overhead_seconds=None,
    )
    assert quiet["checks"]["worst_case_12h_n129"]["passed"] is False
    assert quiet["checks"]["round2_load_plus_129_mean"]["passed"] is True
    assert quiet["checks"]["coordinator_mean_times_120"]["passed"] is True
    assert quiet["blocked"] is False
    blocked = build_projection(
        [{"arm": "A", "wall_seconds": 400, "hit_cap": {}}],
        {"A": {"sha256": "a" * 64}, "B": {"sha256": "b" * 64}},
        60,
        900,
        None,
    )
    assert blocked["blocked"] is True


class Trace:
    def __init__(self):
        self.kind = "atif"
        self.self_ref = self

    def summarize(self):
        return {"total_tokens": 3, "llm_calls": 1}


def test_single_arm_schema_and_check_evaluation(tmp_path):
    def run_evaluate(evaluator, task, dashboard, position, total):
        dashboard.attach_context(
            0,
            type(
                "C",
                (),
                {
                    "task_start_time": 0,
                    "agent_start_time": 1,
                    "agent_end_time": 2,
                    "agent_elapsed_seconds": 1,
                    "llm_calls_used": 1,
                },
            )(),
        )
        return Result(resolved=True, patch="abc\n", trace=Trace())

    outcome = run_session(tmp_path, ["t1"], run_evaluate, requested_tier=2, model_load_seconds=12.5)
    row = outcome["rows"][0]
    single_path = tmp_path / "run" / "results" / "A" / "r1" / "task_results.jsonl"
    single = json.loads(single_path.read_text())
    for key, value in single.items():
        assert row[key] == value
    details = json.loads((tmp_path / "run" / "results" / "A" / "r1" / "t1.json").read_text())
    assert details["agent_patch"] == "abc\n"
    loaded = load_results(tmp_path / "run" / "results" / "A" / "r1" / "task_results.jsonl")
    assert summary(loaded)["resolved"] == 1
    archive = tmp_path / "submission.zip"
    archive.write_bytes(b"pinned-bytes")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    folder = tmp_path / "run" / "results" / "A" / "r1"
    manifest = json.loads((folder / "run_manifest.json").read_text())
    other_path = tmp_path / "run" / "results" / "B" / "r1" / "run_manifest.json"
    other = json.loads(other_path.read_text())
    assert manifest["model_load_seconds"] == 12.5
    assert other["model_load_seconds"] == 12.5
    trace = json.loads((folder / "traces" / "trace_t1.raw.json").read_text())
    assert trace["kind"] == "atif"
    assert trace["self_ref"] == "<cycle>"
    assert not (folder / "traces" / "trace_t1.json").exists()
    assert (folder / "task_results.jsonl").is_file()
    manifest["sha256"] = digest
    (folder / "run_manifest.json").write_text(json.dumps(manifest))
    # The session wrote the arm sha, not this zip. Point the manifest at the zip.
    assert check_evaluation(archive, folder)["tasks"] == 1
    paired = summarize_pair_run(tmp_path / "run")
    assert paired["arms"]["A/r1"]["resolved"] == 1


def test_record_mode_refuses_record_mismatch_and_static_scan(tmp_path):
    from gemma_lab.paired import GRADING_MODULES, grading_mutation_findings, verify_grading_pins

    root = tmp_path / "site"
    origins = {}
    record_lines = []
    for module, rel in GRADING_MODULES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n")
        origins[module] = str(path)
        import base64

        digest = hashlib.sha256(path.read_bytes()).digest()
        encoded = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        record_lines.append(f"{rel},sha256={encoded},\n")
    dist = root / "bundle.dist-info"
    dist.mkdir()
    (dist / "RECORD").write_text("".join(record_lines))
    pins = {
        rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for _, rel in GRADING_MODULES
    }
    assert verify_grading_pins(pins, "record", origins)
    target = root / GRADING_MODULES[0][1]
    target.write_text(target.read_text() + "x")
    with pytest.raises(Exception, match="RECORD mismatch"):
        verify_grading_pins(pins, "record", origins)
    target.write_text("# restored\n")
    digest = hashlib.sha256(target.read_bytes()).digest()
    encoded = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    record_lines[0] = f"{GRADING_MODULES[0][1]},sha256={encoded},\n"
    (dist / "RECORD").write_text("".join(record_lines))
    pins[GRADING_MODULES[0][1]] = "0" * 64
    verify_grading_pins(pins, "record", origins)
    with pytest.raises(Exception, match="grading pin mismatch"):
        verify_grading_pins(pins, "enforce", origins)
    assert "setattr" in grading_mutation_findings("setattr(swegemma, 'x', 1)")
    assert grading_mutation_findings("evaluator.evaluate_task(task)\n") == []


def test_clean_stray_sandboxes_drops_current_session_leftovers(tmp_path):
    root = tmp_path / "tmp"
    root.mkdir()
    old = root / "swegemma_sandbox_old"
    stray = root / "swegemma_sandbox_stray"
    live = root / "swegemma_sandbox_live"
    for path in (old, stray, live):
        path.mkdir()
    now = time.time()
    os.utime(old, (now - 10_000, now - 10_000))
    os.utime(stray, (now, now))
    os.utime(live, (now, now))
    removed = clean_stray_sandboxes(root, now - 100, live_names={live.name})
    assert set(removed) == {old.name, stray.name}
    assert live.is_dir()
    assert not old.exists()
    assert not stray.exists()


def test_collect_live_sandbox_names_keeps_registered_and_open_dirs(tmp_path):
    live = tmp_path / "swegemma_sandbox_registered"
    live.mkdir()

    class Manager:
        def __init__(self):
            self._sandboxes = {"1": {"root": str(live)}}

    class Evaluator:
        def __init__(self):
            self.sandbox = Manager()

    proc = tmp_path / "proc" / "42"
    (proc / "fd").mkdir(parents=True)
    os.symlink("/tmp/swegemma_sandbox_held/workspace", proc / "cwd")
    os.symlink("/var/swegemma_sandbox_fd", proc / "fd" / "3")
    names = collect_live_sandbox_names({"A": (1, Evaluator())}, proc_root=tmp_path / "proc")
    assert live.name in names
    assert "swegemma_sandbox_held" in names
    assert "swegemma_sandbox_fd" in names


def test_session_sweeps_unregistered_sandboxes_between_arms(tmp_path):
    root = tmp_path / "sand"
    root.mkdir()
    preexisting = root / "swegemma_sandbox_preexisting"
    preexisting.mkdir()
    generations = {"A": 0, "B": 0}

    class Manager:
        def __init__(self, label, generation):
            path = root / f"swegemma_sandbox_{label}_{generation}"
            path.mkdir()
            self.path = path
            self._sandboxes = {"id": {"root": str(path)}}

    class Evaluator:
        def __init__(self, label, generation):
            self.label = label
            self.sandbox = Manager(label, generation)

    def rebuild(label, repeat):
        generations[label] += 1
        return Evaluator(label, generations[label])

    def run_evaluate(evaluator, task, dashboard, position, total):
        (root / "swegemma_sandbox_orphan").mkdir(exist_ok=True)
        if evaluator.label == "A":
            raise RuntimeError("boom")
        return Result(resolved=True, patch="ok\n")

    schedule = build_schedule(["t1"], repeats=1)
    arms = {
        "A": arm_meta(tmp_path, "A", "a" * 64),
        "B": arm_meta(tmp_path, "B", "b" * 64),
    }
    execute_session(
        schedule=schedule["entries"],
        tasks={"t1": Task("t1")},
        rebuild=rebuild,
        run_evaluate=run_evaluate,
        output_dir=tmp_path / "run",
        arms=arms,
        schedule_sha256=schedule["sha256"],
        cap_seconds=60,
        session_budget_seconds=10**9,
        clock=Clock(),
        session_start=0,
        sandbox_tmp=root,
        session_start_epoch=time.time(),
    )
    assert not preexisting.exists()
    assert not (root / "swegemma_sandbox_orphan").exists()
    assert not (root / "swegemma_sandbox_A_1").exists()
    assert (root / "swegemma_sandbox_A_2").is_dir()
    assert (root / "swegemma_sandbox_B_1").is_dir()


def test_harness_trace_file_is_left_unchanged(tmp_path):
    payload = b'{"schema":"atif","events":[{"type":"agent"}]}\n'

    def run_evaluate(evaluator, task, dashboard, position, total):
        trace_dir = tmp_path / "run" / "results" / evaluator / "r1" / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / "trace_t1.json").write_bytes(payload)
        return Result(resolved=True, patch="ok\n", trace=Trace())

    run_session(tmp_path, ["t1"], run_evaluate)
    for label in ("A", "B"):
        path = tmp_path / "run" / "results" / label / "r1" / "traces" / "trace_t1.json"
        assert path.read_bytes() == payload
        assert not (path.parent / "trace_t1.raw.json").exists()


def test_trace_filename_turns_slashes_into_double_underscores(tmp_path):
    assert trace_artifact_stem("org/repo") == "trace_org__repo"

    class Saver:
        def save(self, path):
            Path(path).write_text('{"format":"atif"}\n')

    written = write_trace_artifact(tmp_path, "org/repo", Saver())
    assert written.name == "trace_org__repo.json"
    assert written.read_text() == '{"format":"atif"}\n'
    raw = write_trace_artifact(tmp_path, "org/other", Trace())
    assert raw.name == "trace_org__other.raw.json"
    assert not (tmp_path / "traces" / "trace_org__other.json").exists()
    original = (tmp_path / "traces" / "trace_org__repo.json").read_bytes()
    write_trace_artifact(tmp_path, "org/repo", Trace())
    assert (tmp_path / "traces" / "trace_org__repo.json").read_bytes() == original


def test_start_model_server_uses_a_new_session(monkeypatch):
    import subprocess
    import sys
    import types

    calls = []
    original = subprocess.Popen

    class FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
            self.pid = 4321

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    module = types.ModuleType("fake_server_mod")
    module.Popen = FakePopen
    monkeypatch.setitem(sys.modules, "fake_server_mod", module)

    class Server:
        def start(self):
            module.Popen(["vllm"])
            subprocess.Popen(["vllm"])

    start_model_server(Server())
    assert calls[0]["start_new_session"] is True
    assert calls[1]["start_new_session"] is True
    assert module.Popen is FakePopen
    assert subprocess.Popen is FakePopen
    assert original is not FakePopen


def test_release_kills_the_session_child_after_stop_reaps_the_parent():
    import selectors
    import signal
    import subprocess
    import sys

    from gemma_lab.paired import session_pgid

    script = (
        "import os, time\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(300)\n"
        "    raise SystemExit(0)\n"
        "print(child, flush=True)\n"
        "time.sleep(300)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        assert selector.select(5), "fake server did not report its child"
        child = int(proc.stdout.readline().strip())
        parent = proc.pid
        assert os.getpgid(parent) == parent
        assert os.getpgid(child) == parent
        pgid = session_pgid(parent)
        assert pgid == parent
        os.kill(parent, signal.SIGKILL)
        proc.wait(timeout=5)
        with pytest.raises(ProcessLookupError):
            os.getpgid(parent)
        os.kill(child, 0)
        assert session_pgid(parent) == parent
        started = time.perf_counter()
        log = release_server_after_stop(
            pgid,
            "http://127.0.0.1:9",
            nvidia_smi_present=False,
            port_open=lambda port: False,
        )
        elapsed = time.perf_counter() - started
        deadline = time.perf_counter() + 5
        while True:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            if time.perf_counter() >= deadline:
                raise AssertionError(f"child {child} still alive after release")
            time.sleep(0.05)
        assert log["pgid"] == parent
        assert log["timed_out"] is False
        assert elapsed >= 0.15
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait(timeout=5)


def test_kill_process_group_terms_then_kills_a_recorded_pgid():
    import signal

    signals = []

    def killpg(pgid, sig):
        signals.append((pgid, sig))

    killed = kill_process_group(
        50,
        grace=0.2,
        sleep=lambda seconds: signals.append(("sleep", seconds)),
        killpg=killpg,
    )
    assert killed == 50
    assert signals == [(50, signal.SIGTERM), ("sleep", 0.2), (50, signal.SIGKILL)]

    def missing(_pgid, _sig):
        raise ProcessLookupError

    def fail_sleep(seconds):
        raise AssertionError(seconds)

    assert kill_process_group(50, grace=5, sleep=fail_sleep, killpg=missing) == 50


def test_server_release_waits_for_port_and_gpu():
    from gemma_lab.paired import server_process_pid, wait_for_server_release

    assert kill_process_group(None) is None
    assert kill_process_group(0) is None

    class Process:
        pid = 50

    class Server:
        def __init__(self):
            self.process = Process()
            self.base_url = "http://127.0.0.1:8000"
            self.events = []

        def stop(self):
            self.events.append("stop")

        def start(self):
            self.events.append("start")

    server = Server()
    assert server_process_pid(server) == 50
    now = {"t": 0.0}

    def sleep(seconds):
        now["t"] += seconds

    def port_open(port):
        assert port == 8000
        return now["t"] < 0.5

    server.stop()
    log = release_server_after_stop(
        None,
        server.base_url,
        timeout=60,
        sleep=sleep,
        clock=lambda: now["t"],
        port_open=port_open,
        gpu_pids=lambda: [50],
        group_pids=lambda pgid: [50],
        nvidia_smi_present=True,
    )
    server.start()
    assert server.events == ["stop", "start"]
    assert log["waited_on"] == ["port"]
    assert log["port"] == 8000
    assert log["timed_out"] is False
    assert log["nvidia_smi"] is True
    gpu_now = {"t": 0.0}
    held = {"busy": True}

    def gpu_pids():
        if held["busy"]:
            held["busy"] = False
            return [50]
        return []

    waited = wait_for_server_release(
        8000,
        50,
        timeout=60,
        sleep=lambda seconds: gpu_now.__setitem__("t", gpu_now["t"] + 30),
        clock=lambda: gpu_now["t"],
        port_open=lambda port: False,
        gpu_pids=gpu_pids,
        group_pids=lambda pgid: [50],
        nvidia_smi_present=True,
    )
    assert waited["waited_on"] == ["gpu"]
    assert waited["gpu_pids"] == [50]
    assert waited["timed_out"] is False
    gpu_now["t"] = 0.0
    timed = wait_for_server_release(
        8000,
        50,
        timeout=60,
        sleep=lambda seconds: gpu_now.__setitem__("t", gpu_now["t"] + seconds),
        clock=lambda: gpu_now["t"],
        port_open=lambda port: True,
        gpu_pids=lambda: [50],
        group_pids=lambda pgid: [50],
        nvidia_smi_present=True,
    )
    assert timed["timed_out"] is True
    assert timed["waited_on"] == ["port", "gpu"]
    assert timed["seconds"] >= 60
    absent = wait_for_server_release(
        None,
        None,
        timeout=60,
        clock=lambda: 0,
        port_open=lambda port: True,
        gpu_pids=lambda: [1],
        group_pids=lambda pgid: [1],
        nvidia_smi_present=False,
    )
    assert absent["waited_on"] == []
    assert absent["nvidia_smi"] is False
