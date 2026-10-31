"""Combined four-arm smoke. Existing two-arm notebooks stay on notebook-pair."""

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from gemma_lab.multi_arm import (
    assert_multi_compatible,
    build_multi_schedule,
    count_failed_tool_calls,
    generate_multi,
    largest_integer_mean_that_passes,
    load_multi_protocol,
    multi_report_from_runs,
    multi_smoke_report,
    option2_wall_seconds,
    pair_fits_minimum_budget,
    render_multi_smoke_md,
    smoke_binding_sources,
    submission_gate_picture,
    worst_session_wall_seconds,
    write_markdown_atomic,
)
from gemma_lab.notebook import generate_pair
from gemma_lab.paired import (
    build_schedule,
    inspect_arm,
    load_protocol,
    notebook_runtime_source,
)

PROTOCOL = Path("configs/protocols/combined-candidate-smoke.yaml")
MULTI_PROTOCOLS = {
    PROTOCOL,
    Path("configs/protocols/structured-v8-candidate-smoke.yaml"),
}
STARTER = Path("vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb")
CONFOUND = (
    "The 5-task rotation confounds position with task "
    "(slot counts A 2,1,1,1; B 1,2,1,1; C 1,1,2,1; D 1,1,1,2)."
)
TASKS = [
    "rich_4070",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "fastapi_14262",
]
TWO_ARM_SCHEDULE = "5672ef15323e1d59847cc7cde3f1b6cb1912346d7456b13cb716902437b3e9fd"
MULTI_SCHEDULE = "4d2904f77afbafbdc2bc5f52266b60f09bf45c51fc072fb24808e0b3dd2961cd"
LABELS = ["A", "B", "C", "D"]
ARCHIVES = {
    "A": "6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22",
    "B": "64dc727d78c4189c1db1184e74129290574c7b97816dd91f91d2baa7defe0fb0",
    "C": "a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df",
    "D": "f62c8c0b92bc5bd1fb1015f20e7cbd7a5599d5518d2d59097bf2b40d9f3412b0",
}
AGENT_DIRS = {
    "baseline",
    "simple-v1",
    "simple-v2",
    "simple-v3",
    "structured-v4",
    "structured-v4-10m",
    "structured-v5",
    "structured-v5t0",
    "structured-v6",
    "structured-v7",
    "structured-v8",
    "structured-v9",
    "structured-v10",
    "structured-v11",
    "structured-v12",
    "structured-v13",
    "structured-v13-1",
    "structured-v14",
    "structured-v15",
    "structured-v16",
    "structured-v16-1",
    "structured-v16-2",
    "structured-v17",
    "structured-v18",
    "structured-v18-1",
    "structured-v19",
    "structured-v19-1",
    "single-v1",
    "single-v1t0",
    "single-v2",
    "single-v3",
    "single-v4",
    "single-v5",
    "single-v5-think256",
    "single-v6",
    "single-v7",
    "single-v8",
    "single-v8-check",
    "single-v9",
}


def _budgets():
    return {
        "A": {
            "timeout_seconds": 300,
            "max_tool_calls": 150,
            "max_time_minutes": 5.5,
            "max_turns": 200,
        },
        "B": {
            "timeout_seconds": 300,
            "max_tool_calls": 150,
            "max_time_minutes": 5.5,
            "max_turns": 200,
        },
        "C": {
            "timeout_seconds": 300,
            "max_tool_calls": 150,
            "max_time_minutes": 6.0,
            "max_turns": 200,
        },
        "D": {
            "timeout_seconds": 300,
            "max_tool_calls": 48,
            "max_time_minutes": 4.5,
            "max_turns": 64,
        },
    }


def test_agent_directories_stay_at_thirty_nine():
    found = {path.name for path in Path("agents").iterdir() if path.is_dir()}
    assert found == AGENT_DIRS
    assert len(found) == 39
    assert "single-v7-lenient" not in found


