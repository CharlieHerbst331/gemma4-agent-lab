"""Lock the v6 / single-v2 protocol fixes without touching the frozen parents."""

import json
import subprocess
import sys
from pathlib import Path

from gemma_lab.bundle import load_yaml
from gemma_lab.hygiene import lint_candidate
from gemma_lab.paired import assert_arms_compatible, inspect_arm, load_protocol

ROOT = Path("agents")
V6 = ROOT / "structured-v6"
SINGLE = ROOT / "single-v2"
PARENTS = {"structured-v5t0": ROOT / "structured-v5t0", "single-v1t0": ROOT / "single-v1t0"}
EXAMPLE = (
    '{"skill_name":"verify-patch","file_path":"scripts/check.py",'
    '"args":{"mode":"repro","phase":"before",'
    '"code":"assert 1 == 2  # put the real failing assert here","timeout":"20"}}'
)
PLACEHOLDER = "assert 1 == 2  # put the real failing assert here"
NEVER_NEST = "Never put skill_name or file_path inside args"
LOOP = "If a tool returns the same error twice, do not repeat that call."
SHARED = (
    "eval_config.yaml",
    "skills/source-lookup/SKILL.md",
    "skills/source-lookup/scripts/lookup.py",
    "skills/task-memory/SKILL.md",
    "skills/task-memory/scripts/ledger.py",
    "skills/verify-patch/SKILL.md",
    "skills/verify-patch/scripts/check.py",
)
V6_CHANGED = {
    "skills/verify-patch/SKILL.md",
    "skills/verify-patch/scripts/check.py",
    "sub_agents/repair.md",
    "sub_agents/verify.md",
}
SINGLE_CHANGED = {
    "skills/verify-patch/SKILL.md",
    "skills/verify-patch/scripts/check.py",
    "prompts/system.md",
}


