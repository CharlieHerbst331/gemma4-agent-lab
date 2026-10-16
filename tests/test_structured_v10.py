"""structured-v10: parallel repairs, a real-repo fallback, and the 255 s gate."""

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
from gemma_lab.multi_arm import pair_fits_minimum_budget
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
V9 = Path("agents/structured-v9")
V10 = Path("agents/structured-v10")
PROTOCOL = Path("configs/protocols/structured-v8-vs-structured-v10-smoke.yaml")
V8_ARCHIVE = "9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e"
V9_ARCHIVE = "209bd43ed52731813ecc4fc8d40edea186bd1af2a6f00e18acf5aae7809b18a5"
V10_ARCHIVE = "c07fcc5505f509f648a924a09dfa5a0f4c1cfe10d4b0a784f938e69116c66ed0"
SMOKE_SCHEDULE = "5672ef15323e1d59847cc7cde3f1b6cb1912346d7456b13cb716902437b3e9fd"
SMOKE_TASKS = ["rich_4070", "rich_3934", "fastapi_11194", "rich_3938", "fastapi_14262"]
CAP_SECONDS = 300
PROJECTED_MEAN_SECONDS = 255
BRANCH_CALLS = 60
TURN_FALLBACK = 500
CHECK_CALL = '{"skill_name":"check","file_path":"scripts/run.py"}'
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


def _role(name):
    return load_yaml(V10 / "sub_agents" / f"{name}.yaml", V10)