def test_existing_protocols_remain_two_arm():
    paths = sorted(Path("configs/protocols").glob("*.yaml"))
    others = [path for path in paths if path not in MULTI_PROTOCOLS]
    assert len(paths) == 18
    assert len(others) == 16
    for path in others:
        protocol = load_protocol(path)
        assert set(protocol["arms"]) == {"A", "B"}
    for path in MULTI_PROTOCOLS:
        loaded = load_multi_protocol(path)
        assert loaded["multi_arm"] is True


def test_notebook_pair_refuses_the_multi_protocol(tmp_path):
    with pytest.raises(ValueError, match="exactly A and B"):
        generate_pair(
            PROTOCOL,
            "charlesaherbst",
            "combined-candidate-smoke",
            tmp_path / "pair",
            wheelhouse_version=30,
        )


def test_two_label_rotation_matches_build_schedule():
    for repeats in (1, 2):
        multi = build_multi_schedule(TASKS, ["A", "B"], repeats=repeats)
        two = build_schedule(TASKS, repeats=repeats)
        assert multi["entries"] == two["entries"]
        assert multi["sha256"] == two["sha256"]
    assert build_schedule(TASKS, repeats=1)["sha256"] == TWO_ARM_SCHEDULE


def test_four_arm_schedule_keeps_task_order_and_rotates():
    multi = build_multi_schedule(TASKS, LABELS, repeats=1)
    two = build_schedule(TASKS, repeats=1)
    assert multi["sha256"] == MULTI_SCHEDULE
    assert multi["sha256"] != two["sha256"]
    assert [entry["task_id"] for entry in multi["entries"]] == TASKS
    assert [entry["p0"] for entry in multi["entries"]] == [entry["p0"] for entry in two["entries"]]
    assert [entry["order"] for entry in multi["entries"]] == [
        ["A", "B", "C", "D"],
        ["B", "C", "D", "A"],
        ["C", "D", "A", "B"],
        ["D", "A", "B", "C"],
        ["A", "B", "C", "D"],
    ]


def test_protocol_markers_and_session_budget():
    protocol = load_multi_protocol(PROTOCOL)
    assert protocol["purpose"] == "smoke"
    assert protocol["matched_pair"] is False
    assert protocol["notes"].strip()
    assert protocol["repeats"] == 1
    assert protocol["early_stop"] is None
    assert protocol["_task_ids"] == TASKS
    assert set(protocol["allowed_differences"]) >= {
        "eval_config.yaml",
        "sampling.yaml",
        "thinking.yaml",
    }
    assert "sub_agents/*" not in protocol["allowed_differences"]
    for label, digest in ARCHIVES.items():
        assert protocol["arms"][label]["expected_sha256"] == digest
    assert protocol["session_budget_seconds"] == 14400
    minimum = pair_fits_minimum_budget(5, 4, 360, extra_elapsed=300)
    assert minimum == 8640
    assert protocol["session_budget_seconds"] >= minimum
    assert protocol["session_budget_seconds"] < 43200


def test_runtime_numbers():
    assert worst_session_wall_seconds([330, 330, 360, 270], 5) == 7350
    assert 5 * 4 == 20
    assert option2_wall_seconds() == 12450
    assert largest_integer_mean_that_passes() == 260
    picture = submission_gate_picture(360)
    assert picture["warn_seconds"] == 56370
    assert picture["warn"] is True
    assert picture["block_120_if_mean_equals_cap"] == 51600
    assert picture["block_120"] is True
    assert picture["block_129_if_mean_equals_cap"] == 47340
    assert picture["block_129"] is True
    assert submission_gate_picture(330)["warn_seconds"] == 52500
    assert submission_gate_picture(270)["warn_seconds"] == 44760
    assert submission_gate_picture(270)["block_129"] is False
    three_arm = pair_fits_minimum_budget(5, 3, 360, extra_elapsed=300)
    assert three_arm == 6780
    # 6780 s is pair_fits. The own-cap wall for those 15 runs is 6000 s.
    assert worst_session_wall_seconds([330, 330, 360], 5) == 6000


