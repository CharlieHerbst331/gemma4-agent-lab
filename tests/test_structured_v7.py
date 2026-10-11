"""structured-v7: full history, repair-only thinking, verify rejects an empty diff."""

from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, validate
from gemma_lab.hygiene import lint_candidate
from gemma_lab.operations import (
    DEFAULT_MODEL_LOAD_SECONDS,
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    PROJECTED_HIDDEN_TASKS,
    PROJECTED_PUBLIC_TASKS,
    PROJECTED_RUNTIME_LIMIT_SECONDS,
    WORST_CASE_WARN_SECONDS,
)
from gemma_lab.paired import assert_arms_compatible, inspect_arm, load_protocol, protocol_schedule

V6 = Path("agents/structured-v6")
V7 = Path("agents/structured-v7")
V8 = Path("agents/single-v8")
CHECK = Path("agents/single-v8-check")
PROTOCOL = Path("configs/protocols/single-v8-vs-structured-v7-dev13.yaml")
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
CAP_SECONDS = 360
MARKERS = [
    "agent.yaml",
    "sub_agents/*",
    "skills/*",
    "prompts/*",
    "eval_config.yaml",
    "sampling.yaml",
    "thinking.yaml",
]


def _role(name):
    return load_yaml(V7 / "sub_agents" / f"{name}.yaml", V7)


def _pair(allowed, matched_pair):
    assert_arms_compatible(
        inspect_arm(V8),
        inspect_arm(V7),
        allow_identical=False,
        allowed_differences=allowed,
        sha_a="a" * 64,
        sha_b="b" * 64,
        matched_pair=matched_pair,
    )


def test_structured_v7_roles_keep_full_history_and_repair_only_thinking():
    root = load_yaml(V7 / "agent.yaml", V7)
    assert root["agent_class"] == "SequentialAgent"
    assert "include_contents" not in root
    loop = load_yaml(V7 / "sub_agents" / "repair_loop.yaml", V7)
    assert loop["agent_class"] == "LoopAgent"
    assert loop["max_iterations"] == 3
    assert "include_contents" not in loop
    triage, repair, verify = _role("triage"), _role("repair"), _role("verify")
    assert triage["include_contents"] == "default"
    assert repair["include_contents"] == "default"
    assert verify["include_contents"] == "default"
    assert triage["tools"] == []
    assert "submit_patch" not in repair["tools"]
    assert "run_command" in repair["tools"]
    assert verify["tools"] == [
        "get_status",
        "read_file",
        "edit_file",
        "run_command",
        "submit_patch",
    ]
    assert verify["skills"] == ["skills/check"]
    assert "skills" not in repair
    assert repair["generate_content_config"]["thinking_config"] == {
        "include_thoughts": True,
        "thinking_budget": 256,
    }
    for role in (triage, verify):
        assert role["generate_content_config"]["thinking_config"] == {
            "include_thoughts": False,
            "thinking_budget": 0,
        }
        assert role["generate_content_config"]["temperature"] == 1.0
        assert role["generate_content_config"]["top_p"] == 0.95
        assert role["generate_content_config"]["top_k"] == 64
    budgets = load_yaml(V7 / "eval_config.yaml", V7)["evaluation"]
    assert budgets["max_time_minutes"] == 6
    assert budgets["max_tool_calls"] == 150
    assert budgets["max_turns"] == 200
    assert budgets["timeout_seconds"] == 300
    skill = V7 / "skills" / "check" / "scripts" / "run.py"
    assert skill.read_bytes() == (CHECK / "skills" / "check" / "scripts" / "run.py").read_bytes()
    assert "tempfile.gettempdir" in skill.read_text()
    assert not (V7 / "skills" / "verify-patch").exists()
    assert len(validate(V7)) == 13
    report = lint_candidate(V7)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_prompts_reject_empty_diffs_and_stay_small():
    triage = (V7 / "sub_agents" / "triage.md").read_text()
    repair = (V7 / "sub_agents" / "repair.md").read_text()
    verify = (V7 / "sub_agents" / "verify.md").read_text()
    assert len(triage) == 1771
    assert len(repair) == 5152
    assert len(verify) == 3375
    assert "Do not stop with UNCERTAIN" in triage
    assert "include_contents: none" not in repair
    assert "Your history is isolated" not in repair
    assert "full prior history" in repair
    assert "Edit with run_command. That is the primary edit." in repair
    assert "old = b'''OLD'''" in repair
    assert "submit_patch" in repair
    assert "You do not have submit_patch" in repair
    assert "run_command" in verify
    assert "do not call submit_patch" in verify
    assert "make the most plausible minimal edit; do not submit an empty diff" in verify
    assert '{"skill_name":"check","file_path":"scripts/run.py"}' in verify
    assert "verify-patch" not in verify
    assert "submit as is" not in verify
    assert "/tmp" in triage and "/tmp" in repair and "/tmp" in verify
    for prompt in (triage, repair, verify):
        assert "elapsed seconds" not in prompt


def test_dev13_protocol_accepts_the_thinking_and_budget_markers():
    protocol = load_protocol(PROTOCOL)
    assert protocol["matched_pair"] is False
    assert protocol["repeats"] == 1
    assert protocol["arms"]["A"]["source"] == "agents/single-v8"
    assert protocol["arms"]["B"]["source"] == "agents/structured-v7"
    for marker in ("eval_config.yaml", "sampling.yaml", "thinking.yaml"):
        assert marker in protocol["allowed_differences"]
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 13
    assert schedule["sha256"] == DEV_SCHEDULE
    _pair(protocol["allowed_differences"], False)
    with pytest.raises(ValueError, match="thinking_budget"):
        _pair(["eval_config.yaml", "sampling.yaml", "sub_agents/*"], False)
    with pytest.raises(ValueError, match="budgets"):
        _pair(["sampling.yaml", "thinking.yaml"], False)
    parent = load_yaml(V6 / "eval_config.yaml", V6)["evaluation"]
    assert parent["max_time_minutes"] == 4.5
    assert parent["max_tool_calls"] == 48


def test_runtime_cap_warns_and_does_not_block():
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    assert overhead == 70
    assert load == 900
    worst_120 = PROJECTED_HIDDEN_TASKS * (CAP_SECONDS + overhead)
    worst_129 = load + PROJECTED_PUBLIC_TASKS * (CAP_SECONDS + overhead)
    assert worst_120 == 51600
    assert worst_129 == 56370
    assert worst_129 > WORST_CASE_WARN_SECONDS
    assert worst_120 > PROJECTED_RUNTIME_LIMIT_SECONDS
    max_mean = PROJECTED_RUNTIME_LIMIT_SECONDS / PROJECTED_HIDDEN_TASKS - overhead
    assert max_mean == 260
    max_ok_cap = (WORST_CASE_WARN_SECONDS - load) / PROJECTED_PUBLIC_TASKS - overhead
    assert 257 < max_ok_cap < 258
