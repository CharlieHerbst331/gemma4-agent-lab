"""structured-v13 keeps v8's cap and adds a late soft deadline."""

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate
from gemma_lab.operations import (
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    PROJECTED_HIDDEN_TASKS,
    PROJECTED_LOAD_LIMIT_SECONDS,
    PROJECTED_PUBLIC_TASKS,
    PROJECTED_RUNTIME_LIMIT_SECONDS,
    WORST_CASE_WARN_SECONDS,
)

V8 = Path("agents/structured-v8")
V13 = Path("agents/structured-v13")
V8_ARCHIVE = "9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e"
V13_ARCHIVE = "bcae1a1932f4b59547615bdcda69a437629d88fd65f946b48fa3154334f7e7d7"
SMOKE_WALLS = {
    "rich_4070": 303.5,
    "rich_3934": 307.6,
    "rich_3938": 302.5,
    "fastapi_11194": 248.3,
    "rich_3454": 304.7,
}
SAME_AS_V8 = (
    "sub_agents/thinking.yaml",
    "sub_agents/repair_thinking.yaml",
    "sub_agents/repair_1.yaml",
    "sub_agents/repair_2.yaml",
    "sub_agents/repair_3.yaml",
    "sub_agents/verify_1.yaml",
    "sub_agents/verify_2.yaml",
    "sub_agents/verify_3.yaml",
    "sub_agents/triage.md",
    "sub_agents/triage.yaml",
    "skills/check/SKILL.md",
    "skills/check/scripts/run.py",
)


def _prompt(name):
    return (V13 / "sub_agents" / f"{name}.md").read_text()


def _heredoc(text):
    start = text.index("cat > /tmp/line_fix.py <<'EOF'\n")
    end = text.index("\nEOF\n", start)
    return text[start:end]


def test_smoke5_mean_is_the_cap_not_a_long_outlier():
    walls = list(SMOKE_WALLS.values())
    assert sum(walls) == 1466.6
    assert round(sum(walls) / len(walls), 2) == 293.32
    ordered = sorted(walls)
    assert ordered[len(ordered) // 2] == 303.5
    assert sum(wall >= 300 for wall in walls) == 4
    without_short = [wall for wall in walls if wall != 248.3]
    assert round(sum(without_short) / len(without_short), 3) == 304.575
    assert sum(without_short) / len(without_short) > sum(walls) / len(walls)


def test_v13_keeps_the_v8_cap_and_the_late_deadline():
    root = load_yaml(V13 / "agent.yaml", V13)
    assert root["name"] == "structured_v13"
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
    budgets = load_yaml(V13 / "eval_config.yaml", V13)["evaluation"]
    parent = load_yaml(V8 / "eval_config.yaml", V8)["evaluation"]
    assert budgets == {
        "timeout_seconds": 300,
        "max_tool_calls": 220,
        "max_time_minutes": 5,
        "max_turns": 320,
    }
    assert budgets == parent
    assert type(budgets["max_time_minutes"]) is int
    for rel in SAME_AS_V8:
        assert (V13 / rel).read_bytes() == (V8 / rel).read_bytes()
    blob = "\n".join(path.read_text() for path in V13.rglob("*") if path.is_file())
    assert "ParallelAgent" not in blob
    assert "[elapsed" not in blob
    assert "edit-by-110" not in blob
    for name in ("repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3"):
        text = _prompt(name)
        assert "about 240 or more and git diff has a source edit" in text
        assert "Do not paste source lines" in text
    for name in ("repair_1", "repair_2", "verify_1"):
        assert "already appears in the history" in _prompt(name)
    repair_1 = _prompt("repair_1")
    assert "time_seconds_remaining is under 120 and git diff is empty" not in repair_1
    assert "An empty diff does not stop this round" in repair_1
    assert "py_compile.compile(path, doraise=True)" in repair_1
    for name in ("repair_1", "repair_2", "repair_3", "verify_3"):
        assert _heredoc(_prompt(name)) == _heredoc((V8 / "sub_agents" / f"{name}.md").read_text())
    assert len(validate(V13)) == 20
    report = lint_candidate(V13)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_gate_passes_near_255_and_a_252_second_cap_is_not_used():
    overhead = DEFAULT_SCORER_OVERHEAD_SECONDS
    assert overhead == 70
    assert PROJECTED_HIDDEN_TASKS * (260 + overhead) == PROJECTED_RUNTIME_LIMIT_SECONDS
    assert PROJECTED_HIDDEN_TASKS * (255 + overhead) == 39000
    assert 900 + PROJECTED_PUBLIC_TASKS * 255 == 33795
    assert 33795 <= PROJECTED_LOAD_LIMIT_SECONDS
    # Largest integer cap whose +8 s overrun still passes the 120-task block.
    assert PROJECTED_HIDDEN_TASKS * (252 + 8 + overhead) == 39600
    assert PROJECTED_HIDDEN_TASKS * (253 + 8 + overhead) == 39720
    assert 39720 > PROJECTED_RUNTIME_LIMIT_SECONDS
    assert (38880 - 900) / PROJECTED_PUBLIC_TASKS > 294
    # Soft deadline alone leaves the two no-edit cap hits in place.
    soft_only = (303.5 + 240 + 302.5 + 248.3 + 240) / 5
    assert round(soft_only, 2) == 266.86
    assert PROJECTED_HIDDEN_TASKS * (soft_only + overhead) > PROJECTED_RUNTIME_LIMIT_SECONDS
    # No-reread plus the soft deadline is the projection that passes.
    shortened = (255 + 240 + 255 + 248.3 + 240) / 5
    assert round(shortened, 2) == 247.66
    assert PROJECTED_HIDDEN_TASKS * (shortened + overhead) <= PROJECTED_RUNTIME_LIMIT_SECONDS
    assert 900 + PROJECTED_PUBLIC_TASKS * shortened <= PROJECTED_LOAD_LIMIT_SECONDS
    assert 900 + PROJECTED_PUBLIC_TASKS * (300 + overhead) == 48630
    assert 48630 > WORST_CASE_WARN_SECONDS


def test_archive_matches_v13_and_leaves_v8_unchanged(tmp_path):
    archive = tmp_path / "structured-v13.zip"
    manifest = pack(V13, archive)
    assert manifest["sha256"] == V13_ARCHIVE
    assert sha256(archive) == V13_ARCHIVE
    assert pack(V8, tmp_path / "structured-v8.zip")["sha256"] == V8_ARCHIVE


def _v10_helpers():
    spec = importlib.util.spec_from_file_location(
        "structured_v10_compile",
        Path("tests/test_structured_v10.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compiles_on_adk_submission_0_2_12_and_0_2_13(tmp_path):
    helpers = _v10_helpers()
    script = tmp_path / "compile_v13.py"
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
                limits=SubmissionLimits(
                    allowed_file_extensions=frozenset(
                        {".yaml", ".yml", ".md", ".txt", ".py", ".json"}
                    )
                ),
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
            str(V13.resolve()),
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
        [sys.executable, str(script), str(V13.resolve())],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [str(helpers._schema_tree("0.2.11", 1)), str(helpers._ensure_adk())]
            ),
            "PYTHONWARNINGS": "ignore",
        },
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "greater than or equal to 1" in (rejected.stderr + rejected.stdout)