def test_smoke_report_names_no_winner():
    rows = [
        {
            "arm": "A",
            "task_id": "rich_4070",
            "resolved": True,
            "wall_seconds": 100,
            "patch_chars": 0,
            "tool_calls": 4,
            "llm_calls": 3,
            "hit_cap": {"wall": False, "marker": False},
        },
        {"arm": "B", "task_id": "rich_4070", "resolved": False, "wall_seconds": 110},
        {"arm": "C", "task_id": "rich_4070", "resolved": True, "wall_seconds": 120},
        {
            "arm": "D",
            "task_id": "rich_4070",
            "resolved": False,
            "wall_seconds": 90,
            "failure_class": "infrastructure_or_harness",
            "hit_cap": {"wall": True, "marker": True},
        },
    ]
    names = {
        "A": "single-v8",
        "B": "single-v8-check",
        "C": "structured-v7",
        "D": "single-v7",
    }
    report = multi_smoke_report(
        rows,
        labels=LABELS,
        names=names,
        budgets=_budgets(),
        protocol_sha256="abc",
        schedule_sha256=MULTI_SCHEDULE,
        task_schedule_sha256=TWO_ARM_SCHEDULE,
        session_cap_seconds=360,
        notes="budgets differ",
        schedule_entries=build_multi_schedule(TASKS, LABELS, repeats=1)["entries"],
        hygiene={
            "results/D/r1/hygiene.json": {"gate": "warn"},
            "results/C/r1/hygiene.json": {"candidate": {"gate": "block"}},
        },
    )
    assert report["purpose"] == "smoke"
    assert report["promotion"] == "not_eligible"
    assert report["winner"] is None
    assert report["rule_winner"] is None
    assert report["n_arms"] == 4
    assert report["gates"]["runtime_gates"] == "not_applicable"
    assert report["arms"]["D"]["cap_seconds"] == 270
    assert report["arms"]["D"]["max_tool_calls"] == 48
    assert report["arms"]["C"]["cap_seconds"] == 360
    assert report["arms"]["A"]["max_tool_calls"] == 150
    pair = next(
        item for item in report["comparisons"] if item["left"] == "A" and item["right"] == "D"
    )
    assert pair["only_left"] == 1
    assert pair["winner"] is None
    assert report["arms"]["A"]["empty_patches"] == 1
    assert report["arms"]["A"]["tool_calls"] == 4
    assert report["arms"]["A"]["llm_calls"] == 3
    assert report["arms"]["A"]["wall_p50"] == 100
    assert report["arms"]["A"]["failed_skill_calls"] == "not_available"
    assert report["arms"]["D"]["infra_errors"] == 1
    assert report["arms"]["D"]["hit_cap_wall"] == 1
    assert report["arms"]["D"]["hit_cap_marker"] == 1
    assert report["arms"]["D"]["hygiene"] == "warn"
    assert report["arms"]["C"]["hygiene"] == "block"
    assert report["arms"]["A"]["hygiene"] == "not_computed"
    assert report["authoritative_file"] == "multi_report.json"
    assert report["position_confound"] == CONFOUND
    assert "aborted:infra" in report["infra_abort"]
    text = render_multi_smoke_md(report)
    assert text.startswith("smoke, not promotion eligible\n")
    assert "rule_winner: null" in text
    assert "One repeat cannot name a winner." in text
    assert "single-v7" in text
    assert "multi_report.json is the only authoritative file" in text
    assert "A lone pair_report" in text
    assert CONFOUND in text
    assert "empty patches 1" in text
    assert "p50 100.0s" in text
    assert "# Paired evaluation report" not in text


def test_multi_report_refuses_protocol_mismatch(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    manifest = {
        "protocol_sha256": "0" * 64,
        "schedule_sha256": MULTI_SCHEDULE,
    }
    (run / "pair_manifest.json").write_text(json.dumps(manifest))
    (run / "pair_results.jsonl").write_text("")
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="protocol_sha256"):
        multi_report_from_runs([run], PROTOCOL, output)
    assert not output.exists()


