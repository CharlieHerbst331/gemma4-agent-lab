"""structured-v20-1 keeps repros out of the graded diff."""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V201 = Path("agents/structured-v20-1").resolve()
V20 = Path("agents/structured-v20").resolve()
ARCHIVE = "9b34aff376a2d4acc73441ea6beaf73665cd95631c14faa0df221b1a4af70c07"
V20_ARCHIVE = "7d7522e08c149ddd79e4385997fc77f567491082c31b3717d762fa048e523773"
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
BARE_DEV13_NUMBERS = re.compile(
    r"\b(11194|14246|14262|14356|14786|14794|3105|3454|3472|3934|3938|3944|4070)\b"
)
LIBRARY_TERMS = (
    re.compile(r"fastapi", re.IGNORECASE),
    re.compile(r"\brich\b", re.IGNORECASE),
    re.compile(r"\bLive\b"),
    re.compile(r"textualize", re.IGNORECASE),
    re.compile(r"live\.py", re.IGNORECASE),
    re.compile(r"pretty\.py", re.IGNORECASE),
    re.compile(r"live_render", re.IGNORECASE),
)
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
RESTORE = (
    "test -s /tmp/best.diff && git diff > /tmp/repair.diff "
    "&& git checkout -- . && (git apply /tmp/best.diff || git apply /tmp/repair.diff)"
)


def _prompt(name):
    return (V201 / "sub_agents" / f"{name}.md").read_text()


def _yaml(name):
    return load_yaml(V201 / "sub_agents" / name, V201)


def test_three_roles_and_tests_first_handoff():
    root = load_yaml(V201 / "agent.yaml", V201)
    budgets = load_yaml(V201 / "eval_config.yaml", V201)["evaluation"]
    assert root["name"] == "structured_v20_1"
    assert [item["config_path"] for item in root["sub_agents"]] == [
        "sub_agents/triage_localize.yaml",
        "sub_agents/patch_loop.yaml",
        "sub_agents/verify.yaml",
    ]
    assert budgets["timeout_seconds"] == 300
    assert budgets["max_tool_calls"] == 220
    assert float(budgets["max_time_minutes"]) == 5.0
    assert budgets["max_turns"] == 320
    loc = _yaml("triage_localize.yaml")
    patch_loop = _yaml("patch_loop.yaml")
    patch = _yaml("patch.yaml")
    verify = _yaml("verify.yaml")
    assert loc["tools"] == ["get_status", "read_file", "run_command"]
    assert loc["generate_content_config"]["max_output_tokens"] == 1024
    assert loc["generate_content_config"]["stop_sequences"] == ["END_HANDOFF"]
    assert patch_loop["max_iterations"] == 1
    assert patch["tools"] == ["get_status", "run_command"]
    assert "submit_patch" not in patch["tools"]
    assert verify["tools"] == ["get_status", "run_command", "submit_patch"]
    assert "before_tool_callback" not in verify
    handoff = _prompt("triage_localize")
    patch_md = _prompt("patch")
    verify_md = _prompt("verify")
    skill = (V201 / "skills" / "force-heredoc" / "SKILL.md").read_text()
    assert "grep -rln" in handoff
    assert "already fixed" in handoff
    assert "FILE:" in handoff and "FUNCTION:" in handoff
    assert "HYPOTHESIS:" in handoff and "EVIDENCE:" in handoff
    assert "After 12 tool calls" in patch_md
    assert "150 or more" in patch_md
    assert "already ran, see above" in patch_md
    assert "Any other key is unknown" in patch_md
    assert "protected path" in patch_md
    assert "exactly one heredoc" in verify_md
    assert "timeout 40 pytest -x -q" in verify_md
    assert "timeout 20 python3 /tmp/repro_check.py" in handoff
    assert "about 15 lines" in handoff
    assert "git status --porcelain -uall" in verify_md
    assert "ls-files" in verify_md
    assert "git clean" in verify_md
    assert "git diff > /tmp/best.diff" in verify_md
    assert RESTORE in verify_md
    assert "Exactly one edit" in skill
    assert "protected path" in skill
    assert '"testing" in parts' in skill
    assert "pyproject.toml" not in skill.split("banned = name in", 1)[1].split("}", 1)[0]
    assert "setup.cfg" not in skill.split("banned = name in", 1)[1].split("}", 1)[0]
    assert RESTORE in skill


def test_agent_dir_has_no_dev13_ids():
    hits = []
    for path in sorted(V201.rglob("*")):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        text = path.read_text(errors="replace")
        for task_id in DEV13:
            if task_id in text:
                hits.append(f"{path.name}: {task_id}")
        if BARE_DEV13_NUMBERS.search(text):
            hits.append(f"{path.name}: bare dev-13 number")
        for pattern in LIBRARY_TERMS:
            if pattern.search(text):
                hits.append(f"{path.name}: {pattern.pattern}")
    assert hits == []


