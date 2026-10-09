"""Lock the thinking-off copies without touching the frozen parents."""

import hashlib
from pathlib import Path

from gemma_lab.paired import assert_arms_compatible, inspect_arm, load_protocol

ROOT = Path("agents")
PARENTS = {
    "structured-v5": ROOT / "structured-v5" / "sub_agents" / "thinking.yaml",
    "single-v1": ROOT / "single-v1" / "thinking.yaml",
}
COPIES = {
    "structured-v5t0": ROOT / "structured-v5t0" / "sub_agents" / "thinking.yaml",
    "single-v1t0": ROOT / "single-v1t0" / "thinking.yaml",
}
PARENT_THINKING = "8423bf3b5457acca91cda0b7a0893746cb32d5b48764bf3c71a890253a18332f"
PARENT_EVAL = "74ece35136e01df51b67a1718b36b1ef3a8ad49d33bebca1c0abda0843fa6232"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_parents_keep_the_frozen_thinking_and_eval_bytes():
    for path in PARENTS.values():
        assert digest(path) == PARENT_THINKING
        assert "thinking_budget:" not in path.read_text()
    for name in ("structured-v5", "single-v1", "structured-v5t0", "single-v1t0"):
        assert digest(ROOT / name / "eval_config.yaml") == PARENT_EVAL


def test_t0_thinking_files_are_byte_identical_and_budget_zero():
    first, second = COPIES.values()
    assert first.read_bytes() == second.read_bytes()
    assert digest(first) != PARENT_THINKING
    for name, path in COPIES.items():
        text = path.read_text()
        assert "include_thoughts: false" in text
        assert "thinking_budget: 0" in text
        assert inspect_arm(ROOT / name)["sampling"] == [(0.5, 0.95, 0, False)]


def test_t0_dirs_differ_from_parents_only_in_thinking_yaml():
    pairs = (
        ("structured-v5", "structured-v5t0", "sub_agents/thinking.yaml"),
        ("single-v1", "single-v1t0", "thinking.yaml"),
    )
    for parent, copy, knob in pairs:
        parent_files = {
            path.relative_to(ROOT / parent).as_posix()
            for path in (ROOT / parent).rglob("*")
            if path.is_file()
        }
        copy_files = {
            path.relative_to(ROOT / copy).as_posix()
            for path in (ROOT / copy).rglob("*")
            if path.is_file()
        }
        assert parent_files == copy_files
        changed = [
            rel
            for rel in parent_files
            if (ROOT / parent / rel).read_bytes() != (ROOT / copy / rel).read_bytes()
        ]
        assert changed == [knob]


def test_protocol_points_at_the_t0_pair():
    protocol = load_protocol("configs/protocols/v5-vs-single-v1.yaml")
    assert protocol["arms"]["A"]["source"] == "agents/structured-v5t0"
    assert protocol["arms"]["B"]["source"] == "agents/single-v1t0"
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert arms["A"]["sampling"] == arms["B"]["sampling"]
    assert arms["A"]["sampling"] == [(0.5, 0.95, 0, False)]
    assert_arms_compatible(
        arms["A"],
        arms["B"],
        allow_identical=protocol["allow_identical"],
        allowed_differences=protocol["allowed_differences"],
        sha_a="a" * 64,
        sha_b="b" * 64,
    )
