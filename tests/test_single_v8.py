"""single-v8 edits through run_command. single-v8-check adds one flat skill."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml
from gemma_lab.hygiene import lint_candidate
from gemma_lab.notebook import _pair_eval_cell
from gemma_lab.operations import (
    DEFAULT_MODEL_LOAD_SECONDS,
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    PROJECTED_HIDDEN_TASKS,
    PROJECTED_PUBLIC_TASKS,
    PROJECTED_RUNTIME_LIMIT_SECONDS,
    WORST_CASE_WARN_SECONDS,
)
from gemma_lab.paired import (
    assert_arms_compatible,
    inspect_arm,
    load_protocol,
    notebook_runtime_source,
    protocol_schedule,
    report_from_runs,
)

V7 = Path("agents/single-v7")
V8 = Path("agents/single-v8")
CHECK = Path("agents/single-v8-check")
DEV = Path("configs/protocols/single-v7-vs-single-v8-dev13.yaml")
SMOKE = Path("configs/protocols/single-v8-vs-single-v8-check-smoke.yaml")
SIBLING = Path("configs/protocols/single-v6-vs-single-v7-dev13.yaml")
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
SMOKE_SCHEDULE = "5672ef15323e1d59847cc7cde3f1b6cb1912346d7456b13cb716902437b3e9fd"
COHORT = [
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
SMOKE_TASKS = [
    "rich_4070",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "fastapi_14262",
]
CAP_SECONDS = 330


def _files(root):
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _pair(left, right, allowed, matched_pair):
    assert_arms_compatible(
        left,
        right,
        allow_identical=False,
        allowed_differences=allowed,
        sha_a="a" * 64,
        sha_b="b" * 64,
        matched_pair=matched_pair,
    )


def test_single_v8_is_a_prompt_and_budget_change():
    prompt = (V8 / "prompts" / "system.md").read_text()
    parent = (V7 / "prompts" / "system.md").read_text()
    assert prompt != parent
    assert len(parent) == 8024
    assert len(prompt) == 8283
    assert (V8 / "thinking.yaml").read_bytes() == (V7 / "thinking.yaml").read_bytes()
    assert "skills:" not in (V8 / "agent.yaml").read_text()
    sampling = load_yaml(V8 / "sampling.yaml", V8)
    assert sampling["temperature"] == 1.0
    assert sampling["top_p"] == 0.95
    assert sampling["top_k"] == 64
    assert sampling["max_output_tokens"] == 2048
    assert sampling["thinking_config"]["thinking_budget"] == 0
    assert sampling["thinking_config"]["include_thoughts"] is False
    budgets = load_yaml(V8 / "eval_config.yaml", V8)["evaluation"]
    assert budgets["max_tool_calls"] == 150
    assert budgets["max_turns"] == 200
    assert budgets["max_time_minutes"] == 5.5
    assert budgets["timeout_seconds"] == 300
    inspected = inspect_arm(V8)
    assert inspected["sampling"] == [(1.0, 0.95, 0, False)]
    assert inspected["budgets"]["max_time_minutes"] == 5.5
    for phrase in (
        "Edit with run_command. That is the primary edit.",
        "cat > /tmp/line_fix.py <<'EOF'",
        "assert s.count(old) == 1",
        "assert new in s",
        "Do not use read_text or write_text",
        "newline=''",
        "about 90 seconds",
        "about 38 counted calls",
        "about 75",
        "165 seconds",
        "When adding a new parameter to an internal class",
        "After the second edit_file error of any kind on the same file",
        "Failed to replace: old_string not found",
        "mandatory input parameters are not present",
        "Target string occurs N times",
        "git diff must be non-empty",
        "Do not submit an empty diff",
        "not reproducible, already fixed, and not a bug never end the task",
        "Call counts are not a reason to stop",
        "fewer than 60 seconds",
        "fewer than 20 seconds",
        "Make the most plausible minimal edit; do not submit an empty diff.",
        "Call get_status about every 5 calls, and before submit_patch",
        "old = b'''OLD'''",
        "new = b'''NEW'''",
        "free of backslashes and triple quotes",
        "Non-ASCII bytes need \\xNN",
        "While the check has not passed and time_seconds_remaining is above 60, keep editing.",
        "After a passing check, run git diff and call submit_patch.",
    ):
        assert phrase in prompt, phrase
    assert "An empty diff is never allowed" not in prompt
    assert "While time_seconds_remaining is above 60, keep editing" not in prompt
    assert "UNCERTAIN" not in prompt
    assert "call 24" not in prompt
    assert "95 seconds" not in prompt
    assert "skill_name" not in prompt
    wrapper = prompt.index("When adding a new parameter")
    second = prompt.index("second edit_file error of any kind")
    assert wrapper < second
    report = lint_candidate(V8)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_single_v8_check_adds_only_the_flat_skill():
    shared = ("thinking.yaml", "eval_config.yaml", "sampling.yaml")
    for name in shared:
        assert (V8 / name).read_bytes() == (CHECK / name).read_bytes()
    prompt = (CHECK / "prompts" / "system.md").read_text()
    parent = (V8 / "prompts" / "system.md").read_text()
    sentence = (
        "After a source edit, you may call the check skill once. The only call is "
        '{"skill_name":"check","file_path":"scripts/run.py"} with no args. Both keys stay '
        "top-level. If that call fails twice, stop using the skill and keep using "
        "run_command.\n\n"
    )
    assert len(prompt) == 8524
    assert sentence in prompt
    assert prompt.replace(sentence, "", 1) == parent
    agent = (CHECK / "agent.yaml").read_text()
    assert "skills:\n- skills/check\n" in agent
    skill = CHECK / "skills" / "check"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "scripts" / "run.py").is_file()
    assert _files(CHECK) - _files(V8) == {
        "skills/check/SKILL.md",
        "skills/check/scripts/run.py",
    }
    report = lint_candidate(CHECK)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_dev13_protocol_allows_the_budget_and_sampling_markers():
    protocol = load_protocol(DEV)
    assert protocol.get("purpose") != "smoke"
    assert protocol["matched_pair"] is False
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == COHORT
    assert protocol["arms"]["A"]["source"] == "agents/single-v7"
    assert protocol["arms"]["B"]["source"] == "agents/single-v8"
    assert "eval_config.yaml" in protocol["allowed_differences"]
    assert "sampling.yaml" in protocol["allowed_differences"]
    assert "thinking.yaml" not in protocol["allowed_differences"]
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 13
    assert schedule["sha256"] == DEV_SCHEDULE
    assert protocol_schedule(load_protocol(SIBLING))["sha256"] == DEV_SCHEDULE
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert arms["A"]["budgets"] != arms["B"]["budgets"]
    assert arms["A"]["sampling"] != arms["B"]["sampling"]
    _pair(arms["A"], arms["B"], protocol["allowed_differences"], False)


def test_smoke_protocol_is_the_bad_call_tasks():
    protocol = load_protocol(SMOKE)
    assert protocol["purpose"] == "smoke"
    assert protocol["matched_pair"] is True
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == SMOKE_TASKS
    for required in ("rich_4070", "rich_3934", "fastapi_11194"):
        assert required in SMOKE_TASKS
    assert "fastapi_14786" not in SMOKE_TASKS
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert arms["A"]["budgets"] == arms["B"]["budgets"]
    assert arms["A"]["sampling"] == arms["B"]["sampling"]
    _pair(arms["A"], arms["B"], protocol["allowed_differences"], True)
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 5
    assert schedule["sha256"] == SMOKE_SCHEDULE


def test_budget_and_sampling_markers_are_not_implied(tmp_path):
    left = inspect_arm(V7)
    right = inspect_arm(V8)
    with pytest.raises(ValueError, match="budgets"):
        _pair(left, right, ["prompts/*", "agent.yaml"], False)
    with pytest.raises(ValueError, match="generation settings"):
        _pair(left, right, ["prompts/*", "eval_config.yaml"], False)
    with pytest.raises(ValueError, match="budgets"):
        _pair(left, right, ["prompts/*", "eval_config.yaml", "sampling.yaml"], True)
    _pair(left, right, ["prompts/*", "eval_config.yaml", "sampling.yaml"], False)
    changed = tmp_path / "think"
    changed.mkdir()
    for name in ("agent.yaml", "eval_config.yaml", "prompts"):
        source = V8 / name
        target = changed / name
        if source.is_dir():
            target.mkdir()
            (target / "system.md").write_text((source / "system.md").read_text())
        else:
            target.write_text(source.read_text())
    (changed / "sampling.yaml").write_text((V8 / "sampling.yaml").read_text())
    (changed / "thinking.yaml").write_text("thinking_budget: 256\ninclude_thoughts: true\n")
    with pytest.raises(ValueError, match="generation settings"):
        _pair(
            inspect_arm(V8),
            inspect_arm(changed),
            ["prompts/*", "sampling.yaml"],
            True,
        )


def test_runtime_cap_warns_and_does_not_block():
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    load = DEFAULT_MODEL_LOAD_SECONDS
    assert overhead == 70
    assert load == 900
    assert PROJECTED_HIDDEN_TASKS == 120
    assert PROJECTED_PUBLIC_TASKS == 129
    worst_120 = PROJECTED_HIDDEN_TASKS * (CAP_SECONDS + overhead)
    worst_129 = load + PROJECTED_PUBLIC_TASKS * (CAP_SECONDS + overhead)
    assert worst_120 == 48000
    assert worst_129 == 52500
    assert worst_129 > WORST_CASE_WARN_SECONDS
    assert worst_120 > PROJECTED_RUNTIME_LIMIT_SECONDS
    # The upload block uses a measured mean, not the cap. A mean equal to the
    # cap would block. The largest mean that still passes is 260 s.
    max_mean = PROJECTED_RUNTIME_LIMIT_SECONDS / PROJECTED_HIDDEN_TASKS - overhead
    assert max_mean == 260
    max_ok_cap = (WORST_CASE_WARN_SECONDS - load) / PROJECTED_PUBLIC_TASKS - overhead
    assert 257 < max_ok_cap < 258


def test_dev13_report_is_not_a_smoke(tmp_path):
    run = tmp_path / "run"
    _arm_row(run, "A", "rich_4070", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "rich_4070", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], DEV, output)
    text = (output / "pair_report.md").read_text()
    assert not text.startswith("smoke, not promotion eligible")
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved.get("purpose") != "smoke"
    assert saved["schedule_sha256"] == DEV_SCHEDULE


def test_unmatched_report_counts_wall_against_each_arm_cap(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {
            "arm": "A",
            "repeat": 1,
            "task_id": "rich_4070",
            "resolved": False,
            "wall_seconds": 275,
            "hit_cap": {"wall": False, "marker": True},
        },
        {
            "arm": "B",
            "repeat": 1,
            "task_id": "rich_4070",
            "resolved": False,
            "wall_seconds": 275,
            "hit_cap": {"wall": False, "marker": False},
        },
    ]
    (run / "pair_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    output = tmp_path / "report"
    report_from_runs([run], DEV, output)
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["raw_totals"]["A"]["hit_cap_wall"] == 1
    assert saved["raw_totals"]["B"]["hit_cap_wall"] == 0
    assert saved["raw_totals"]["A"]["hit_cap_marker"] == 1
    assert saved["raw_totals"]["B"]["hit_cap_marker"] == 0
    matched = tmp_path / "matched"
    report_from_runs([run], SIBLING, matched)
    kept = json.loads((matched / "pair_report.json").read_text())
    assert kept["raw_totals"]["A"]["hit_cap_wall"] == 0
    assert kept["raw_totals"]["B"]["hit_cap_wall"] == 0


def test_smoke_report_banner(tmp_path):
    run = tmp_path / "run"
    _arm_row(run, "A", "rich_4070", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "rich_4070", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], SMOKE, output)
    text = (output / "pair_report.md").read_text()
    assert text.startswith("smoke, not promotion eligible\n")


def test_notebook_runtime_does_not_include_the_new_markers():
    runtime = notebook_runtime_source()
    assert "_budget_difference_allowed" not in runtime
    assert "_card_sampling_difference_allowed" not in runtime


def _eval_source():
    return (
        "SAMPLE_TASKS = tasks[:2]\n"
        "eval_config = EvalConfig(\n"
        "    results_dir=WORKING_DIR / 'results',\n"
        "    submission_dir=AGENT_DIR,\n"
        "    sandbox='subprocess',\n"
        ")\n"
        "submission_df = None\n"
    )


def test_session_cap_uses_the_larger_arm():
    unequal = _pair_eval_cell(
        _eval_source(),
        {},
        {"A": {"max_time_minutes": 4.5}, "B": {"max_time_minutes": 5.5}},
        None,
    )
    assert "cap_seconds=330.0" in unequal
    assert "cap_seconds=270.0" not in unequal
    assert "budgets = ARM_BUDGETS[label]" in unequal
    swapped = _pair_eval_cell(
        _eval_source(),
        {},
        {"A": {"max_time_minutes": 5.5}, "B": {"max_time_minutes": 4.5}},
        None,
    )
    assert "cap_seconds=330.0" in swapped
    equal = _pair_eval_cell(
        _eval_source(),
        {},
        {"A": {"max_time_minutes": 4.5}, "B": {"max_time_minutes": 4.5}},
        None,
    )
    assert "cap_seconds=270.0" in equal


def test_report_cap_is_the_larger_arm_even_when_b_is_smaller(tmp_path):
    swapped = tmp_path / "swapped.yaml"
    text = DEV.read_text()
    text = text.replace("source: agents/single-v7", "source: ARM_V7")
    text = text.replace("source: agents/single-v8", "source: agents/single-v7")
    text = text.replace("source: ARM_V7", "source: agents/single-v8")
    swapped.write_text(text)
    run = tmp_path / "run"
    _arm_row(run, "A", "rich_4070", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "rich_4070", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], swapped, output)
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["projection"]["arms"]["A"]["cap_seconds"] == 330
    assert saved["projection"]["arms"]["B"]["cap_seconds"] == 330
    sibling = tmp_path / "sibling-report"
    report_from_runs([run], SIBLING, sibling)
    matched = json.loads((sibling / "pair_report.json").read_text())
    assert matched["projection"]["arms"]["A"]["cap_seconds"] == 270
    assert matched["projection"]["arms"]["B"]["cap_seconds"] == 270


def test_check_script_pins_the_repro_from_another_cwd(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "pkg.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "pkg.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "conftest.py").write_text("a = 1\n")
    (repo / "pytest.ini").write_text("[pytest]\n")
    subprocess.run(
        ["git", "add", "conftest.py", "pytest.ini"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    repro = tmp_path / "repro_check.py"
    repro.write_text("raise SystemExit(1)\n")
    pin = tmp_path / "pin.txt"
    script = (CHECK / "skills" / "check" / "scripts" / "run.py").resolve()
    source = script.read_text()
    assert "tempfile.gettempdir" in source
    assert "GEMMA_CHECK_ROOT" in source
    env = os.environ.copy()
    env.update(
        {
            "GEMMA_CHECK_ROOT": str(repo),
            "GEMMA_CHECK_REPRO": str(repro),
            "GEMMA_CHECK_PIN": str(pin),
        }
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    first = subprocess.run(
        [sys.executable, str(script)],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "before: FAIL exit=1" in first.stdout
    assert "[protected]" not in first.stdout
    assert "not a git repository" not in first.stdout
    assert pin.read_text().strip()
    (repo / "pkg.py").write_text("x = 2\n")
    second = subprocess.run(
        [sys.executable, str(script)],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "after: FAIL exit=1" in second.stdout
    assert "weakening" not in second.stdout
    stat = second.stdout.split("git diff --stat:", 1)[1]
    assert "pkg.py" in stat
    assert "empty" not in stat.split("pytest", 1)[0]
    assert "[protected]" in second.stdout
    repro.write_text("raise SystemExit(0)\n")
    third = subprocess.run(
        [sys.executable, str(script)],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "repro changed since pinned (weakening?)" in third.stdout
    assert "after: PASS exit=0" in third.stdout


def _arm_row(root, arm, task_id, steps):
    folder = root / "results" / arm / "r1"
    (folder / "patches").mkdir(parents=True)
    (folder / "traces").mkdir()
    (folder / "patches" / f"{task_id}.patch").write_text("")
    trace = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": arm},
        "steps": [
            {
                "step_id": index,
                "source": "agent",
                "tool_calls": [
                    {
                        "tool_call_id": f"c{index}",
                        "function_name": tool,
                        "arguments": arguments,
                    }
                ],
                "observation": {"results": [{"source_call_id": f"c{index}", "content": output}]},
            }
            for index, (tool, arguments, output) in enumerate(steps, start=1)
        ],
    }
    (folder / "traces" / f"trace_{task_id}.json").write_text(json.dumps(trace))
    (folder / "task_results.jsonl").write_text(
        json.dumps({"instance_id": task_id, "resolved": False}) + "\n"
    )
    with (root / "pair_results.jsonl").open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "arm": arm,
                    "repeat": 1,
                    "task_id": task_id,
                    "resolved": False,
                    "wall_seconds": 10,
                    "hit_cap": {},
                }
            )
            + "\n"
        )