def test_multi_report_refuses_schedule_mismatch(tmp_path):
    protocol = load_multi_protocol(PROTOCOL)
    run = tmp_path / "run"
    run.mkdir()
    manifest = {"protocol_sha256": protocol["_sha256"], "schedule_sha256": "ab" * 32}
    (run / "pair_manifest.json").write_text(json.dumps(manifest))
    (run / "pair_results.jsonl").write_text("")
    with pytest.raises(ValueError, match="schedule hash"):
        multi_report_from_runs([run], PROTOCOL, tmp_path / "report")


def test_multi_report_warns_when_protocol_sha_is_absent(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "pair_manifest.json").write_text(json.dumps({"status": "generated"}))
    (run / "pair_results.jsonl").write_text("")
    with pytest.warns(UserWarning, match="no protocol_sha256"):
        result = multi_report_from_runs([run], PROTOCOL, tmp_path / "report")
    assert result["winner"] is None
    assert result["promotion"] == "not_eligible"
    assert result["n_arms"] == 4


@pytest.mark.skipif(
    not STARTER.is_file(),
    reason="official starter notebook is not in this checkout",
)
def test_generate_multi_notebook_keeps_the_two_arm_runtime(tmp_path):
    output = tmp_path / "notebook"
    result = generate_multi(
        PROTOCOL,
        "charlesaherbst",
        "combined-candidate-smoke",
        output,
        wheelhouse_version=30,
    )
    assert result["arms"] == ARCHIVES
    assert result["schedule_sha256"] == MULTI_SCHEDULE
    assert result["task_schedule_sha256"] == TWO_ARM_SCHEDULE
    assert result["session_cap_seconds"] == 360
    assert result["n_task_runs"] == 20
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    sources = ["".join(cell["source"]) for cell in notebook["cells"]]
    runtime = next(source for source in sources if "def execute_session" in source)
    assert runtime == notebook_runtime_source()
    payload = next(source for source in sources if "ARM_BUDGETS" in source)
    eval_cell = next(source for source in sources if "def make_evaluator" in source)
    assert "LABELS = ('A', 'B', 'C', 'D')" in payload
    assert "for _label in LABELS:" in payload
    assert "build_schedule(" not in payload
    assert "('A', 'B')" not in payload
    assert "('A', 'B')" not in eval_cell
    assert "cap_seconds=360.0" in eval_cell
    assert "max_tool_calls = int(budgets['max_tool_calls'])" in eval_cell
    assert "'max_tool_calls': 48" in payload
    assert "'max_time_minutes': 4.5" in payload
    assert "'max_time_minutes': 6.0" in payload
    assert "SESSION_BUDGET_SECONDS = 14400" in payload
    assert "smoke, not promotion eligible" in sources[0]
    assert "winner" in eval_cell
    assert "_SMOKE_REPORT['winner'] is None" in eval_cell
    rebind = eval_cell.index("\ninstall_smoke_report_bindings()\n")
    session = eval_cell.index("SESSION_RESULT = execute_session(")
    assert eval_cell.index("def multi_smoke_report") < rebind < session
    assert eval_cell.index("PROTOCOL_NOTES = ") < rebind
    assert "multi_report.json is the only authoritative file" in eval_cell
    schedule = json.loads((output / "schedule.json").read_text())
    assert schedule["sha256"] == MULTI_SCHEDULE
    assert schedule["task_schedule_sha256"] == TWO_ARM_SCHEDULE
    assert 'for label in ("A", "B")' in inspect.getsource(generate_pair)


def test_unknown_allowed_difference_is_rejected(tmp_path):
    text = PROTOCOL.read_text().replace(
        "  - thinking.yaml\n",
        "  - thinking.yaml\n  - not-a-real-marker\n",
        1,
    )
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="Unknown allowed_differences"):
        load_multi_protocol(path)