def _prompt(name):
    return (V10 / "sub_agents" / f"{name}.md").read_text()


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_parallel_repairs_keep_v8_sampling_and_raise_shared_counters():
    root = load_yaml(V10 / "agent.yaml", V10)
    assert root["agent_class"] == "SequentialAgent"
    assert root["name"] == "structured_v10"
    assert "include_contents" not in root
    assert [child["config_path"] for child in root["sub_agents"]] == [
        "sub_agents/triage.yaml",
        "sub_agents/repairs.yaml",
        "sub_agents/select.yaml",
    ]
    repairs = _role("repairs")
    assert repairs["agent_class"] == "ParallelAgent"
    assert repairs["name"] == "repairs"
    assert "include_contents" not in repairs
    assert [child["config_path"] for child in repairs["sub_agents"]] == [
        "repair_a.yaml",
        "repair_b.yaml",
        "repair_c.yaml",
    ]
    blob = "\n".join(path.read_text() for path in V10.rglob("*.yaml"))
    assert "LoopAgent" not in blob
    assert "max_llm_calls" not in blob
    assert "callback" not in blob.lower()
    triage = _role("triage")
    assert triage["tools"] == []
    assert triage["include_contents"] == "default"
    assert triage["output_key"] == "triage_brief"
    assert triage["generate_content_config"]["max_output_tokens"] == 1024
    assert triage["generate_content_config"]["thinking_config"]["thinking_budget"] == 0
    repair_a, repair_b, repair_c = _role("repair_a"), _role("repair_b"), _role("repair_c")
    assert repair_a["tools"] == [
        "get_status",
        "read_file",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
    ]
    assert repair_b["tools"] == ["get_status", "read_file", "run_command"]
    assert repair_c["tools"] == [
        "get_status",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
    ]
    assert "read_file" not in repair_c["tools"]
    seeds = {"repair_a": 101, "repair_b": 202, "repair_c": 303}
    for name, role in ("repair_a", repair_a), ("repair_b", repair_b), ("repair_c", repair_c):
        assert "submit_patch" not in role["tools"]
        assert "edit_file" not in role["tools"]
        assert "write_file" not in role["tools"]
        assert role["include_contents"] == "default"
        sampling = role["generate_content_config"]
        assert sampling["top_p"] == 0.95
        assert sampling["top_k"] == 64
        assert sampling["seed"] == seeds[name]
        assert sampling["thinking_config"] == {"include_thoughts": True, "thinking_budget": 256}
        assert sampling["max_output_tokens"] == 2048
    assert repair_a["generate_content_config"]["temperature"] == 1.0
    assert repair_b["generate_content_config"]["temperature"] == 1.0
    assert repair_c["generate_content_config"]["temperature"] == 1.3
    select = _role("select")
    assert select["include_contents"] == "none"
    assert select["tools"] == ["get_status", "run_command", "submit_patch"]
    assert select["skills"] == ["skills/check"]
    assert "output_key" not in select
    assert select["generate_content_config"]["temperature"] == 1.0
    assert select["generate_content_config"]["thinking_config"]["thinking_budget"] == 0
    budgets = load_yaml(V10 / "eval_config.yaml", V10)["evaluation"]
    assert budgets["max_time_minutes"] == 5
    assert type(budgets["max_time_minutes"]) is int
    assert budgets["timeout_seconds"] == 300
    assert budgets["max_tool_calls"] == 300
    assert budgets["max_turns"] == 480
    assert budgets["max_tool_calls"] >= 3 * BRANCH_CALLS
    assert budgets["max_turns"] <= TURN_FALLBACK
    parent = load_yaml(V8 / "eval_config.yaml", V8)["evaluation"]
    assert parent["max_time_minutes"] == 5
    assert parent["max_tool_calls"] == 220
    assert parent["max_turns"] == 320
    assert budgets["max_tool_calls"] > parent["max_tool_calls"]
    assert budgets["max_turns"] > parent["max_turns"]
    skill = V10 / "skills" / "check" / "scripts" / "run.py"
    assert skill.read_bytes() == (V8 / "skills" / "check" / "scripts" / "run.py").read_bytes()
    assert (V10 / "skills" / "check" / "SKILL.md").read_bytes() == (
        V8 / "skills" / "check" / "SKILL.md"
    ).read_bytes()
    assert (V10 / "sub_agents" / "thinking.yaml").read_bytes() == (
        V8 / "sub_agents" / "thinking.yaml"
    ).read_bytes()
    assert (V10 / "sub_agents" / "repair_thinking.yaml").read_bytes() == (
        V8 / "sub_agents" / "repair_thinking.yaml"
    ).read_bytes()
    assert len(validate(V10)) == 17
    report = lint_candidate(V10)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_prompts_keep_the_heredoc_and_branch_a_edits_the_real_repo():
    repair_a, repair_b, repair_c = _prompt("repair_a"), _prompt("repair_b"), _prompt("repair_c")
    select = _prompt("select")
    triage = _prompt("triage")
    assert "under 20 seconds" in triage
    assert "Do not stop with UNCERTAIN" in triage
    for prompt, letter in (repair_a, "a"), (repair_b, "b"), (repair_c, "c"):
        assert f"git worktree add -q /tmp/cand_{letter} HEAD" in prompt
        assert f"/tmp/cand_{letter}.diff" in prompt
        assert f"/tmp/cand_{letter}_repro.py" in prompt
        assert f"/tmp/line_fix_{letter}.py" in prompt
        assert 'ast.parse(s.decode("utf-8"))' in prompt
        assert f'backup = "/tmp/pre_{letter}_" + path.replace("/", "_")' in prompt
        assert "shutil.copyfile(path, backup)" in prompt
        assert "shutil.copyfile(backup, path)" in prompt
        assert "py_compile.compile(path, doraise=True)" in prompt
        assert "onto no other file" in prompt
        assert "Never run git checkout" in prompt
        assert "git checkout --" not in prompt
        assert "the next call is the heredoc" in prompt
        assert "time_seconds_remaining is under 120" in prompt
        assert "agent_elapsed_seconds is 170 or more" in prompt
        assert "Call get_status again before every run_command" in prompt
        assert "220 or more" not in prompt
        conftest = (
            "test -f /workspace/conftest.py && cp /workspace/conftest.py "
            f"/tmp/cand_{letter}/conftest.py"
        )
        pytest_ini = (
            "test -f /workspace/pytest.ini && cp /workspace/pytest.ini "
            f"/tmp/cand_{letter}/pytest.ini"
        )
        quiet_apply = f"cd /workspace && git diff --quiet && git apply /tmp/cand_{letter}.diff"
        assert conftest in prompt
        assert pytest_ini in prompt
        assert quiet_apply in prompt
        assert "You do not have submit_patch" in prompt
        assert "line_fix.bak" not in prompt
        assert "Never revert a non-empty source diff" in prompt
        assert "Never run git apply" not in prompt
    assert "repro-first" in repair_a
    assert "A cap hit with no diff must not happen once that compile has succeeded." in repair_a
    assert "edit-first" in repair_b
    assert "Do not write a repro until a source edit exists." in repair_b
    assert "graph tools only" in repair_c
    assert "You do not have read_file" in repair_c
    assert "Select owns the final choice" in repair_a
    assert "Select owns the final choice" in repair_b
    assert "Select owns the final choice" in repair_c
    assert "py_compile" in select
    assert "python /tmp/cand_X_repro.py" in select
    assert "Do not run the other branches' repro scripts." in select
    assert "time_seconds_remaining is under 90" in select
    assert "skip pytest" in select
    assert "cd /workspace && git checkout -- . && git apply /tmp/cand_X.diff" in select
    assert CHECK_CALL in select
    assert "call submit_patch anyway" in select
    assert "time_seconds_remaining is under 45" in select
    assert "submit_patch" in select
    joined = "\n".join([triage, repair_a, repair_b, repair_c, select])
    assert "By 220 elapsed seconds" not in joined
    assert "By 170 elapsed seconds" not in joined
    assert "git add -A" not in joined
    assert "git add ." not in joined


