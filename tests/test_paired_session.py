import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from gemma_lab.metrics import load_results, summary
from gemma_lab.operations import (
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    check_evaluation,
    runtime_projection,
)
from gemma_lab.paired import (
    abort_code,
    build_projection,
    build_report,
    build_schedule,
    clean_stray_sandboxes,
    collect_live_sandbox_names,
    decision_rule,
    early_stop_loser,
    execute_session,
    kill_process_group,
    projection_for_arm,
    release_server_after_stop,
    render_report_md,
    repeat_is_valid,
    report_from_runs,
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


def _down(status=503, kind="http_error", url="http://h:1/health", process_exited=False):
    return {
        "ok": False,
        "url": url,
        "status": status,
        "error": f"HTTPError({status})" if status is not None else "URLError('down')",
        "kind": kind,
        "process_exited": process_exited,
    }


def _up():
    return {
        "ok": True,
        "url": "http://h:1/health",
        "status": 200,
        "error": None,
        "kind": None,
        "process_exited": False,
    }


def _events(tmp_path):
    path = tmp_path / "run" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_one_server_restart_then_abort(tmp_path):
    pauses = []
    restarts = []

    def health():
        return _down()

    def restart():
        restarts.append(1)
        return 4.0

    def run_evaluate(evaluator, task, dashboard, position, total):
        raise AssertionError("task must not run when the re-check stays down")

    outcome = run_session(
        tmp_path,
        ["t1", "t2"],
        run_evaluate,
        health=health,
        restart_server=restart,
        health_pause=pauses.append,
    )
    assert pauses == [2.0, 2.0]
    assert restarts == [1]
    assert outcome["status"] == "aborted:model_server"
    unhealthy = [row for row in outcome["rows"] if row["error"] == "model_server_unhealthy"]
    assert len(unhealthy) == 1
    assert unhealthy[0]["post_restart"] is True
    failed = [row for row in _events(tmp_path) if row["event"] == "health_check_failed"]
    assert [row["attempt"] for row in failed] == [1, 2, 3, 1]
    assert failed[-1]["after_restart"] is True
    assert failed[0]["kind"] == "http_error"
    assert failed[0]["status"] == 503
    assert "HTTPError(503)" in failed[0]["error"]


def test_one_or_two_health_failures_do_not_restart(tmp_path):
    for failures in (1, 2):
        pauses = []
        restarts = []
        state = {"n": 0}

        def health(needed=failures, state=state):
            state["n"] += 1
            if state["n"] <= needed:
                return _down(status=404, url="http://h:1/v1/health")
            return _up()

        def restart(bucket=restarts):
            bucket.append(1)
            return 1.0

        def run_evaluate(evaluator, task, dashboard, position, total):
            return Result(resolved=True)

        root = tmp_path / str(failures)
        root.mkdir()
        outcome = run_session(
            root,
            ["t1"],
            run_evaluate,
            health=health,
            restart_server=restart,
            health_pause=pauses.append,
        )
        assert restarts == []
        assert pauses == [2.0] * failures
        assert outcome["status"] == "complete"
        assert not any(row.get("error") == "model_server_unhealthy" for row in outcome["rows"])
        kinds = [row["kind"] for row in _events(root) if row["event"] == "health_check_failed"]
        assert kinds == ["http_error"] * failures


def test_dead_process_restarts_immediately_and_retries_the_task(tmp_path):
    pauses = []
    restarts = []
    ran = []
    state = {"n": 0}

    def health():
        state["n"] += 1
        if state["n"] == 1:
            return _down(status=None, kind="connection_error", process_exited=True)
        return _up()

    def restart():
        restarts.append(1)
        return 1.5

    def run_evaluate(evaluator, task, dashboard, position, total):
        ran.append((evaluator, task.instance_id))
        return Result(resolved=True)

    outcome = run_session(
        tmp_path,
        ["t1"],
        run_evaluate,
        health=health,
        restart_server=restart,
        health_pause=pauses.append,
    )
    assert pauses == []
    assert restarts == [1]
    assert ran == [("A", "t1"), ("B", "t1")]
    assert outcome["status"] == "complete"
    assert not any(row.get("error") == "model_server_unhealthy" for row in outcome["rows"])
    events = _events(tmp_path)
    failed = [row for row in events if row["event"] == "health_check_failed"]
    assert len(failed) == 1
    assert failed[0]["kind"] == "connection_error"
    assert failed[0]["status"] is None
    assert failed[0]["attempt"] == 1
    assert failed[0]["process_exited"] is True
    retries = [row for row in events if row["event"] == "task_retry"]
    assert len(retries) == 1
    assert retries[0]["arm"] == "A"
    assert retries[0]["task_id"] == "t1"


def test_three_failures_retry_once_and_a_later_failure_aborts(tmp_path):
    pauses = []
    restarts = []
    ran = []
    state = {"n": 0}

    def health():
        state["n"] += 1
        if state["n"] <= 3:
            return _down()
        if state["n"] == 4:
            return _up()
        return _down(status=None, kind="connection_error")

    def restart():
        restarts.append(1)
        return 2.0

    def run_evaluate(evaluator, task, dashboard, position, total):
        ran.append(evaluator)
        return Result(resolved=True)

    outcome = run_session(
        tmp_path,
        ["t1"],
        run_evaluate,
        health=health,
        restart_server=restart,
        health_pause=pauses.append,
    )
    assert pauses == [2.0, 2.0, 2.0, 2.0]
    assert restarts == [1]
    assert ran == ["A"]
    assert outcome["status"] == "aborted:model_server"
    unhealthy = [row for row in outcome["rows"] if row.get("error") == "model_server_unhealthy"]
    assert len(unhealthy) == 1
    assert unhealthy[0]["arm"] == "B"
    assert [row for row in outcome["rows"] if row["arm"] == "A"][0]["resolved"] is True
    retries = [row for row in _events(tmp_path) if row["event"] == "task_retry"]
    assert len(retries) == 1


def test_failed_task_rerun_is_a_crash_row_not_another_restart(tmp_path):
    restarts = []
    state = {"n": 0}

    def health():
        state["n"] += 1
        if state["n"] <= 3:
            return _down()
        return _up()

    def restart():
        restarts.append(1)
        return 1.0

    def run_evaluate(evaluator, task, dashboard, position, total):
        if evaluator == "A":
            raise RuntimeError("rerun failed")
        return Result(resolved=True)

    outcome = run_session(
        tmp_path,
        ["t1"],
        run_evaluate,
        health=health,
        restart_server=restart,
        health_pause=lambda _seconds: None,
    )
    assert restarts == [1]
    assert outcome["status"] == "complete"
    crashed = [row for row in outcome["rows"] if row["arm"] == "A"]
    assert crashed[0]["crashed"] is True
    assert "rerun failed" in crashed[0]["error"]
    assert crashed[0]["error"] != "model_server_unhealthy"
    assert len([row for row in _events(tmp_path) if row["event"] == "task_retry"]) == 1


def test_root_health_probe_and_old_v1_probe(tmp_path):
    from gemma_lab.paired import (
        copy_server_log,
        model_server_root,
        probe_http,
        probe_model_health,
        read_model_prefix_cache,
        record_startup_health,
        server_process_exited,
    )
    from gemma_lab.stub_server import ScriptedResponder, StubModelServer, empty_submit_turns

    class Dead:
        def poll(self):
            return 1

    assert server_process_exited(type("Missing", (), {})()) is False
    assert server_process_exited(type("Exited", (), {"process": Dead()})()) is True

    server = StubModelServer(ScriptedResponder({"": empty_submit_turns()}))
    with server:
        assert server.base_url.endswith("/v1")
        assert server.health_url == server.root_url + "/health"
        probed = probe_model_health(server)
        assert probed["ok"] is True
        assert probed["status"] == 200
        assert probed["url"] == server.health_url
        bare = type("Bare", (), {"base_url": server.base_url})()
        assert not hasattr(bare, "health_url")
        assert model_server_root(bare) == server.root_url
        fallback = probe_model_health(bare)
        assert fallback["ok"] is True
        assert fallback["url"] == server.root_url + "/health"
        metrics = read_model_prefix_cache(bare)
        assert metrics["vllm:prefix_cache_hits_total"] == 0.0
        missed = probe_http(server.base_url + "/health", 5)
        assert missed["ok"] is False
        assert missed["status"] == 404
        assert missed["kind"] == "http_error"
        metrics_missed = probe_http(server.base_url + "/metrics", 5)
        assert metrics_missed["status"] == 404
        assert metrics_missed["kind"] == "http_error"
        events = tmp_path / "events.jsonl"
        record_startup_health(server, events)
        polls = [json.loads(line) for line in events.read_text().splitlines()]
        assert [row["attempt"] for row in polls] == [1, 2, 3]
        assert all(row["event"] == "health_poll" and row["status"] == 200 for row in polls)
        assert all(row["url"].endswith("/health") for row in polls)
        assert all("/v1/health" not in row["url"] for row in polls)
        log = tmp_path / "vllm.log"
        log.write_text("ready\n")
        logged = type("Logged", (), {"log_path": log})()
        assert copy_server_log(logged, tmp_path / "server.log") is True
        assert (tmp_path / "server.log").read_text() == "ready\n"
        assert copy_server_log(type("NoLog", (), {})(), tmp_path / "missing.log") is False

    refused = probe_http("http://127.0.0.1:9/health", 0.2)
    assert refused["ok"] is False
    assert refused["status"] is None
    assert refused["kind"] == "connection_error"


def _old_base_url_health(server):
    """The t0-r1 probe: base_url already ends in /v1, so this requests /v1/health."""
    import urllib.request

    try:
        with urllib.request.urlopen(server.base_url.rstrip("/") + "/health", timeout=5) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def test_old_probe_aborts_and_root_probe_runs_thirteen_tasks(tmp_path):
    from gemma_lab.paired import probe_model_health
    from gemma_lab.stub_server import ScriptedResponder, StubModelServer, empty_submit_turns

    ids = [f"t{index:02d}" for index in range(13)]
    server = StubModelServer(ScriptedResponder({"": empty_submit_turns()}))
    with server:
        assert _old_base_url_health(server) is False
        assert server.base_url.rstrip("/") + "/health" == server.base_url + "/health"
        assert probe_model_health(server)["ok"] is True

        def run_evaluate(evaluator, task, dashboard, position, total):
            return Result(resolved=True)

        def restart():
            return 0.1

        (tmp_path / "old").mkdir()
        (tmp_path / "new").mkdir()
        old = run_session(
            tmp_path / "old",
            ids,
            run_evaluate,
            health=lambda: _old_base_url_health(server),
            restart_server=restart,
            health_pause=lambda _seconds: None,
        )
        assert old["status"] == "aborted:model_server"
        assert old["rows"][0]["task_id"] == ids[0]
        assert old["rows"][0]["error"] == "model_server_unhealthy"
        assert {row["task_id"] for row in old["rows"]} == {ids[0]}

        fresh = run_session(
            tmp_path / "new",
            ids,
            run_evaluate,
            health=lambda: probe_model_health(server),
            restart_server=restart,
            health_pause=lambda _seconds: None,
        )
    assert fresh["status"] == "complete"
    assert fresh["restarts"] == 0
    assert {row["task_id"] for row in fresh["rows"]} == set(ids)
    assert len(fresh["rows"]) == 26
    assert not any(row.get("error") == "model_server_unhealthy" for row in fresh["rows"])
    phases = [
        (row["phase"], row["task_id"])
        for row in _events(tmp_path / "new")
        if row["event"] == "gpu_memory"
    ]
    assert phases[0] == ("before_task", ids[0])
    assert phases[1][0] == "after_task"


def test_gpu_memory_snapshot_tolerates_a_missing_tool(monkeypatch):
    import shutil

    from gemma_lab.paired import gpu_memory_snapshot

    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert gpu_memory_snapshot() == {"gpus": None, "error": "nvidia-smi not found"}


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
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    assert quiet["checks"]["worst_case_12h"]["value"] == 900 + 129 * (10 + overhead)
    assert quiet["checks"]["worst_case_12h"]["passed"] is True
    assert quiet["checks"]["worst_case_12h"]["severity"] == "warn"
    assert "worst_case_12h_n129" not in quiet["checks"]
    assert "worst_case_12h_n120" not in quiet["checks"]
    assert quiet["checks"]["round2_load_plus_129_mean"]["passed"] is True
    assert quiet["checks"]["round2_load_plus_129_mean"]["formula"] == "L + 129 * mean_wall"
    assert quiet["checks"]["coordinator_mean_times_120"]["passed"] is True
    assert quiet["checks"]["coordinator_mean_times_120"]["formula"] == "mean_wall * 120"
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


def test_start_model_server_skips_lazy_class_namespace(monkeypatch):
    import subprocess
    import sys
    import types

    calls = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
            self.pid = 4321

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    class Proxy:
        def __getattr__(self, attr):
            raise RuntimeError(
                "Tried to instantiate class 'subprocess."
                f"{attr}', but it does not exist! "
                "Ensure that it is registered via torch::class_"
            )

    class LazyNamespace(types.ModuleType):
        def __init__(self, name):
            super().__init__(name)
            self.lookups = []

        def __getattr__(self, name):
            self.lookups.append(name)
            return Proxy()

    lazy = LazyNamespace("torch.classes")
    other = types.ModuleType("not_subprocess")
    other.Popen = FakePopen
    holder = types.ModuleType("holds_other_subprocess")
    holder.subprocess = other
    monkeypatch.setitem(sys.modules, "torch.classes", lazy)
    monkeypatch.setitem(sys.modules, "holds_other_subprocess", holder)

    class Server:
        def start(self):
            subprocess.Popen(["vllm"])
            return "started"

    assert start_model_server(Server()) == "started"
    assert calls == [{"start_new_session": True}]
    assert lazy.lookups == []
    assert subprocess.Popen is FakePopen
    assert other.Popen is FakePopen


def test_start_model_server_survives_real_torch_classes():
    import subprocess
    import sys

    torch = pytest.importorskip("torch")
    classes = sys.modules.get("torch.classes", getattr(torch, "classes", None))
    if classes is None:
        pytest.skip("torch.classes is not registered")
    original = subprocess.Popen

    class Server:
        def start(self):
            return "started"

    assert start_model_server(Server()) == "started"
    assert subprocess.Popen is original


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


def test_kill_process_group_refuses_the_notebook_group(monkeypatch):
    calls = []

    def spy(pgid, sig):
        calls.append((pgid, sig))

    monkeypatch.setattr(os, "killpg", spy)
    own = os.getpgrp()
    with pytest.warns(UserWarning, match="notebook's own process group"):
        assert kill_process_group(own, grace=5) is None
    assert calls == []
    for bad in (None, 0, -1, 1):
        with pytest.warns(UserWarning, match="not a server process group"):
            assert kill_process_group(bad) is None
        assert calls == []


def test_hung_nvidia_smi_returns_within_the_deadline(monkeypatch):
    import shutil
    import subprocess
    import warnings

    from gemma_lab.paired import (
        NVIDIA_SMI_POLL_TIMEOUT_SECONDS,
        nvidia_smi_gpu_pids,
        wait_for_server_release,
    )

    observed = []
    waits = []

    class Hung:
        def __init__(self, *args, **kwargs):
            self.stdout = None
            self.stderr = None
            self.returncode = None

        def communicate(self, timeout=None):
            observed.append(timeout)
            raise subprocess.TimeoutExpired("nvidia-smi", timeout)

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            waits.append(timeout)
            raise subprocess.TimeoutExpired("nvidia-smi", timeout)

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", Hung)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        log = wait_for_server_release(
            None,
            424242,
            timeout=60,
            nvidia_smi_present=True,
            group_pids=lambda pgid: [],
        )
    elapsed = time.perf_counter() - started
    messages = " ".join(str(item.message) for item in caught)
    assert observed == [NVIDIA_SMI_POLL_TIMEOUT_SECONDS]
    assert waits == [2]
    assert elapsed < 1
    assert log["gpu_memory"] == "unknown"
    assert log["timed_out"] is False
    assert "nvidia-smi timed out" in messages
    assert "did not exit after kill" in messages
    with warnings.catch_warnings(record=True) as shortened:
        warnings.simplefilter("always")
        assert nvidia_smi_gpu_pids(timeout=2) == "deadline"
    shortened_text = " ".join(str(item.message) for item in shortened)
    assert "nvidia-smi timed out" not in shortened_text
    assert "did not exit after kill" in shortened_text