def test_hygiene_and_validation():
    report = lint_candidate(V201)
    assert report["gate"] == "pass", report["findings"]
    assert len(validate(V201)) == 15


def test_archive_pins_v20_1_and_leaves_v20_unchanged(tmp_path):
    archive = tmp_path / "structured-v20-1.zip"
    manifest = pack(V201, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 15
    assert "Hypothesis" in (V201 / "README.md").read_text()
    assert pack(V20, tmp_path / "structured-v20.zip")["sha256"] == V20_ARCHIVE


def _compiler_source(tmp_path):
    root = tmp_path / "compiler"
    schema = root / "adk_submission" / "schema.py"
    if schema.is_file() and "ge=1" in schema.read_text():
        return root
    import urllib.request

    for rel in COMPILER_FILES:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(COMPILER_URL + rel, dest)
    return root


def _adk_target(tmp_path):
    target = tmp_path / "google-adk"
    if (target / "google" / "adk" / "__init__.py").is_file():
        return target
    uv = shutil.which("uv")
    if uv is None:
        home = Path.home() / ".local" / "bin" / "uv"
        uv = str(home) if home.is_file() else None
    if uv is None:
        raise AssertionError("uv is required to install google-adk==1.36.1")
    completed = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "google-adk==1.36.1",
            "--target",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr[-2000:] or completed.stdout[-2000:])
    return target


def _schema_tree(tmp_path, version):
    source = _compiler_source(tmp_path)
    root = tmp_path / f"schema-{version.replace('.', '')}"
    shutil.copytree(source / "adk_submission", root / "adk_submission")
    schema = root / "adk_submission" / "schema.py"
    text = schema.read_text()
    old = "thinking_budget: int | None = Field(default=None, ge=1)"
    new = "thinking_budget: int | None = Field(default=None, ge=0)"
    if old not in text:
        raise AssertionError("public schema no longer has thinking_budget ge=1")
    schema.write_text(text.replace(old, new, 1))
    init = root / "adk_submission" / "__init__.py"
    init.write_text(init.read_text() + f'\n__version__ = "{version}"\n')
    return root


def _run_compiler(pkg_root, adk_root, script, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(pkg_root), str(adk_root)])
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
    archive = tmp_path / "structured-v20-1.zip"
    pack(V201, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v19.py"
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


            def tool(name):
                def _fn(*args, **kwargs):
                    return None
                _fn.__name__ = name
                return _fn


            def walk(agent, rows):
                config = getattr(agent, "generate_content_config", None)
                tools = []
                for item in getattr(agent, "tools", []) or []:
                    tools.append(getattr(item, "__name__", type(item).__name__))
                rows.append({
                    "name": agent.name,
                    "kind": type(agent).__name__,
                    "max_iterations": getattr(agent, "max_iterations", None),
                    "tools": tools,
                    "max_output_tokens": None if config is None else getattr(
                        config, "max_output_tokens", None
                    ),
                    "stop_sequences": None if config is None else getattr(
                        config, "stop_sequences", None
                    ),
                    "before_tool": bool(getattr(agent, "before_tool_callback", None)),
                })
                for child in getattr(agent, "sub_agents", []) or []:
                    walk(child, rows)


            tools = ToolRegistry()
            for name in (
                "get_status", "read_file", "run_command", "search_similar_code",
                "get_code_neighbors", "get_code_subgraph", "submit_patch",
            ):
                tools.register(name, tool(name))
            models = ModelRegistry()
            models.register("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-31b-it-qat-w4a16-ct")
            agent = compile_submission(
                SOURCE,
                tools,
                models,
                limits=SubmissionLimits(
                    allowed_file_extensions=frozenset(
                        {".yaml", ".yml", ".md", ".txt", ".py", ".json"}
                    )
                ),
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
    adk_root = _adk_target(tmp_path)
    payloads = {}
    for version in ("0.2.12", "0.2.13"):
        payloads[version] = _run_compiler(
            _schema_tree(tmp_path, version),
            adk_root,
            script,
            str(unpacked),
        )
    for version, payload in payloads.items():
        assert payload["version"] == version
        rows = {row["name"]: row for row in payload["rows"]}
        assert rows["structured_v20_1"]["kind"] == "SequentialAgent"
        assert rows["patch_loop"]["kind"] == "LoopAgent"
        assert rows["patch_loop"]["max_iterations"] == 1
        assert rows["triage_localize"]["tools"] == ["get_status", "read_file", "run_command"]
        assert rows["triage_localize"]["stop_sequences"] == ["END_HANDOFF"]
        assert [name for name in rows["patch"]["tools"] if name != "SkillToolset"] == [
            "get_status",
            "run_command",
        ]
        assert "submit_patch" in rows["verify"]["tools"]
        assert "repair" not in rows
        for row in rows.values():
            assert row["before_tool"] is False
