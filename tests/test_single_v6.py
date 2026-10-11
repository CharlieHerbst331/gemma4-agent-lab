"""single-v6 is single-v5 plus two prompt rules. The dev-13 pair is matched."""

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

V5 = Path("agents/single-v5")
V6 = Path("agents/single-v6")
PROTOCOL = Path("configs/protocols/single-v5-vs-single-v6-dev13.yaml")
DEV13 = Path("configs/protocols/v6-vs-single-v3.yaml")
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


def test_single_v6_changes_only_the_prompt():
    assert _files(V5) == _files(V6)
    for name in ("agent.yaml", "thinking.yaml", "eval_config.yaml"):
        assert (V5 / name).read_bytes() == (V6 / name).read_bytes()
    prompt = (V6 / "prompts" / "system.md").read_text()
    parent = (V5 / "prompts" / "system.md").read_text()
    assert prompt != parent
    assert len(parent) == 6984
    assert len(prompt) == 7459
    for phrase in (
        "Nothing rendered is not the same as None.",
        "empty-but-non-None",
        "Group()",
        "zero-width render",
        "After two failed edit_file calls on the same file",
        "str.replace",
        "print the diff with git diff",
        "pass it through the public wrapper too",
        "Check where the public API constructs the class.",
        "about 12 counted calls or about 95 seconds",
        "By call 24 you must have edited a source file",
        "only a bare issue number, such as Fix #3104",
    ):
        assert phrase in prompt
    assert prompt.count("After two failed edit_file calls on the same file") == 1
    assert "After a second failure" not in prompt
    for banned in ("run_skill_script", "skill_name", "SKILL.md", "scripts/check.py"):
        assert banned not in prompt
    assert prompt.count("check.py") == prompt.count("repro_check.py")
    report = lint_candidate(V6)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_dev13_protocol_is_a_matched_promotion_pair():
    protocol = load_protocol(PROTOCOL)
    assert protocol.get("purpose") != "smoke"
    assert protocol["matched_pair"] is True
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == COHORT
    assert protocol["arms"]["A"]["source"] == "agents/single-v5"
    assert protocol["arms"]["B"]["source"] == "agents/single-v6"
    assert "thinking.yaml" not in protocol["allowed_differences"]
    assert "prompts/*" in protocol["allowed_differences"]
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 13
    assert schedule["sha256"] == DEV_SCHEDULE
    sibling = load_protocol(DEV13)
    assert protocol_schedule(sibling)["sha256"] == DEV_SCHEDULE
    assert sibling["_task_ids"] == protocol["_task_ids"]
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
    _arm_row(run, "A", "fastapi_11194", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "fastapi_11194", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], PROTOCOL, output)
    text = (output / "pair_report.md").read_text()
    assert not text.startswith("smoke, not promotion eligible")
    assert "not promotion eligible" not in text.splitlines()[0]
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