@pytest.mark.parametrize("deadline", [2, 3, 5])
def test_slow_nvidia_smi_at_a_short_deadline_keeps_holders(monkeypatch, deadline):
    import shutil
    import subprocess
    import warnings

    from gemma_lab.paired import wait_for_server_release

    timeouts = []

    class Slow:
        def __init__(self, *args, **kwargs):
            self.stdout = None
            self.stderr = None
            self.returncode = None

        def communicate(self, timeout=None):
            timeouts.append(timeout)
            time.sleep(0.7)
            if timeout is not None and timeout < 0.7:
                raise subprocess.TimeoutExpired("nvidia-smi", timeout)
            self.returncode = 0
            return ("777777\n", "")

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(subprocess, "Popen", Slow)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        log = wait_for_server_release(
            None,
            424242,
            timeout=deadline,
            nvidia_smi_present=True,
            group_pids=lambda pgid: [777777],
        )
    messages = " ".join(str(item.message) for item in caught)
    assert log["timed_out"] is True
    assert log["gpu_pids"] == [777777]
    assert log["waited_on"] == ["gpu"]
    assert log["gpu_memory"] != "unknown"
    assert log["detail"] == "release deadline reached"
    assert "nvidia-smi timed out" not in messages
    assert timeouts
    assert min(timeouts) >= 1.0


