"""single-v1 loads its own skills and locks the structured-v5 control knobs."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, validate

CANDIDATE = Path("agents/single-v1").resolve()
FORK = Path("agents/structured-v4-10m")


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


def test_skills_load_from_single_v1_not_the_fork():
    for loaded in (memory, lookup, check):
        assert "agents/single-v1/" in Path(loaded.__file__).as_posix()
    for rel in [
        "skills/task-memory/SKILL.md",
        "skills/task-memory/scripts/ledger.py",
        "skills/source-lookup/SKILL.md",
        "skills/source-lookup/scripts/lookup.py",
    ]:
        assert (CANDIDATE / rel).read_bytes() == (FORK / rel).read_bytes()
    own = CANDIDATE / "skills/verify-patch/scripts/check.py"
    forked = FORK / "skills/verify-patch/scripts/check.py"
    assert own.read_bytes() != forked.read_bytes()
    assert '"-I"' not in own.read_text() and '"-E"' not in own.read_text()


def test_single_agent_matches_v5_control_knobs():
    root = load_yaml(CANDIDATE / "agent.yaml", CANDIDATE)
    assert root["agent_class"] == "LlmAgent"
    assert root["name"] == "single_v1"
    assert root["model"] == "gemma-4-31b-it-qat-w4a16-ct"
    assert "sub_agents" not in root
    sampling = root["generate_content_config"]
    assert sampling["temperature"] == 0.5
    assert sampling["top_p"] == 0.95
    assert sampling["max_output_tokens"] == 2048
    assert sampling["thinking_config"]["thinking_budget"] == 0
    assert sampling["thinking_config"]["include_thoughts"] is True
    assert root["include_contents"] == "default"
    assert set(root["tools"]) == {
        "get_status",
        "read_file",
        "edit_file",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
        "submit_patch",
    }
    assert "write_file" not in root["tools"]
    assert root["skills"] == [
        "skills/task-memory",
        "skills/source-lookup",
        "skills/verify-patch",
    ]
    source = (CANDIDATE / "agent.yaml").read_text()
    assert source.count("thinking_budget:") == 1
    assert "temperature: 0.2" not in source
    assert sampling["temperature"] != 0.2
    assert "SequentialAgent" not in source and "LoopAgent" not in source
    budgets = load_yaml(CANDIDATE / "eval_config.yaml", CANDIDATE)["evaluation"]
    assert budgets["max_time_minutes"] * 60 == 270
    assert budgets["max_tool_calls"] == 50
    assert budgets["max_turns"] == 50
    assert 40 <= budgets["max_tool_calls"] <= 60
    assert 40 <= budgets["max_turns"] <= 60
    assert budgets["timeout_seconds"] == 300
    prompt = " ".join(root["instruction"].split())
    for phrase in [
        "top 3 candidate files",
        "12 counted calls",
        "18 counted calls",
        "35% of the 50-call cap",
        "cd /workspace && python3 -c",
        "os.path.realpath(m.__file__)",
        "INSTALLED-COPY: edits not imported",
        "PYTHONPATH=/workspace/src:/workspace",
        "Never use python -I or python -E.",
        "top-level /workspace/build/ or /tmp",
        "Never create real source files under a nested build/ or dist/",
        "Resubmit after every edit.",
        "submit_patch is the final action.",
        "Do not repeat an identical call.",
        'skill_name="verify-patch"',
        'file_path="scripts/check.py"',
        '{"mode":"audit"}',
        'skill_name="source-lookup"',
        'file_path="scripts/lookup.py"',
        'skill_name="task-memory"',
        'file_path="scripts/ledger.py"',
        "{problem_description}",
    ]:
        assert phrase in prompt
    assert "0.2" not in prompt
    assert len(validate(CANDIDATE)) == 9


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("conftest.py", True),
        ("pkg/conftest.py", True),
        ("pkg/test_unit.py", True),
        ("pkg/test/helper.py", True),
        ("tests/helper.txt", True),
        ("test/helper.py", True),
        ("pytest.ini", True),
        ("nested/pytest.ini", True),
        ("pyproject.toml", True),
        ("setup.cfg", True),
        ("pkg/__init__.py", False),
        ("pkg/widget_test.py", False),
        ("tox.ini", False),
        ("testing/helper.py", False),
        ("pkg/build/mod.py", False),
    ],
)
def test_protected_predicate_matches_the_v5_set(path, protected):
    assert check.is_protected(path) is protected


def test_audit_flags_protected_paths_and_ignores_source(workspace):
    root, _ = workspace
    (root / "pkg/__init__.py").write_text("VALUE = 2\n")
    assert check.audit(root)["passed"]
    (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    (root / "tests/test_pkg.py").write_text("assert True\n")
    (root / "pkg/conftest.py").write_text("# nested\n")
    (root / "pkg/test_unit.py").write_text("def test_x():\n    assert True\n")
    (root / "pkg/test").mkdir()
    (root / "pkg/test/helper.py").write_text("x = 1\n")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")
    (root / "setup.cfg").write_text("[metadata]\nname=x\n")
    (root / "nested").mkdir()
    (root / "nested/pytest.ini").write_text("[pytest]\n")
    (root / "pkg/widget_test.py").write_text("x = 1\n")
    (root / "tox.ini").write_text("[tox]\n")
    result = check.audit(root)
    assert not result["passed"]
    forbidden = set(result["forbidden"])
    for path in [
        "pytest.ini",
        "tests/test_pkg.py",
        "pkg/conftest.py",
        "pkg/test_unit.py",
        "pkg/test/helper.py",
        "pyproject.toml",
        "setup.cfg",
        "nested/pytest.ini",
    ]:
        assert path in forbidden
    assert "pkg/__init__.py" not in forbidden
    assert "pkg/widget_test.py" not in forbidden
    assert "tox.ini" not in forbidden
    assert "pkg/widget_test.py" in result["untracked"]


def test_classify_origin_and_installed_copy_fails_closed(tmp_path):
    root = tmp_path / "workspace"
    (root / "pkg").mkdir(parents=True)
    inside = root / "pkg/__init__.py"
    inside.write_text("VALUE = 1\n")
    outside = tmp_path / "site/pkg/__init__.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("VALUE = 1\n")
    assert check.classify_origin(str(inside), root) == "WORKSPACE"
    assert check.classify_origin(str(outside), root) == "INSTALLED-COPY"
    assert check.classify_origin("", root) == "UNKNOWN"
    result = {"passed": True}
    check.apply_import_origin(
        result,
        [
            {
                "module": "requests",
                "file": "/usr/lib/requests/__init__.py",
                "verdict": "INSTALLED-COPY",
            }
        ],
    )
    assert result["passed"] is False
    assert result["imports_outside_workspace"] is True


def test_repro_reports_workspace_import_origin(workspace):
    root, scratch = workspace
    result = check.repro(root, scratch, "before", "import pkg\nassert pkg.VALUE == 1\n")
    assert result["passed"]
    assert result["imports_outside_workspace"] is False
    origin = result["import_origin"][0]
    assert origin["module"] == "pkg"
    assert origin["verdict"] == "WORKSPACE"
    assert origin["file"].startswith(str(root) + "/")
    assert '"-I"' not in check._origin_script() and '"-E"' not in check._origin_script()


def test_repro_import_origin_prefers_src_layout(workspace):
    root, scratch = workspace
    package = root / "src/requests"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("ORIGIN = 'workspace'\n")
    result = check.repro(
        root,
        scratch,
        "probe",
        "import requests\nassert requests.ORIGIN == 'workspace'\n",
    )
    assert result["passed"]
    origin = next(row for row in result["import_origin"] if row["module"] == "requests")
    assert origin["verdict"] == "WORKSPACE"
    assert "/src/requests/" in origin["file"]


def test_copied_memory_and_lookup_execute(workspace):
    root, scratch = workspace
    updated = memory.update(root, scratch, "update", {"hypothesis": "VALUE", "evidence": ["pkg:1"]})
    assert updated["hypothesis"] == "VALUE"
    assert memory.update(root, scratch, "read")["evidence"] == ["pkg:1"]
    hits = lookup.lookup(root, ["VALUE"], ["pkg"])
    assert hits["hits"][0]["path"] == "pkg/__init__.py"
    assert len(json.dumps(hits)) <= 4000