def test_arm_labels_must_be_contiguous(tmp_path):
    text = PROTOCOL.read_text().replace(
        "  D:\n    source: agents/single-v7\n",
        "  E:\n    source: agents/single-v7\n",
        1,
    )
    path = tmp_path / "gap.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="contiguous"):
        load_multi_protocol(path)


def test_matched_v8_pair_still_passes_without_sub_agents():
    protocol = load_multi_protocol(PROTOCOL)
    labels = list(protocol["arms"])
    inspected = {label: inspect_arm(protocol["arms"][label]["source"]) for label in labels}
    assert_multi_compatible(
        inspected,
        ARCHIVES,
        protocol["allowed_differences"],
        allow_identical=False,
    )


def test_markdown_report_replaces_a_temp_file(tmp_path):
    path = tmp_path / "multi_report.md"
    seen = {}
    original = Path.replace

    def spy(self, target):
        seen["tmp"] = Path(self).read_text()
        seen["final_exists"] = path.exists()
        return original(self, target)

    Path.replace = spy
    try:
        write_markdown_atomic(path, "smoke, not promotion eligible\n")
    finally:
        Path.replace = original
    assert seen["tmp"].startswith("smoke, not promotion eligible")
    assert seen["final_exists"] is False
    assert path.read_text().startswith("smoke, not promotion eligible")
    assert not path.with_suffix(".md.tmp").exists()


def test_trace_failure_counts_match_the_tool_failure_parser():
    from gemma_lab.tool_failures import summarize_trace

    payload = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "repair"},
        "steps": [
            {
                "tool_calls": [{"function_name": "run_skill_script", "tool_call_id": "c1"}],
                "observation": {"content": "INVALID_ARGUMENTS: file_path"},
            },
            {
                "tool_calls": [{"function_name": "edit_file", "tool_call_id": "c2"}],
                "observation": {"content": "Failed to replace: old_string not found"},
            },
            {
                "tool_calls": [{"function_name": "edit_file", "tool_call_id": "c3"}],
                "observation": {
                    "content": (
                        '{"status": "ok", "raw": "Failed to replace: old_string not found"}'
                    )
                },
            },
        ],
    }
    counts = count_failed_tool_calls(payload)
    summary = summarize_trace(payload)
    assert counts["failed_skill_calls"] == summary["failed_skill_calls"] == 1
    assert counts["failed_edit_calls"] == summary["failed_edit_calls"] == 1


class _Task:
    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.repo = "example/repo"


class _Result:
    def __init__(self):
        self.resolved = False
        self.error_message = None
        self.test_output = ""
        self.agent_patch = "diff\n"
        self.test_exit_code = 0
        self.tool_calls = 2
        self.duration_seconds = 3.0
        self.trace = None

    def model_dump(self):
        return {"resolved": False, "agent_patch": self.agent_patch}


class _Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def _arm_dirs(tmp_path, labels):
    arms = {}
    for label in labels:
        root = tmp_path / label
        root.mkdir()
        blob = root / "agent.yaml"
        blob.write_text(f"name: {label}\n")
        digest = hashlib.sha256(blob.read_bytes()).hexdigest()
        arms[label] = {
            "sha256": label.lower() * 64,
            "root": root,
            "files": {"agent.yaml": digest},
        }
    return arms


def _smoke_namespace(tmp_path, labels, budgets, schedule_entries):
    import pathlib

    original = pathlib.Path.write_text
    namespace = {"__name__": "notebook_runtime"}
    exec(notebook_runtime_source(), namespace)
    exec(smoke_binding_sources(), namespace)
    namespace["LABELS"] = tuple(labels)
    namespace["ARM_BUDGETS"] = budgets
    namespace["ARM_NAMES"] = {label: label for label in labels}
    namespace["PROTOCOL_NOTES"] = "budgets differ"
    namespace["TASK_SCHEDULE_SHA"] = TWO_ARM_SCHEDULE
    namespace["MULTI_SCHEDULE"] = schedule_entries
    namespace["WORKING_DIR"] = tmp_path / "run"
    namespace["install_smoke_report_bindings"]()
    return namespace, original