def test_refused_kill_is_written_to_events(tmp_path):
    from gemma_lab.paired import append_jsonl

    own = os.getpgrp()
    with pytest.warns(UserWarning, match="notebook's own process group"):
        log = release_server_after_stop(
            own,
            "http://127.0.0.1:9",
            nvidia_smi_present=False,
            port_open=lambda port: False,
        )
    assert log["kill_refused_pgid"] == own
    assert log["kill_refused_reason"] == "own_group"
    path = tmp_path / "events.jsonl"
    row = {"event": "server_restart_release", "release": log}
    row["kill_refused_pgid"] = log["kill_refused_pgid"]
    row["kill_refused_reason"] = log["kill_refused_reason"]
    append_jsonl(path, row)
    saved = json.loads(path.read_text())
    assert saved["kill_refused_pgid"] == own
    assert saved["kill_refused_reason"] == "own_group"
    assert saved["release"]["kill_refused_pgid"] == own
    with pytest.warns(UserWarning, match="not a server process group"):
        invalid = release_server_after_stop(
            1,
            "http://127.0.0.1:9",
            nvidia_smi_present=False,
            port_open=lambda port: False,
        )
    assert invalid["kill_refused_pgid"] == 1
    assert invalid["kill_refused_reason"] == "invalid_pgid"


