"""structured-v12: elapsed line on every shell result, cap that still passes."""

import fcntl
import importlib.util
import os
import re
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate
from gemma_lab.multi_arm import pair_fits_minimum_budget, submission_gate_picture
from gemma_lab.operations import (
    DEFAULT_MODEL_LOAD_SECONDS,
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    PROJECTED_HIDDEN_TASKS,
    PROJECTED_LOAD_LIMIT_SECONDS,
    PROJECTED_PUBLIC_TASKS,
    PROJECTED_RUNTIME_LIMIT_SECONDS,
    WORST_CASE_WARN_SECONDS,
)
from gemma_lab.paired import (
    assert_arms_compatible,
    inspect_arm,
    load_protocol,
    protocol_schedule,
)

V8 = Path("agents/structured-v8")
V10 = Path("agents/structured-v10")
V12 = Path("agents/structured-v12")
PROTOCOL = Path("configs/protocols/structured-v8-vs-structured-v12-smoke.yaml")
V8_ARCHIVE = "9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e"
V10_ARCHIVE = "c07fcc5505f509f648a924a09dfa5a0f4c1cfe10d4b0a784f938e69116c66ed0"
V12_ARCHIVE = "1db40320137309e3a496b1590156ca98579e02ae385cc2cd7d44d43879515f39"
SMOKE_TASKS = [
    "rich_4070",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "rich_3454",
]
SMOKE_SCHEDULE = "067cc5710f85233ec4e8f61662ba1a9adda77e9e48496e65d65f2ede5787a4a7"
HANDOFF = re.compile(r"By\s+(\d+)\s+elapsed seconds")
ELAPSED_LINE = re.compile(r"^\[elapsed (\d+)s\]$")
PREFIX = (
    "test -f /tmp/t0 || date +%s > /tmp/t0; "
    "printf '[elapsed %ss]\\n' \"$(( $(date +%s) - $(cat /tmp/t0) ))\";"
)
TRIAGE_COMMAND = (
    "date +%s > /tmp/t0; printf '[elapsed %ss]\\n' \"$(( $(date +%s) - $(cat /tmp/t0) ))\""
)
SAFE_ENV = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "USER",
    "LOGNAME",
    "SYSTEMROOT",
    "LD_LIBRARY_PATH",
    "TMPDIR",
    "TEST_TMPDIR",
)
SAME_AS_V8 = (
    "sub_agents/thinking.yaml",
    "sub_agents/repair_thinking.yaml",
    "sub_agents/verify_1.yaml",
    "sub_agents/verify_2.yaml",
    "sub_agents/verify_3.yaml",
    "skills/check/SKILL.md",
    "skills/check/scripts/run.py",
)


def _prompt(name):
    return (V12 / "sub_agents" / f"{name}.md").read_text()


def _sanitized_env(home: Path) -> dict[str, str]:
    """Mirror subprocess_sandbox.build_sanitized_env: no BASH_ENV, HOME is tmp."""
    env = {key: os.environ[key] for key in SAFE_ENV if key in os.environ}
    env["HOME"] = str(home)
    env["TMPDIR"] = str(home)
    env["TEST_TMPDIR"] = str(home)
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


