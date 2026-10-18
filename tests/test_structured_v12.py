"""structured-v12: elapsed line on every shell result, cap that still passes."""

import fcntl
import os
import re
import shlex
import subprocess
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
V12_ARCHIVE = "3d3f320ec7b9efbb92f0a732db1750fb63c6dbbde34624aa171d1dbe22e94d7b"
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
    "sub_agents/repair_3.yaml",
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
    assert "The task cap is 260 seconds" in repair_1
    assert "line is 150 or more" in repair_1
    assert "line is 120 or more and git diff is empty" in repair_1
    assert "still under 150" in repair_1
    assert "Do not call read_file" in repair_1
    assert "line is 210 or more" in repair_2
    assert "line is 120 or more and git diff is empty" in repair_2
    assert "which is 215" in verify_3
    assert "line is 215 or more" in verify_3
    assert "call submit_patch anyway" in verify_3
    assert '{"skill_name":"check","file_path":"scripts/run.py"}' in verify_3
    for name in ("repair_1", "repair_2", "repair_3", "verify_3"):
        assert _heredoc(_prompt(name)) == _heredoc((V8 / "sub_agents" / f"{name}.md").read_text())
        text = _prompt(name)
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
    assert budgets["timeout_seconds"] == 260
    assert budgets["max_time_minutes"] * 60 == 260
    assert type(budgets["max_time_minutes"]) is float
    assert len(validate(V12)) == 20
    report = lint_candidate(V12)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_cap_hit_mean_passes_at_260_and_fails_at_270():
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    assert overhead == 70
    assert load == 900
    assert submission_gate_picture(260)["block_120"] is False
    assert submission_gate_picture(260)["block_120_if_mean_equals_cap"] == 39600
    assert submission_gate_picture(260)["block_129"] is False
    assert submission_gate_picture(260)["block_129_if_mean_equals_cap"] == 34440
    assert submission_gate_picture(260)["warn"] is True
    assert submission_gate_picture(260)["warn_seconds"] == 43470
    assert submission_gate_picture(270)["block_120"] is True
    assert submission_gate_picture(270)["block_120_if_mean_equals_cap"] == 40800
    assert PROJECTED_HIDDEN_TASKS * (260 + overhead) == PROJECTED_RUNTIME_LIMIT_SECONDS
    assert PROJECTED_HIDDEN_TASKS * (270 + overhead) == 40800
    assert 40800 > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert load + PROJECTED_PUBLIC_TASKS * 260 <= PROJECTED_LOAD_LIMIT_SECONDS
    assert load + PROJECTED_PUBLIC_TASKS * (260 + overhead) > WORST_CASE_WARN_SECONDS
    # The smoke mean, 293.3 s, fails the same block. Submit at cap minus 45.
    assert PROJECTED_HIDDEN_TASKS * (293.3 + overhead) > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert 260 - 45 == 215
    assert PROJECTED_HIDDEN_TASKS * (215 + overhead) == 34200
    assert 34200 <= PROJECTED_RUNTIME_LIMIT_SECONDS


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
