"""Load structured-v5's own skills and lock the unevaluated candidate contract."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, validate

CANDIDATE = Path("agents/structured-v5").resolve()
PREVIOUS = Path("agents/structured-v4-10m").resolve()


def module(skill, filename):
    path = CANDIDATE / "skills" / skill / "scripts" / filename
    spec = importlib.util.spec_from_file_location(f"v5_{skill.replace('-', '_')}", path)
    result = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(result)
    finally:
        sys.dont_write_bytecode = prior
    assert Path(result.__file__).resolve().is_relative_to(CANDIDATE)
    return result


memory = module("task-memory", "ledger.py")
lookup = module("source-lookup", "lookup.py")
check = module("verify-patch", "check.py")


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def role(name):
    return load_yaml(CANDIDATE / "sub_agents" / f"{name}.yaml", CANDIDATE)


@pytest.fixture
def workspace(tmp_path):
    root, scratch = tmp_path / "workspace", tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg/__init__.py").write_text("VALUE = 1\n")
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "conftest.py").write_text("# baseline config\n")
    (root / "tests").mkdir()
    (root / "tests/test_pkg.py").write_text("def test_value():\n    assert True\n")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Skill fixture")
    git(root, "config", "user.email", "fixture@example.test")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture baseline")
    git(root, "tag", "_swegemma_baseline")
    return root, scratch


def test_unchanged_skills_match_v4_10m_bytes():
    for rel in [
        "skills/task-memory/SKILL.md",
        "skills/task-memory/scripts/ledger.py",
        "skills/source-lookup/SKILL.md",
        "skills/source-lookup/scripts/lookup.py",
    ]:
        assert (CANDIDATE / rel).read_bytes() == (PREVIOUS / rel).read_bytes()


def test_candidate_compiles_to_the_bounded_loop():
    root = load_yaml(CANDIDATE / "agent.yaml", CANDIDATE)
    assert root["agent_class"] == "SequentialAgent"
    assert [item["config_path"] for item in root["sub_agents"]] == [
        "sub_agents/triage.yaml",
        "sub_agents/repair_loop.yaml",
    ]
    loop = load_yaml(CANDIDATE / "sub_agents/repair_loop.yaml", CANDIDATE)
    assert loop["agent_class"] == "LoopAgent"
    assert loop["max_iterations"] == 3
    assert [item["config_path"] for item in loop["sub_agents"]] == ["repair.yaml", "verify.yaml"]
    triage, repair, verify = role("triage"), role("repair"), role("verify")
    assert triage["tools"] == []
    assert not triage.get("skills")
    assert triage["include_contents"] == "none"
    assert triage["output_key"] == "triage_brief"
    assert "submit_patch" not in repair["tools"]
    assert "run_command" in repair["tools"]
    assert repair["include_contents"] == "none"
    assert verify["tools"] == ["get_status", "read_file", "edit_file", "submit_patch"]
    assert verify["skills"] == ["skills/verify-patch"]
    assert verify["include_contents"] == "none"
    assert "run_command" not in verify["tools"]
    assert "write_file" not in verify["tools"]
    for agent in (triage, repair, verify):
        assert agent["model"] == "gemma-4-31b-it-qat-w4a16-ct"
        sampling = agent["generate_content_config"]
        assert sampling["temperature"] == 0.5
        assert sampling["top_p"] == 0.95
        assert sampling["temperature"] != 0.2
        assert sampling["thinking_config"]["thinking_budget"] == 0
        assert sampling["thinking_config"]["include_thoughts"] is True
    assert triage["generate_content_config"]["max_output_tokens"] == 1024
    assert repair["generate_content_config"]["max_output_tokens"] == 2048
    assert verify["generate_content_config"]["max_output_tokens"] == 1536
    budgets = load_yaml(CANDIDATE / "eval_config.yaml", CANDIDATE)["evaluation"]
    assert budgets["max_time_minutes"] == 4.5
    assert budgets["max_tool_calls"] == 48
    assert 40 <= budgets["max_tool_calls"] <= 60
    assert budgets["max_turns"] == 48
    assert budgets["timeout_seconds"] == 300
    for path in CANDIDATE.rglob("*"):
        if path.suffix in {".yaml", ".yml", ".md"}:
            text = path.read_text()
            assert "max_llm_calls" not in text
            assert "callback" not in text
            assert "temperature: 0.2" not in text
    for name in ("triage", "repair", "verify"):
        raw = (CANDIDATE / "sub_agents" / f"{name}.yaml").read_text()
        assert "!include thinking.yaml" in raw
        assert "thinking_budget" not in raw
    knob = (CANDIDATE / "sub_agents/thinking.yaml").read_text()
    assert knob.count("thinking_budget:") == 1
    assert "thinking_budget: 0" in knob
    assert len(validate(CANDIDATE)) == 16


def test_prompts_state_import_scratch_and_final_submit_rules():
    triage = (CANDIDATE / "sub_agents/triage.md").read_text()
    repair = (CANDIDATE / "sub_agents/repair.md").read_text()
    verify = (CANDIDATE / "sub_agents/verify.md").read_text()
    skill = (CANDIDATE / "skills/verify-patch/SKILL.md").read_text()
    for prompt in (triage, repair, verify, skill):
        assert "/workspace/build/" in prompt
        assert "nested build/" in prompt
        assert ".adk_exec_*.py" in prompt
    for prompt in (triage, repair):
        assert "{problem_description}" in prompt
        assert "PYTHONPATH=/workspace/src:/workspace" in prompt
        assert "python -I" in prompt and "python -E" in prompt
        assert "INSTALLED-COPY" in prompt
        assert "module.__file__" in prompt or "m.__file__" in prompt
    assert "at most 3" in triage
    assert "You do not have submit_patch" in repair
    assert "12 counted calls" in repair
    assert "95 seconds" in repair
    assert "loop_iteration" in repair and "loop_iteration" in verify
    assert 'skill_name "verify-patch"' in verify or 'skill_name is "verify-patch"' in verify
    assert 'file_path is "scripts/check.py"' in verify
    assert "submit_patch must be your last tool call" in verify
    assert "run_command" in verify and "write_file" in verify
    assert "import_origin" in skill and "default_import_origin" in skill
    assert "pyproject.toml" in skill and "setup.cfg" in skill


def test_v5_memory_and_lookup_roundtrip(workspace):
    root, scratch = workspace
    updated = memory.update(root, scratch, "update", {"hypothesis": "VALUE", "evidence": ["pkg:1"]})
    assert updated["evidence"] == ["pkg:1"]
    assert memory.update(root, scratch, "read")["hypothesis"] == "VALUE"
    hits = lookup.lookup(root, ["VALUE"], ["pkg"])
    assert hits["hits"][0]["path"] == "pkg/__init__.py"


@pytest.mark.parametrize(
    ("path", "flagged"),
    [
        ("pkg/app.py", False),
        ("pkg/test.py", False),
        ("testing/helper.py", False),
        ("pytest.ini", True),
        ("pkg/pytest.ini", True),
        ("pyproject.toml", True),
        ("src/setup.cfg", True),
        ("conftest.py", True),
        ("pkg/conftest.py", True),
        ("test_foo.py", True),
        ("pkg/test_extra.py", True),
        ("tests/helper.py", True),
        ("src/test/util.py", True),
        ("tests/test_pkg.py", True),
    ],
)
def test_protected_path_matches_the_grading_set(path, flagged):
    assert check.protected_path(path) is flagged


def test_audit_flags_nested_protected_paths_and_not_implementation(workspace):
    root, _ = workspace
    (root / "pkg/impl.py").write_text("VALUE = 2\n")
    (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    (root / "tests/test_pkg.py").write_text("def test_value():\n    assert False\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (root / "setup.cfg").write_text("[metadata]\nname = x\n")
    (root / "pkg/conftest.py").write_text("# nested\n")
    (root / "test_root.py").write_text("def test_root():\n    assert True\n")
    (root / "src/test").mkdir(parents=True)
    (root / "src/test/util.py").write_text("VALUE = 1\n")
    (root / "pkg/pytest.ini").write_text("[pytest]\n")
    result = check.audit(root)
    assert not result["passed"]
    assert "pkg/impl.py" in result["untracked"]
    assert "pkg/impl.py" not in result["forbidden"]
    assert {
        "pytest.ini",
        "tests/test_pkg.py",
        "pyproject.toml",
        "setup.cfg",
        "pkg/conftest.py",
        "test_root.py",
        "src/test/util.py",
        "pkg/pytest.ini",
    } <= set(result["forbidden"])


def test_repro_reports_workspace_and_default_import_origin(workspace):
    root, scratch = workspace
    package = root / "src" / "requests"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("MARKER = 'workspace-requests'\n")
    code = (
        "import pkg, requests\n"
        "assert pkg.VALUE == 1\n"
        "assert requests.MARKER == 'workspace-requests'\n"
    )
    result = check.repro(root, scratch, "before", code)
    assert result["passed"]
    assert result["imports_installed_copy"] is False
    used = {item["module"]: item for item in result["import_origin"]}
    default = {item["module"]: item for item in result["default_import_origin"]}
    assert used["pkg"]["origin"] == "WORKSPACE"
    assert used["requests"]["origin"] == "WORKSPACE"
    assert "src/requests" in used["requests"]["file"].replace("\\", "/")
    assert default["pkg"]["origin"] == "WORKSPACE"
    assert default["requests"]["origin"] == "INSTALLED-COPY"
    assert "site-packages" in default["requests"]["file"]
    # pytest is installed for the test run and is not in this fixture, so the
    # skill's own PYTHONPATH still resolves the host copy.
    host = check.repro(root, scratch, "probe", "import pytest\nassert pytest.__file__\n")
    assert host["imports_installed_copy"] is True
    assert host["import_origin"][0]["origin"] == "INSTALLED-COPY"
