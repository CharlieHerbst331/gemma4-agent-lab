"""single-v4 is single-v3 plus a filepath-only read rule. No other candidate changes."""

import json
from pathlib import Path

from gemma_lab.hygiene import lint_candidate
from gemma_lab.paired import (
    assert_arms_compatible,
    inspect_arm,
    load_protocol,
    protocol_schedule,
    report_from_runs,
)

V3 = Path("agents/single-v3")
V4 = Path("agents/single-v4")
PROTOCOL = Path("configs/protocols/single-v3-vs-single-v4-toolcall-smoke.yaml")
SMOKE_IDS = [
    "fastapi_14786",
    "rich_3934",
    "fastapi_11194",
    "rich_3938",
    "fastapi_14262",
]
ORIGINAL_SMOKE = "31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345"
FULL_SCHEDULE = "e146f4d602957611c53428087c43ba8201d66a9881c4648d8f239f572a23e030"
DEV_SCHEDULE = "629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed"
REVERSED_SMOKE = "0c4e0c31473075ab9cfed9cf305a3ed988e274c9da1d684630136b2b16d18704"
NOTES = "The arms differ only in the prompt read rule and the loop breaker."


def test_single_v4_changes_only_the_prompt():
    names = {path.relative_to(V3).as_posix() for path in V3.rglob("*") if path.is_file()}
    assert names == {path.relative_to(V4).as_posix() for path in V4.rglob("*") if path.is_file()}
    for name in ("agent.yaml", "thinking.yaml", "eval_config.yaml"):
        assert (V3 / name).read_bytes() == (V4 / name).read_bytes()
    prompt = (V4 / "prompts" / "system.md").read_text()
    parent = (V3 / "prompts" / "system.md").read_text()
    assert prompt != parent
    assert len(prompt) <= len(parent)
    assert len(prompt) <= 6656
    for phrase in (
        "Call read_file with filepath only",
        "Do not pass start_line or end_line",
        "sed -n 'A,Bp' path | head -c 4000",
        "sed -n '151,300p' rich/live.py | head -c 4000",
        "grep -n",
        "same first lines twice",
        "start_line: 1",
        "stop re-reading and use sed",
        "If the same tool call fails twice, change the call or the tool",
        "Never run the same command more than twice",
        'python -c "import X; print(X.__version__)"',
        "about 12 counted calls or about 95 seconds",
        "primary rule",
        "cat > /tmp/repro_check.py <<'EOF'",
        "never write repro*.py in /workspace or the repo",
    ):
        assert phrase in prompt
    assert prompt.count("If the same tool call fails twice, change the call or the tool") == 1
    for banned in ("run_skill_script", "skill_name", "SKILL.md", "scripts/check.py"):
        assert banned not in prompt
    assert prompt.count("check.py") == prompt.count("repro_check.py")
    for pattern in ('"start_line"', '"end_line"', "start_line=", "end_line="):
        assert pattern not in prompt
    report = lint_candidate(V4)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_smoke_protocol_keeps_the_original_task_order():
    protocol = load_protocol(PROTOCOL)
    assert protocol["purpose"] == "smoke"
    assert protocol["repeats"] == 1
    assert protocol["_task_ids"] == SMOKE_IDS
    assert "matched_pair" not in protocol
    assert protocol["notes"] == NOTES
    assert protocol["arms"]["A"]["source"] == "agents/single-v3"
    assert protocol["arms"]["B"]["source"] == "agents/single-v4"
    schedule = protocol_schedule(protocol)
    assert len(schedule["entries"]) == 5
    assert schedule["sha256"] == ORIGINAL_SMOKE
    frozen = {
        "v5-vs-single-v1.yaml": FULL_SCHEDULE,
        "v6-vs-single-v2.yaml": FULL_SCHEDULE,
        "v6-vs-single-v3.yaml": DEV_SCHEDULE,
        "v6-vs-single-v2-toolcall-smoke.yaml": ORIGINAL_SMOKE,
        "single-v2-vs-single-v3-toolcall-smoke.yaml": REVERSED_SMOKE,
    }
    for name, digest in frozen.items():
        loaded = load_protocol(Path("configs/protocols") / name)
        assert protocol_schedule(loaded)["sha256"] == digest
    arms = {label: inspect_arm(spec["source"]) for label, spec in protocol["arms"].items()}
    assert_arms_compatible(
        arms["A"],
        arms["B"],
        allow_identical=False,
        allowed_differences=protocol["allowed_differences"],
        sha_a="a" * 64,
        sha_b="b" * 64,
        matched_pair=True,
    )


def test_smoke_report_prints_the_banner_and_the_note(tmp_path):
    run = tmp_path / "run"
    _arm_row(run, "A", "fastapi_14786", [("submit_patch", {}, "ok")])
    _arm_row(run, "B", "fastapi_14786", [("submit_patch", {}, "ok")])
    output = tmp_path / "report"
    report_from_runs([run], PROTOCOL, output)
    text = (output / "pair_report.md").read_text()
    assert text.startswith("smoke, not promotion eligible\n")
    assert NOTES in "\n".join(text.splitlines()[:6])
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["purpose"] == "smoke"
    assert saved["notes"] == NOTES
    assert "matched_pair" not in saved


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
