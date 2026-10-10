"""single-v5 is a prompt-only copy of single-v4. think256 changes only thinking.yaml."""

import json
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml
from gemma_lab.hygiene import lint_candidate
from gemma_lab.paired import (
    assert_arms_compatible,
    inspect_arm,
    load_protocol,
    protocol_schedule,
    report_from_runs,
)

V4 = Path("agents/single-v4")
V5 = Path("agents/single-v5")
THINK = Path("agents/single-v5-think256")
PROTOCOL = Path("configs/protocols/single-v5-vs-single-v5-think256-smoke.yaml")
SMOKE_IDS = [
    "fastapi_14786",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "fastapi_14262",
]
ORIGINAL_SMOKE = "31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345"
FULL_SCHEDULE = "e146f4d602957611c53428087c43ba8201d66a9881c4648d8f239f572a23e030"
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
REVERSED_SMOKE = "0c4e0c31473075ab9cfed9cf305a3ed988e274c9da1d684630136b2b16d18704"
NOTES = (
    "The arms differ in thinking.yaml only. Arm B has thinking ON at budget 256. "
    "The observed per-call overhead can't be gated; the gates don't apply to smoke."
)
CALL_24 = (
    "By call 24 you must have edited a source file. If you haven't, stop reading now, "
    "make the most plausible minimal edit implied by the issue, then verify it."
)
GIT_STATUS = (
    "Before submit_patch, run git status --short and git diff --stat so no scratch or "
    "test file is in the patch. Remove any stray repro file with rm. Skip that git step "
    "when fewer than 60 s remain and on the issue-number-only UNCERTAIN path. git status "
    "--short may show harness-staged files such as A conftest.py and A pytest.ini before "
    "any edit; those are expected and are not stray repro files, so do not remove them."
)
UNDER_60 = (
    "If under 20 s remain, submit as is. Do not start a best-guess edit. If\n"
    "get_status shows fewer than 60 seconds remain and a source edit exists, call\n"
    "submit_patch immediately, even when the check failed. Do not rerun the repro."
)


def _files(root):
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_single_v5_changes_only_the_prompt():
    assert _files(V4) == _files(V5)
    for name in ("agent.yaml", "thinking.yaml", "eval_config.yaml"):
        assert (V4 / name).read_bytes() == (V5 / name).read_bytes()
    prompt = (V5 / "prompts" / "system.md").read_text()
    parent = (V4 / "prompts" / "system.md").read_text()
    assert prompt != parent
    assert len(parent) == 6699
    assert len(prompt) == 7097
    for phrase in (
        CALL_24,
        "The call-24 line above is the hard rule.",
        "about 12 counted calls or about 95 seconds",
        "primary rule",
        "Never weaken, delete or loosen an assert in a repro to make it pass.",
        "stray newline in output",
        "The failing assert stays until the code fix makes it pass.",
        "title with no description of behavior",
        "If the issue text describes any behavior, UNCERTAIN, 'not a bug', and 'already fixed'",
        "UNCERTAIN is only the no-behavior-clue path above.",
        "Call read_file with filepath only",
        "sed -n '151,300p' rich/live.py | head -c 4000",
        GIT_STATUS,
        UNDER_60,
    ):
        assert phrase in prompt
    for gone in ("about 30 counted calls", "about 18", "backstop"):
        assert gone not in prompt
    report = lint_candidate(V5)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_think256_changes_only_thinking_yaml():
    assert _files(V5) == _files(THINK)
    for name in _files(V5):
        if name == "thinking.yaml":
            continue
        assert (V5 / name).read_bytes() == (THINK / name).read_bytes()
    thinking = load_yaml(THINK / "thinking.yaml", THINK)
    assert thinking["include_thoughts"] is True
    assert thinking["thinking_budget"] == 256
    text = (THINK / "thinking.yaml").read_text()
    assert "270" in text
    assert "4096" in text
    assert "26 ms" in text
    assert (V4 / "eval_config.yaml").read_bytes() == (V5 / "eval_config.yaml").read_bytes()
    assert (V5 / "eval_config.yaml").read_bytes() == (THINK / "eval_config.yaml").read_bytes()
    assert inspect_arm(V5)["sampling"] == [(0.5, 0.95, 0, False)]
    assert inspect_arm(THINK)["sampling"] == [(0.5, 0.95, 256, True)]
    assert inspect_arm(V5)["budgets"] == inspect_arm(THINK)["budgets"]
    report = lint_candidate(THINK)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_smoke_protocol_allows_only_this_thinking_difference():
    protocol = load_protocol(PROTOCOL)
    assert protocol["purpose"] == "smoke"
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == SMOKE_IDS
    assert "matched_pair" not in protocol
    assert protocol["notes"] == NOTES
    assert "thinking.yaml" in protocol["allowed_differences"]
    assert protocol["arms"]["A"]["source"] == "agents/single-v5"
    assert protocol["arms"]["B"]["source"] == "agents/single-v5-think256"
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 5
    assert schedule["sha256"] == ORIGINAL_SMOKE
    frozen = {
        "v5-vs-single-v1.yaml": FULL_SCHEDULE,
        "v6-vs-single-v2.yaml": FULL_SCHEDULE,
        "v6-vs-single-v3.yaml": DEV_SCHEDULE,
        "v6-vs-single-v2-toolcall-smoke.yaml": ORIGINAL_SMOKE,
        "single-v2-vs-single-v3-toolcall-smoke.yaml": REVERSED_SMOKE,
        "single-v3-vs-single-v4-toolcall-smoke.yaml": ORIGINAL_SMOKE,
    }
    for name, digest in frozen.items():
        loaded = load_protocol(Path("configs/protocols") / name)
        assert protocol_schedule(loaded)["sha256"] == digest
        assert "thinking.yaml" not in loaded["allowed_differences"]
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert_arms_compatible(
        arms["A"],
        arms["B"],
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a="a" * 64,
        sha_b="b" * 64,
        matched_pair=True,
    )
    ordinary = [item for item in protocol["allowed_differences"] if item != "thinking.yaml"]
    with pytest.raises(ValueError, match="thinking_budget"):
        assert_arms_compatible(
            arms["A"],
            arms["B"],
            allow_identical=False,
            allowed_differences=ordinary,
            sha_a="a" * 64,
            sha_b="b" * 64,
            matched_pair=True,
        )


def test_smoke_report_names_thinking_on_and_skips_gates(tmp_path):
    run = tmp_path / "run"
    _arm_row(run, "A", "fastapi_14786", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "fastapi_14786", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], PROTOCOL, output)
    text = (output / "pair_report.md").read_text()
    assert text.startswith("smoke, not promotion eligible\n")
    head = "\n".join(text.splitlines()[:8])
    assert "Arm B has thinking ON at budget 256" in head
    assert "the gates don't apply to smoke" in head
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["purpose"] == "smoke"
    assert saved["notes"] == NOTES
    assert saved["decision_rule"]["promotion"] != "promote"
    assert "not applicable" in saved["decision_rule"]["note"]


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