def test_branch_stop_is_170_seconds():
    for name in ("repair_a", "repair_b", "repair_c"):
        prompt = _prompt(name)
        assert prompt.count("agent_elapsed_seconds is 170 or more") >= 2
        assert "220" not in prompt
    select = _prompt("select")
    assert "Commands are serialized" in select
    assert "time_seconds_remaining is under 90" in select


def test_fallback_apply_leaves_a_source_diff_without_tmp_or_worktree_paths(tmp_path):
    repo = tmp_path / "workspace"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "pkg.py").write_text("value = 1\n")
    _git(repo, "add", "pkg.py")
    _git(repo, "commit", "-qm", "init")
    worktree = tmp_path / "cand_a"
    repro = tmp_path / "cand_a_repro.py"
    diff_path = tmp_path / "cand_a.diff"
    _git(repo, "worktree", "add", "-q", str(worktree), "HEAD")
    try:
        (worktree / "pkg.py").write_text("value = 2\n")
        (worktree / "repro_check.py").write_text("print('scratch')\n")
        repro.write_text("assert False\n")
        diff_path.write_text(subprocess.check_output(["git", "diff"], cwd=worktree, text=True))
        assert diff_path.read_text().strip()
        assert "/tmp" not in diff_path.read_text()
        assert "worktree" not in diff_path.read_text()
        assert "repro_check.py" not in diff_path.read_text()
        assert "cand_a_repro" not in diff_path.read_text()
        subprocess.run(["git", "apply", str(diff_path)], cwd=repo, check=True)
        names = subprocess.check_output(["git", "diff", "--name-only"], cwd=repo, text=True).split()
        body = subprocess.check_output(["git", "diff"], cwd=repo, text=True)
        assert names == ["pkg.py"]
        assert "value = 2" in body
        assert "/tmp" not in body
        assert "worktree" not in body
        assert "cand_" not in body
        status = subprocess.check_output(["git", "status", "--short"], cwd=repo, text=True)
        assert "repro" not in status
        assert ".git" not in status
        # Selector skipped: the real repo already holds branch a's compiling edit.
        assert body.strip()
    finally:
        _git(repo, "worktree", "remove", "--force", str(worktree))


