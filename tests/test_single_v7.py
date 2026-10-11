"""single-v7 stops edit_file after one old_string miss. The dev-13 pair is matched."""

import json
from pathlib import Path

from gemma_lab.hygiene import lint_candidate
from gemma_lab.paired import (
    assert_arms_compatible,
    inspect_arm,
    load_protocol,
    protocol_schedule,
    report_from_runs,
)

V6 = Path("agents/single-v6")
V7 = Path("agents/single-v7")
PROTOCOL = Path("configs/protocols/single-v6-vs-single-v7-dev13.yaml")
SIBLING = Path("configs/protocols/single-v5-vs-single-v6-dev13.yaml")
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
COHORT = [
    "fastapi_11194",
    "fastapi_14246",
    "fastapi_14262",
    "fastapi_14356",
    "fastapi_14786",
    "fastapi_14794",
    "rich_3105",
    "rich_3454",
    "rich_3472",
    "rich_3934",
    "rich_3938",
    "rich_3944",
    "rich_4070",
]


def _files(root):
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_single_v7_changes_only_the_prompt():
    assert _files(V6) == _files(V7)
    for name in ("agent.yaml", "thinking.yaml", "eval_config.yaml"):
        assert (V6 / name).read_bytes() == (V7 / name).read_bytes()
    prompt = (V7 / "prompts" / "system.md").read_text()
    parent = (V6 / "prompts" / "system.md").read_text()
    assert prompt != parent
    assert len(parent) == 7459
    assert len(prompt) == 7619
    for phrase in (
        "After one missing-parameter error, retry a smaller edit.",
        "Never repeat the same failing edit_file call more than once.",
        "could not find old_string",
        "stop using edit_file on that file",
        "assert old in s",
        "assert the old string was present before and the new string is present after",
        "When adding a new parameter to an internal class",
        "Check where the public API constructs the class.",
        "If that rewrite fails too, stop editing and call submit_patch with the current diff.",
    ):
        assert phrase in prompt
    wrapper = prompt.index("When adding a new parameter")
    miss = prompt.index("could not find old_string")
    fallback = prompt.index("If that rewrite fails too")
    assert wrapper < miss < fallback
    assert "After two failed edit_file calls" not in prompt
    assert prompt.count("If the same tool call fails twice, change the call or the tool") == 1
    report = lint_candidate(V7)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_dev13_protocol_is_a_matched_promotion_pair():
    protocol = load_protocol(PROTOCOL)
    assert protocol.get("purpose") != "smoke"
    assert protocol["matched_pair"] is True
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == COHORT
    assert protocol["arms"]["A"]["source"] == "agents/single-v6"
    assert protocol["arms"]["B"]["source"] == "agents/single-v7"
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 13
    assert schedule["sha256"] == DEV_SCHEDULE
    sibling = load_protocol(SIBLING)
    assert protocol_schedule(sibling)["sha256"] == DEV_SCHEDULE
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert arms["A"]["sampling"] == arms["B"]["sampling"]
    assert arms["A"]["budgets"] == arms["B"]["budgets"]
    assert_arms_compatible(
        arms["A"],
        arms["B"],
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a="a" * 64,
        sha_b="b" * 64,
        matched_pair=True,
    )


def test_dev13_report_is_not_a_smoke(tmp_path):
    run = tmp_path / "run"
    _arm_row(run, "A", "rich_4070", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "rich_4070", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], PROTOCOL, output)
    text = (output / "pair_report.md").read_text()
    assert not text.startswith("smoke, not promotion eligible")
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved.get("purpose") != "smoke"
    assert saved["schedule_sha256"] == DEV_SCHEDULE


def _arm_row(root, arm, task_id, steps):
    folder = root / "results" / arm / "r1"
    (folder / "patches").mkdir(parents=True)
    (folder / "traces").mkdir()
    (folder / "patches" / f"{task_id}.patch").write_text("")
    trace = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": arm},
        "steps": [
            {
                "step_id": index,
                "source": "agent",
                "tool_calls": [
                    {
                        "tool_call_id": f"c{index}",
                        "function_name": tool,
                        "arguments": arguments,
                    }
                ],
                "observation": {"results": [{"source_call_id": f"c{index}", "content": output}]},
            }
            for index, (tool, arguments, output) in enumerate(steps, start=1)
        ],
    }
    (folder / "traces" / f"trace_{task_id}.json").write_text(json.dumps(trace))
    (folder / "task_results.jsonl").write_text(
        json.dumps({"instance_id": task_id, "resolved": False}) + "\n"
    )
    with (root / "pair_results.jsonl").open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "arm": arm,
                    "repeat": 1,
                    "task_id": task_id,
                    "resolved": False,
                    "wall_seconds": 10,
                    "hit_cap": {},
                }
            )
            + "\n"
        )