def test_server_release_waits_for_port_and_gpu():
    from gemma_lab.paired import server_process_pid, wait_for_server_release

    with pytest.warns(UserWarning, match="not a server process group"):
        assert kill_process_group(None) is None
    with pytest.warns(UserWarning, match="not a server process group"):
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
    with pytest.warns(UserWarning, match="not a server process group"):
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
    assert timed["seconds"] >= 59
    assert timed["detail"] == "release deadline reached"
    assert timed["gpu_pids"] == [50]
    assert timed["gpu_memory"] != "unknown"
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


def _decision_rows(*, a_wins=True):
    rows = []
    for repeat in (1, 2):
        for task_id in ("t1", "t2"):
            for arm in ("A", "B"):
                resolved = a_wins if arm == "A" else not a_wins
                rows.append(
                    {
                        "arm": arm,
                        "repeat": repeat,
                        "task_id": task_id,
                        "resolved": resolved,
                        "wall_seconds": 10,
                        "hit_cap": {},
                    }
                )
    return rows


def _decision_projection(rows):
    return build_projection(
        rows,
        {"A": {"sha256": "a" * 64}, "B": {"sha256": "b" * 64}},
        60,
        900,
        None,
    )


def _hygiene_sidecar(gate):
    return {
        "gate": gate,
        "candidate": {"gate": gate, "explicit_finalization": [1, 1]},
        "tasks": [],
    }


