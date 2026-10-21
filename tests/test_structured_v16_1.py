"""structured-v16.1 is a 240 second prompt copy of structured-v16."""

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

V16 = Path("agents/structured-v16").resolve()
V161 = Path("agents/structured-v16-1").resolve()
V131 = Path("agents/structured-v13-1").resolve()
NOTEBOOK = Path("notebooks/structured-v16-1-dev13/evaluation.ipynb").resolve()
ARCHIVE = "dff316a37290895d377574bbedfd43d0b962f9871e700974b2c1b663be7f6c38"
V16_ARCHIVE = "6b8920c396f4e84fe14e7b7a907c1771436a55b840fae7464b3ce6f7cac13491"
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
# Library-specific terms from the v16 smoke7 analysis. They must not appear
# in the agent directory. Generic steering words such as display, render,
# stop, and __exit__ are allowed.
LIBRARY_TERMS = (
    re.compile(r"fastapi", re.IGNORECASE),
    re.compile(r"\brich\b", re.IGNORECASE),
    re.compile(r"\bLive\b"),
    re.compile(r"textualize", re.IGNORECASE),
    re.compile(r"live\.py", re.IGNORECASE),
    re.compile(r"__enter__"),
    re.compile(r"test_live", re.IGNORECASE),
    re.compile(r"console\.py", re.IGNORECASE),
    re.compile(r"table\.py", re.IGNORECASE),
    re.compile(r"progress\.py", re.IGNORECASE),
    re.compile(r"get_body_field"),
    re.compile(r"request_body_to_args"),
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
STEERING = (
    'A repro that runs without an exception has not "passed". '
    "Print repr() of the captured output and compare it with the issue title: "
    'for an "empty"/"nothing" case, any newline, blank line or escape code left behind '
    "IS the bug. Output that appears when a context manager or display ends comes from "
    "the object's stop / __exit__ / close / cleanup path - read that method before the "
    "render path. Before editing, grep tests/test_<module>.py for the closest existing "
    "test and reuse its capture helper."
)


def _prompt(name):
    return (V161 / "sub_agents" / f"{name}.md").read_text()


def test_repair_1_reads_through_the_clock_and_ends_the_round():
    text = _prompt("repair_1")
    repair = load_yaml(V161 / "sub_agents" / "repair_1.yaml", V161)
    assert repair["tools"] == [
        "get_status",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
    ]
    assert "read_file" not in repair["tools"]
    assert "You do not have read_file." in text
    assert "Call read_file" not in text
    read = (
        "test -f /tmp/t0 || date +%s > /tmp/t0; "
        "printf '[elapsed %ss]\\n' \"$(( $(date +%s) - $(cat /tmp/t0) ))\"; "
        "nl -ba PATH | sed -n 'A,Bp' | head -c 4000"
    )
    assert read in text
    assert "When any [elapsed] line shows 100 or more, or you have made 6 reads" in text
    assert (
        "your next reply is the HYPOTHESIS line and the round: 1 report with no tool call" in text
    )
    assert "repair_2 makes the edit." in text
    assert "Repro is optional and costs at most 2 calls." in text
    assert "two non-failing repros means stop reproducing" in text
    assert (
        "If two repros show no failure, stop reproducing: the bug is in the code path "
        "the issue names; write HYPOTHESIS for the most specific function there."
    ) in text
    assert "A passing repro is not evidence you have the wrong place." in text
    assert STEERING in text


def test_thresholds_scale_to_the_240_second_cap():
    repair_1 = _prompt("repair_1")
    repair_2 = _prompt("repair_2")
    verify_3 = _prompt("verify_3")
    budgets = load_yaml(V161 / "eval_config.yaml", V161)["evaluation"]
    assert budgets["timeout_seconds"] == 240
    assert budgets["max_time_minutes"] == 4.0
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert "120 seconds is the hand-off" in repair_1
    assert (
        "time_seconds_remaining is under 96 and at least 36 seconds remain, "
        "write the HYPOTHESIS line and the next call is the heredoc."
    ) in repair_1
    assert "time_seconds_remaining is under 36" in repair_1
    assert "Do not run the missed-hand-off heredoc." in repair_1
    assert "about 192 seconds" in repair_1
    assert "your FIRST tool call is the heredoc edit" in repair_2
    assert "latest HYPOTHESIS line" in repair_2
    assert "first file and function named in the triage brief or the round 1 report" in repair_2
    assert "Do not read first." in repair_2
    assert "under 96" in repair_2
    assert "36 seconds or more remain" in repair_2
    assert "about 192" in _prompt("verify_1")
    assert "under 72" in _prompt("verify_1")
    assert "under 96" in _prompt("verify_1")
    assert "about 192" in _prompt("repair_3")
    assert "under 96" in _prompt("repair_3")
    assert "Submit at 200." in verify_3
    assert "agent_elapsed_seconds is 200 or more" in verify_3
    assert "Skip the check." in verify_3
    assert "144 second line" in verify_3
    assert "about-192 line" in verify_3
    assert "under 36 seconds remain" in verify_3
    root = load_yaml(V161 / "agent.yaml", V161)
    assert root["name"] == "structured_v16_1"
    assert root["agent_class"] == "SequentialAgent"


def test_agent_dir_has_no_dev13_ids_or_library_terms():
    hits = []
    for path in sorted(V161.rglob("*")):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        text = path.read_text(errors="replace")
        for task_id in DEV13:
            if task_id in text:
                hits.append(f"{path.name}: {task_id}")
        for pattern in LIBRARY_TERMS:
            if pattern.search(text):
                hits.append(f"{path.name}: {pattern.pattern}")
    assert hits == []


def test_notebook_embeds_the_archive_and_keeps_traces():
    source = NOTEBOOK.read_text()
    assert ARCHIVE in source
    assert "register_callbacks" not in source
    assert "CallbackRegistry" not in source
    assert "callback_registry" not in source
    assert "submission_dir=AGENT_DIR" in source
    assert "Evaluator(" in source
    assert "max_tool_calls = 220" in source
    assert "max_time_minutes = 4.0" in source
    assert "results/traces/trace_" in source
    assert "this cell must not replace that file" in source
    assert "HYPOTHESIS" in source
    assert "calls_to_first_edit" in source
    assert "no_edit" in source
    assert "repair_1_returned_before_cap" in source
    assert "handoff_elapsed" in source
    assert "CAP_SECONDS = 240" in source
    for task_id in DEV13:
        assert task_id in source
    notebook = json.loads(source)
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        compile("".join(cell["source"]), "structured_v16_1_notebook", "exec")


def test_notebook_handoff_uses_the_240_second_cap(tmp_path, monkeypatch):
    notebook = json.loads(NOTEBOOK.read_text())
    source = ""
    for cell in notebook["cells"]:
        text = "".join(cell["source"])
        if "def repair_1_handoff" in text:
            source = text
    assert source
    monkeypatch.setenv("V161_RESULTS", str(tmp_path))
    namespace = {}
    exec(source, namespace)
    stuck = namespace["repair_1_handoff"](
        {"events": [{"author": "repair_1", "extra": {"elapsed_s": 239}}]},
        250,
    )
    assert stuck == {"returned_before_cap": False, "handoff_elapsed": None}
    early = namespace["repair_1_handoff"](
        {
            "events": [
                {"author": "repair_1", "extra": {"elapsed_s": 118}, "text": "round: 1"},
                {"author": "verify_1", "extra": {"elapsed_s": 130}},
            ]
        },
        200,
    )
    assert early == {"returned_before_cap": True, "handoff_elapsed": 118.0}
    late = namespace["repair_1_handoff"](
        {
            "steps": [
                {"extra": {"author": "repair_1", "elapsed_s": 250}},
                {"extra": {"author": "verify_1", "elapsed_s": 255}},
            ]
        },
        260,
    )
    assert late == {"returned_before_cap": False, "handoff_elapsed": 250.0}


def test_hygiene_and_validation():
    report = lint_candidate(V161)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []
    assert len(validate(V161)) == 20


def test_archive_pins_v16_1_and_leaves_earlier_archives_unchanged(tmp_path):
    archive = tmp_path / "structured-v16-1.zip"
    manifest = pack(V161, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 20
    assert pack(V16, tmp_path / "structured-v16.zip")["sha256"] == V16_ARCHIVE
    assert pack(V131, tmp_path / "structured-v13-1.zip")["sha256"] == V131_ARCHIVE
    assert not list(V161.rglob("__pycache__"))


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
    archive = tmp_path / "structured-v16-1.zip"
    pack(V161, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v16_1.py"
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
            print(json.dumps({"version": __import__("adk_submission").__version__, "rows": rows}))
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
        assert rows["structured_v16_1"]["kind"] == "SequentialAgent"
        assert "repair_1_loop" not in rows
        assert rows["repair_1"]["kind"] == "LlmAgent"
        assert rows["repair_1"]["tools"] == [
            "get_status",
            "run_command",
            "search_similar_code",
            "get_code_neighbors",
            "get_code_subgraph",
        ]
        assert "read_file" not in rows["repair_1"]["tools"]
        assert rows["repair_2"]["tools"] == ["get_status", "read_file", "run_command"]
        assert rows["repair_3"]["tools"] == ["get_status", "run_command"]
        assert rows["verify_3"]["tools"] == ["get_status", "run_command", "submit_patch"]
        assert rows["verify_3"]["skills"] == ["check"]
        for row in rows.values():
            assert row["before_tool"] is False
            assert row["after_tool"] is False
            assert row["before_model"] is False