def _files(root):
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _changed(parent, copy):
    parent_files = _files(parent)
    assert parent_files == _files(copy)
    return {rel for rel in parent_files if (parent / rel).read_bytes() != (copy / rel).read_bytes()}


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_check_defaults_to_repro_and_prints_a_corrected_example(tmp_path):
    root, scratch = tmp_path / "workspace", tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    (root / "pkg.py").write_text("VALUE = 1\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Skill fixture")
    _git(root, "config", "user.email", "fixture@example.test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture baseline")
    for candidate in (V6, SINGLE):
        script = candidate / "skills/verify-patch/scripts/check.py"
        text = script.read_text()
        assert 'args.mode = "repro"' in text
        assert "the default is repro" in text
        assert json.loads(EXAMPLE)["args"]["code"] == PLACEHOLDER
        default = subprocess.run(
            [
                sys.executable,
                str(script),
                "--workspace",
                str(root),
                "--scratch",
                str(scratch),
                "--phase",
                "before",
                "--code",
                "assert True",
                "--timeout",
                "20",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert default.returncode == 0, default.stderr
        payload = json.loads(default.stdout)
        assert payload["kind"] == "behavior-check"
        assert payload["phase"] == "before"
        assert "usage:" not in default.stdout.lower()
        assert "usage:" not in default.stderr.lower()
        broken = subprocess.run(
            [sys.executable, str(script), "--mode", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert broken.returncode == 2
        error = json.loads(broken.stdout)
        assert error["passed"] is False
        assert EXAMPLE in error["error"]
        assert NEVER_NEST in error["error"]
        assert error["example_call"]["skill_name"] == "verify-patch"
        assert error["example_call"]["file_path"] == "scripts/check.py"
        assert "skill_name" not in error["example_call"]["args"]
        assert error["example_call"]["args"]["code"] == PLACEHOLDER
        assert "usage:" not in broken.stdout.lower()
        assert "usage:" not in broken.stderr.lower()
        omitted = subprocess.run(
            [
                sys.executable,
                str(script),
                "--workspace",
                str(root),
                "--scratch",
                str(scratch),
                "--code",
                PLACEHOLDER,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert omitted.returncode == 2
        omitted_error = json.loads(omitted.stdout)
        assert EXAMPLE in omitted_error["error"]
        assert omitted_error["example_call"]["args"]["code"] == PLACEHOLDER
        assert "Baseline repro changed" not in omitted.stdout
        assert "usage:" not in omitted.stdout.lower()
        assert "usage:" not in omitted.stderr.lower()


def test_prompts_and_skill_carry_the_call_shape_and_fallbacks():
    texts = {
        "v6-skill": (V6 / "skills/verify-patch/SKILL.md").read_text(),
        "single-skill": (SINGLE / "skills/verify-patch/SKILL.md").read_text(),
        "repair": (V6 / "sub_agents/repair.md").read_text(),
        "verify": (V6 / "sub_agents/verify.md").read_text(),
        "single": (SINGLE / "prompts/system.md").read_text(),
    }
    assert texts["v6-skill"] == texts["single-skill"]
    assert json.loads(EXAMPLE)["args"]["phase"] == "before"
    assert "Verify has no run_command" in texts["v6-skill"]
    for name, text in texts.items():
        assert EXAMPLE in text, name
        assert NEVER_NEST in text, name
        assert LOOP in text, name
        assert "/tmp" in text, name
        assert "repro*.py" in text, name
        assert "repro.py" in text, name
    for name in ("repair", "verify", "single"):
        text = texts[name]
        assert "about 30 counted calls" in text
        assert "about 18" in text
        assert "about 8 files" in text
        assert "few plain lines" in text
        assert "missing-parameter" in text
        assert "smaller edit" in text
        assert "Fix #3104" in text
        assert "No backticks" in text
    assert "No searches, no edits." in texts["repair"]
    assert "Do not search." in texts["single"]
    assert "primary edit point" in texts["repair"]
    assert "primary edit point" in texts["single"]
    assert "hard backstop" in texts["repair"]
    assert "hard backstop" in texts["single"]
    assert "only the hard backstop" in texts["repair"]
    assert "only the hard backstop" in texts["single"]
    for name in ("repair", "single"):
        assert "12 counted calls" in texts[name]
        assert "95 seconds" in texts[name]
    assert (
        "If that rewrite fails too, stop editing and end with the final report" in texts["repair"]
    )
    assert (
        "If that rewrite fails too, stop editing and call submit_patch with the current diff"
        in texts["single"]
    )
    assert "A best-guess edit is allowed only on the last iteration" in texts["verify"]
    assert "Hand back to repair" in texts["verify"]
    assert "If under 20 s remain, submit as is" in texts["verify"]
    assert "If under 20 s remain, submit as is" in texts["single"]
    assert "stop editing and call submit_patch with the current diff" in texts["verify"]
    assert (
        "make the smallest change the issue text implies, then submit that edit"
        not in texts["verify"]
    )
    for name in ("repair", "single"):
        text = texts[name]
        assert "short Python snippet" in text
        assert (
            "must not touch protected paths: tests, conftest.py, pyproject.toml, or setup.cfg"
            in text
        )
        assert "Switch to run_command or edit_file." in text
    assert "You do not have run_command" in texts["verify"]
    assert "Switch to edit_file." in texts["verify"]
    assert "short Python snippet" not in texts["verify"]
    assert "INVALID_ARGUMENTS" in texts["v6-skill"]
    assert "That text is not produced here" in texts["v6-skill"]
    assert "submit_patch" in texts["verify"]
    assert "You do not have submit_patch" in texts["repair"]


def test_shared_files_match_and_thinking_eval_stay_on_the_t0_bytes():
    for rel in SHARED:
        assert (V6 / rel).read_bytes() == (SINGLE / rel).read_bytes(), rel
    thinking = (V6 / "sub_agents/thinking.yaml").read_bytes()
    assert thinking == (SINGLE / "thinking.yaml").read_bytes()
    assert thinking == (PARENTS["structured-v5t0"] / "sub_agents/thinking.yaml").read_bytes()
    assert thinking == (PARENTS["single-v1t0"] / "thinking.yaml").read_bytes()
    assert b"thinking_budget: 0" in thinking
    assert b"include_thoughts: false" in thinking
    eval_bytes = (V6 / "eval_config.yaml").read_bytes()
    assert eval_bytes == (PARENTS["structured-v5t0"] / "eval_config.yaml").read_bytes()
    loaded = load_yaml(V6 / "eval_config.yaml", V6)["evaluation"]
    assert loaded["max_time_minutes"] == 4.5
    assert loaded["max_tool_calls"] == 48
    assert loaded["timeout_seconds"] == 300
    assert _changed(PARENTS["structured-v5t0"], V6) == V6_CHANGED
    assert _changed(PARENTS["single-v1t0"], SINGLE) == SINGLE_CHANGED
    sampling = inspect_arm(V6)["sampling"]
    assert sampling == [(0.5, 0.95, 0, False)]
    assert inspect_arm(SINGLE)["sampling"] == sampling


def test_parents_still_require_mode_and_new_dirs_pass_hygiene():
    for parent in PARENTS.values():
        script = (parent / "skills/verify-patch/scripts/check.py").read_text()
        assert 'choices=["audit", "repro"], required=True' in script
        assert "ExampleParser" not in script
    for source in (V6, SINGLE):
        report = lint_candidate(source)
        assert report["gate"] == "pass", report["findings"]
        assert report["findings"] == []


def test_protocol_points_at_the_v6_pair_and_leaves_the_t0_protocol():
    previous = Path("configs/protocols/v5-vs-single-v1.yaml").read_text()
    assert "agents/structured-v5t0" in previous
    assert "agents/single-v1t0" in previous
    assert "agents/structured-v6" not in previous
    assert "agents/single-v2" not in previous
    protocol = load_protocol("configs/protocols/v6-vs-single-v2.yaml")
    assert protocol["arms"]["A"]["source"] == "agents/structured-v6"
    assert protocol["arms"]["B"]["source"] == "agents/single-v2"
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert_arms_compatible(
        arms["A"],
        arms["B"],
        allow_identical=protocol["allow_identical"],
        allowed_differences=protocol["allowed_differences"],
        sha_a="a" * 64,
        sha_b="b" * 64,
    )
