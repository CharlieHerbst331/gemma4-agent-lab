"""structured-v16 is prompt text on a v13-1 tree. No loop and no registry."""

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

V131 = Path("agents/structured-v13-1").resolve()
V16 = Path("agents/structured-v16").resolve()
NOTEBOOK = Path("notebooks/structured-v16-smoke7.ipynb").resolve()
ARCHIVE = "6b8920c396f4e84fe14e7b7a907c1771436a55b840fae7464b3ce6f7cac13491"
V131_ARCHIVE = "74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe"
SMOKE = (
    "rich_3934",
    "rich_3105",
    "rich_3938",
    "rich_3472",
    "rich_3944",
    "fastapi_11194",
    "rich_3454",
)
ROLES = ("repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3")
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
    return (V16 / "sub_agents" / f"{name}.md").read_text()


def test_repair_1_hypothesis_and_optional_repro():
    text = _prompt("repair_1")
    assert "Repro is optional and costs at most 2 calls." in text
    assert "A passing repro is not evidence you have the wrong place." in text
    assert "that is NOT evidence that you have the wrong place." in text
    assert "Never write a third repro before the first edit." in text
    assert "The first assert must fail before the edit." not in text
    assert "Hypothesis rule. After at most 4 file reads" in text
    assert "HYPOTHESIS: <path>:<function> - <one-sentence change>" in text
    assert "Your very next tool call is the heredoc edit on that function." in text
    assert "assert s.count(old) == 1" in text
    assert "cat > /tmp/line_fix.py <<'EOF'" in text


def test_repair_1_hands_off_at_150_and_is_already_one_pass():
    text = _prompt("repair_1")
    assert "shows 150 or more, stop." in text
    assert "even if git diff is empty." in text
    assert "Repair round 2 owns the edit." in text
    assert "not this round's job" not in text
    assert "Do not run the heredoc in this round once 150 seconds have passed." not in text
    root = load_yaml(V16 / "agent.yaml", V16)
    assert root["name"] == "structured_v16"
    assert root["agent_class"] == "SequentialAgent"
    assert root["sub_agents"][1]["config_path"] == "sub_agents/repair_1.yaml"
    repair = load_yaml(V16 / "sub_agents" / "repair_1.yaml", V16)
    assert repair["agent_class"] == "LlmAgent"
    assert "max_iterations" not in repair
    assert list(V16.rglob("*loop*")) == []


def test_repair_1_missed_handoff_still_heredocs_an_empty_diff():
    text = _prompt("repair_1")
    sentence = (
        "If you are still in this round, git diff is empty, and "
        "time_seconds_remaining is under 120 and at least 45 seconds remain, "
        "write the HYPOTHESIS line and the next call is the heredoc."
    )
    assert sentence in text
    assert "Do not run the missed-hand-off heredoc." in text
    assert text.index("shows 150 or more, stop.") < text.index(sentence)
    assert text.index(sentence) < text.index("Do not run the missed-hand-off heredoc.")


def test_repair_2_edits_the_hypothesis_first():
    text = _prompt("repair_2")
    assert "your FIRST tool call is the heredoc edit" in text
    assert "latest HYPOTHESIS line" in text
    assert "If no HYPOTHESIS line exists" in text
    assert "first file and function named in the triage brief or the round 1 report" in text
    assert "Do not read first." in text
    assert "40 numbered lines" in text
    assert "Do not wait until time_seconds_remaining is under 120." in text
    assert "A passing repro is not evidence you have the wrong place." in text
    assert "assert s.count(old) == 1" in text
    assert "about 240 or more and git diff has a source edit" in text


def test_verify_3_submits_at_250_and_keeps_the_empty_diff_net():
    text = _prompt("verify_3")
    assert "agent_elapsed_seconds is 250 or more" in text
    assert "Skip the check." in text
    assert "The empty-diff net still runs once." in text
    assert "Do not submit an empty diff without that one heredoc." in text
    assert "time_seconds_remaining is under 120 and git diff is empty" in text
    assert "agent_elapsed_seconds is under 250" in text
    assert "assert s.count(old) == 1" in text
    assert "submit_patch" in text


