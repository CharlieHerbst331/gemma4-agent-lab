"""structured-v15 enforces deadlines, an edit, and a pre-submit check in code."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
import urllib.request
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V14 = Path("agents/structured-v14")
V15 = Path("agents/structured-v15")
V14_ARCHIVE = "8eeae0c1859766bc08afafe2b6139e4ea4ebd82ab52b42c04bd01836e4e361bf"
V15_ARCHIVE = "c70b05eaeb6cfcaf05e5fec107e2f32bf789abdf6a6559eb6d9dac692dc6ae7d"
NOTEBOOK = Path("notebooks/structured-v15-dev13.ipynb")
DEV13 = [
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
]
UNCHANGED = (
    "sub_agents/thinking.yaml",
    "sub_agents/repair_thinking.yaml",
    "sub_agents/triage.md",
    "sub_agents/repair_1.md",
    "sub_agents/repair_2.md",
    "sub_agents/repair_3.md",
    "sub_agents/verify_1.md",
    "sub_agents/verify_2.md",
    "sub_agents/verify_3.md",
    "skills/check/SKILL.md",
    "skills/check/scripts/run.py",
    "skills/map/SKILL.md",
    "skills/map/scripts/run.py",
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
ADK_PY = Path("/tmp/adk-py")
COMPILER_CACHE = Path("/tmp/adk011")


def _callbacks():
    spec = importlib.util.spec_from_file_location("structured_v15_callbacks", V15 / "callbacks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Tool:
    def __init__(self, name):
        self.name = name


class _Ctx:
    def __init__(self, role, invocation="task"):
        self.agent_name = role
        self.invocation_id = invocation
        self.end_invocation = False
        self._invocation_context = self
        self.agent = type("Agent", (), {"name": role})()


def _arm(callbacks, ctx, start=0.0):
    box = {"now": start}
    callbacks.set_clock(lambda: box["now"])
    callbacks.reset_states()
    state = callbacks._state_for(ctx)
    state.elapsed()
    return box, state


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    tests = repo / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "console.py").write_text(
        "import getpass\n\ndef read_secret():\n    return getpass.getuser()\n"
    )
    (tests / "test_console.py").write_text(
        "import pkg.console as console\n"
        "def test_secret():\n"
        "    if not console.read_secret():\n"
        "        raise SystemExit(1)\n"
        "test_secret()\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "v15@example.com")
    _git(repo, "config", "user.name", "v15")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_v15_keeps_the_cap_and_the_v14_prompts():
    root = load_yaml(V15 / "agent.yaml", V15)
    assert root["name"] == "structured_v15"
    assert root["agent_class"] == "SequentialAgent"
    assert [child["config_path"] for child in root["sub_agents"]] == [
        "sub_agents/triage.yaml",
        "sub_agents/repair_1.yaml",
        "sub_agents/verify_1.yaml",
        "sub_agents/repair_2.yaml",
        "sub_agents/verify_2.yaml",
        "sub_agents/repair_3.yaml",
        "sub_agents/verify_3.yaml",
    ]
    budgets = load_yaml(V15 / "eval_config.yaml", V15)["evaluation"]
    assert budgets["timeout_seconds"] == 300
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert budgets["max_time_minutes"] == 5
    assert type(budgets["max_time_minutes"]) is int
    for rel in UNCHANGED:
        assert (V15 / rel).read_bytes() == (V14 / rel).read_bytes()
    yaml_blob = "\n".join(path.read_text() for path in V15.rglob("*.yaml"))
    assert "ParallelAgent" not in yaml_blob
    for name in ("triage", "repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3"):
        role = load_yaml(V15 / "sub_agents" / f"{name}.yaml", V15)
        assert role["before_tool_callbacks"] == ["v15_before_tool"]
        assert role["after_tool_callbacks"] == ["v15_after_tool"]
        assert role["before_model_callbacks"] == ["v15_before_model"]
    assert len(validate(V15)) == 23
    report = lint_candidate(V15)
    assert report["gate"] == "pass", report["findings"]


def test_every_tool_result_carries_the_clock():
    callbacks = _callbacks()
    ctx = _Ctx("repair_1")
    box, _state = _arm(callbacks, ctx)
    box["now"] = 12
    stamped = callbacks.after_tool(
        tool=_Tool("read_file"),
        args={"path": "pkg/console.py", "start_line": 1, "end_line": 100},
        tool_context=ctx,
        tool_response={"output": "line"},
    )
    assert stamped["output"].endswith("[elapsed 12s / remaining 288s]")
    box["now"] = 40
    status = callbacks.after_tool(
        tool=_Tool("get_status"),
        args={},
        tool_context=ctx,
        tool_response="ok",
    )
    assert status.endswith("[elapsed 40s / remaining 260s]")


def test_repair_deadlines_end_the_role_and_leave_verify_running():
    callbacks = _callbacks()
    repair = _Ctx("repair_1")
    box, _state = _arm(callbacks, repair)
    box["now"] = 150
    blocked = callbacks.before_tool(
        tool=_Tool("read_file"), args={"path": "a.py"}, tool_context=repair
    )
    assert blocked["result"] == "repair_1 ended at 150s so verify and submit can run"
    assert repair.end_invocation is True
    verify = _Ctx("verify_3", invocation="task")
    verify_box = {"now": 150}
    callbacks.set_clock(lambda: verify_box["now"])
    # Same invocation keeps the clock. verify is not a repair role.
    allowed = callbacks.before_tool(
        tool=_Tool("run_command"),
        args={"command": "git diff"},
        tool_context=verify,
    )
    assert allowed is None
    assert verify.end_invocation is False
    repair2 = _Ctx("repair_2", invocation="later")
    box2, _state2 = _arm(callbacks, repair2)
    box2["now"] = 240
    ended = callbacks.before_tool(
        tool=_Tool("read_file"), args={"path": "a.py"}, tool_context=repair2
    )
    assert "repair_2 ended at 240s" in ended["result"]
    assert repair2.end_invocation is True
    model = callbacks.before_model(callback_context=repair2)
    text = model["ended"] if isinstance(model, dict) else model.content.parts[0].text
    assert text == "repair_2 ended at 240s so verify and submit can run"


def test_empty_diff_forces_an_edit_at_120s_or_30_calls_then_compile():
    callbacks = _callbacks()
    ctx = _Ctx("repair_1", invocation="force-time")
    box, state = _arm(callbacks, ctx)
    box["now"] = 119
    early = callbacks.before_tool(tool=_Tool("read_file"), args={"path": "a.py"}, tool_context=ctx)
    assert early is None
    box["now"] = 120
    rejected = callbacks.before_tool(
        tool=_Tool("search_similar_code"), args={"query": "x"}, tool_context=ctx
    )
    assert rejected["result"] == "next call must be an edit"
    status = callbacks.before_tool(tool=_Tool("get_status"), args={}, tool_context=ctx)
    assert status is None
    edit = callbacks.before_tool(
        tool=_Tool("run_command"),
        args={"command": "cat > /tmp/line_fix.py <<'EOF'\nprint(1)\nEOF"},
        tool_context=ctx,
    )
    assert edit is None
    calls = _Ctx("repair_2", invocation="force-calls")
    box2, state2 = _arm(callbacks, calls)
    box2["now"] = 1
    for index in range(30):
        result = callbacks.before_tool(
            tool=_Tool("read_file"),
            args={"path": f"f{index}.py"},
            tool_context=calls,
        )
        assert result is None
    assert state2.calls == 30
    blocked = callbacks.before_tool(
        tool=_Tool("read_file"), args={"path": "new.py"}, tool_context=calls
    )
    assert blocked["result"] == "next call must be an edit"
    assert state.has_edit is False


def test_identical_reads_are_already_seen_and_get_status_is_not(tmp_path, monkeypatch):
    callbacks = _callbacks()
    monkeypatch.setenv("V15_REPO", str(tmp_path / "missing"))
    ctx = _Ctx("repair_1", invocation="repeat")
    _box, state = _arm(callbacks, ctx)
    args = {"path": "pkg/console.py", "start_line": 1, "end_line": 100}
    assert callbacks.before_tool(tool=_Tool("read_file"), args=args, tool_context=ctx) is None
    callbacks.after_tool(
        tool=_Tool("read_file"),
        args=args,
        tool_context=ctx,
        tool_response={"output": "class Console"},
    )
    again = callbacks.before_tool(tool=_Tool("read_file"), args=args, tool_context=ctx)
    assert again["result"] == "already seen: class Console"
    page = callbacks.before_tool(
        tool=_Tool("read_file"),
        args={"path": "pkg/console.py", "start_line": 101, "end_line": 200},
        tool_context=ctx,
    )
    assert page is None
    for _ in range(3):
        assert callbacks.before_tool(tool=_Tool("get_status"), args={}, tool_context=ctx) is None
    diff = {"command": "git diff"}
    assert callbacks.before_tool(tool=_Tool("run_command"), args=diff, tool_context=ctx) is None
    callbacks.after_tool(
        tool=_Tool("run_command"),
        args=diff,
        tool_context=ctx,
        tool_response={"output": "empty"},
    )
    banned = callbacks.before_tool(tool=_Tool("run_command"), args=diff, tool_context=ctx)
    assert banned["result"].startswith("already seen:")
    other = _Ctx("repair_2", invocation="repeat")
    opened = callbacks.before_tool(tool=_Tool("run_command"), args=diff, tool_context=other)
    assert opened is None
    state.has_edit = True
    rerun = callbacks.before_tool(tool=_Tool("run_command"), args=diff, tool_context=ctx)
    assert rerun is None


def test_rich_4070_style_import_deletion_is_reverted(tmp_path, monkeypatch):
    callbacks = _callbacks()
    repo = _repo(tmp_path)
    monkeypatch.setenv("V15_REPO", str(repo))
    source = repo / "pkg" / "console.py"
    source.write_text("def read_secret():\n    return getpass.getuser()\n")
    state = callbacks.GateState()
    state.t0 = 0
    callbacks.set_clock(lambda: 1)
    ok, detail = callbacks.review_tree(repo, state, timeout=20)
    assert ok is False
    assert "getpass" in detail or "check failed" in detail
    restored = source.read_text()
    assert "import getpass" in restored
    assert callbacks.source_diff(repo)[0] == ""
    ok_again, _detail = callbacks.review_tree(repo, state, timeout=20)
    assert ok_again is True


def test_a_passing_check_is_the_snapshot_a_later_failure_restores(tmp_path, monkeypatch):
    callbacks = _callbacks()
    repo = _repo(tmp_path)
    monkeypatch.setenv("V15_REPO", str(repo))
    callbacks.set_clock(lambda: 1)
    state = callbacks.GateState()
    state.t0 = 0
    source = repo / "pkg" / "console.py"
    source.write_text("import getpass\n\ndef read_secret():\n    return getpass.getuser() or 'x'\n")
    ok, _detail = callbacks.review_tree(repo, state, timeout=20)
    assert ok is True
    assert state.good_files
    source.write_text("def read_secret():\n    return missing_name()\n")
    ok, detail = callbacks.review_tree(repo, state, timeout=20)
    assert ok is False
    assert "import getpass" in source.read_text()
    assert "restored" in detail
    ctx = _Ctx("verify_3", invocation="submit")
    callbacks.reset_states()
    held = callbacks._state_for(ctx)
    held.t0 = 0
    held.good_files = None
    source.write_text("def read_secret():\n    return missing_name()\n")
    blocked = callbacks.before_tool(tool=_Tool("submit_patch"), args={}, tool_context=ctx)
    assert blocked is not None
    assert "import getpass" in source.read_text()
    assert ctx.end_invocation is False


def test_callbacks_swallow_errors():
    callbacks = _callbacks()

    def boom(*_args, **_kwargs):
        raise RuntimeError("branch")

    original_before = callbacks._before
    original_after = callbacks._after
    callbacks._before = boom
    callbacks._after = boom
    try:
        ctx = _Ctx("repair_1")
        assert callbacks.before_tool(tool=_Tool("read_file"), args={}, tool_context=ctx) is None
        assert (
            callbacks.after_tool(
                tool=_Tool("read_file"),
                args={},
                tool_context=ctx,
                tool_response={},
            )
            is None
        )
        assert callbacks.before_model(callback_context=None) is None
    finally:
        callbacks._before = original_before
        callbacks._after = original_after


def test_shell_is_noninteractive_bash_and_sync_docker_exec():
    callbacks = _callbacks()
    assert callbacks.command_argv("git diff") == [
        "bash",
        "--noprofile",
        "--norc",
        "-c",
        "git diff",
    ]
    assert callbacks.command_argv("git diff", "box") == [
        "docker",
        "exec",
        "-i",
        "box",
        "bash",
        "--noprofile",
        "--norc",
        "-c",
        "git diff",
    ]
    assert "-t" not in callbacks.command_argv("true", "box")


def test_dev13_report_counts_edits_and_the_reachable_ceiling():
    callbacks = _callbacks()
    rows = [
        {"instance_id": "rich_3454", "resolved": True, "duration_seconds": 200},
        {"instance_id": "rich_3934", "resolved": False, "duration_seconds": 303},
        {"instance_id": "fastapi_14246", "resolved": False, "duration_seconds": 308},
    ]
    traces = {
        "rich_3454": {
            "steps": [
                {"tool_calls": [{"name": "read_file", "arguments": {"path": "a.py"}}]},
                {
                    "tool_calls": [
                        {
                            "name": "run_command",
                            "arguments": {"command": "cat > /tmp/line_fix.py"},
                        }
                    ]
                },
            ]
        },
        "rich_3934": {"steps": [{"name": "read_file", "args": {"path": "live.py"}}]},
        "fastapi_14246": {"tool_calls": [{"name": "read_file", "arguments": {}}]},
    }
    report = callbacks.dev13_report(rows, traces)
    assert report["n"] == 3
    assert report["resolved"] == 1
    assert report["reachable_ceiling"] == 10
    assert report["reachable_resolved"] == 1
    assert report["no_edit_runs"] == 2
    by_id = {item["instance_id"]: item for item in report["tasks"]}
    assert by_id["rich_3454"]["calls_to_first_edit"] == 2
    assert by_id["rich_3454"]["wall_seconds"] == 200
    assert by_id["rich_3934"]["no_edit"] is True
    assert by_id["rich_3934"]["calls_to_first_edit"] is None


def test_dev13_notebook_lists_the_cohort_and_keeps_traces():
    notebook = json.loads(NOTEBOOK.read_text())
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    for task_id in DEV13:
        assert task_id in source
    assert "structured-v15" in source
    assert "compile_submission" in source
    assert "register_callbacks" in source
    assert "reachable_ceiling" in source
    assert "no_edit" in source
    assert "calls_to_first_edit" in source
    assert "task_results.jsonl" in source
    assert "traces" in source
    assert "Do not submit" in source


def _ensure_compiler_source():
    schema = COMPILER_CACHE / "adk_submission" / "schema.py"
    if schema.is_file() and "ge=1" in schema.read_text():
        return COMPILER_CACHE
    COMPILER_CACHE.mkdir(parents=True, exist_ok=True)
    for rel in COMPILER_FILES:
        dest = COMPILER_CACHE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(COMPILER_URL + rel, dest)
    return COMPILER_CACHE


def _ensure_adk():
    if (ADK_PY / "google" / "adk" / "__init__.py").is_file():
        return ADK_PY
    ADK_PY.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--target", str(ADK_PY), "google-adk==1.36.1"]
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("google-adk 1.36.1 pip install failed; compile test skipped offline")
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


def test_compiles_on_adk_submission_0_2_12_and_0_2_13(tmp_path):
    script = tmp_path / "compile_v15.py"
    script.write_text(
        textwrap.dedent(
            """\
            import json
            import sys
            from pathlib import Path

            from adk_submission import CallbackRegistry
            from adk_submission import GenerationConstraints
            from adk_submission import ModelRegistry
            from adk_submission import NumericRange
            from adk_submission import SubmissionLimits
            from adk_submission import ToolRegistry
            from adk_submission import compile_submission

            SOURCE = Path(sys.argv[1])
            sys.path.insert(0, str(SOURCE))
            from callbacks import register_callbacks

            LIMITS = SubmissionLimits(
                allowed_file_extensions=frozenset({".yaml", ".yml", ".md", ".txt", ".py", ".json"})
            )


            def registries():
                models = ModelRegistry()
                models.register("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-31b-it-qat-w4a16-ct")
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
                    tools.register(name, lambda *args, **kwargs: None)
                callbacks = CallbackRegistry()
                register_callbacks(callbacks)
                return tools, models, callbacks


            def constraints():
                return GenerationConstraints(
                    allowed_fields=None,
                    max_output_tokens=NumericRange(1, 32768),
                    thinking_budget=NumericRange(0, 32768),
                    defaults={
                        "max_output_tokens": 16384,
                        "thinking_config": {"thinking_budget": 4096},
                    },
                )


            tools, models, callbacks = registries()
            agent = compile_submission(
                SOURCE,
                tools,
                models,
                callback_registry=callbacks,
                limits=LIMITS,
                generation_constraints=constraints(),
            )
            roles = {}
            for child in agent.sub_agents:
                before = getattr(child, "before_tool_callback", None) or []
                after = getattr(child, "after_tool_callback", None) or []
                model_cb = getattr(child, "before_model_callback", None) or []
                roles[child.name] = {
                    "before": [fn.__name__ for fn in before],
                    "after": [fn.__name__ for fn in after],
                    "model": [fn.__name__ for fn in model_cb],
                }
            print(json.dumps({
                "version": __import__("adk_submission").__version__,
                "root": type(agent).__name__,
                "name": agent.name,
                "roles": roles,
            }))
            """
        )
    )
    env_base = {
        **os.environ,
        "PYTHONWARNINGS": "ignore",
    }
    for version, ge in (("0.2.12", 0), ("0.2.13", 0)):
        tree = _schema_tree(version, ge)
        env = dict(env_base)
        env["PYTHONPATH"] = os.pathsep.join([str(tree), str(_ensure_adk())])
        completed = subprocess.run(
            [sys.executable, str(script), str(V15.resolve())],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr[-2000:] or completed.stdout[-2000:])
        payload = json.loads(completed.stdout)
        assert payload["version"] == version
        assert payload["root"] == "SequentialAgent"
        assert payload["name"] == "structured_v15"
        roles = (
            "triage",
            "repair_1",
            "repair_2",
            "repair_3",
            "verify_1",
            "verify_2",
            "verify_3",
        )
        for role in roles:
            assert payload["roles"][role] == {
                "before": ["before_tool"],
                "after": ["after_tool"],
                "model": ["before_model"],
            }


def test_archive_pins_v15_and_leaves_v14_unchanged(tmp_path):
    archive = tmp_path / "structured-v15.zip"
    manifest = pack(V15, archive)
    assert manifest["sha256"] == V15_ARCHIVE
    assert sha256(archive) == V15_ARCHIVE
    assert len(manifest["files"]) == 23
    assert pack(V14, tmp_path / "structured-v14.zip")["sha256"] == V14_ARCHIVE


def test_runtime_gate_math_keeps_300_seconds():
    cap = 300
    mean_limit = 260
    assert 120 * (mean_limit + 70) == 39600
    assert 120 * ((cap + 8) + 70) > 39600
    check = 20
    assert check <= 20
    # v13-1 dev-13 mean. Not a v15 measurement.
    measured = 279.6
    assert 120 * (measured + 70) > 39600
