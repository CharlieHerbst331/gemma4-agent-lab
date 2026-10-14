"""single-v9 keeps single-v8 and adds the 120/45 deadlines plus a syntax check."""

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

V8 = Path("agents/single-v8")
V9 = Path("agents/single-v9")
V8_ARCHIVE = "6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22"
V9_ARCHIVE = "42665a7febbfc63a1811df5fd1f46ade4afd78977cbf6576dd285d9543fdd7f3"
CAP_SECONDS = 330
# 330 - 45. This aimed submit point is above the 255 second mean ceiling.
PROJECTED_SUBMIT_SECONDS = 285


def test_single_v9_changes_only_the_prompt():
    for name in ("agent.yaml", "eval_config.yaml", "sampling.yaml", "thinking.yaml"):
        assert (V9 / name).read_bytes() == (V8 / name).read_bytes()
    root = load_yaml(V9 / "agent.yaml", V9)
    assert root["agent_class"] == "LlmAgent"
    assert root["name"] == "single_v1"
    assert "submit_patch" in root["tools"]
    assert "edit_file" in root["tools"]
    assert "skills" not in root
    budgets = load_yaml(V9 / "eval_config.yaml", V9)["evaluation"]
    assert budgets["max_time_minutes"] == 5.5
    assert budgets["max_tool_calls"] == 150
    assert budgets["max_turns"] == 200
    assert budgets["timeout_seconds"] == 300
    thinking = load_yaml(V9 / "thinking.yaml", V9)
    assert thinking["thinking_budget"] == 0
    assert thinking["include_thoughts"] is False
    prompt = (V9 / "prompts" / "system.md").read_text()
    parent = (V8 / "prompts" / "system.md").read_text()
    assert prompt != parent
    assert len(prompt) == 9286
    assert "about 90 seconds" in prompt
    assert "about 165 seconds" in prompt
    assert "time_seconds_remaining is under 120" in prompt
    assert "time_seconds_remaining is under 45" in prompt
    assert "the next call is the heredoc edit" in prompt
    assert "A cap hit with no diff must not happen." in prompt
    assert 'ast.parse(s.decode("utf-8"))' in prompt
    assert 'backup = "/tmp/pre_" + path.replace("/", "_")' in prompt
    assert "shutil.copyfile(backup, path)" in prompt
    assert "py_compile.compile(path, doraise=True)" in prompt
    assert "onto no other file" in prompt
    assert "line_fix.bak" not in prompt
    assert "git checkout --" not in prompt
    assert "Never run git checkout" in prompt
    assert "fewer than 60 seconds remain" not in prompt
    assert "fewer than 20 seconds remain" not in prompt
    assert "/tmp" in prompt
    assert "submit_patch" in prompt
    assert len(validate(V9)) == 5
    report = lint_candidate(V9)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_single_v9_archive_and_projected_submit_point(tmp_path):
    archive = tmp_path / "single-v9.zip"
    manifest = pack(V9, archive)
    assert manifest["sha256"] == V9_ARCHIVE
    assert sha256(archive) == V9_ARCHIVE
    parent = tmp_path / "single-v8.zip"
    assert pack(V8, parent)["sha256"] == V8_ARCHIVE
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    cap_warn = load + PROJECTED_PUBLIC_TASKS * (CAP_SECONDS + overhead)
    assert cap_warn == 52500
    assert cap_warn > WORST_CASE_WARN_SECONDS
    submit_120 = PROJECTED_HIDDEN_TASKS * (PROJECTED_SUBMIT_SECONDS + overhead)
    submit_129 = load + PROJECTED_PUBLIC_TASKS * PROJECTED_SUBMIT_SECONDS
    submit_warn = load + PROJECTED_PUBLIC_TASKS * (PROJECTED_SUBMIT_SECONDS + overhead)
    assert submit_120 == 42600
    assert submit_129 == 37665
    assert submit_warn == 46695
    assert submit_120 > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert submit_129 <= PROJECTED_LOAD_LIMIT_SECONDS
    assert submit_warn > WORST_CASE_WARN_SECONDS
