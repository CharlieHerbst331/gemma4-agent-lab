"""structured-v16.2 is a hand-off copy of structured-v16.1. Caps stay 240/220/320."""

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
V162 = Path("agents/structured-v16-2").resolve()
NOTEBOOK = Path("notebooks/structured-v16-2-dev13/evaluation.ipynb").resolve()
KERNEL_META = Path("notebooks/structured-v16-2-dev13/kernel-metadata.json").resolve()
PROVENANCE = Path("notebooks/structured-v16-2-dev13/provenance.json").resolve()
ARCHIVE = "62937003fe519fa62e4c48f317abd6534d8ab80df25485e0929b18ede76c206d"
V161_ARCHIVE = "2bcee926e39c71c7ca4c8b8443195c7a78fc563f3ab3b4fe0b051c61f2ad7159"
V16_ARCHIVE = "6b8920c396f4e84fe14e7b7a907c1771436a55b840fae7464b3ce6f7cac13491"
DOCKER_IMAGE = (
    "gcr.io/kaggle-private-byod/python@sha256:"
    "37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461"
)
PREFIX = (
    "test -f /tmp/t0 || date +%s > /tmp/t0; "
    "e=$(( $(date +%s) - $(cat /tmp/t0) + 25 )); "
    "printf '[elapsed %ss]\\n' \"$e\"; "
    '[ "$e" -ge 100 ] && echo "HAND-OFF DUE: reply now with HYPOTHESIS and '
    'END_""ROUND_1, no tool call";'
)
CLOCK = (
    "test -f /tmp/t0 || date +%s > /tmp/t0; "
    "e=$(( $(date +%s) - $(cat /tmp/t0) + 25 )); "
    "printf '[elapsed %ss]\\n' \"$e\";"
)
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
BARE_DEV13_NUMBERS = re.compile(
    r"\b(11194|14246|14262|14356|14786|14794|3105|3454|3472|3934|3938|3944|4070)\b"
)
MODULE_TERMS = (
    re.compile(r"pretty\.py", re.IGNORECASE),
    re.compile(r"live_render", re.IGNORECASE),
    re.compile(r"routing\.py", re.IGNORECASE),
    re.compile(r"params\.py", re.IGNORECASE),
    re.compile(r"dependencies/utils"),
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
    return (V162 / "sub_agents" / f"{name}.md").read_text()


def _consume_stop(text, sequences):
    """OpenAI and vLLM drop the stop string and keep the text before it."""
    cut = len(text)
    for sequence in sequences:
        index = text.find(sequence)
        if index != -1:
            cut = min(cut, index)
    return text[:cut]


def test_repair_1_clock_banner_and_ten_calls():
    text = _prompt("repair_1")
    repair = load_yaml(V162 / "sub_agents" / "repair_1.yaml", V162)
    assert repair["tools"] == ["get_status", "run_command"]
    assert "read_file" not in repair["tools"]
    assert "search_similar_code" not in repair["tools"]
    assert repair["generate_content_config"]["max_output_tokens"] == 1024
    assert repair["generate_content_config"]["stop_sequences"] == ["END_ROUND_1"]
    assert repair["generate_content_config"]["thinking_config"]["thinking_budget"] == 0
    assert repair["generate_content_config"]["thinking_config"]["include_thoughts"] is False
    assert PREFIX in text
    assert "nl -ba PATH | sed -n 'A,Bp' | head -c 4000" in text
    assert "When any output shows HAND-OFF DUE, or you have made 10 tool calls of any kind" in text
    assert "then END_ROUND_1. No tool call." in text
    assert "The exact marker to emit, as its own last line, is END_ROUND_1." in text
    assert "END_ROUND_1" not in PREFIX
    assert "6 reads" not in text
    assert "line_fix" not in text
    assert "search_similar_code" not in text
    assert STEERING in text
    assert "two non-failing repros means stop reproducing" in text
    budgets = load_yaml(V162 / "eval_config.yaml", V162)["evaluation"]
    assert budgets["timeout_seconds"] == 240
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_time_minutes"] == 4.0
    assert budgets["max_turns"] == 320
    root = load_yaml(V162 / "agent.yaml", V162)
    assert root["name"] == "structured_v16_2"


def _command_templates(text):
    """Shell lines and example tool calls the model is told to copy."""
    chunks = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if re.search(r"\{[^{}]*skill_name[^{}]*\}", stripped):
            chunks.append(stripped)
        starts = stripped.startswith(
            ("test ", "cat ", "python", "cd ", "git ", "nl ", "pytest", "echo ", "printf ")
        )
        if starts or stripped.startswith("test -f /tmp/t0"):
            block = [stripped]
            if "<<" in stripped:
                index += 1
                while index < len(lines) and lines[index].strip() != "EOF":
                    block.append(lines[index])
                    index += 1
                if index < len(lines):
                    block.append(lines[index])
            chunks.append("\n".join(block))
        index += 1
    return chunks


def _configured_stops():
    stops = []
    for path in sorted((V162 / "sub_agents").glob("*.yaml")):
        loaded = load_yaml(path, V162)
        if not isinstance(loaded, dict):
            continue
        config = loaded.get("generate_content_config") or {}
        for sequence in config.get("stop_sequences") or []:
            stops.append((path.name, sequence))
    return stops


def test_command_templates_do_not_contain_stop_sequences():
    stops = [sequence for _, sequence in _configured_stops()]
    assert stops == ["END_ROUND_1"]
    hits = []
    for path in sorted((V162 / "sub_agents").glob("*.md")):
        for chunk in _command_templates(path.read_text()):
            for sequence in stops:
                if sequence in chunk:
                    hits.append(f"{path.name}: {sequence}")
    assert hits == []
    banner = _command_templates(_prompt("repair_1"))
    assert any('END_""ROUND_1' in chunk for chunk in banner)
    printed = subprocess.run(
        [
            "bash",
            "-c",
            'echo "HAND-OFF DUE: reply now with HYPOTHESIS and END_""ROUND_1, no tool call"',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert printed.stdout.strip() == (
        "HAND-OFF DUE: reply now with HYPOTHESIS and END_ROUND_1, no tool call"
    )
    for name in ("repair_2", "repair_3", "verify_1", "verify_2", "verify_3"):
        assert CLOCK in _prompt(name)


def test_stop_sequence_keeps_the_hypothesis_line():
    report = (
        "round: 1\n"
        "HYPOTHESIS: pkg/mod.py:func - drop the extra newline\n"
        "git diff is empty.\n"
        "END_ROUND_1"
    )
    kept = _consume_stop(report, ["END_ROUND_1"])
    assert "HYPOTHESIS: pkg/mod.py:func - drop the extra newline" in kept
    assert "END_ROUND_1" not in kept
    assert "latest HYPOTHESIS line" in _prompt("repair_2")
    assert "END_ROUND_1" not in "HYPOTHESIS:"
    truncated = _consume_stop(
        "HYPOTHESIS: pkg/mod.py:func - END_ROUND_1 drops the rest\n",
        ["END_ROUND_1"],
    )
    assert "drops the rest" not in truncated
    assert "Do not put the end marker inside the HYPOTHESIS line." in _prompt("repair_1")


def test_agent_dir_has_no_dev13_ids_or_library_terms():
    hits = []
    for path in sorted(V162.rglob("*")):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        text = path.read_text(errors="replace")
        for task_id in DEV13:
            if task_id in text:
                hits.append(f"{path.name}: {task_id}")
        if BARE_DEV13_NUMBERS.search(text):
            hits.append(f"{path.name}: bare dev-13 number")
        for pattern in (*LIBRARY_TERMS, *MODULE_TERMS):
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
    assert "hypothesis_elapsed" in source
    assert "handoff_due" in source
    assert "end_round_1" in source
    assert "HAND-OFF DUE" in source
    assert "END_ROUND_1" in source
    assert "malformed_repair_1_calls" in source
    assert "CAP_SECONDS = 240" in source
    for task_id in DEV13:
        assert task_id in source
    metadata = json.loads(KERNEL_META.read_text())
    assert metadata["model_sources"] == ["google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"]
    assert metadata["machine_shape"] == "NvidiaL4"
    assert metadata["docker_image"] == DOCKER_IMAGE
    assert metadata["dataset_sources"] == ["metric/gemma-4-developer-agent-wheelhouse/30"]
    provenance = json.loads(PROVENANCE.read_text())
    assert provenance["bundle"]["worktree_dirty"] is False
    assert provenance["bundle"]["candidate_source_dirty"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", provenance["bundle"]["candidate_source_commit"])
    assert not str(provenance["git_revision"]).endswith("-dirty")
    assert provenance["bundle"]["sha256"] == ARCHIVE
    notebook = json.loads(source)
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        compile("".join(cell["source"]), "structured_v16_2_notebook", "exec")


def test_notebook_report_sees_banner_and_consumed_stop(tmp_path, monkeypatch):
    notebook = json.loads(NOTEBOOK.read_text())
    source = ""
    for cell in notebook["cells"]:
        text = "".join(cell["source"])
        if "def repair_1_handoff" in text:
            source = text
    assert source
    monkeypatch.setenv("V162_RESULTS", str(tmp_path))
    namespace = {}
    exec(source, namespace)
    stuck = namespace["repair_1_handoff"](
        {"events": [{"author": "repair_1", "extra": {"elapsed_s": 239}}]},
        250,
    )
    assert stuck == {"returned_before_cap": False, "handoff_elapsed": None}
    marked = namespace["hypothesis_elapsed"](
        {
            "events": [
                {"author": "repair_1", "output": "[elapsed 102s]\nnl window"},
                {"author": "repair_1", "text": "HYPOTHESIS: stop leaves a newline"},
            ]
        }
    )
    assert marked == 102
    rows = [{"instance_id": "sample", "resolved": False, "duration_seconds": 200}]
    consumed = {
        "events": [
            {"author": "repair_1", "output": "[elapsed 100s]\nHAND-OFF DUE: reply now"},
            {
                "author": "repair_1",
                "text": "HYPOTHESIS: pkg/mod.py:func - drop the newline\nround: 1\n",
            },
            {"author": "verify_1", "extra": {"elapsed_s": 110}},
        ]
    }
    summary = namespace["summarize"](rows, {"sample": consumed})
    task = summary["tasks"][0]
    assert task["hypothesis"] is True
    assert task["hypothesis_elapsed"] == 100
    assert task["handoff_due"] is True
    assert task["end_round_1"] is False
    assert task["repair_1_returned_before_cap"] is True
    observed = namespace["summarize"](
        rows,
        {
            "sample": {
                "events": [
                    {"author": "repair_1", "text": "HYPOTHESIS: x\nEND_ROUND_1"},
                ]
            }
        },
    )["tasks"][0]
    assert observed["end_round_1"] is True
    assert observed["handoff_due"] is False
    broken = namespace["summarize"](
        rows,
        {
            "sample": {
                "events": [
                    {"author": "repair_1", "text": "get_status{}<tool_call|>"},
                    {"author": "repair_1", "tool": "run_command", "args": {"command": "git diff"}},
                ]
            }
        },
    )["tasks"][0]
    assert broken["malformed_repair_1_calls"] == 1


def test_hygiene_and_validation():
    report = lint_candidate(V162)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []
    assert len(validate(V162)) == 20


def test_archive_pins_v16_2_and_leaves_earlier_archives_unchanged(tmp_path):
    archive = tmp_path / "structured-v16-2.zip"
    manifest = pack(V162, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 20
    assert pack(V161, tmp_path / "structured-v16-1.zip")["sha256"] == V161_ARCHIVE
    assert pack(V16, tmp_path / "structured-v16.zip")["sha256"] == V16_ARCHIVE
    assert not list(V162.rglob("__pycache__"))


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
    archive = tmp_path / "structured-v16-2.zip"
    pack(V162, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v16_2.py"
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
            from adk_submission.resolvers.generation import apply_thinking_config_to_model
            from google.adk.models.base_llm import BaseLlm

            class BridgeModel(BaseLlm):
                async def generate_content_async(self, llm_request, stream=False):
                    if False:
                        yield None

                def __init__(self, **data):
                    super().__init__(**data)
                    object.__setattr__(self, "_additional_args", {})

            SOURCE = Path(sys.argv[1])
            LIMITS = SubmissionLimits(
                allowed_file_extensions=frozenset({".yaml", ".yml", ".md", ".txt", ".py", ".json"})
            )


            def tool(name):
                def _fn(*args, **kwargs):
                    return None
                _fn.__name__ = name
                return _fn


            def gen_fields(agent):
                config = getattr(agent, "generate_content_config", None)
                if config is None:
                    return {
                        "max_output_tokens": None,
                        "stop_sequences": None,
                        "thinking_budget": None,
                        "include_thoughts": None,
                        "enable_thinking": None,
                    }
                thinking = getattr(config, "thinking_config", None)
                stop = getattr(config, "stop_sequences", None)
                model = getattr(agent, "model", None)
                enable = None
                extra = getattr(model, "_additional_args", None)
                if isinstance(extra, dict):
                    body = extra.get("extra_body") or {}
                    kwargs = body.get("chat_template_kwargs") or {}
                    enable = kwargs.get("enable_thinking")
                return {
                    "max_output_tokens": getattr(config, "max_output_tokens", None),
                    "stop_sequences": None if stop is None else list(stop),
                    "thinking_budget": None if thinking is None else getattr(
                        thinking, "thinking_budget", None
                    ),
                    "include_thoughts": None if thinking is None else getattr(
                        thinking, "include_thoughts", None
                    ),
                    "enable_thinking": enable,
                }


            def walk(agent, rows):
                tools = []
                skills = []
                for item in getattr(agent, "tools", []) or []:
                    if type(item).__name__ == "SkillToolset":
                        skills.extend(sorted(item._skills))
                    else:
                        tools.append(getattr(item, "__name__", type(item).__name__))
                row = {
                    "name": agent.name,
                    "kind": type(agent).__name__,
                    "tools": tools,
                    "skills": skills,
                    "before_tool": bool(getattr(agent, "before_tool_callback", None)),
                    "after_tool": bool(getattr(agent, "after_tool_callback", None)),
                    "before_model": bool(getattr(agent, "before_model_callback", None)),
                }
                row.update(gen_fields(agent))
                rows.append(row)
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
            models.register(
                "gemma-4-31b-it-qat-w4a16-ct",
                BridgeModel(model="gemma-4-31b-it-qat-w4a16-ct"),
            )
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
            repair = next(row for row in rows if row["name"] == "repair_1")
            bridge = apply_thinking_config_to_model(
                BridgeModel(model="gemma-4-31b-it-qat-w4a16-ct"),
                agent.sub_agents[1].generate_content_config,
            )
            kwargs = bridge._additional_args["extra_body"]["chat_template_kwargs"]
            bridged = kwargs["enable_thinking"]
            print(json.dumps({
                "version": __import__("adk_submission").__version__,
                "rows": rows,
                "bridge_enable_thinking": bridged,
                "repair_stop": repair["stop_sequences"],
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
        assert payload["bridge_enable_thinking"] is False
        rows = {row["name"]: row for row in payload["rows"]}
        assert rows["structured_v16_2"]["kind"] == "SequentialAgent"
        repair = rows["repair_1"]
        assert repair["kind"] == "LlmAgent"
        assert repair["tools"] == ["get_status", "run_command"]
        assert repair["max_output_tokens"] == 1024
        assert repair["stop_sequences"] == ["END_ROUND_1"]
        assert repair["thinking_budget"] == 0
        assert repair["include_thoughts"] is False
        assert repair["enable_thinking"] is False
        assert rows["repair_2"]["tools"] == ["get_status", "read_file", "run_command"]
        assert rows["repair_2"]["max_output_tokens"] == 2048
        assert rows["repair_2"]["thinking_budget"] == 256
        assert rows["repair_2"]["stop_sequences"] is None
        assert rows["verify_3"]["tools"] == ["get_status", "run_command", "submit_patch"]
        assert rows["verify_3"]["skills"] == ["check"]
        for row in rows.values():
            assert row["before_tool"] is False
            assert row["after_tool"] is False
            assert row["before_model"] is False