def _harness_bash(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """docker.py runs bash -c of `timeout ... /bin/bash -c <quoted command>`."""
    outer = f"timeout -k 5s 30 /bin/bash -c {shlex.quote(command)}"
    return subprocess.run(
        ["/bin/bash", "-c", outer],
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )


def _heredoc(text: str) -> str:
    start = text.index("cat > /tmp/line_fix.py <<'EOF'\n")
    end = text.index("\nEOF\n", start)
    return text[start:end]


def test_sandbox_bash_c_ignores_bashrc_and_prompt_command(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("echo BASHRC_RAN\n")
    env = _sanitized_env(home)
    env["PROMPT_COMMAND"] = "echo PROMPT_RAN"
    result = _harness_bash("echo CMD", env)
    assert result.returncode == 0
    assert result.stdout == "CMD\n"
    combined = result.stdout + result.stderr
    assert "BASHRC_RAN" not in combined
    assert "PROMPT_RAN" not in combined
    assert "[elapsed" not in combined
    assert "BASH_ENV" not in _sanitized_env(home)


def test_bash_env_would_inject_but_the_harness_env_omits_it(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    hook = home / "elapsed.sh"
    hook.write_text("printf '[elapsed injected]\\n'\n")
    with_hook = _sanitized_env(home)
    with_hook["BASH_ENV"] = str(hook)
    injected = _harness_bash("echo CMD", with_hook)
    assert injected.returncode == 0
    assert "[elapsed injected]" in injected.stdout
    assert injected.stdout.endswith("CMD\n")
    plain = _harness_bash("echo CMD", _sanitized_env(home))
    assert plain.stdout == "CMD\n"
    assert "BASH_ENV" not in _sanitized_env(home)


def test_mandatory_prefix_prints_elapsed_in_a_harness_shell(tmp_path):
    repair = _prompt("repair_1")
    triage = _prompt("triage")
    assert PREFIX in repair
    assert TRIAGE_COMMAND in triage
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("echo BASHRC_RAN\n")
    env = _sanitized_env(home)
    lock = open("/tmp/v12-elapsed-prefix.lock", "a")  # noqa: SIM115
    fcntl.flock(lock, fcntl.LOCK_EX)
    path = Path("/tmp/t0")
    saved = path.read_bytes() if path.exists() else None
    try:
        path.write_text(str(int(time.time()) - 12))
        prefixed = _harness_bash(PREFIX.rstrip(";") + "; echo hi", env)
        assert prefixed.returncode == 0
        lines = prefixed.stdout.splitlines()
        assert lines[0].startswith("[elapsed ")
        assert lines[-1] == "hi"
        assert "BASHRC_RAN" not in prefixed.stdout
        match = ELAPSED_LINE.fullmatch(lines[0])
        assert match is not None
        assert 11 <= int(match.group(1)) <= 20
        started = _harness_bash(TRIAGE_COMMAND, env)
        assert started.returncode == 0
        assert ELAPSED_LINE.fullmatch(started.stdout.strip())
        assert int(path.read_text().strip()) > 0
    finally:
        if saved is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(saved)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def test_prompts_key_handoffs_on_the_elapsed_line_and_keep_the_heredoc():
    triage = _prompt("triage")
    repair_1 = _prompt("repair_1")
    repair_2 = _prompt("repair_2")
    verify_3 = _prompt("verify_3")
    joined = "\n".join(
        _prompt(name)
        for name in (
            "triage",
            "repair_1",
            "repair_2",
            "repair_3",
            "verify_1",
            "verify_2",
            "verify_3",
        )
    )
    assert HANDOFF.search(joined) is None
    assert "date +%s > /tmp/t0" in triage
    assert "Do not run any other command" in triage
    for name in ("repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3"):
        assert PREFIX in _prompt(name)
        assert "get_status does not replace it" in _prompt(name)
    assert "The task cap is 250 seconds" in repair_1
    assert "line is 130 or more" in repair_1
    assert "line is 110 or more and git diff is empty" in repair_1
    assert "still under 130" in repair_1
    assert "first file named in the triage brief" in repair_1
    assert "/tmp/repro_check.py already exists" in repair_1
    assert "Do not call read_file" in repair_1
    assert "line is 160 or more" in repair_2
    assert "line is 110 or more and git diff is empty" in repair_2
    assert "which is 205" in verify_3
    assert "line is 205 or more" in verify_3
    assert "call submit_patch anyway" in verify_3
    assert '{"skill_name":"check","file_path":"scripts/run.py"}' in verify_3
    assert "145 or more" in _prompt("verify_1")
    assert "175 or more" in _prompt("verify_2")
    assert "line is 190 or more" in _prompt("repair_3")
    for name in ("repair_1", "repair_2", "repair_3", "verify_3"):
        text = _prompt(name)
        cat_line = next(line for line in text.splitlines() if "cat > /tmp/line_fix.py" in line)
        assert cat_line.startswith(PREFIX.rstrip(";"))
        assert cat_line.endswith("cat > /tmp/line_fix.py <<'EOF'")
        assert _heredoc(text) == _heredoc((V8 / "sub_agents" / f"{name}.md").read_text())
        assert 'backup = "/tmp/pre_" + path.replace("/", "_")' in text
        assert "py_compile.compile(path, doraise=True)" in text
        assert "shutil.copyfile(backup, path)" in text
        assert "Never run git checkout" in text
    root = load_yaml(V12 / "agent.yaml", V12)
    assert root["name"] == "structured_v12"
    assert root["agent_class"] == "SequentialAgent"
    assert "ParallelAgent" not in (V12 / "agent.yaml").read_text()
    blob = "\n".join(path.read_text() for path in V12.rglob("*") if path.is_file())
    assert "ParallelAgent" not in blob
    triage_role = load_yaml(V12 / "sub_agents" / "triage.yaml", V12)
    assert triage_role["tools"] == ["run_command"]
    assert load_yaml(V8 / "sub_agents" / "triage.yaml", V8)["tools"] == []
    repair_1_role = load_yaml(V12 / "sub_agents" / "repair_1.yaml", V12)
    parent = load_yaml(V8 / "sub_agents" / "repair_1.yaml", V8)
    assert repair_1_role["tools"] == parent["tools"]
    assert repair_1_role["generate_content_config"] == parent["generate_content_config"]
    for rel in SAME_AS_V8:
        assert (V12 / rel).read_bytes() == (V8 / rel).read_bytes()
    budgets = load_yaml(V12 / "eval_config.yaml", V12)["evaluation"]
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert budgets["timeout_seconds"] == 250
    assert budgets["max_time_minutes"] == 4.166666666666667
    # 4.166666666666667 * 60 is 250.00000000000003. The 120-task block of
    # that product is 38400.0, the same as an exact 250 second cap.
    assert round(budgets["max_time_minutes"] * 60) == 250
    assert PROJECTED_HIDDEN_TASKS * (budgets["max_time_minutes"] * 60 + 70) == 38400
    repair_3_role = load_yaml(V12 / "sub_agents" / "repair_3.yaml", V12)
    parent_3 = load_yaml(V8 / "sub_agents" / "repair_3.yaml", V8)
    assert repair_3_role["tools"] == parent_3["tools"]
    assert type(budgets["max_time_minutes"]) is float
    assert len(validate(V12)) == 20
    report = lint_candidate(V12)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_cap_hit_mean_with_overrun_passes_at_250():
    """A measured cap-hit is the cap plus 2-8 s, not the cap itself."""
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    assert overhead == 70
    assert load == 900
    # v8 smoke5 hit 302-308 on a 300 s cap. The same +8 s on 260 fails.
    assert PROJECTED_HIDDEN_TASKS * (268 + overhead) == 40560
    assert PROJECTED_HIDDEN_TASKS * (262 + overhead) == 39840
    assert 40560 > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert 39840 > PROJECTED_RUNTIME_LIMIT_SECONDS
    # 250 + 8 = 258. 120 * 328 = 39360, which still passes.
    assert PROJECTED_HIDDEN_TASKS * (258 + overhead) == 39360
    assert 39360 <= PROJECTED_RUNTIME_LIMIT_SECONDS
    assert PROJECTED_HIDDEN_TASKS * (252 + overhead) == 38640
    assert 38640 <= PROJECTED_RUNTIME_LIMIT_SECONDS
    picture = submission_gate_picture(250)
    assert picture["block_120"] is False
    assert picture["block_120_if_mean_equals_cap"] == 38400
    assert picture["block_129"] is False
    assert picture["block_129_if_mean_equals_cap"] == 33150
    assert picture["warn"] is False
    assert picture["warn_seconds"] == 42180
    assert load + PROJECTED_PUBLIC_TASKS * 258 == 34182
    assert 34182 <= PROJECTED_LOAD_LIMIT_SECONDS
    assert load + PROJECTED_PUBLIC_TASKS * (250 + overhead) <= WORST_CASE_WARN_SECONDS
    # 135/170/195/205 leaves the five later roles 70 s, short of 5 * 15.
    assert 205 - 135 == 70
    assert 5 * 15 == 75
    assert 70 < 75
    stops = (130, 145, 160, 175, 190, 205)
    pairs = zip(stops, stops[1:], strict=False)
    assert all(right - left >= 15 for left, right in pairs)
    assert stops[-1] == 250 - 45
    assert PROJECTED_HIDDEN_TASKS * (293.3 + overhead) > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert PROJECTED_HIDDEN_TASKS * (205 + overhead) == 33000
    assert 33000 <= PROJECTED_RUNTIME_LIMIT_SECONDS


def test_smoke_protocol_uses_the_v8_smoke5_tasks(tmp_path):
    protocol = load_protocol(PROTOCOL)
    assert protocol["purpose"] == "smoke"
    assert protocol["matched_pair"] is False
    assert protocol["repeats"] == 1
    assert protocol["arms"]["A"]["source"] == "agents/structured-v8"
    assert protocol["arms"]["B"]["source"] == "agents/structured-v12"
    assert protocol["arms"]["A"]["expected_sha256"] == V8_ARCHIVE
    assert protocol["arms"]["B"]["expected_sha256"] == V12_ARCHIVE
    assert protocol["_task_ids"] == SMOKE_TASKS
    assert "fastapi_14262" not in protocol["_task_ids"]
    schedule = protocol_schedule(protocol)
    assert [entry["task_id"] for entry in schedule["entries"]] == SMOKE_TASKS
    assert schedule["sha256"] == SMOKE_SCHEDULE
    assert_arms_compatible(
        inspect_arm(V8),
        inspect_arm(V12),
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a=V8_ARCHIVE,
        sha_b=V12_ARCHIVE,
        matched_pair=False,
    )
    # v8's 300 s cap is the larger arm, so it is the pair_fits session cap.
    assert pair_fits_minimum_budget(5, 2, 300, extra_elapsed=300) == 4320
    assert protocol["session_budget_seconds"] == 14400
    assert protocol["session_budget_seconds"] >= 4320
    archive = tmp_path / "structured-v12.zip"
    manifest = pack(V12, archive)
    assert manifest["sha256"] == V12_ARCHIVE
    assert sha256(archive) == V12_ARCHIVE
    assert pack(V8, tmp_path / "structured-v8.zip")["sha256"] == V8_ARCHIVE
    assert pack(V10, tmp_path / "structured-v10.zip")["sha256"] == V10_ARCHIVE


def _v10_helpers():
    spec = importlib.util.spec_from_file_location(
        "structured_v10_compile",
        Path("tests/test_structured_v10.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compiles_on_adk_submission_0_2_12_and_0_2_13(tmp_path):
    """thinking_budget 0 compiles when the schema ge is 0, as on 0.2.12 and 0.2.13."""
    helpers = _v10_helpers()
    script = tmp_path / "compile_v12.py"
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
                allowed_file_extensions=frozenset(
                    {".yaml", ".yml", ".md", ".txt", ".py", ".json"}
                )
            )
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
            agent = compile_submission(
                SOURCE,
                tools,
                models,
                limits=LIMITS,
                generation_constraints=GenerationConstraints(
                    allowed_fields=None,
                    max_output_tokens=NumericRange(1, 32768),
                    thinking_budget=NumericRange(0, 32768),
                    defaults={
                        "max_output_tokens": 16384,
                        "thinking_config": {"thinking_budget": 4096},
                    },
                ),
            )

            def budget(child):
                config = child.generate_content_config
                thinking = getattr(config, "thinking_config", None)
                if thinking is None:
                    return None
                return getattr(thinking, "thinking_budget", None)

            print(json.dumps({
                "version": __import__("adk_submission").__version__,
                "root": type(agent).__name__,
                "names": [child.name for child in agent.sub_agents],
                "budgets": {child.name: budget(child) for child in agent.sub_agents},
            }))
            """
        )
    )
    compiled = {
        version: helpers._run_compiler(
            helpers._schema_tree(version, 0),
            script,
            str(V12.resolve()),
        )
        for version in ("0.2.12", "0.2.13")
    }
    for version, payload in compiled.items():
        assert payload["version"] == version
        assert payload["root"] == "SequentialAgent"
        assert payload["names"] == [
            "triage",
            "repair_1",
            "verify_1",
            "repair_2",
            "verify_2",
            "repair_3",
            "verify_3",
        ]
        assert payload["budgets"]["triage"] == 0
        assert payload["budgets"]["repair_1"] == 256
        assert payload["budgets"]["verify_3"] == 0
    rejected = subprocess.run(
        [sys.executable, str(script), str(V12.resolve())],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(helpers._schema_tree("0.2.11", 1)),
                    str(helpers._ensure_adk()),
                ]
            ),
            "PYTHONWARNINGS": "ignore",
        },
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "greater than or equal to 1" in (rejected.stderr + rejected.stdout)
