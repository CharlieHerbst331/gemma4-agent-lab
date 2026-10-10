"""single-v3 has no skills. The two new protocols are unmatched and not the old schedules."""

import json
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml
from gemma_lab.hygiene import lint_candidate
from gemma_lab.paired import (
    assert_arms_compatible,
    inspect_arm,
    load_protocol,
    notebook_runtime_source,
    protocol_schedule,
    report_from_runs,
)

ROOT = Path("agents")
V2 = ROOT / "single-v2"
V3 = ROOT / "single-v3"
DEV = Path("configs/protocols/v6-vs-single-v3.yaml")
SMOKE = Path("configs/protocols/single-v2-vs-single-v3-toolcall-smoke.yaml")
OLD_SMOKE = Path("configs/protocols/v6-vs-single-v2-toolcall-smoke.yaml")
FULL_SCHEDULE = "e146f4d602957611c53428087c43ba8201d66a9881c4648d8f239f572a23e030"
OLD_SMOKE_SCHEDULE = "31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345"
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
NEW_SMOKE_SCHEDULE = "0c4e0c31473075ab9cfed9cf305a3ed988e274c9da1d684630136b2b16d18704"
SMOKE_IDS = [
    "fastapi_14786",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "fastapi_14262",
]
UNMATCHED = "not a matched pair: arm A uses skills, arm B has none"
BANNED = ("run_skill_script", "skill_name", "check.py", "SKILL.md")


def test_single_v3_drops_skills_and_keeps_the_other_files():
    assert not (V3 / "skills").exists()
    assert (V2 / "thinking.yaml").read_bytes() == (V3 / "thinking.yaml").read_bytes()
    assert (V2 / "eval_config.yaml").read_bytes() == (V3 / "eval_config.yaml").read_bytes()
    prompt = (V3 / "prompts" / "system.md").read_text()
    parent = (V2 / "prompts" / "system.md").read_text()
    assert len(prompt) <= len(parent)
    for banned in BANNED:
        assert banned not in prompt
    for phrase in (
        "about 12 counted calls or about 95 seconds",
        "primary rule",
        "hard backstop",
        "about 30 counted calls",
        "few plain lines",
        "retry a smaller edit",
        "stop editing and call submit_patch with the current diff",
        "If the same tool call fails twice, change the call or the tool",
        "never write repro*.py in /workspace or the repo",
        "python - <<'EOF'",
        "Do not nest quotes",
        "unquoted heredoc",
        "python -m pytest <path>::<test> -x -q -p no:cacheprovider",
        "git status --short",
        "git diff --stat",
        "Fix #3104",
        "Do not search",
        "module.__file__",
    ):
        assert phrase in prompt
    left = load_yaml(V2 / "agent.yaml", V2)
    right = load_yaml(V3 / "agent.yaml", V3)
    assert right["tools"] == left["tools"]
    assert "skills" not in right
    for name in ("run_command", "read_file", "edit_file", "get_status", "submit_patch"):
        assert name in right["tools"]
    report = lint_candidate(V3)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_new_protocols_load_and_use_distinct_schedules():
    dev = load_protocol(DEV)
    smoke = load_protocol(SMOKE)
    assert dev["matched_pair"] is False
    assert smoke["matched_pair"] is False
    assert dev["repeats"] == 1
    assert smoke["repeats"] == 1
    assert smoke["purpose"] == "smoke"
    assert dev.get("purpose") is None
    assert dev["arms"]["A"]["source"] == "agents/structured-v6"
    assert dev["arms"]["B"]["source"] == "agents/single-v3"
    assert smoke["arms"]["A"]["source"] == "agents/single-v2"
    assert smoke["arms"]["B"]["source"] == "agents/single-v3"
    assert UNMATCHED in dev["notes"]
    assert "multi-agent" in dev["notes"]
    assert UNMATCHED in smoke["notes"]
    assert "skill removal and the run_command recipe" in smoke["notes"]
    assert set(smoke["_task_ids"]) == set(SMOKE_IDS)
    assert smoke["_task_ids"] == list(reversed(SMOKE_IDS))
    dev_hash = protocol_schedule(dev)["sha256"]
    smoke_hash = protocol_schedule(smoke)["sha256"]
    assert dev_hash == DEV_SCHEDULE
    assert smoke_hash == NEW_SMOKE_SCHEDULE
    assert len({dev_hash, smoke_hash, FULL_SCHEDULE, OLD_SMOKE_SCHEDULE}) == 4
    for protocol in (dev, smoke):
        arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
        assert_arms_compatible(
            arms["A"],
            arms["B"],
            allow_identical=protocol["allow_identical"],
            allowed_differences=protocol["allowed_differences"],
            sha_a="a" * 64,
            sha_b="b" * 64,
            matched_pair=protocol["matched_pair"],
        )


def test_existing_protocols_are_unchanged():
    expected = {
        "v5-vs-single-v1.yaml": FULL_SCHEDULE,
        "v6-vs-single-v2.yaml": FULL_SCHEDULE,
        "v6-vs-single-v2-toolcall-smoke.yaml": OLD_SMOKE_SCHEDULE,
    }
    for name, schedule in expected.items():
        path = Path("configs/protocols") / name
        text = path.read_text()
        assert "matched_pair" not in text
        assert "agents/single-v3" not in text
        protocol = load_protocol(path)
        assert "matched_pair" not in protocol
        assert protocol_schedule(protocol)["sha256"] == schedule
    assert "matched_pair" not in notebook_runtime_source()