def test_selector_replaces_the_fallback_without_leaking_scratch(tmp_path):
    repo = tmp_path / "workspace"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "pkg.py").write_text("value = 1\n")
    _git(repo, "add", "pkg.py")
    _git(repo, "commit", "-qm", "init")
    fallback = tmp_path / "cand_a.diff"
    winner = tmp_path / "cand_b.diff"
    vote = tmp_path / "select_vote"
    _git(repo, "worktree", "add", "-q", str(vote), "HEAD")
    try:
        (vote / "pkg.py").write_text("value = 2\n")
        fallback.write_text(subprocess.check_output(["git", "diff"], cwd=vote, text=True))
        subprocess.run(["git", "checkout", "--", "."], cwd=vote, check=True)
        (vote / "pkg.py").write_text("value = 3\n")
        (vote / "scratch.py").write_text("print(1)\n")
        winner.write_text(subprocess.check_output(["git", "diff"], cwd=vote, text=True))
        subprocess.run(["git", "checkout", "--", "."], cwd=vote, check=True)
        subprocess.run(["git", "apply", str(fallback)], cwd=repo, check=True)
        assert "value = 2" in (repo / "pkg.py").read_text()
        subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
        subprocess.run(["git", "apply", "--check", str(winner)], cwd=repo, check=True)
        subprocess.run(["git", "apply", str(winner)], cwd=repo, check=True)
        body = subprocess.check_output(["git", "diff"], cwd=repo, text=True)
        names = subprocess.check_output(["git", "diff", "--name-only"], cwd=repo, text=True).split()
        assert names == ["pkg.py"]
        assert "value = 3" in body
        assert "scratch.py" not in body
        assert "/tmp" not in body
        assert "worktree" not in body
        assert not (repo / "scratch.py").exists()
    finally:
        _git(repo, "worktree", "remove", "--force", str(vote))


def test_runtime_gates_pass_at_the_aimed_mean():
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    assert overhead == 70
    assert load == 900
    cap_120 = PROJECTED_HIDDEN_TASKS * (CAP_SECONDS + overhead)
    cap_warn = load + PROJECTED_PUBLIC_TASKS * (CAP_SECONDS + overhead)
    cap_129 = load + PROJECTED_PUBLIC_TASKS * CAP_SECONDS
    assert cap_120 == 44400
    assert cap_warn == 48630
    assert cap_129 == 39600
    assert cap_warn > WORST_CASE_WARN_SECONDS
    assert cap_120 > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert cap_129 > PROJECTED_LOAD_LIMIT_SECONDS
    mean_120 = PROJECTED_HIDDEN_TASKS * (PROJECTED_MEAN_SECONDS + overhead)
    mean_129 = load + PROJECTED_PUBLIC_TASKS * PROJECTED_MEAN_SECONDS
    mean_warn = load + PROJECTED_PUBLIC_TASKS * (PROJECTED_MEAN_SECONDS + overhead)
    assert mean_120 == 39000
    assert mean_129 == 33795
    assert mean_warn == 42825
    assert mean_120 <= PROJECTED_RUNTIME_LIMIT_SECONDS
    assert mean_129 <= PROJECTED_LOAD_LIMIT_SECONDS
    assert mean_warn <= WORST_CASE_WARN_SECONDS
    # Shared counters: 3 branches x 60 calls fit, and turns stay under the
    # runner fallback of 500. The clock is still the binding cap.
    assert 3 * BRANCH_CALLS <= 300
    assert 480 <= TURN_FALLBACK
    assert CAP_SECONDS - 45 == PROJECTED_MEAN_SECONDS
    # Branches stop at 170 so select has 130 seconds. Tool time is summed,
    # so a later mean can drift. 260 is the last integer mean that passes
    # the 120-task block. 270 fails that block and still passes the 129-task
    # block.
    assert CAP_SECONDS - 170 == 130
    mean_260 = PROJECTED_HIDDEN_TASKS * (260 + overhead)
    mean_270 = PROJECTED_HIDDEN_TASKS * (270 + overhead)
    public_270 = load + PROJECTED_PUBLIC_TASKS * 270
    assert mean_260 == 39600
    assert mean_260 <= PROJECTED_RUNTIME_LIMIT_SECONDS
    assert mean_270 == 40800
    assert mean_270 > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert public_270 == 35730
    assert public_270 <= PROJECTED_LOAD_LIMIT_SECONDS


