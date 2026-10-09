"""Smoke subset of the dev-13 pair. No GPU run and no agent edits."""

import json
from pathlib import Path

import pytest

from gemma_lab.paired import load_cohort_ids, load_protocol, protocol_schedule, report_from_runs

SMOKE = Path("configs/protocols/v6-vs-single-v2-toolcall-smoke.yaml")
COHORT = Path("configs/cohorts/dev-13-environment-screened.json")
FULL_SCHEDULE = "e146f4d602957611c53428087c43ba8201d66a9881c4648d8f239f572a23e030"
SMOKE_SCHEDULE = "31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345"
SMOKE_IDS = [
    "fastapi_14786",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "fastapi_14262",
]
SCRATCH_PATCH = """diff --git a/repro.py b/repro.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/repro.py
@@ -0,0 +1 @@
+x = 1
"""
CODE_PATCH = """diff --git a/pkg/core.py b/pkg/core.py
index 1111111..2222222 100644
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -1 +1 @@
-a = 1
+a = 2
"""
# ATIF observation.content from the harness when edit_file omits a required argument.
HARNESS_EDIT_FAILURE = (
    "Invoking `edit_file()` failed as the following mandatory input parameters are not present"
)


def atif(agent, steps, *, content=False):
    built = []
    for index, (tool, arguments, output) in enumerate(steps, start=1):
        if content:
            observation = {"content": output}
        else:
            observation = {"results": [{"source_call_id": f"c{index}", "content": output}]}
        built.append(
            {
                "step_id": index,
                "source": "agent",
                "extra": {"author": agent},
                "tool_calls": [
                    {
                        "tool_call_id": f"c{index}",
                        "function_name": tool,
                        "arguments": arguments,
                    }
                ],
                "observation": observation,
            }
        )
    return {"schema_version": "ATIF-v1.7", "agent": {"name": agent}, "steps": built}


def test_smoke_protocol_is_five_tasks_and_a_different_schedule():
    cohort = load_cohort_ids(COHORT)
    for task_id in SMOKE_IDS:
        assert task_id in cohort
    protocol = load_protocol(SMOKE)
    assert protocol["purpose"] == "smoke"
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == SMOKE_IDS
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 5
    assert schedule["sha256"] == SMOKE_SCHEDULE
    assert schedule["sha256"] != FULL_SCHEDULE
    assert not schedule["sha256"].startswith("e146f4d60295")
    for name in ("v5-vs-single-v1.yaml", "v6-vs-single-v2.yaml"):
        frozen = load_protocol(Path("configs/protocols") / name)
        assert frozen.get("task_ids") is None
        assert frozen["_task_ids"] == cohort
        assert protocol_schedule(frozen)["sha256"] == FULL_SCHEDULE


def test_holdout_and_unknown_task_ids_are_rejected(tmp_path):
    text = SMOKE.read_text()
    listed = "\n  - fastapi_14786\n"
    holdout = tmp_path / "holdout.yaml"
    holdout.write_text(text.replace(listed, "\n  - fastapi_13537\n", 1))
    with pytest.raises(ValueError, match="holdout"):
        load_protocol(holdout)
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(text.replace(listed, "\n  - not_a_real_task\n", 1))
    with pytest.raises(ValueError, match="unknown"):
        load_protocol(unknown)


def test_smoke_report_banner_and_stub_tool_failures(tmp_path):
    from gemma_lab.tool_failures import summarize_trace

    nested = {"args": {"skill_name": "verify-patch", "file_path": "scripts/check.py"}}
    top_level = {"skill_name": "verify-patch", "file_path": "scripts/check.py", "args": {}}
    steps = [
        ("run_skill_script", nested, "INVALID_ARGUMENTS: Argument file_path is required"),
        ("run_skill_script", nested, "INVALID_ARGUMENTS: Argument file_path is required"),
        ("run_skill_script", top_level, "usage: check.py [-h] --mode {audit,repro}"),
        (
            "run_skill_script",
            top_level,
            "mode and phase were both omitted. Corrected example call: {}",
        ),
        ("edit_file", {"path": "pkg/core.py"}, HARNESS_EDIT_FAILURE),
        ("edit_file", {"path": "pkg/core.py"}, HARNESS_EDIT_FAILURE + ": old_string"),
        ("submit_patch", {}, "ok"),
    ]
    summary = summarize_trace(atif("repair", steps, content=True))
    assert summary["failed_skill_calls"] == 4
    assert summary["failed_edit_calls"] == 2
    assert summary["max_consecutive_failures"] == 6
    assert summary["tail_streak"] == 0
    assert summary["submit_patch_count"] == 1
    assert summary["trace_schema"] == "atif"
    kept = summarize_trace(
        atif("repair", [("edit_file", {"path": "pkg/core.py"}, "missing-parameter: old_string")])
    )
    assert kept["failed_edit_calls"] == 1

    run = tmp_path / "run"
    _arm(run, "A", "fastapi_14786", atif("repair", steps), SCRATCH_PATCH)
    _arm(run, "B", "fastapi_14786", atif("single", [("submit_patch", {}, "ok")]), "")
    (run / "pair_results.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "arm": arm,
                    "repeat": 1,
                    "task_id": "fastapi_14786",
                    "resolved": False,
                    "wall_seconds": 10,
                    "hit_cap": {},
                }
            )
            + "\n"
            for arm in ("A", "B")
        )
    )
    output = tmp_path / "report"
    report_from_runs([run], SMOKE, output)
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["purpose"] == "smoke"
    assert saved["decision_rule"]["rule_winner"] is None
    assert saved["decision_rule"]["conditions"]["budget"] == "not applicable for smoke"
    text = (output / "pair_report.md").read_text()
    assert text.startswith("smoke, not promotion eligible\n")
    assert "not applicable for smoke" in text
    assert "passed=True" not in text
    assert "passed=False" not in text
    assert "rule_winner: null" in text
    assert "tail streak" in text
    assert "AB, BA, AB, BA, AB" in text
    assert "gemma-lab pair-report" in text
    assert "projection.json" in text
    assert "| A | r1 | fastapi_14786 | 4 | 2 | 6 | True | 1 | scratch-only |" in text
    assert "| B | r1 | fastapi_14786 | 0 | 0 | 0 | True | 1 | empty |" in text
    assert "Hygiene A/r1:" in text
    assert (run / "results" / "A" / "r1" / "hygiene.json").is_file()
    assert (run / "results" / "B" / "r1" / "hygiene.json").is_file()