def test_unmatched_flag_is_rejected_where_not_allowed(tmp_path):
    base = Path("configs/protocols/v6-vs-single-v2.yaml").read_text()
    bad_type = tmp_path / "type.yaml"
    bad_type.write_text(base + 'matched_pair: "no"\n')
    with pytest.raises(ValueError, match="true or false"):
        load_protocol(bad_type)
    missing_notes = tmp_path / "notes.yaml"
    missing_notes.write_text(base + "matched_pair: false\n")
    with pytest.raises(ValueError, match="not allowed"):
        load_protocol(missing_notes)
    left = _mini(tmp_path / "left")
    right = _mini(tmp_path / "right")
    (left / "limits.txt").write_text("1\n")
    (right / "limits.txt").write_text("2\n")
    inspected = (inspect_arm(left), inspect_arm(right))
    with pytest.raises(ValueError, match="allowed_differences"):
        _pair(*inspected, matched_pair=True)
    _pair(*inspected, matched_pair=False)
    (right / "eval_config.yaml").write_text(
        "evaluation:\n  timeout_seconds: 300\n  max_tool_calls: 48\n"
        "  max_time_minutes: 6\n  max_turns: 48\n"
    )
    with pytest.raises(ValueError, match="budgets"):
        _pair(inspect_arm(left), inspect_arm(right), matched_pair=False)
    with pytest.raises(ValueError, match="true or false"):
        _pair(*inspected, matched_pair="no")


def test_report_banners_and_skill_table_without_skills(tmp_path):
    dev_run = tmp_path / "dev"
    _arm_row(dev_run, "A", "fastapi_14786", [("submit_patch", {}, "ok")])
    _arm_row(dev_run, "B", "fastapi_14786", [("edit_file", {"path": "pkg/a.py"}, "applied")])
    dev_out = tmp_path / "dev-report"
    report_from_runs([dev_run], DEV, dev_out)
    dev_text = (dev_out / "pair_report.md").read_text()
    assert dev_text.startswith(UNMATCHED)
    assert "multi-agent" in dev_text.splitlines()[0]
    assert "smoke, not promotion eligible" not in dev_text
    saved = json.loads((dev_out / "pair_report.json").read_text())
    assert saved["matched_pair"] is False
    assert saved.get("purpose") != "smoke"

    smoke_run = tmp_path / "smoke"
    _arm_row(
        smoke_run,
        "A",
        "fastapi_14786",
        [("run_skill_script", {"skill_name": "verify-patch"}, "INVALID_ARGUMENTS")],
    )
    _arm_row(smoke_run, "B", "fastapi_14786", [("submit_patch", {}, "ok")])
    smoke_out = tmp_path / "smoke-report"
    report_from_runs([smoke_run], SMOKE, smoke_out)
    text = (smoke_out / "pair_report.md").read_text()
    assert text.startswith("smoke, not promotion eligible\n")
    head = "\n".join(text.splitlines()[:8])
    assert UNMATCHED in head
    assert "skill removal and the run_command recipe" in head
    assert "Arm B has no skills. Skill calls for that arm are 0." in text
    assert "| B | r1 | fastapi_14786 | 0 | 0 | 0 | True | 1 | empty |" in text
    assert "| A | r1 | fastapi_14786 | 1 |" in text

    old_run = tmp_path / "old"
    _arm_row(old_run, "B", "fastapi_14786", [("submit_patch", {}, "ok")])
    old_out = tmp_path / "old-report"
    report_from_runs([old_run], OLD_SMOKE, old_out)
    old_text = (old_out / "pair_report.md").read_text()
    assert old_text.startswith("smoke, not promotion eligible\n")
    assert "has no skills" not in old_text
    assert UNMATCHED not in old_text


def _pair(left, right, *, matched_pair):
    assert_arms_compatible(
        left,
        right,
        allow_identical=False,
        allowed_differences=["prompts/*"],
        sha_a="a" * 64,
        sha_b="b" * 64,
        matched_pair=matched_pair,
    )


def _mini(root):
    root.mkdir(parents=True)
    (root / "thinking.yaml").write_text("thinking_budget: 0\ninclude_thoughts: false\n")
    (root / "agent.yaml").write_text(
        "agent_class: LlmAgent\n"
        "name: mini\n"
        "model: gemma-4-31b-it-qat-w4a16-ct\n"
        "instruction: !include prompts/system.md\n"
        "generate_content_config:\n"
        "  temperature: 0.5\n"
        "  top_p: 0.95\n"
        "  thinking_config: !include thinking.yaml\n"
    )
    (root / "prompts").mkdir()
    (root / "prompts" / "system.md").write_text("prompt\n")
    (root / "eval_config.yaml").write_text(
        "evaluation:\n  timeout_seconds: 300\n  max_tool_calls: 48\n"
        "  max_time_minutes: 4.5\n  max_turns: 48\n"
    )
    return root


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