def test_smoke_protocol_compares_v8_and_v10_on_the_combined_five():
    protocol = load_protocol(PROTOCOL)
    assert protocol["purpose"] == "smoke"
    assert protocol["matched_pair"] is False
    assert protocol["repeats"] == 1
    assert protocol["arms"]["A"]["source"] == "agents/structured-v8"
    assert protocol["arms"]["B"]["source"] == "agents/structured-v10"
    assert protocol["arms"]["A"]["expected_sha256"] == V8_ARCHIVE
    assert protocol["arms"]["B"]["expected_sha256"] == V10_ARCHIVE
    assert protocol["_task_ids"] == SMOKE_TASKS
    schedule = protocol_schedule(protocol)
    assert [entry["task_id"] for entry in schedule["entries"]] == SMOKE_TASKS
    assert schedule["sha256"] == SMOKE_SCHEDULE
    assert_arms_compatible(
        inspect_arm(V8),
        inspect_arm(V10),
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a=V8_ARCHIVE,
        sha_b=V10_ARCHIVE,
        matched_pair=False,
    )
    minimum = pair_fits_minimum_budget(5, 2, CAP_SECONDS, extra_elapsed=300)
    assert minimum == 4320
    assert protocol["session_budget_seconds"] == 14400
    assert protocol["session_budget_seconds"] >= minimum
    assert protocol["session_budget_seconds"] < WORST_CASE_WARN_SECONDS


def test_archive_pins_v10_and_leaves_v8_and_v9_unchanged(tmp_path):
    archive = tmp_path / "structured-v10.zip"
    manifest = pack(V10, archive)
    assert manifest["sha256"] == V10_ARCHIVE
    assert sha256(archive) == V10_ARCHIVE
    names = set(json.loads(json.dumps(manifest["files"])))
    assert all("/tmp" not in name and "worktree" not in name for name in names)
    assert pack(V8, tmp_path / "structured-v8.zip")["sha256"] == V8_ARCHIVE
    assert pack(V9, tmp_path / "structured-v9.zip")["sha256"] == V9_ARCHIVE


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
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(ADK_PY),
                "google-adk==1.36.1",
            ]
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("google-adk 1.36.1 pip install failed; compile test skipped offline")
    if not (ADK_PY / "google" / "adk" / "__init__.py").is_file():
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


def _run_compiler(pkg_root, script, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(pkg_root), str(_ensure_adk())])
    env["PYTHONWARNINGS"] = "ignore"
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr[-2000:] or completed.stdout[-2000:])
    return json.loads(completed.stdout)


