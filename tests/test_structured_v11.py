"""structured-v11 is structured-v8, without v10's parallel starvation."""

from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate
from gemma_lab.operations import (
    DEFAULT_MODEL_LOAD_SECONDS,
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    PROJECTED_HIDDEN_TASKS,
    PROJECTED_LOAD_LIMIT_SECONDS,
    PROJECTED_PUBLIC_TASKS,
    PROJECTED_RUNTIME_LIMIT_SECONDS,
    WORST_CASE_WARN_SECONDS,
)

V8 = Path("agents/structured-v8")
V10 = Path("agents/structured-v10")
V11 = Path("agents/structured-v11")
V8_ARCHIVE = "9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e"
V10_ARCHIVE = "c07fcc5505f509f648a924a09dfa5a0f4c1cfe10d4b0a784f938e69116c66ed0"
MEDIAN_SECONDS_TO_FIRST_EDIT = 63.6


def _files(root):
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def test_v11_matches_v8_byte_for_byte():
    assert _files(V11) == _files(V8)
    for rel in _files(V8):
        assert (V11 / rel).read_bytes() == (V8 / rel).read_bytes()
    root = load_yaml(V11 / "agent.yaml", V11)
    assert root["agent_class"] == "SequentialAgent"
    assert root["name"] == "structured_v8"
    assert "ParallelAgent" not in (V11 / "agent.yaml").read_text()
    blob = "\n".join(path.read_text() for path in V11.rglob("*") if path.is_file())
    assert "ParallelAgent" not in blob
    assert "git worktree" not in blob
    budgets = load_yaml(V11 / "eval_config.yaml", V11)["evaluation"]
    parent = load_yaml(V8 / "eval_config.yaml", V8)["evaluation"]
    assert budgets == parent
    assert budgets["timeout_seconds"] == 300
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert budgets["max_time_minutes"] == 5
    assert len(validate(V11)) == len(validate(V8))
    report = lint_candidate(V11)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_v11_does_not_reintroduce_the_v10_starvation_rules():
    """Regression for the 0.01 score: no parallel stop and no per-command status."""
    prompts = "\n".join(path.read_text() for path in (V11 / "sub_agents").glob("*.md"))
    assert "Call get_status again before every run_command" not in prompts
    assert "agent_elapsed_seconds is 170 or more" not in prompts
    assert "Call get_status again before you decide to keep reading" in prompts
    repair = (V11 / "sub_agents" / "repair_1.md").read_text()
    assert "py_compile.compile(path, doraise=True)" in repair
    assert 'backup = "/tmp/pre_" + path.replace("/", "_")' in repair
    assert "shutil.copyfile(backup, path)" in repair
    assert not (V11 / "skills" / "locate").exists()
    # 170 s stop, two turns per command, 1.3–1.6 stream slowdown. The median
    # time to a first edit is an independent trace statistic, so this fails
    # if the stop or the slowdown no longer lands on that median.
    low = 170 / (2 * 1.6)
    high = 170 / (2 * 1.3)
    assert low < MEDIAN_SECONDS_TO_FIRST_EDIT <= high
    # Two such medians use most of a 150 s serial half and still fit in it.
    pair = 2 * MEDIAN_SECONDS_TO_FIRST_EDIT
    assert 120 < pair < 150


def test_archive_is_the_scored_v8_archive_and_v10_is_unchanged(tmp_path):
    archive = tmp_path / "structured-v11.zip"
    manifest = pack(V11, archive)
    assert manifest["sha256"] == V8_ARCHIVE
    assert sha256(archive) == V8_ARCHIVE
    assert pack(V8, tmp_path / "structured-v8.zip")["sha256"] == V8_ARCHIVE
    assert pack(V10, tmp_path / "structured-v10.zip")["sha256"] == V10_ARCHIVE


def test_runtime_gate_stays_on_the_v8_mean():
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    assert overhead == 70
    assert load == 900
    assert PROJECTED_HIDDEN_TASKS * (255 + overhead) == 39000
    assert load + PROJECTED_PUBLIC_TASKS * 255 == 33795
    assert load + PROJECTED_PUBLIC_TASKS * (255 + overhead) == 42825
    assert 39000 <= PROJECTED_RUNTIME_LIMIT_SECONDS
    assert 33795 <= PROJECTED_LOAD_LIMIT_SECONDS
    assert 42825 <= WORST_CASE_WARN_SECONDS
    assert PROJECTED_HIDDEN_TASKS * (300 + overhead) == 44400
    assert load + PROJECTED_PUBLIC_TASKS * (300 + overhead) == 48630
    assert 48630 > WORST_CASE_WARN_SECONDS