def _hygiene_sides(gate_a, gate_b):
    return {
        "results/A/r1/hygiene.json": _hygiene_sidecar(gate_a),
        "results/B/r1/hygiene.json": _hygiene_sidecar(gate_b),
    }


def test_decision_rule_reads_hygiene_sidecars():
    rows = _decision_rows()
    projection = _decision_projection(rows)
    absent = decision_rule(rows, projection, None)
    assert absent["conditions"]["hygiene"]["status"] == "not_computed"
    assert absent["conditions"]["hygiene"]["pass"] is None
    assert absent["conditions"]["hygiene"]["arms"] == {"A": "not_computed", "B": "not_computed"}
    assert absent["rule_winner"] is None
    blank = decision_rule(rows, projection, "not_computed")
    assert blank["rule_winner"] is None
    assert blank["conditions"]["hygiene"]["status"] == "not_computed"

    passed = decision_rule(rows, projection, _hygiene_sides("pass", "pass"))
    assert passed["conditions"]["hygiene"]["status"] == "pass"
    assert passed["conditions"]["hygiene"]["pass"] is True
    assert passed["conditions"]["hygiene"]["arms"] == {"A": "pass", "B": "pass"}
    assert passed["rule_winner"] == "A"

    warned = decision_rule(rows, projection, _hygiene_sides("warn", "pass"))
    assert warned["conditions"]["hygiene"]["status"] == "warn"
    assert warned["conditions"]["hygiene"]["arms"]["A"] == "warn"
    assert warned["rule_winner"] == "A"

    blocked = decision_rule(rows, projection, _hygiene_sides("block", "pass"))
    assert blocked["conditions"]["hygiene"]["status"] == "block"
    assert blocked["conditions"]["hygiene"]["pass"] is False
    assert blocked["rule_winner"] is None
    assert "Hygiene block on A" in blocked["note"]
    assert "cannot win" in blocked["note"]

    both = decision_rule(rows, projection, _hygiene_sides("block", "block"))
    assert both["rule_winner"] is None
    assert both["conditions"]["hygiene"]["arms"] == {"A": "block", "B": "block"}

    rival_rows = _decision_rows(a_wins=False)
    rival_projection = _decision_projection(rival_rows)
    rival = decision_rule(rival_rows, rival_projection, _hygiene_sides("block", "pass"))
    assert rival["rule_winner"] == "B"
    held = decision_rule(rival_rows, rival_projection, _hygiene_sides("pass", "block"))
    assert held["rule_winner"] is None
    assert "Hygiene block on B" in held["note"]