def test_compiles_on_adk_submission_0_2_12_and_0_2_13(tmp_path):
    """Compile against the public compiler plus the documented ge=0 schema.

    adk-submission 0.2.12 and 0.2.13 are not on PyPI. The public source is
    0.2.11, whose schema rejects thinking_budget 0 (ge=1). 0.2.12 and 0.2.13
    accept 0. Each labeled tree is that source with ge set to 0, compiled
    with google-adk 1.36.1 and the competition generation defaults.
    """
    script = tmp_path / "compile_v10.py"
    script.write_text(
        textwrap.dedent(
            """\
            import json
            import sys
            import tempfile
            import textwrap
            from pathlib import Path

            from adk_submission import GenerationConstraints
            from adk_submission import ModelRegistry
            from adk_submission import NumericRange
            from adk_submission import SubmissionLimits
            from adk_submission import ToolRegistry
            from adk_submission import compile_submission
            from google.adk.agents import ParallelAgent

            SOURCE = Path(sys.argv[1])
            MODE = sys.argv[2]
            LIMITS = SubmissionLimits(
                allowed_file_extensions=frozenset({".yaml", ".yml", ".md", ".txt", ".py", ".json"})
            )


            def constraints(missing_budget):
                defaults = {"max_output_tokens": 16384}
                if missing_budget == "4096":
                    defaults["thinking_config"] = {"thinking_budget": 4096}
                return GenerationConstraints(
                    allowed_fields=None,
                    max_output_tokens=NumericRange(1, 32768),
                    thinking_budget=NumericRange(0, 32768),
                    defaults=defaults,
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
                return tools, models


            def budget(agent):
                config = agent.generate_content_config
                thinking = getattr(config, "thinking_config", None)
                return None if thinking is None else getattr(thinking, "thinking_budget", None)


            if MODE == "candidate":
                tools, models = registries()
                agent = compile_submission(
                    SOURCE,
                    tools,
                    models,
                    limits=LIMITS,
                    generation_constraints=constraints("4096"),
                )
                parallel = next(
                    child
                    for child in agent.sub_agents
                    if isinstance(child, ParallelAgent)
                )
                branches = {child.name: child for child in parallel.sub_agents}
                select = agent.sub_agents[-1]
                repair_c = branches["repair_c"].generate_content_config
                print(json.dumps({
                    "version": __import__("adk_submission").__version__,
                    "root": type(agent).__name__,
                    "parallel": parallel.name,
                    "branches": sorted(branches),
                    "repair_c_temperature": repair_c.temperature,
                    "seeds": {
                        name: child.generate_content_config.seed
                        for name, child in branches.items()
                    },
                    "contents": {
                        name: child.include_contents
                        for name, child in branches.items()
                    },
                    "select_contents": select.include_contents,
                    "triage_budget": budget(agent.sub_agents[0]),
                    "repair_budget": budget(branches["repair_a"]),
                    "select_budget": budget(select),
                }))
            elif MODE == "missing":
                root = Path(tempfile.mkdtemp())
                (root / "t.md").write_text("hi\\n")
                (root / "t.yaml").write_text("include_thoughts: false\\n")
                (root / "agent.yaml").write_text(textwrap.dedent('''\\
                    agent_class: LlmAgent
                    name: one
                    model: gemma-4-31b-it-qat-w4a16-ct
                    description: one
                    instruction: !include t.md
                    generate_content_config:
                      temperature: 1.0
                      max_output_tokens: 1024
                      thinking_config: !include t.yaml
                    tools: []
                '''))
                tools, models = registries()
                agent = compile_submission(
                    root,
                    tools,
                    models,
                    limits=LIMITS,
                    generation_constraints=constraints("4096"),
                )
                print(json.dumps({"missing_budget": budget(agent)}))
            else:
                raise SystemExit("unknown mode")
            """
        )
    )
    tree_012 = _schema_tree("0.2.12", 0)
    tree_013 = _schema_tree("0.2.13", 0)
    tree_011 = _schema_tree("0.2.11", 1)
    compiled = {
        version: _run_compiler(tree, script, str(V10.resolve()), "candidate")
        for version, tree in (("0.2.12", tree_012), ("0.2.13", tree_013))
    }
    for version, payload in compiled.items():
        assert payload["version"] == version
        assert payload["root"] == "SequentialAgent"
        assert payload["parallel"] == "repairs"
        assert payload["branches"] == ["repair_a", "repair_b", "repair_c"]
        assert payload["repair_c_temperature"] == 1.3
        assert payload["seeds"] == {"repair_a": 101, "repair_b": 202, "repair_c": 303}
        assert payload["contents"] == {
            "repair_a": "default",
            "repair_b": "default",
            "repair_c": "default",
        }
        assert payload["select_contents"] == "none"
        assert payload["triage_budget"] == 0
        assert payload["repair_budget"] == 256
        assert payload["select_budget"] == 0
    missing = _run_compiler(tree_013, script, str(V10.resolve()), "missing")
    assert missing["missing_budget"] == 4096
    rejected = subprocess.run(
        [sys.executable, str(script), str(V10.resolve()), "candidate"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(tree_011), str(_ensure_adk())]),
            "PYTHONWARNINGS": "ignore",
        },
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "greater than or equal to 1" in (rejected.stderr + rejected.stdout)
