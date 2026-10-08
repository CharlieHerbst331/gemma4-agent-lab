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
# Byte copies of structured-v5 at origin/cursor/structured-v5-3d40 (5d03a8b).
V5_SHA256 = {
    "skills/verify-patch/scripts/check.py": (
        "c544234492a8846e5d4ba1082d20923b036ab0f4789a4748dc747500612baa4f"
    ),
    "skills/verify-patch/SKILL.md": (
        "0ef00d11676ae17f367cd9fbe38194c64dc972972fa18574393a05957969af50"
    ),
    "thinking.yaml": "f55a333a6a4f6c3855c532ad8edc5adfd71feff85cee1ad57479aa734e4d6acd",
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
    assert "thinking_budget" not in sampling["thinking_config"]
    assert sampling["thinking_config"]["include_thoughts"] is False
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
    live = "\n".join(
        line for line in knob.splitlines() if line.strip() and not line.strip().startswith("#")
    )
    assert live.strip() == "include_thoughts: false"
    assert "thinking_budget:" not in live
    budgets = load_yaml(CANDIDATE / "eval_config.yaml", CANDIDATE)["evaluation"]
    assert budgets["max_time_minutes"] * 60 == 270
    assert budgets["max_tool_calls"] == 48
    assert budgets["max_turns"] == 64
    assert 40 <= budgets["max_tool_calls"] <= 60
    assert budgets["timeout_seconds"] == 300
    eval_text = " ".join(
        line.split("#", 1)[-1].strip()
        for line in (CANDIDATE / "eval_config.yaml").read_text().splitlines()
    )
    assert "binding call cap" not in eval_text
    assert "binding cap" not in eval_text
    assert "Skill script runs count as tool calls" in eval_text
    assert "roughly co-binding" in eval_text
    assert "270s clock usually binds first" in eval_text
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
        "Never edit after the last submit.",
        "After each edit_file, rerun the verify-patch check.",
        "fewer than 60 seconds remain",
        "exactly one short sentence",
        "changed_paths list is empty",
        "UNCERTAIN",
        "same response as the next tool call",
        "Never send the checkpoint as a message of its own.",
        "a response with no function call is the final response and ends the turn.",
        "That sentence is the only text-only reply",
        "python -P",
        'skill_name "verify-patch"',
        'file_path "scripts/check.py"',
        '{"mode":"audit"}',
        'skill_name "source-lookup"',
        'file_path "scripts/lookup.py"',
    ]:
        assert phrase in prompt
    assert "under 40" not in prompt
    assert "temperature: 0.2" not in prompt
    script = (CANDIDATE / "skills/verify-patch/scripts/check.py").read_text()
    assert 'os.pathsep.join([str(root / "src"), str(root)])' in script
    assert '"-P"' in script
    assert len(validate(CANDIDATE)) == 10


@pytest.mark.parametrize(
    ("path", "flagged"),
    [
        ("pkg/app.py", False),
        ("pkg/test.py", False),
        ("testing/helper.py", True),
        ("Testing/helper.py", True),
        ("pkg/testing/helper.py", True),
        ("TESTS/helper.py", True),
        ("src/TEST/util.py", True),
        ("deep/TESTING/mod.py", True),
        ("mytesting/helper.py", False),
        ("testing/data.txt", False),
        ("tests/data.json", False),
        ("tests/notes.md", False),
        ("tests.py", False),
        ("test_foo.txt", False),
        ("pytest.ini", True),
        ("pkg/pytest.ini", True),
        ("pyproject.toml", True),
        ("src/setup.cfg", True),
        ("tox.ini", True),
        ("pkg/tox.ini", True),
        (".pytest.ini", True),
        ("nested/sub/.pytest.ini", True),
        ("conftest.py", True),
        ("pkg/conftest.py", True),
        ("sitecustomize.py", True),
        ("a/b/sitecustomize.py", True),
        ("usercustomize.py", True),
        ("a/b/usercustomize.py", True),
        ("_swegemma_stubs.py", True),
        ("vendor/_swegemma_stubs.py", True),
        ("src/_extra.pth", True),
        ("hooks/vendor/extra.pth", True),
        ("test_foo.py", True),
        ("pkg/test_extra.py", True),
        ("foo_test.py", True),
        ("pkg/widget_test.py", True),
        ("tests/helper.py", True),
        ("src/test/util.py", True),
        ("tests/test_pkg.py", True),
        ("pkg/build/mod.py", False),
    ],
)
def test_protected_path_matches_the_grading_predicate(path, flagged):
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
    (root / "tox.ini").write_text("[tox]\n")
    (root / "tests/data.json").write_text("{}\n")
    result = check.audit(root)
    assert not result["passed"]
    assert "pkg/impl.py" in result["untracked"]
    assert "pkg/impl.py" not in result["forbidden"]
    assert "tests/data.json" in result["untracked"]
    assert "tests/data.json" not in result["forbidden"]
    assert {
        "pytest.ini",
        "tests/test_pkg.py",
        "pyproject.toml",
        "setup.cfg",
        "pkg/conftest.py",
        "test_root.py",
        "src/test/util.py",
        "pkg/pytest.ini",
        "tox.ini",
    } <= set(result["forbidden"])


def test_audit_flags_import_hooks_and_case_insensitive_test_dirs(workspace):
    root, _ = workspace
    files = [
        "pkg/widget_test.py",
        "src/testing/helper.py",
        "TESTS/helper.py",
        "deep/TESTING/mod.py",
        "nested/sub/.pytest.ini",
        "hooks/sitecustomize.py",
        "hooks/usercustomize.py",
        "hooks/_swegemma_stubs.py",
        "hooks/vendor/extra.pth",
    ]
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# grading reset\n")
    (root / "hooks/notes.txt").write_text("not protected\n")
    result = check.audit(root)
    assert set(files) <= set(result["forbidden"])
    assert "hooks/notes.txt" in result["untracked"]
    assert "hooks/notes.txt" not in result["forbidden"]


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
    dual_root = root / "dualpkg"
    dual_src = root / "src" / "dualpkg"
    dual_root.mkdir()
    dual_src.mkdir()
    (dual_root / "__init__.py").write_text("MARKER = 'from-root'\n")
    (dual_src / "__init__.py").write_text("MARKER = 'from-src'\n")
    preferred = check.repro(
        root,
        scratch,
        "probe",
        "import dualpkg\nassert dualpkg.MARKER == 'from-src'\n",
    )
    assert preferred["passed"]
    assert preferred["import_origin"][0]["origin"] == "WORKSPACE"
    assert "src/dualpkg" in preferred["import_origin"][0]["file"].replace("\\", "/")
    assert preferred["default_import_origin"][0]["origin"] == "WORKSPACE"
    assert "src/dualpkg" not in preferred["default_import_origin"][0]["file"].replace("\\", "/")


def test_copied_memory_and_lookup_execute(workspace):
    root, scratch = workspace
    updated = memory.update(root, scratch, "update", {"hypothesis": "VALUE", "evidence": ["pkg:1"]})
    assert updated["hypothesis"] == "VALUE"
    assert memory.update(root, scratch, "read")["evidence"] == ["pkg:1"]
    hits = lookup.lookup(root, ["VALUE"], ["pkg"])
    assert hits["hits"][0]["path"] == "pkg/__init__.py"