def test_worst_case_line_matches_the_upload_gate(tmp_path):
    import zipfile

    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("eval_config.yaml", "evaluation:\n  max_time_minutes: 4.5\n")
    uploaded = runtime_projection(
        [{"instance_id": "t", "duration_seconds": 10}],
        {"model_load_seconds": 900},
        archive,
        DEFAULT_SCORER_OVERHEAD_SECONDS,
    )
    projected = projection_for_arm(
        [{"wall_seconds": 10, "hit_cap": {}}],
        arm_sha256="a" * 64,
        cap_seconds=270,
        model_load_seconds=900,
        session_overhead_seconds=None,
    )
    check = projected["checks"]["worst_case_12h"]
    assert check["severity"] == "warn"
    assert check["formula"] == "L + 129 * (cap + 70)"
    assert check["value"] == uploaded["worst_case_seconds"]
    assert check["value"] == 900 + 129 * (270 + 70)
    assert check["passed"] is False
    assert uploaded["worst_case_warn"] is True
    assert projected["blocked"] is False
    assert projected["checks"]["round2_load_plus_129_mean"]["formula"] == "L + 129 * mean_wall"
    report = build_report(
        [{"arm": "A", "repeat": 1, "task_id": "t", "resolved": False, "wall_seconds": 10}],
        projection={"arms": {"A": projected}, "blocked": False},
        hygiene="not_computed",
    )
    text = render_report_md(report)
    assert "worst_case_12h [warn]:" in text
    assert f"value={check['value']}" in text
    assert "Hygiene: not_computed" in text


