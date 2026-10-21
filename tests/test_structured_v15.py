"""structured-v15 ships only levers the hosted compiler executes."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V14 = Path("agents/structured-v14").resolve()
V15 = Path("agents/structured-v15").resolve()
NOTEBOOK = Path("notebooks/structured-v15-dev13.ipynb").resolve()
ARCHIVE = "9b9e3bb1f3b500811358d00c608def24573ed12f8090ebb59a0900168636e072"
V14_ARCHIVE = "8eeae0c1859766bc08afafe2b6139e4ea4ebd82ab52b42c04bd01836e4e361bf"
STEP_SECONDS = 10
REPAIR_ITERS = {"repair_1_loop": 15, "repair_2_loop": 6, "repair_3_loop": 3}
READ_TOOLS = {"read_file", "search_similar_code", "get_code_neighbors", "get_code_subgraph"}
LATE_ROLES = ("repair_2", "repair_3", "verify_1", "verify_2", "verify_3")
DEV13 = (
    "fastapi_11194",
    "fastapi_14246",
    "fastapi_14262",
    "fastapi_14356",
    "fastapi_14786",
    "fastapi_14794",
    "rich_3105",
    "rich_3454",
    "rich_3472",
    "rich_3934",
    "rich_3938",
    "rich_3944",
    "rich_4070",
)
UNREACHABLE = {"fastapi_14246", "fastapi_14262", "fastapi_14356"}
COMPILER_FILES = (
    "adk_submission/__init__.py",
    "adk_submission/compiler.py",
    "adk_submission/context.py",
    "adk_submission/discovery.py",
    "adk_submission/errors.py",
    "adk_submission/limits.py",
    "adk_submission/paths.py",
    "adk_submission/registry.py",
    "adk_submission/schema.py",
    "adk_submission/server.py",
    "adk_submission/yaml_loader.py",
    "adk_submission/builders/__init__.py",
    "adk_submission/builders/llm.py",
    "adk_submission/builders/sub_agents.py",
    "adk_submission/builders/workflows.py",
    "adk_submission/resolvers/__init__.py",
    "adk_submission/resolvers/callbacks.py",
    "adk_submission/resolvers/generation.py",
    "adk_submission/resolvers/models.py",
    "adk_submission/resolvers/tools.py",
)
COMPILER_URL = "https://raw.githubusercontent.com/happyc0der/gemma-swe-agent/main/harness/official/"
COMPILER_CACHE = Path("/tmp/adk011")
ADK_PY = Path("/tmp/adk-py")


def _yaml(name):
    return load_yaml(V15 / "sub_agents" / name, V15)


def _prompt(name):
    return (V15 / "sub_agents" / f"{name}.md").read_text()


def _load(path):
    spec = importlib.util.spec_from_file_location(f"v15_gate_{path.stat().st_ino}", path)
    module = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prior
    return module


def _gate(tmp_path):
    dest = tmp_path / "gate_run.py"
    shutil.copy(V15 / "skills/gate/scripts/run.py", dest)
    return _load(dest)


def _git(root, *args):
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _repo(path):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "Test")
    pkg = path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("VALUE = 1\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "base")
    return path


def test_caps_stay_at_v14_and_loops_target_150_and_240():
    loaded = load_yaml(V15 / "eval_config.yaml", V15)
    assert loaded["evaluation"]["timeout_seconds"] == 300
    assert loaded["evaluation"]["max_tool_calls"] == 220
    assert loaded["evaluation"]["max_time_minutes"] == 5
    assert loaded["evaluation"]["max_turns"] == 320
    assert sum(REPAIR_ITERS.values()) * STEP_SECONDS == 240
    assert REPAIR_ITERS["repair_1_loop"] * STEP_SECONDS == 150
    assert (V15 / "callbacks.py").exists() is False


def test_role_tool_lists_drop_reads_on_late_roles():
    triage = _yaml("triage.yaml")
    repair_1 = _yaml("repair_1.yaml")
    assert triage["tools"] == []
    assert triage["skills"] == ["skills/map"]
    assert triage["generate_content_config"]["max_output_tokens"] == 1024
    assert repair_1["tools"] == [
        "get_status",
        "read_file",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
    ]
    assert repair_1["generate_content_config"]["max_output_tokens"] == 2048
    assert _yaml("repair_2.yaml")["tools"] == ["get_status", "run_command"]
    assert _yaml("repair_3.yaml")["tools"] == ["get_status", "run_command"]
    assert _yaml("verify_1.yaml")["tools"] == ["get_status", "run_command"]
    assert _yaml("verify_2.yaml")["tools"] == ["get_status", "run_command"]
    assert _yaml("verify_3.yaml")["tools"] == ["get_status", "run_command", "submit_patch"]
    assert _yaml("verify_1.yaml")["skills"] == ["skills/check"]
    assert _yaml("verify_2.yaml")["skills"] == ["skills/check"]
    assert _yaml("verify_3.yaml")["skills"] == ["skills/gate"]
    assert _yaml("verify_1.yaml")["generate_content_config"]["max_output_tokens"] == 512
    assert _yaml("verify_3.yaml")["generate_content_config"]["max_output_tokens"] == 1024
    for name, iters in REPAIR_ITERS.items():
        loop = _yaml(f"{name}.yaml")
        assert loop["agent_class"] == "LoopAgent"
        assert loop["max_iterations"] == iters
    root = load_yaml(V15 / "agent.yaml", V15)
    assert root["agent_class"] == "SequentialAgent"
    assert [item["config_path"] for item in root["sub_agents"]] == [
        "sub_agents/triage.yaml",
        "sub_agents/repair_1_loop.yaml",
        "sub_agents/verify_1.yaml",
        "sub_agents/repair_2_loop.yaml",
        "sub_agents/verify_2.yaml",
        "sub_agents/repair_3_loop.yaml",
        "sub_agents/verify_3.yaml",
    ]
    for path in V15.rglob("*.yaml"):
        text = path.read_text()
        assert "before_tool_callbacks" not in text
        assert "after_tool_callbacks" not in text
        assert "before_model_callbacks" not in text


def test_prompts_use_get_status_and_require_the_gate():
    prefix = "printf '[elapsed %ss]\\n'"
    for name in ("repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3"):
        text = _prompt(name)
        assert "agent_elapsed_seconds" in text
        assert prefix in text
        assert "A write under /tmp is not a source edit." in text
    assert "15 times" in _prompt("repair_1")
    assert "150 or more" in _prompt("repair_1")
    assert "6 times" in _prompt("repair_2")
    assert "3 times" in _prompt("repair_3")
    assert "240 second" in _prompt("repair_3")
    for name in LATE_ROLES:
        text = _prompt(name)
        assert "read_file" in text
        assert "do not have" in text.lower()
    verify_3 = _prompt("verify_3")
    assert '{"skill_name":"gate","file_path":"scripts/run.py"}' in verify_3
    assert "submit_patch" in verify_3
    assert "skills/check" not in (V15 / "sub_agents" / "verify_3.yaml").read_text()
    gate = (V15 / "skills/gate/scripts/run.py").read_text()
    assert "git rev-parse" in gate
    assert "git show" not in gate
    assert "end_invocation" not in gate
    body = gate.split("def repo_root", 1)[1].split("\ndef ", 1)[0]
    assert "/workspace" not in body
    agent_text = "\n".join(path.read_text() for path in V15.rglob("*") if path.is_file())
    for task_id in UNREACHABLE:
        assert task_id not in agent_text


def test_map_and_check_stay_byte_identical_to_v14():
    for rel in (
        "skills/map/SKILL.md",
        "skills/map/scripts/run.py",
        "skills/check/SKILL.md",
        "skills/check/scripts/run.py",
        "sub_agents/thinking.yaml",
        "sub_agents/repair_thinking.yaml",
    ):
        assert (V15 / rel).read_bytes() == (V14 / rel).read_bytes()


def test_repo_root_uses_rev_parse_and_not_the_lab_checkout(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    monkeypatch.chdir(skill_dir)
    monkeypatch.delenv("GEMMA_CHECK_ROOT", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(repo))
    monkeypatch.setenv("PWD", str(skill_dir))
    module = _gate(tmp_path)
    assert module.repo_root() == repo.resolve()


def test_tmp_writes_are_not_edits_and_empty_diff_stays(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "note.py").write_text("VALUE = 2\n")
    monkeypatch.chdir(scratch)
    monkeypatch.setenv("PYTHONPATH", str(repo))
    module = _gate(tmp_path)
    assert module.is_tmp_path(repo, "pkg/mod.py") is False
    assert module.is_tmp_path(repo, "tmp/note.py") is True
    assert module.handle() == "PASS empty"
    assert (repo / "pkg" / "mod.py").read_text() == "VALUE = 1\n"


def test_py_compile_failure_restores_only_a_tmp_backup(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    target = repo / "pkg" / "mod.py"
    target.write_text("def broken(:\n")
    backup = Path(os.environ.get("TMPDIR", "/tmp")) / "pre_pkg_mod.py"
    backup.write_text("VALUE = 1\n")
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYTHONPATH", str(repo))
        module = _gate(tmp_path)
        text = module.handle()
        assert "compile FAIL pkg/mod.py restored" in text
        assert target.read_text() == "VALUE = 1\n"
        assert "git show" not in text
    finally:
        backup.unlink(missing_ok=True)


def test_py_compile_failure_without_backup_is_left_in_place(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    target = repo / "pkg" / "mod.py"
    target.write_text("def broken(:\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(repo))
    text = _gate(tmp_path).handle()
    assert "compile FAIL pkg/mod.py left" in text
    assert target.read_text() == "def broken(:\n"
    assert text.endswith("FAIL")


def test_import_and_test_failures_do_not_revert(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    broken = "raise RuntimeError('missing dep')\n"
    target = repo / "pkg" / "mod.py"
    target.write_text(broken)
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_mod.py").write_text("raise SystemExit('should not run')\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(repo))
    text = _gate(tmp_path).handle()
    assert "import FAIL pkg/mod.py" in text
    assert "restored" not in text
    assert target.read_text() == broken
    assert text.endswith("FAIL")


def test_src_layout_import_passes_without_a_wipe(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    src = repo / "src" / "pkg"
    src.mkdir(parents=True)
    module_path = src / "mod.py"
    module_path.write_text("VALUE = 3\n")
    (src / "__init__.py").write_text("")
    (repo / "src" / "__init__.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(repo))
    text = _gate(tmp_path).handle()
    assert "import PASS pkg.mod" in text or "import PASS src.pkg.mod" in text
    assert module_path.read_text() == "VALUE = 3\n"
    assert text.endswith("PASS")


def test_touched_module_test_failure_keeps_the_edit(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    target = repo / "pkg" / "mod.py"
    target.write_text("VALUE = 4\n")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_mod.py").write_text("raise SystemExit(1)\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(repo))
    text = _gate(tmp_path).handle()
    assert "test FAIL tests/test_mod.py exit=1" in text
    assert target.read_text() == "VALUE = 4\n"
    assert text.endswith("FAIL")


def test_hygiene_has_no_block_and_validation_passes():
    report = lint_candidate(V15)
    blocked = [item for item in report["findings"] if item.get("severity") == "block"]
    assert blocked == []
    assert validate(V15)


def test_notebook_compiles_the_plain_zip_with_nothing_registered():
    source = NOTEBOOK.read_text()
    assert "register_callbacks" not in source
    assert "CallbackRegistry" not in source
    assert "callback_registry" not in source
    assert "compile_submission" in source
    for task_id in DEV13:
        assert task_id in source
    assert "reachable ceiling" in source
    assert "calls_to_first_edit" in source


def test_archive_pins_v15_and_leaves_v14_unchanged(tmp_path):
    archive = tmp_path / "structured-v15.zip"
    manifest = pack(V15, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 27
    assert "callbacks.py" not in manifest["files"]
    assert "skills/gate/scripts/run.py" in manifest["files"]
    with zipfile.ZipFile(archive) as packed:
        script = packed.read("skills/gate/scripts/run.py")
    assert script == (V15 / "skills/gate/scripts/run.py").read_bytes()
    assert pack(V14, tmp_path / "structured-v14.zip")["sha256"] == V14_ARCHIVE
    assert not list(V15.rglob("__pycache__"))


def _ensure_compiler_source():
    schema = COMPILER_CACHE / "adk_submission" / "schema.py"
    if schema.is_file() and "ge=1" in schema.read_text():
        return COMPILER_CACHE
    COMPILER_CACHE.mkdir(parents=True, exist_ok=True)
    import urllib.request

    for rel in COMPILER_FILES:
        dest = COMPILER_CACHE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(COMPILER_URL + rel, dest)
    return COMPILER_CACHE


def _ensure_adk():
    if (ADK_PY / "google" / "adk" / "__init__.py").is_file():
        return ADK_PY
    pytest.skip("google-adk 1.36.1 is not installed under /tmp/adk-py")
    return ADK_PY


def _schema_tree(version, ge):
    source = _ensure_compiler_source()
    root = Path(f"/tmp/adk-schema-{version.replace('.', '')}")
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(source / "adk_submission", root / "adk_submission")
    schema = root / "adk_submission" / "schema.py"
    text = schema.read_text()
    old = "thinking_budget: int | None = Field(default=None, ge=1)"
    new = f"thinking_budget: int | None = Field(default=None, ge={ge})"
    if old not in text:
        raise AssertionError("public schema no longer has thinking_budget ge=1")
    schema.write_text(text.replace(old, new, 1))
    init = root / "adk_submission" / "__init__.py"
    init.write_text(init.read_text() + f'\n__version__ = "{version}"\n')
    return root


def _run_compiler(pkg_root, script, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(pkg_root), str(_ensure_adk())])
    env["PYTHONWARNINGS"] = "ignore"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr[-4000:] or completed.stdout[-4000:])
    return json.loads(completed.stdout)


def test_plain_archive_compiles_with_no_registry(tmp_path):
    archive = tmp_path / "structured-v15.zip"
    pack(V15, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v15.py"
    script.write_text(
        textwrap.dedent(
            """\
            import json
            import sys
            from pathlib import Path

            from adk_submission import GenerationConstraints
            from adk_submission import ModelRegistry
            from adk_submission import NumericRange
            from adk_submission import SubmissionLimits
            from adk_submission import ToolRegistry
            from adk_submission import compile_submission

            SOURCE = Path(sys.argv[1])
            LIMITS = SubmissionLimits(
                allowed_file_extensions=frozenset({".yaml", ".yml", ".md", ".txt", ".py", ".json"})
            )


            def tool(name):
                def _fn(*args, **kwargs):
                    return None
                _fn.__name__ = name
                return _fn


            def walk(agent, rows):
                config = getattr(agent, "generate_content_config", None)
                tokens = None if config is None else getattr(config, "max_output_tokens", None)
                tools = []
                skills = []
                for item in getattr(agent, "tools", []) or []:
                    if type(item).__name__ == "SkillToolset":
                        skills.extend(sorted(item._skills))
                    else:
                        tools.append(getattr(item, "__name__", type(item).__name__))
                rows.append({
                    "name": agent.name,
                    "kind": type(agent).__name__,
                    "max_iterations": getattr(agent, "max_iterations", None),
                    "tools": tools,
                    "skills": skills,
                    "max_output_tokens": tokens,
                    "before_tool": bool(getattr(agent, "before_tool_callback", None)),
                    "after_tool": bool(getattr(agent, "after_tool_callback", None)),
                    "before_model": bool(getattr(agent, "before_model_callback", None)),
                })
                for child in getattr(agent, "sub_agents", []) or []:
                    walk(child, rows)


            tools = ToolRegistry()
            for name in (
                "get_status",
                "read_file",
                "run_command",
                "search_similar_code",
                "get_code_neighbors",
                "get_code_subgraph",
                "submit_patch",
            ):
                tools.register(name, tool(name))
            models = ModelRegistry()
            models.register("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-31b-it-qat-w4a16-ct")
            agent = compile_submission(
                SOURCE,
                tools,
                models,
                limits=LIMITS,
                generation_constraints=GenerationConstraints(
                    allowed_fields=None,
                    max_output_tokens=NumericRange(1, 32768),
                    thinking_budget=NumericRange(0, 32768),
                    defaults={"max_output_tokens": 16384},
                ),
            )
            rows = []
            walk(agent, rows)
            print(json.dumps({
                "version": __import__("adk_submission").__version__,
                "rows": rows,
            }))
            """
        )
    )
    payloads = {}
    for version in ("0.2.12", "0.2.13"):
        tree = _schema_tree(version, 0)
        payloads[version] = _run_compiler(tree, script, str(unpacked))
    for version, payload in payloads.items():
        assert payload["version"] == version
        rows = {row["name"]: row for row in payload["rows"]}
        assert rows["structured_v15"]["kind"] == "SequentialAgent"
        assert rows["repair_1_loop"]["max_iterations"] == 15
        assert rows["repair_2_loop"]["max_iterations"] == 6
        assert rows["repair_3_loop"]["max_iterations"] == 3
        assert rows["triage"]["tools"] == []
        assert rows["triage"]["skills"] == ["map"]
        assert rows["triage"]["max_output_tokens"] == 1024
        assert rows["repair_1"]["tools"] == [
            "get_status",
            "read_file",
            "run_command",
            "search_similar_code",
            "get_code_neighbors",
            "get_code_subgraph",
        ]
        assert rows["repair_1"]["max_output_tokens"] == 2048
        for name in LATE_ROLES:
            assert READ_TOOLS.isdisjoint(rows[name]["tools"])
        assert rows["verify_3"]["tools"] == ["get_status", "run_command", "submit_patch"]
        assert rows["verify_3"]["skills"] == ["gate"]
        assert rows["verify_1"]["skills"] == ["check"]
        assert rows["verify_1"]["max_output_tokens"] == 512
        for row in payload["rows"]:
            assert row["before_tool"] is False
            assert row["after_tool"] is False
            assert row["before_model"] is False
    assert not list(V15.rglob("__pycache__"))
