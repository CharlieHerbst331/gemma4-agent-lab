"""Combined four-arm smoke. Existing two-arm notebooks stay on notebook-pair."""

import inspect
import json
from pathlib import Path

import pytest

from gemma_lab.multi_arm import (
    build_multi_schedule,
    generate_multi,
    largest_integer_mean_that_passes,
    load_multi_protocol,
    multi_report_from_runs,
    multi_smoke_report,
    option2_wall_seconds,
    pair_fits_minimum_budget,
    render_multi_smoke_md,
    submission_gate_picture,
    worst_session_wall_seconds,
)
from gemma_lab.notebook import generate_pair
from gemma_lab.paired import build_schedule, load_protocol, notebook_runtime_source

PROTOCOL = Path("configs/protocols/combined-candidate-smoke.yaml")
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


def test_agent_directories_stay_at_twenty_one():
    found = {path.name for path in Path("agents").iterdir() if path.is_dir()}
    assert found == AGENT_DIRS
    assert "single-v7-lenient" not in found


def test_existing_protocols_remain_two_arm():
    paths = sorted(Path("configs/protocols").glob("*.yaml"))
    others = [path for path in paths if path != PROTOCOL]
    assert len(others) == 12
    for path in others:
        protocol = load_protocol(path)
        assert set(protocol["arms"]) == {"A", "B"}


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


def test_smoke_report_names_no_winner():
    rows = [
        {"arm": "A", "task_id": "rich_4070", "resolved": True, "wall_seconds": 100},
        {"arm": "B", "task_id": "rich_4070", "resolved": False, "wall_seconds": 110},
        {"arm": "C", "task_id": "rich_4070", "resolved": True, "wall_seconds": 120},
        {"arm": "D", "task_id": "rich_4070", "resolved": False, "wall_seconds": 90},
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
    text = render_multi_smoke_md(report)
    assert text.startswith("smoke, not promotion eligible\n")
    assert "rule_winner: null" in text
    assert "One repeat cannot name a winner." in text
    assert "single-v7" in text


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
    schedule = json.loads((output / "schedule.json").read_text())
    assert schedule["sha256"] == MULTI_SCHEDULE
    assert schedule["task_schedule_sha256"] == TWO_ARM_SCHEDULE
    assert 'for label in ("A", "B")' in inspect.getsource(generate_pair)
