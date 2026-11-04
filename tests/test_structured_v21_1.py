"""structured-v21-1 keeps the v21 cap and applies the verification fixes."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V211 = Path("agents/structured-v21-1").resolve()
V21 = Path("agents/structured-v21").resolve()
# Pack digest with the README hex replaced by 64 zeros. The README states this.
ZERO_PACK = "cefbcfe540ad99c0a24f6face5ea0edd40dc19166b838536a1ed2930d53e0291"
# gemma-lab pack digest of the committed directory. README cannot embed it.
ARCHIVE = "1a49094d9954e029333f76f202261fc8ae7d6951504ae3252f04140ceb6adc5d"
V21_ARCHIVE = "df8cf3319db43c45f208d111731c486ed8b44d7781a160558b87235577609572"
BASE_NOTEBOOK_SHA = "205a677fdcbd122f50ac3138b1cda0403aeb625453c93edf4c53b7b691926186"
ZEROS = "0" * 64


def _text(rel):
    return (V211 / rel).read_text()


def test_settings_stay_at_the_v21_cap():
    root = load_yaml(V211 / "agent.yaml", V211)
    sampling = load_yaml(V211 / "configs" / "sampling.yaml", V211)
    budgets = load_yaml(V211 / "eval_config.yaml", V211)["evaluation"]
    assert root["name"] == "structured_v21_1"
    assert "sub_agents" not in root
    assert root["tools"] == [
        "run_command",
        "read_file",
        "edit_file",
        "get_status",
        "submit_patch",
    ]
    assert "write_file" not in root["tools"]
    assert (V211 / "configs" / "sampling.yaml").read_bytes() == (
        V21 / "configs" / "sampling.yaml"
    ).read_bytes()
    assert (V211 / "eval_config.yaml").read_bytes() == (V21 / "eval_config.yaml").read_bytes()
    assert sampling["temperature"] == 0.2
    assert sampling["top_p"] == 0.95
    assert sampling["max_output_tokens"] == 8192
    assert sampling["thinking_config"]["thinking_budget"] == 4096
    assert sampling["thinking_config"]["include_thoughts"] is True
    assert budgets["timeout_seconds"] == 240
    assert budgets["max_tool_calls"] == 28
    assert float(budgets["max_time_minutes"]) == 8.0
    assert budgets["max_turns"] == 80


def test_prompt_fixes_and_attribution():
    prompt = _text("prompts/system.md")
    assert "{" not in prompt and "}" not in prompt
    assert "FastAPI" not in prompt
    assert "docs_src" not in prompt
    assert "Do not call write_file." in prompt
    assert 'name == "pytest.ini"' in prompt
    assert 'name == "tox.ini"' in prompt
    assert "At about call 18" in prompt
    assert "Do not end the run." in prompt
    assert "first batched search also greps the repo tests" in prompt
    assert "A passing repro still means edit." in prompt
    assert "mandatory input parameters are not present" in prompt
    assert "protected path" in prompt
    assert '"testing" in parts' in prompt
    assert "pyproject.toml" not in prompt
    assert "timeout 45 python -m pytest" in prompt
    assert "Do not delete untracked files." in prompt
    assert "Do not make a second repair." in prompt
    readme = _text("README.md")
    notice = _text("NOTICE.md")
    for text in (readme, notice, prompt):
        assert "verracodeguacas" in text
        assert "gemma-4-baseline-lb-0-24" in text
        assert "flexonafft/gemma-4-budget-aware-coding-agent-v2" in text
        assert "Apache License" in text
    assert BASE_NOTEBOOK_SHA in readme
    assert ZERO_PACK in readme
    assert "Hypothesis" in readme
    assert "not ready" in readme
    assert "Apache License" in (V211 / "LICENSE.txt").read_text()


def test_hygiene_passes_without_write_file():
    report = lint_candidate(V211)
    blocks = [item["rule"] for item in report["findings"] if item["severity"] == "block"]
    assert blocks == []
    assert report["gate"] != "block"
    assert len(validate(V211)) == 7


def test_archive_pin_and_v21_unchanged(tmp_path):
    archive = tmp_path / "structured-v21-1.zip"
    manifest = pack(V211, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 7
    readme = _text("README.md")
    restored = readme.replace(ZERO_PACK, ZEROS, 1)
    assert restored != readme
    copy = tmp_path / "zero-readme"
    shutil.copytree(V211, copy)
    (copy / "README.md").write_text(restored)
    assert pack(copy, tmp_path / "zero.zip")["sha256"] == ZERO_PACK
    assert pack(V21, tmp_path / "structured-v21.zip")["sha256"] == V21_ARCHIVE


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


def test_plain_archive_compiles_on_both_adk_versions(tmp_path):
    archive = tmp_path / "structured-v21-1.zip"
    pack(V211, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v21_1.py"
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
                "get_status", "read_file", "run_command", "edit_file", "write_file",
                "search_similar_code", "get_code_neighbors", "get_code_subgraph",
                "submit_patch",
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
        assert rows["structured_v21_1"]["kind"] == "LlmAgent"
        names = rows["structured_v21_1"]["tools"]
        assert names == [
            "run_command",
            "read_file",
            "edit_file",
            "get_status",
            "submit_patch",
        ]
        assert "write_file" not in names
        assert "search_similar_code" not in names
        assert rows["structured_v21_1"]["max_output_tokens"] == 8192
        assert rows["structured_v21_1"]["before_tool"] is False