_SCRATCH_PATCH = """diff --git a/repro.py b/repro.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/repro.py
@@ -0,0 +1 @@
+x = 1
"""


def _arm_repeat(root, arm, task_id="fastapi_11194"):
    folder = root / "results" / arm / "r1"
    (folder / "patches").mkdir(parents=True)
    (folder / "patches" / f"{task_id}.patch").write_text(_SCRATCH_PATCH)
    (folder / "task_results.jsonl").write_text(
        json.dumps({"instance_id": task_id, "resolved": False}) + "\n"
    )
    return folder


def _pair_protocol(tmp_path):
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps(["fastapi_11194"]))
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(
        "arms:\n"
        "  A:\n"
        "    source: missing-a\n"
        "  B:\n"
        "    source: missing-b\n"
        "cohort:\n"
        f"  path: {cohort}\n"
        "repeats: 2\n"
    )
    return protocol


def _pair_rows():
    rows = []
    for repeat in (1, 2):
        for arm in ("A", "B"):
            rows.append(
                {
                    "arm": arm,
                    "repeat": repeat,
                    "task_id": "fastapi_11194",
                    "resolved": arm == "A",
                    "wall_seconds": 10,
                    "hit_cap": {},
                }
            )
    return rows


def test_pair_report_writes_hygiene_sidecars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = tmp_path / "run"
    _arm_repeat(run, "A")
    _arm_repeat(run, "B")
    (run / "pair_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in _pair_rows()))
    output = tmp_path / "report"
    report_from_runs([run], _pair_protocol(tmp_path), output)
    for arm in ("A", "B"):
        sidecar = json.loads((run / "results" / arm / "r1" / "hygiene.json").read_text())
        assert sidecar["gate"] == "block"
        assert "H1 scratch file repro.py in fastapi_11194" in sidecar["candidate"]["reasons"]
        assert all("is below" not in reason for reason in sidecar["candidate"]["reasons"])
        assert sidecar["candidate"]["findings"][0]["severity"] == "warn"
    text = (output / "pair_report.md").read_text()
    assert "Hygiene A/r1: gate block, H1 1, H2 0, H3 1, H5 0, explicit submit 0/1" in text
    assert "Hygiene B/r1: gate block, H1 1, H2 0, H3 1, H5 0, explicit submit 0/1" in text
    assert "Hygiene: {" not in text
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["decision_rule"]["conditions"]["hygiene"]["arms"] == {"A": "block", "B": "block"}
    assert saved["decision_rule"]["rule_winner"] is None


def test_pair_report_keeps_existing_hygiene_sidecars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = tmp_path / "run"
    for arm in ("A", "B"):
        folder = _arm_repeat(run, arm)
        payload = {
            "gate": "pass",
            "candidate": {"gate": "pass", "explicit_finalization": [1, 1], "reasons": ["leave me"]},
            "tasks": [],
        }
        (folder / "hygiene.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    before = {
        arm: (run / "results" / arm / "r1" / "hygiene.json").read_bytes() for arm in ("A", "B")
    }
    (run / "pair_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in _pair_rows()))
    output = tmp_path / "report"
    report_from_runs([run], _pair_protocol(tmp_path), output)
    for arm in ("A", "B"):
        path = run / "results" / arm / "r1" / "hygiene.json"
        assert path.read_bytes() == before[arm]
    text = (output / "pair_report.md").read_text()
    assert "Hygiene A/r1: gate pass, H1 0, H2 0, H3 0, H5 0, explicit submit 1/1" in text
    assert "Hygiene: {" not in text
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["decision_rule"]["conditions"]["hygiene"]["status"] == "pass"
