"""structured-v18-1 bounds localize_1 and inlines the line_fix heredoc."""

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

V181 = Path("agents/structured-v18-1").resolve()
V18 = Path("agents/structured-v18").resolve()
ARCHIVE = "0fde003c39592d8c2a3439231e3d333d6f0f31e27761a6210620693fffcde475"
V18_ARCHIVE = "b6137580f3870e312491f68f97cfdd36cb88d89387dbd782d8007ba3056b42d5"
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
READ_ONLY = ["get_status", "read_file"]
PATCH_TOOLS = ["get_status", "run_command"]


def _prompt(name):
    return (V181 / "sub_agents" / f"{name}.md").read_text()


def _yaml(name):
    return load_yaml(V181 / "sub_agents" / name, V181)


def test_localize_is_bounded_without_a_loop():
    root = load_yaml(V181 / "agent.yaml", V181)
    budgets = load_yaml(V181 / "eval_config.yaml", V181)["evaluation"]
    localize = _yaml("localize_1.yaml")
    prompt = _prompt("localize_1")
    assert root["name"] == "structured_v18_1"
    assert root["agent_class"] == "SequentialAgent"
    assert [item["config_path"] for item in root["sub_agents"]][1] == "sub_agents/localize_1.yaml"
    assert localize["agent_class"] == "LlmAgent"
    assert "max_iterations" not in localize
    assert not (V181 / "sub_agents" / "localize_1_loop.yaml").exists()
    assert localize["tools"] == READ_ONLY
    assert "run_command" not in localize["tools"]
    assert "search_similar_code" not in localize["tools"]
    sampling = localize["generate_content_config"]
    assert sampling["max_output_tokens"] == 512
    assert sampling["stop_sequences"] == ["END_LOCALIZE"]
    assert "before_tool_callback" not in localize
    assert "At most 6 tool calls" in prompt
    assert "END_LOCALIZE" in prompt
    assert "HYPOTHESIS: <path>:<function> - <one-sentence change>" in prompt
    assert budgets["timeout_seconds"] == 300
    assert float(budgets["max_time_minutes"]) == 5.0
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320


def test_patch_prompts_inline_the_heredoc_and_keep_the_skill():
    for name in ("patch_1", "patch_2", "patch_3"):
        prompt = _prompt(name)
        role = _yaml(f"{name}.yaml")
        assert "cat > /tmp/line_fix.py <<'EOF'" in prompt
        assert "Do not call load_skill." in prompt
        assert "from skill force-heredoc" not in prompt
        assert role["skills"] == ["skills/force-heredoc"]
        assert role["tools"] == PATCH_TOOLS
    skill = (V181 / "skills" / "force-heredoc" / "SKILL.md").read_bytes()
    assert skill == (V18 / "skills" / "force-heredoc" / "SKILL.md").read_bytes()
    assert (V181 / "skills" / "check" / "scripts" / "run.py").read_bytes() == (
        V18 / "skills" / "check" / "scripts" / "run.py"
    ).read_bytes()


def test_agent_dir_has_no_dev13_ids():
    hits = []
    for path in sorted(V181.rglob("*")):
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
    report = lint_candidate(V181)
    assert report["gate"] == "pass", report["findings"]
    assert len(validate(V181)) == 26


def test_archive_pins_v18_1_and_leaves_v18_unchanged(tmp_path):
    archive = tmp_path / "structured-v18-1.zip"
    manifest = pack(V181, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 26
    readme = (V181 / "README.md").read_text()
    assert "SHA256: `" in readme
    assert pack(V18, tmp_path / "structured-v18.zip")["sha256"] == V18_ARCHIVE


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
    if root.exists():
        shutil.rmtree(root)
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


def _harness_tools(row):
    return [name for name in row["tools"] if name != "SkillToolset"]


def test_plain_archive_compiles_with_no_registry(tmp_path):
    archive = tmp_path / "structured-v18-1.zip"
    pack(V181, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v181.py"
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
    adk_root = _adk_target(tmp_path)
    payloads = {}
    for version in ("0.2.12", "0.2.13"):
        payloads[version] = _run_compiler(
            _schema_tree(tmp_path, version), adk_root, script, str(unpacked)
        )
    for version, payload in payloads.items():
        assert payload["version"] == version
        rows = {row["name"]: row for row in payload["rows"]}
        assert rows["structured_v18_1"]["kind"] == "SequentialAgent"
        assert rows["localize_1"]["kind"] == "LlmAgent"
        assert rows["localize_1"]["max_iterations"] is None
        assert rows["localize_1"]["tools"] == READ_ONLY
        assert rows["localize_1"]["max_output_tokens"] == 512
        assert rows["localize_1"]["stop_sequences"] == ["END_LOCALIZE"]
        assert "localize_1_loop" not in rows
        assert rows["patch_1_loop"]["kind"] == "LoopAgent"
        assert rows["patch_1_loop"]["max_iterations"] == 2
        assert _harness_tools(rows["patch_1"]) == PATCH_TOOLS
        assert "SkillToolset" in rows["patch_1"]["tools"]
        assert "submit_patch" in rows["verify_3"]["tools"]
        for row in rows.values():
            assert row["before_tool"] is False
