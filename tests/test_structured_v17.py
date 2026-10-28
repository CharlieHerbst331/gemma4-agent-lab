"""structured-v17 is a call-bounded hypothesis-then-edit copy of structured-v13-1."""

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

V17 = Path("agents/structured-v17").resolve()
V131 = Path("agents/structured-v13-1").resolve()
ARCHIVE = "27b47d34554d9b64f3786b430856dd950d678d5ea6dbd4a0ae6fb7dd687e79e6"
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


def _prompt(name):
    return (V17 / "sub_agents" / f"{name}.md").read_text()


def test_hypothesis_then_heredoc_is_a_count_rule():
    repair_1 = _prompt("repair_1")
    repair_2 = _prompt("repair_2")
    repair = load_yaml(V17 / "sub_agents" / "repair_1.yaml", V17)
    budgets = load_yaml(V17 / "eval_config.yaml", V17)["evaluation"]
    root = load_yaml(V17 / "agent.yaml", V17)
    assert root["name"] == "structured_v17"
    assert root["agent_class"] == "SequentialAgent"
    assert repair["agent_class"] == "LlmAgent"
    assert not (V17 / "sub_agents" / "repair_1_loop.yaml").exists()
    assert "stop_sequences" not in repair
    assert budgets["timeout_seconds"] == 300
    assert float(budgets["max_time_minutes"]) == 5.0
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert "Repro is optional and costs at most 2 calls." in repair_1
    assert "A passing repro is NOT evidence you have the wrong place." in repair_1
    assert "first assert must fail" not in repair_1
    assert "After at most 4 file reads" in repair_1
    assert "HYPOTHESIS: <path>:<function> - <one-sentence change>" in repair_1
    assert "The VERY NEXT tool call MUST be the guarded heredoc edit" in repair_1
    assert "An imperfect edit is better than an empty diff." in repair_1
    assert "After the first successful heredoc, or after that HYPOTHESIS line" in repair_1
    assert "one LlmAgent pass" in repair_1
    assert "time_seconds_remaining is under 120" in repair_1
    assert "about 240" in repair_1
    assert "180 or more" in repair_1
    assert "HAND-OFF DUE" not in repair_1
    assert "your FIRST tool call is the heredoc edit" in repair_2
    assert "latest HYPOTHESIS line" in repair_2
    assert "first file and function named in the triage brief or the round 1 report" in repair_2
    assert "one 40-line window" in repair_2
    assert "retry the heredoc once" in repair_2
    assert "time_seconds_remaining is under 120" in repair_2
    assert not list(V17.rglob("**/map/**"))
    assert (V17 / "skills" / "check" / "SKILL.md").is_file()


def test_agent_dir_has_no_dev13_ids():
    hits = []
    for path in sorted(V17.rglob("*")):
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
    report = lint_candidate(V17)
    assert report["gate"] == "pass", report["findings"]
    assert len(validate(V17)) == 20


def test_archive_pins_v17_and_leaves_v13_1_unchanged(tmp_path):
    archive = tmp_path / "structured-v17.zip"
    manifest = pack(V17, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 20
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


def test_plain_archive_compiles_with_no_registry(tmp_path):
    archive = tmp_path / "structured-v17.zip"
    pack(V17, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v17.py"
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
        assert rows["structured_v17"]["kind"] == "SequentialAgent"
        assert "repair_1_loop" not in rows
        assert rows["repair_1"]["kind"] == "LlmAgent"
        assert rows["repair_1"]["max_iterations"] is None
        assert "read_file" in rows["repair_1"]["tools"]
        assert "run_command" in rows["repair_1"]["tools"]
        assert rows["repair_1"]["stop_sequences"] is None
        assert rows["repair_2"]["tools"] == ["get_status", "read_file", "run_command"]
        assert "submit_patch" in rows["verify_3"]["tools"]
        for row in rows.values():
            assert row["before_tool"] is False
