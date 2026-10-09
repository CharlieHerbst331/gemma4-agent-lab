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


def atif(agent, steps):
    built = []
    for index, (tool, arguments, output) in enumerate(steps, start=1):
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
                "observation": {"results": [{"source_call_id": f"c{index}", "content": output}]},
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
        ("edit_file", {"path": "pkg/core.py"}, "missing-parameter: old_string"),
        ("edit_file", {"path": "pkg/core.py"}, "missing-parameter: new_string"),
        ("submit_patch", {}, "ok"),
    ]
    summary = summarize_trace(atif("repair", steps))
    assert summary["failed_skill_calls"] == 4
    assert summary["failed_edit_calls"] == 2
    assert summary["max_consecutive_failures"] == 6
    assert summary["unrecovered_loop"] is True
    assert summary["submit_patch_count"] == 1
    assert summary["trace_schema"] == "atif"

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
    assert "| A | r1 | fastapi_14786 | 4 | 2 | 6 | True | 1 | scratch-only |" in text
    assert "| B | r1 | fastapi_14786 | 0 | 0 | 0 | False | 1 | empty |" in text
    assert "Hygiene A/r1:" in text
    assert (run / "results" / "A" / "r1" / "hygiene.json").is_file()
    assert (run / "results" / "B" / "r1" / "hygiene.json").is_file()


def _arm(root, arm, task_id, trace, patch):
    folder = root / "results" / arm / "r1"
    (folder / "patches").mkdir(parents=True)
    (folder / "traces").mkdir()
    (folder / "patches" / f"{task_id}.patch").write_text(patch)
    (folder / "traces" / f"trace_{task_id}.json").write_text(json.dumps(trace))
    (folder / "task_results.jsonl").write_text(
        json.dumps({"instance_id": task_id, "resolved": False}) + "\n"
    )