def _run_bound_session(tmp_path, labels, budgets, order, clock, cap_seconds=360):
    schedule = [
        {
            "repeat": 1,
            "position": 1,
            "task_id": "t1",
            "p0": 0,
            "order": list(order),
            "pair_id": "p1",
        }
    ]
    namespace, original = _smoke_namespace(
        tmp_path,
        labels,
        budgets,
        build_multi_schedule(TASKS, LABELS, repeats=1)["entries"],
    )
    try:

        def run_evaluate(evaluator, task, dashboard, position, total):
            return _Result()

        if clock is not None:
            held = run_evaluate

            def run_evaluate(evaluator, task, dashboard, position, total):
                clock.advance(clock.step)
                return held(evaluator, task, dashboard, position, total)

        result = namespace["execute_session"](
            schedule=schedule,
            tasks={"t1": _Task("t1")},
            rebuild=lambda label, repeat: label,
            run_evaluate=run_evaluate,
            output_dir=tmp_path / "run",
            arms=_arm_dirs(tmp_path, labels),
            schedule_sha256=MULTI_SCHEDULE,
            cap_seconds=cap_seconds,
            session_budget_seconds=10**9,
            clock=clock or _Clock(),
            session_start=0,
            model_load_seconds=1,
            session_overhead_seconds=1,
            protocol_sha256="p" * 64,
            early_stop=None,
        )
        return result
    finally:
        import pathlib

        pathlib.Path.write_text = original


def test_kill_after_execute_session_leaves_the_smoke_report(tmp_path):
    """The session writes pair_report.* before the tail writes multi_report.json."""
    clock = _Clock()
    clock.step = 1
    _run_bound_session(tmp_path, LABELS, _budgets(), LABELS, clock)
    run = tmp_path / "run"
    assert not (run / "multi_report.json").exists()
    assert not (run / "multi_report.md").exists()
    report = json.loads((run / "pair_report.json").read_text())
    text = (run / "pair_report.md").read_text()
    assert report["purpose"] == "smoke"
    assert report["n_arms"] == 4
    assert report["winner"] is None
    assert report["promotion"] == "not_eligible"
    assert report["authoritative_file"] == "multi_report.json"
    assert "paired" not in report
    assert "decision_rule" not in report
    assert text.startswith("smoke, not promotion eligible\n")
    assert "# Paired evaluation report" not in text
    assert CONFOUND in text
    assert not (run / "pair_report.md.tmp").exists()


def test_pair_results_hit_cap_uses_each_arm_cap(tmp_path):
    labels = ["A", "D"]
    budgets = {"A": _budgets()["A"], "D": _budgets()["D"]}
    clock = _Clock()
    clock.step = 300
    _run_bound_session(tmp_path, labels, budgets, labels, clock, cap_seconds=360)
    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "pair_results.jsonl").read_text().splitlines()
    ]
    by_arm = {row["arm"]: row for row in rows}
    assert by_arm["A"]["hit_cap"]["wall"] is False
    assert by_arm["A"]["hit_cap"]["cap_seconds"] == 330
    assert by_arm["D"]["hit_cap"]["wall"] is True
    assert by_arm["D"]["hit_cap"]["cap_seconds"] == 270


def test_wall_abort_uses_each_arm_cap(tmp_path):
    """400 s exceeds arm D's 270 + 120 and does not exceed the 360 s session cap + 120."""
    labels = ["D"]
    budgets = {"D": _budgets()["D"]}
    clock = _Clock()
    clock.step = 400
    result = _run_bound_session(tmp_path, labels, budgets, labels, clock, cap_seconds=360)
    assert result["status"] == "aborted:budget_anomaly"