def test_repeat_ban_heredoc_and_caps_stay():
    for name in ROLES:
        text = _prompt(name)
        assert text.count("get_status never counts as a repeat and is always allowed.") == 1
        assert "A later identical git diff or git status" in text
    budgets = load_yaml(V16 / "eval_config.yaml", V16)["evaluation"]
    parent = load_yaml(V131 / "eval_config.yaml", V131)["evaluation"]
    assert budgets == parent
    assert budgets["timeout_seconds"] == 300
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    triage = load_yaml(V16 / "sub_agents" / "triage.yaml", V16)
    assert triage["tools"] == []
    assert "skills" not in triage
    blob = "\n".join(path.read_text() for path in V16.rglob("*") if path.is_file())
    assert "skills/map" not in blob
    for task_id in SMOKE:
        assert task_id not in blob


def test_notebook_lists_the_smoke_and_compiles_without_a_registry():
    source = NOTEBOOK.read_text()
    assert "register_callbacks" not in source
    assert "CallbackRegistry" not in source
    assert "callback_registry" not in source
    assert "compile_submission" in source
    assert "HYPOTHESIS" in source
    assert "calls_to_first_edit" in source
    assert "no_edit" in source
    assert "repair_1_returned_before_cap" in source
    assert "handoff_elapsed" in source
    for task_id in SMOKE:
        assert task_id in source
    notebook = json.loads(source)
    listed = None
    for cell in notebook["cells"]:
        text = "".join(cell["source"])
        if "TASK_IDS" in text and "rich_3934" in text:
            listed = text
    assert listed is not None
    for task_id in SMOKE:
        assert task_id in listed


def test_notebook_handoff_uses_later_roles_and_elapsed():
    notebook = json.loads(NOTEBOOK.read_text())
    source = ""
    for cell in notebook["cells"]:
        text = "".join(cell["source"])
        if "def repair_1_handoff" in text:
            source = text
    assert "repair_1_returned_before_cap" in source
    assert "handoff_elapsed" in source
    namespace = {}
    exec(source, namespace)
    stuck = namespace["repair_1_handoff"](
        {"events": [{"author": "repair_1", "extra": {"elapsed_s": 302}}]},
        302,
    )
    assert stuck == {"returned_before_cap": False, "handoff_elapsed": None}
    early = namespace["repair_1_handoff"](
        {
            "events": [
                {"author": "repair_1", "extra": {"elapsed_s": 148}, "text": "round: 1"},
                {"author": "verify_1", "extra": {"elapsed_s": 160}},
            ]
        },
        302,
    )
    assert early == {"returned_before_cap": True, "handoff_elapsed": 148.0}
    late = namespace["repair_1_handoff"](
        {
            "steps": [
                {"extra": {"author": "repair_1", "elapsed_s": 310}},
                {"extra": {"author": "verify_1", "elapsed_s": 315}},
            ]
        },
        315,
    )
    assert late == {"returned_before_cap": False, "handoff_elapsed": 310.0}


def test_hygiene_and_validation():
    report = lint_candidate(V16)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []
    assert len(validate(V16)) == 20


def test_archive_pins_v16_and_leaves_v13_1_unchanged(tmp_path):
    archive = tmp_path / "structured-v16.zip"
    manifest = pack(V16, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert len(manifest["files"]) == 20
    assert "callbacks.py" not in manifest["files"]
    assert pack(V131, tmp_path / "structured-v13-1.zip")["sha256"] == V131_ARCHIVE
    assert not list(V16.rglob("__pycache__"))


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
    archive = tmp_path / "structured-v16.zip"
    pack(V16, archive)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as packed:
        packed.extractall(unpacked)
    script = tmp_path / "compile_v16.py"
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
        assert rows["structured_v16"]["kind"] == "SequentialAgent"
        assert rows["structured_v16"]["max_iterations"] is None
        assert "repair_1_loop" not in rows
        assert rows["repair_1"]["kind"] == "LlmAgent"
        assert rows["repair_1"]["max_iterations"] is None
        assert rows["triage"]["tools"] == []
        assert rows["triage"]["skills"] == []
        assert rows["repair_1"]["tools"] == [
            "get_status",
            "read_file",
            "run_command",
            "search_similar_code",
            "get_code_neighbors",
            "get_code_subgraph",
        ]
        assert rows["repair_2"]["tools"] == ["get_status", "read_file", "run_command"]
        assert rows["repair_3"]["tools"] == ["get_status", "run_command"]
        assert rows["verify_3"]["tools"] == ["get_status", "run_command", "submit_patch"]
        assert rows["verify_3"]["skills"] == ["check"]
        for row in rows.values():
            assert row["before_tool"] is False
            assert row["after_tool"] is False
            assert row["before_model"] is False