def test_real_harness_edit_string_and_unrecovered_conditions(tmp_path):
    """Fixture traces. The r1b run directory is not on this machine.

    The edit observations use the harness sentence verbatim, on ATIF
    ``observation.content``. Counts match the r1b correction: B rich_3934 is
    25 failed edits in one streak ending in an empty submit, and A
    fastapi_14262 has 3 failed edits. A fastapi_14356 and A rich_3938 each
    have one success after the long streak and still ran to the cap.
    """
    from gemma_lab.tool_failures import collect_tool_failures

    run = tmp_path / "run"
    _write_task(
        run,
        "B",
        "rich_3934",
        atif("single", _edits(25) + [("submit_patch", {}, "ok")], content=True),
        "",
    )
    _write_task(
        run,
        "A",
        "fastapi_14262",
        atif("repair", _edits(3), content=True),
        "",
    )
    _write_task(
        run,
        "A",
        "fastapi_14356",
        atif("repair", _edits(21) + _success(), content=True),
        CODE_PATCH,
    )
    _write_task(
        run,
        "A",
        "rich_3938",
        atif("repair", _edits(12) + _success(), content=True),
        CODE_PATCH,
        task_row={
            "agent_error": "Agent exceeded session timeout (4.5 min)",
            "failure_class": "agent_budget",
        },
    )
    _write_task(
        run,
        "A",
        "recovered_edit",
        atif("repair", _edits(4) + _success(), content=True),
        CODE_PATCH,
    )
    _write_task(
        run,
        "B",
        "tail_streak",
        atif(
            "single",
            [
                ("edit_file", {"path": "pkg/core.py"}, "applied"),
                ("submit_patch", {}, "ok"),
                *_edits(3),
            ],
            content=True,
        ),
        CODE_PATCH,
    )
    (run / "pair_results.jsonl").write_text(
        json.dumps(
            {
                "arm": "A",
                "repeat": 1,
                "task_id": "fastapi_14356",
                "resolved": False,
                "hit_cap": {"wall": True, "marker": False},
            }
        )
        + "\n"
    )
    rows = {(row["arm"], row["task_id"]): row for row in collect_tool_failures(run)}
    rich = rows[("B", "rich_3934")]
    assert rich["failed_skill_calls"] == 0
    assert rich["failed_edit_calls"] == 25
    assert rich["max_consecutive_failures"] == 25
    assert rich["tail_streak"] == 0
    assert rich["unrecovered_loop"] is True
    assert rich["submit_patch_count"] == 1
    assert rich["patch"] == "empty"
    edited = rows[("A", "fastapi_14262")]
    assert edited["failed_edit_calls"] == 3
    assert edited["max_consecutive_failures"] == 3
    assert edited["unrecovered_loop"] is True
    capped = rows[("A", "fastapi_14356")]
    assert capped["failed_edit_calls"] == 21
    assert capped["max_consecutive_failures"] == 21
    assert capped["tail_streak"] == 0
    assert capped["submit_patch_count"] == 1
    assert capped["patch"] == "other"
    assert capped["unrecovered_loop"] is True
    other = rows[("A", "rich_3938")]
    assert other["failed_edit_calls"] == 12
    assert other["max_consecutive_failures"] == 12
    assert other["patch"] == "other"
    assert other["unrecovered_loop"] is True
    recovered = rows[("A", "recovered_edit")]
    assert recovered["max_consecutive_failures"] == 4
    assert recovered["unrecovered_loop"] is False
    tail = rows[("B", "tail_streak")]
    assert tail["tail_streak"] == 3
    assert tail["submit_patch_count"] == 1
    assert tail["patch"] == "other"
    assert tail["unrecovered_loop"] is True


def _edits(count):
    return [("edit_file", {"path": "pkg/core.py"}, HARNESS_EDIT_FAILURE) for _ in range(count)]


def _success():
    return [
        ("edit_file", {"path": "pkg/core.py"}, "applied"),
        ("submit_patch", {}, "ok"),
    ]


def _write_task(root, arm, task_id, trace, patch, task_row=None):
    folder = root / "results" / arm / "r1"
    (folder / "patches").mkdir(parents=True, exist_ok=True)
    (folder / "traces").mkdir(exist_ok=True)
    (folder / "patches" / f"{task_id}.patch").write_text(patch)
    (folder / "traces" / f"trace_{task_id}.json").write_text(json.dumps(trace))
    row = {"instance_id": task_id, "resolved": False}
    if task_row:
        row.update(task_row)
    with (folder / "task_results.jsonl").open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def _arm(root, arm, task_id, trace, patch):
    folder = root / "results" / arm / "r1"
    (folder / "patches").mkdir(parents=True)
    (folder / "traces").mkdir()
    (folder / "patches" / f"{task_id}.patch").write_text(patch)
    (folder / "traces" / f"trace_{task_id}.json").write_text(json.dumps(trace))
    (folder / "task_results.jsonl").write_text(
        json.dumps({"instance_id": task_id, "resolved": False}) + "\n"
    )
