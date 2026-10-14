"""structured-v8: unrolled rounds, prompt deadlines, check before submit."""

import re
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate
from gemma_lab.multi_arm import (
    assert_multi_compatible,
    build_multi_schedule,
    load_multi_protocol,
    pair_fits_minimum_budget,
)
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
    pair_fits,
    protocol_schedule,
)

V7 = Path("agents/structured-v7")
V8 = Path("agents/structured-v8")
SINGLE_V8 = Path("agents/single-v8")
CHECK = Path("agents/single-v8-check")
SINGLE_V7 = Path("agents/single-v7")
SINGLE_V9 = Path("agents/single-v9")
DEV_PROTOCOL = Path("configs/protocols/structured-v7-vs-structured-v8-dev13.yaml")
SMOKE_PROTOCOL = Path("configs/protocols/structured-v8-candidate-smoke.yaml")
V9_PROTOCOL = Path("configs/protocols/structured-v8-vs-single-v9-dev13.yaml")
V9_ARCHIVE = "42665a7febbfc63a1811df5fd1f46ade4afd78977cbf6576dd285d9543fdd7f3"
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
SMOKE_SCHEDULE = "50ea6e7f7f7e54213ec78a1cec8edd9fd0398deff22450fae42abd781bba7857"
SMOKE_TASKS = ["rich_4070", "rich_3934", "fastapi_11194", "rich_3938", "fastapi_14262"]
CAP_SECONDS = 300
PROJECTED_MEAN_SECONDS = 255
V7_ARCHIVE = "a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df"
V8_ARCHIVE = "9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e"
SINGLE_V8_ARCHIVE = "6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22"
CHECK_ARCHIVE = "64dc727d78c4189c1db1184e74129290574c7b97816dd91f91d2baa7defe0fb0"
SINGLE_V7_ARCHIVE = "f62c8c0b92bc5bd1fb1015f20e7cbd7a5599d5518d2d59097bf2b40d9f3412b0"
HANDOFF = re.compile(r"By\s+(\d+)\s+elapsed seconds")
CHECK_CALL = '{"skill_name":"check","file_path":"scripts/run.py"}'
MARKERS = [
    "agent.yaml",
    "sub_agents/*",
    "skills/*",
    "prompts/*",
    "eval_config.yaml",
    "sampling.yaml",
    "thinking.yaml",
]


def _role(name):
    return load_yaml(V8 / "sub_agents" / f"{name}.yaml", V8)


def _prompt(name):
    return (V8 / "sub_agents" / f"{name}.md").read_text()


