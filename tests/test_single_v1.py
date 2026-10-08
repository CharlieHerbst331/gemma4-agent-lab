"""single-v1 loads its own skills and locks the structured-v5 control knobs."""

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, validate

CANDIDATE = Path("agents/single-v1").resolve()
FORK = Path("agents/structured-v4-10m")
# Byte copies of structured-v5 at origin/cursor/structured-v5-3d40 (cc080df).
V5_SHA256 = {
    "skills/verify-patch/scripts/check.py": (
        "ddb9e3bd7f3a7f94165f091c3ab8ef8c2be68b954679b43ee514502bdd386b98"
    ),
    "skills/verify-patch/SKILL.md": (
        "cb5c9106fcad0f5a323465a293548226a6f78c829deb4b929dd1f3dfe37ada84"
    ),
    "thinking.yaml": "caa6ab7d581e681bf5a933c27250c73ba68df2de368a20647c88aa124e7a0f2c",
    "eval_config.yaml": "88c2a5f1f9ebd441a5c4070b42d270428c03ac1523939a7f181df3d5d4e5b740",
}


def module(skill, filename):
    path = CANDIDATE / "skills" / skill / "scripts" / filename
    spec = importlib.util.spec_from_file_location(f"single_v1_{skill}", path)
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


def test_skills_load_from_single_v1_and_match_v5_bytes():
    for loaded in (memory, lookup, check):
        assert "agents/single-v1/" in Path(loaded.__file__).as_posix()
    for rel in [
        "skills/task-memory/SKILL.md",
        "skills/task-memory/scripts/ledger.py",
        "skills/source-lookup/SKILL.md",
        "skills/source-lookup/scripts/lookup.py",
    ]:
        assert (CANDIDATE / rel).read_bytes() == (FORK / rel).read_bytes()
    for rel, digest in V5_SHA256.items():
        data = (CANDIDATE / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
    own = (CANDIDATE / "skills/verify-patch/scripts/check.py").read_bytes()
    forked = (FORK / "skills/verify-patch/scripts/check.py").read_bytes()
    assert own != forked


def test_single_agent_matches_v5_control_knobs():
    root = load_yaml(CANDIDATE / "agent.yaml", CANDIDATE)
    assert root["agent_class"] == "LlmAgent"
    assert root["name"] == "single_v1"
    assert root["model"] == "gemma-4-31b-it-qat-w4a16-ct"
    assert "sub_agents" not in root
    sampling = root["generate_content_config"]
    assert sampling["temperature"] == 0.5
    assert sampling["top_p"] == 0.95
    assert sampling["temperature"] != 0.2
    assert sampling["max_output_tokens"] == 2048
    assert sampling["thinking_config"]["thinking_budget"] == 0
    assert sampling["thinking_config"]["include_thoughts"] is True
    assert root["include_contents"] == "default"
    assert root["tools"] == [
        "get_status",
        "read_file",
        "edit_file",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
        "submit_patch",
    ]
    assert "write_file" not in root["tools"]
    assert root["skills"] == [
        "skills/task-memory",
        "skills/source-lookup",
        "skills/verify-patch",
    ]
    source = (CANDIDATE / "agent.yaml").read_text()
    assert "!include thinking.yaml" in source
    assert "thinking_budget" not in source
    assert "temperature: 0.2" not in source
    assert "SequentialAgent" not in source and "LoopAgent" not in source
    knob = (CANDIDATE / "thinking.yaml").read_text()
    assert knob.count("thinking_budget:") == 1
    assert "thinking_budget: 0" in knob
    budgets = load_yaml(CANDIDATE / "eval_config.yaml", CANDIDATE)["evaluation"]
    assert budgets["max_time_minutes"] * 60 == 270
    assert budgets["max_tool_calls"] == 48
    assert budgets["max_turns"] == 48
    assert 40 <= budgets["max_tool_calls"] <= 60
    assert 40 <= budgets["max_turns"] <= 60
    assert budgets["timeout_seconds"] == 300
    prompt = " ".join(root["instruction"].split())
    for phrase in [
        "{problem_description}",
        "{hints?}",
        "Name at most 3 candidate files",
        "end - start < 80",
        "head -n 40",
        "head -c 4000",
        "Do not cat whole files.",
        "Never repeat an identical call",
        "Before the first repro, run the import-origin probe once.",
        "cd /workspace && python3 -c",
        "os.path.realpath(m.__file__)",
        "INSTALLED-COPY: edits not imported",
        "PYTHONPATH=/workspace/src:/workspace",
        "Never use python -I, python -E, python3 -I, or python3 -E.",
        "12 counted calls",
        "95 seconds",
        "35 percent of the 270 second cap",
        "top-level /workspace/build/ or /tmp",
        "nested build/ or dist/",
        ".adk_exec_*.py",
        "pkg/build/module.py",
        "submit_patch must be your last tool call.",
        "time_seconds_remaining under 40",
        "call submit_patch as your last tool even when the check failed",
        'skill_name "verify-patch"',
        'file_path "scripts/check.py"',
        '{"mode":"audit"}',
        'skill_name "source-lookup"',
        'file_path "scripts/lookup.py"',
    ]:
        assert phrase in prompt
    assert "temperature: 0.2" not in prompt
    assert len(validate(CANDIDATE)) == 10


@pytest.mark.parametrize(
    ("path", "flagged"),
    [
        ("pkg/app.py", False),
        ("pkg/test.py", False),
        ("testing/helper.py", False),
        ("pkg/widget_test.py", False),
        ("tox.ini", False),
        ("pkg/build/mod.py", False),
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
def test_protected_path_matches_the_v5_set(path, flagged):
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
    host = check.repro(root, scratch, "probe", "import pytest\nassert pytest.__file__\n")
    assert host["imports_installed_copy"] is True
    assert host["import_origin"][0]["origin"] == "INSTALLED-COPY"


def test_copied_memory_and_lookup_execute(workspace):
    root, scratch = workspace
    updated = memory.update(root, scratch, "update", {"hypothesis": "VALUE", "evidence": ["pkg:1"]})
    assert updated["hypothesis"] == "VALUE"
    assert memory.update(root, scratch, "read")["evidence"] == ["pkg:1"]
    hits = lookup.lookup(root, ["VALUE"], ["pkg"])
    assert hits["hits"][0]["path"] == "pkg/__init__.py"
