"""structured-v18 is a localize/patch split of structured-v13-1."""

import json
import os
import re
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

V18 = Path("agents/structured-v18").resolve()
V17 = Path("agents/structured-v17").resolve()
V131 = Path("agents/structured-v13-1").resolve()
ARCHIVE = "b6137580f3870e312491f68f97cfdd36cb88d89387dbd782d8007ba3056b42d5"
V17_ARCHIVE = "27b47d34554d9b64f3786b430856dd950d678d5ea6dbd4a0ae6fb7dd687e79e6"
V131_ARCHIVE = "74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe"
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
EMPTY_DIFF_ESCAPE = (
    "If time_seconds_remaining is under 45, the next response is text only, "
    "even when git diff is empty"
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
COMPILER_CACHE = Path("/tmp/adk011")
ADK_PY = Path("/tmp/adk-py")
READ_ONLY = [
    "get_status",
    "read_file",
    "search_similar_code",
    "get_code_neighbors",
    "get_code_subgraph",
]
PATCH_TOOLS = ["get_status", "run_command"]


def _prompt(name):
    return (V18 / "sub_agents" / f"{name}.md").read_text()


def _yaml(name):
    return load_yaml(V18 / "sub_agents" / name, V18)


def test_full_localize_patch_split():
    root = load_yaml(V18 / "agent.yaml", V18)
    budgets = load_yaml(V18 / "eval_config.yaml", V18)["evaluation"]
    localize = _yaml("localize_1.yaml")
    patch_1_loop = _yaml("patch_1_loop.yaml")
    patch_1 = _yaml("patch_1.yaml")
    patch_2_loop = _yaml("patch_2_loop.yaml")
    patch_2 = _yaml("patch_2.yaml")
    patch_3 = _yaml("patch_3.yaml")
    verify_3 = _yaml("verify_3.yaml")
    assert root["name"] == "structured_v18"
    assert root["agent_class"] == "SequentialAgent"
    assert [item["config_path"] for item in root["sub_agents"]] == [
        "sub_agents/triage.yaml",
        "sub_agents/localize_1.yaml",
        "sub_agents/patch_1_loop.yaml",
        "sub_agents/verify_1.yaml",
        "sub_agents/patch_2_loop.yaml",
        "sub_agents/verify_2.yaml",
        "sub_agents/patch_3.yaml",
        "sub_agents/verify_3.yaml",
    ]
    assert localize["agent_class"] == "LlmAgent"
    assert localize["tools"] == READ_ONLY
    assert "run_command" not in localize["tools"]
    assert "skills" not in localize
    assert patch_1_loop["agent_class"] == "LoopAgent"
    assert patch_1_loop["max_iterations"] == 2
    assert patch_2_loop["agent_class"] == "LoopAgent"
    assert patch_2_loop["max_iterations"] == 2
    assert patch_1["agent_class"] == "LlmAgent"
    assert patch_1["tools"] == PATCH_TOOLS
    assert patch_2["tools"] == PATCH_TOOLS
    assert patch_3["agent_class"] == "LlmAgent"
    assert patch_3["tools"] == PATCH_TOOLS
    assert not (V18 / "sub_agents" / "patch_3_loop.yaml").exists()
    assert verify_3["tools"] == ["get_status", "run_command", "submit_patch"]
    assert _yaml("verify_1.yaml")["tools"] == ["get_status", "read_file", "run_command"]
    assert "submit_patch" not in _yaml("verify_1.yaml")["tools"]
    assert "submit_patch" not in _yaml("verify_2.yaml")["tools"]
    assert patch_1["skills"] == ["skills/force-heredoc"]
    assert verify_3["skills"] == ["skills/check", "skills/force-heredoc"]
    assert "before_tool_callback" not in patch_1
    assert "stop_sequences" not in patch_1
    assert budgets["timeout_seconds"] == 300
    assert float(budgets["max_time_minutes"]) == 5.0
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert not list(V18.rglob("repair_[0-9]*"))
    assert (V18 / "sub_agents" / "repair_thinking.yaml").is_file()
    assert not list(V18.rglob("**/map/**"))
    assert (V18 / "skills" / "check" / "SKILL.md").read_bytes() == (
        V17 / "skills" / "check" / "SKILL.md"
    ).read_bytes()
    assert (V18 / "skills" / "check" / "scripts" / "run.py").read_bytes() == (
        V17 / "skills" / "check" / "scripts" / "run.py"
    ).read_bytes()
    readme = (V18 / "README.md").read_text()
    assert "scored 0.12, tying v13-1, below v8 at 0.13" in readme
    assert "about 50 of 118 tasks" in readme


def test_empty_diff_escapes_are_gone_and_patch_slots_are_wired():
    patch_1 = _prompt("patch_1")
    patch_2 = _prompt("patch_2")
    patch_3 = _prompt("patch_3")
    verify_1 = _prompt("verify_1")
    verify_2 = _prompt("verify_2")
    verify_3 = _prompt("verify_3")
    for text in (patch_1, patch_2, patch_3, verify_1, verify_2, verify_3):
        assert EMPTY_DIFF_ESCAPE not in text
        assert "The last verify owns that edit" not in text
        assert "{repair_" not in text
    assert "your FIRST run_command MUST be the guarded heredoc" in patch_1
    assert "text-only ending while DIFF is empty when 30 or more seconds remain" in patch_2
    assert "text only even when empty" in patch_3
    assert "{localize_1_report?}" in patch_1
    assert "{patch_1_report?}" in verify_1
    assert "{patch_2_report?}" in verify_2
    assert "{verify_2_report?}" in patch_3
    assert "{patch_3_report?}" in verify_3
    assert "FORCE_NEXT: heredoc" in verify_1
    assert "call submit_patch anyway" in verify_3
    assert "HYPOTHESIS: <path>:<function> - <one-sentence change>" in _prompt("localize_1")
    assert "Do not call run_command." in _prompt("localize_1")


def test_agent_dir_has_no_dev13_ids():
    hits = []
    for path in sorted(V18.rglob("*")):
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
    report = lint_candidate(V18)
    assert report["gate"] == "pass", report["findings"]
    assert len(validate(V18)) == 26


def test_archive_pins_v18_and_leaves_baselines_unchanged(tmp_path):
    archive = tmp_path / "structured-v18.zip"
    manifest = pack(V18, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 26
    assert pack(V17, tmp_path / "structured-v17.zip")["sha256"] == V17_ARCHIVE
    assert pack(V131, tmp_path / "structured-v13-1.zip")["sha256"] == V131_ARCHIVE


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


def _harness_tools(row):
    return [name for name in row["tools"] if name != "SkillToolset"]


def test_plain_archive_compiles_with_no_registry(tmp_path):
    archive = tmp_path / "structured-v18.zip"
    pack(V18, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v18.py"
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
                thinking = None
                if config is not None:
                    thinking_config = getattr(config, "thinking_config", None)
                    if thinking_config is not None:
                        thinking = getattr(thinking_config, "thinking_budget", None)
                tools = []
                for item in getattr(agent, "tools", []) or []:
                    tools.append(getattr(item, "__name__", type(item).__name__))
                rows.append({
                    "name": agent.name,
                    "kind": type(agent).__name__,
                    "max_iterations": getattr(agent, "max_iterations", None),
                    "tools": tools,
                    "thinking_budget": thinking,
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
            print(json.dumps({"version": __import__("adk_submission").__version__, "rows": rows}))
            """
        )
    )
    payloads = {}
    for version in ("0.2.12", "0.2.13"):
        payloads[version] = _run_compiler(_schema_tree(version, 0), script, str(unpacked))
    for version, payload in payloads.items():
        assert payload["version"] == version
        rows = {row["name"]: row for row in payload["rows"]}
        assert rows["structured_v18"]["kind"] == "SequentialAgent"
        assert rows["localize_1"]["kind"] == "LlmAgent"
        assert rows["localize_1"]["tools"] == READ_ONLY
        assert rows["localize_1"]["thinking_budget"] == 0
        assert rows["patch_1_loop"]["kind"] == "LoopAgent"
        assert rows["patch_1_loop"]["max_iterations"] == 2
        assert rows["patch_2_loop"]["kind"] == "LoopAgent"
        assert rows["patch_2_loop"]["max_iterations"] == 2
        assert _harness_tools(rows["patch_1"]) == PATCH_TOOLS
        assert "SkillToolset" in rows["patch_1"]["tools"]
        assert rows["patch_1"]["thinking_budget"] == 256
        assert _harness_tools(rows["patch_2"]) == PATCH_TOOLS
        assert _harness_tools(rows["patch_3"]) == PATCH_TOOLS
        assert rows["patch_3"]["max_iterations"] is None
        assert "read_file" not in rows["patch_3"]["tools"]
        assert "submit_patch" not in rows["patch_1"]["tools"]
        assert "submit_patch" in rows["verify_3"]["tools"]
        assert "read_file" not in rows["verify_3"]["tools"]
        assert "repair_1" not in rows
        for row in rows.values():
            assert row["before_tool"] is False