def test_structured_v8_is_three_unrolled_rounds():
    root = load_yaml(V8 / "agent.yaml", V8)
    assert root["agent_class"] == "SequentialAgent"
    assert root["name"] == "structured_v8"
    assert "include_contents" not in root
    assert "max_iterations" not in root
    names = [child["config_path"] for child in root["sub_agents"]]
    assert names == [
        "sub_agents/triage.yaml",
        "sub_agents/repair_1.yaml",
        "sub_agents/verify_1.yaml",
        "sub_agents/repair_2.yaml",
        "sub_agents/verify_2.yaml",
        "sub_agents/repair_3.yaml",
        "sub_agents/verify_3.yaml",
    ]
    assert not (V8 / "sub_agents" / "repair_loop.yaml").exists()
    blob = "\n".join(path.read_text() for path in V8.rglob("*.yaml"))
    assert "LoopAgent" not in blob
    assert "max_llm_calls" not in blob
    assert "callback" not in blob.lower()
    triage = _role("triage")
    assert triage["tools"] == []
    assert triage["include_contents"] == "default"
    assert triage["generate_content_config"]["max_output_tokens"] == 1024
    assert triage["generate_content_config"]["thinking_config"]["thinking_budget"] == 0
    repair_1 = _role("repair_1")
    repair_2 = _role("repair_2")
    repair_3 = _role("repair_3")
    for role in (repair_1, repair_2, repair_3):
        assert "submit_patch" not in role["tools"]
        assert "edit_file" not in role["tools"]
        assert "write_file" not in role["tools"]
        assert role["include_contents"] == "default"
        assert role["generate_content_config"]["thinking_config"] == {
            "include_thoughts": True,
            "thinking_budget": 256,
        }
    assert repair_1["tools"] == [
        "get_status",
        "read_file",
        "run_command",
        "search_similar_code",
        "get_code_neighbors",
        "get_code_subgraph",
    ]
    assert repair_2["tools"] == ["get_status", "read_file", "run_command"]
    assert repair_3["tools"] == ["get_status", "run_command"]
    verify_1, verify_2, verify_3 = _role("verify_1"), _role("verify_2"), _role("verify_3")
    assert verify_1["tools"] == ["get_status", "read_file", "run_command"]
    assert verify_2["tools"] == ["get_status", "read_file", "run_command"]
    assert "submit_patch" not in verify_1["tools"]
    assert "submit_patch" not in verify_2["tools"]
    assert verify_3["tools"] == ["get_status", "run_command", "submit_patch"]
    for role in (verify_1, verify_2, verify_3):
        assert role["skills"] == ["skills/check"]
        assert role["generate_content_config"]["thinking_config"]["thinking_budget"] == 0
        assert role["include_contents"] == "default"
    budgets = load_yaml(V8 / "eval_config.yaml", V8)["evaluation"]
    assert budgets["max_time_minutes"] == 5
    assert type(budgets["max_time_minutes"]) is int
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert budgets["timeout_seconds"] == 300
    skill = V8 / "skills" / "check" / "scripts" / "run.py"
    assert skill.read_bytes() == (V7 / "skills" / "check" / "scripts" / "run.py").read_bytes()
    assert skill.read_bytes() == (CHECK / "skills" / "check" / "scripts" / "run.py").read_bytes()
    assert len(validate(V8)) == 20
    report = lint_candidate(V8)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_prompts_force_handoff_deadlines_without_a_ratio_warning():
    triage = _prompt("triage")
    repair_1 = _prompt("repair_1")
    repair_2 = _prompt("repair_2")
    repair_3 = _prompt("repair_3")
    verify_1 = _prompt("verify_1")
    verify_2 = _prompt("verify_2")
    verify_3 = _prompt("verify_3")
    assert len(triage) == 1937
    assert len(repair_1) == 5417
    assert len(repair_2) == 3019
    assert len(repair_3) == 2376
    assert len(verify_1) == 1685
    assert len(verify_2) == 1316
    assert len(verify_3) == 4303
    assert "under 20 seconds" in triage
    assert "Do not stop with UNCERTAIN" in triage
    joined = "\n".join([triage, repair_1, repair_2, repair_3, verify_1, verify_2, verify_3])
    assert HANDOFF.search(joined) is None
    assert "agent_elapsed_seconds is 180 or more" in repair_1
    assert "agent_elapsed_seconds is 240 or more" in repair_2
    for prompt in (repair_1, repair_2, repair_3, verify_3):
        assert "time_seconds_remaining is under 120" in prompt
        assert "the next call is the heredoc" in prompt
        assert 'ast.parse(s.decode("utf-8"))' in prompt
        assert 'backup = "/tmp/pre_" + path.replace("/", "_")' in prompt
        assert "shutil.copyfile(path, backup)" in prompt
        assert "shutil.copyfile(backup, path)" in prompt
        assert "py_compile.compile(path, doraise=True)" in prompt
        assert "onto no other file" in prompt
        assert "line_fix.bak" not in prompt
        assert "git checkout --" not in prompt
        assert "Never run git checkout" in prompt
        assert "/tmp" in prompt
    assert "Never revert a non-empty source diff" in repair_1
    assert "this role is running again" in repair_1
    assert "Never revert a non-empty source diff" in repair_2
    assert "Never revert a non-empty source diff" in repair_3
    assert "time_seconds_remaining is under 90" in verify_1
    assert "time_seconds_remaining is under 90" in verify_2
    assert "all seven roles run from triage" in verify_3
    assert "call submit_patch anyway" in verify_3
    assert "time_seconds_remaining is under 45" in verify_3
    assert "A cap hit with no diff must not happen." in verify_3
    assert CHECK_CALL in verify_1
    assert CHECK_CALL in verify_2
    assert CHECK_CALL in verify_3
    assert "the flat check is required before submit_patch" in verify_3
    assert "You do not have submit_patch" in verify_1
    assert "You do not have submit_patch" in verify_2
    assert "submit_patch" in verify_3
    for prompt in (repair_1, repair_2, repair_3):
        assert "You do not have submit_patch" in prompt


def test_dev13_and_smoke_protocols_load():
    protocol = load_protocol(DEV_PROTOCOL)
    assert protocol["matched_pair"] is False
    assert protocol["repeats"] == 1
    assert protocol["arms"]["A"]["source"] == "agents/structured-v7"
    assert protocol["arms"]["B"]["source"] == "agents/structured-v8"
    assert protocol["arms"]["A"]["expected_sha256"] == V7_ARCHIVE
    assert protocol["arms"]["B"]["expected_sha256"] == V8_ARCHIVE
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 13
    assert schedule["sha256"] == DEV_SCHEDULE
    assert_arms_compatible(
        inspect_arm(V7),
        inspect_arm(V8),
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a=V7_ARCHIVE,
        sha_b=V8_ARCHIVE,
        matched_pair=False,
    )
    with pytest.raises(ValueError, match="budgets"):
        assert_arms_compatible(
            inspect_arm(V7),
            inspect_arm(V8),
            allow_identical=False,
            allowed_differences=["sampling.yaml", "thinking.yaml"],
            sha_a="a" * 64,
            sha_b="b" * 64,
            matched_pair=False,
        )
    smoke = load_multi_protocol(SMOKE_PROTOCOL)
    assert smoke["purpose"] == "smoke"
    assert smoke["multi_arm"] is True
    assert list(smoke["arms"]) == ["A", "B", "C"]
    assert smoke["_task_ids"] == SMOKE_TASKS
    assert smoke["session_budget_seconds"] == 14400
    built = build_multi_schedule(smoke["_task_ids"], ["A", "B", "C"], repeats=1)
    assert built["sha256"] == SMOKE_SCHEDULE
    assert len(built["entries"]) == 5
    inspected = {label: inspect_arm(smoke["arms"][label]["source"]) for label in "ABC"}
    shas = {label: smoke["arms"][label]["expected_sha256"] for label in "ABC"}
    assert_multi_compatible(inspected, shas, smoke["allowed_differences"], allow_identical=False)
    minimum = pair_fits_minimum_budget(5, 3, 360, extra_elapsed=300)
    assert minimum == 6780
    assert smoke["session_budget_seconds"] >= minimum
    assert smoke["session_budget_seconds"] < WORST_CASE_WARN_SECONDS


def test_structured_v8_vs_single_v9_dev13_protocol():
    protocol = load_protocol(V9_PROTOCOL)
    assert protocol["matched_pair"] is False
    assert protocol["repeats"] == 1
    assert protocol["session_budget_seconds"] == 40200
    assert protocol["arms"]["A"]["source"] == "agents/structured-v8"
    assert protocol["arms"]["B"]["source"] == "agents/single-v9"
    assert protocol["arms"]["A"]["expected_sha256"] == V8_ARCHIVE
    assert protocol["arms"]["B"]["expected_sha256"] == V9_ARCHIVE
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 13
    assert schedule["sha256"] == DEV_SCHEDULE
    assert_arms_compatible(
        inspect_arm(V8),
        inspect_arm(SINGLE_V9),
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a=V8_ARCHIVE,
        sha_b=V9_ARCHIVE,
        matched_pair=False,
    )
    # Session clock is the max arm cap (330 s). extra_elapsed is the tasks.jsonl wait.
    minimum = pair_fits_minimum_budget(13, 2, 330, extra_elapsed=300)
    assert minimum == 9900
    assert protocol["session_budget_seconds"] >= minimum
    # Elapsed before the last task if every earlier arm hit the 330 s session cap:
    # 900 + 300 + 12 * 2 * 330 = 9120. The last pair still fits.
    assert pair_fits(9120, 2, 330, 0, protocol["session_budget_seconds"], 60) is True


def test_runtime_gates_for_cap_and_projected_mean():
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
    # The live warn still uses the cap, so a 300 second cap warns even when the
    # aimed submit point is 255 seconds.
    assert cap_warn > WORST_CASE_WARN_SECONDS


def test_archive_hashes_pin_v8_and_leave_existing_candidates_unchanged(tmp_path):
    expected = {
        V8: V8_ARCHIVE,
        V7: V7_ARCHIVE,
        SINGLE_V8: SINGLE_V8_ARCHIVE,
        CHECK: CHECK_ARCHIVE,
        SINGLE_V7: SINGLE_V7_ARCHIVE,
    }
    for source, digest in expected.items():
        archive = tmp_path / f"{source.name}.zip"
        manifest = pack(source, archive)
        assert manifest["sha256"] == digest
        assert sha256(archive) == digest
