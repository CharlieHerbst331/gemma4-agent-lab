"""structured-v9 keeps v8's clock and drops full history from the handoff."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V8 = Path("agents/structured-v8")
V9 = Path("agents/structured-v9")
V9_ARCHIVE = "209bd43ed52731813ecc4fc8d40edea186bd1af2a6f00e18acf5aae7809b18a5"
V8_ARCHIVE = "9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e"
SINGLE_V9_ARCHIVE = "42665a7febbfc63a1811df5fd1f46ade4afd78977cbf6576dd285d9543fdd7f3"
V7_ARCHIVE = "a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df"
CHECK_CALL = '{"skill_name":"check","file_path":"scripts/run.py"}'
LOCATE_CALL = '{"skill_name":"locate","file_path":"scripts/run.py","args":["literal text"]}'
SUMMARIES = (
    "triage_summary",
    "repair_1_summary",
    "verify_1_summary",
    "repair_2_summary",
    "verify_2_summary",
    "repair_3_summary",
)


def _role(name):
    return load_yaml(V9 / "sub_agents" / f"{name}.yaml", V9)


def _prompt(name):
    return (V9 / "sub_agents" / f"{name}.md").read_text()


def _load(path, name):
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.dont_write_bytecode = previous
    return module


def test_structured_v9_keeps_v8_shape_and_drops_history():
    root = load_yaml(V9 / "agent.yaml", V9)
    parent = load_yaml(V8 / "agent.yaml", V8)
    assert root["agent_class"] == "SequentialAgent"
    assert root["name"] == "structured_v9"
    assert [child["config_path"] for child in root["sub_agents"]] == [
        child["config_path"] for child in parent["sub_agents"]
    ]
    assert (V9 / "eval_config.yaml").read_bytes() == (V8 / "eval_config.yaml").read_bytes()
    assert (V9 / "sub_agents" / "thinking.yaml").read_bytes() == (
        V8 / "sub_agents" / "thinking.yaml"
    ).read_bytes()
    assert (V9 / "sub_agents" / "repair_thinking.yaml").read_bytes() == (
        V8 / "sub_agents" / "repair_thinking.yaml"
    ).read_bytes()
    budgets = load_yaml(V9 / "eval_config.yaml", V9)["evaluation"]
    assert budgets["max_time_minutes"] == 5
    assert budgets["max_tool_calls"] == 220
    assert budgets["max_turns"] == 320
    assert budgets["timeout_seconds"] == 300
    names = [
        "triage",
        "repair_1",
        "verify_1",
        "repair_2",
        "verify_2",
        "repair_3",
        "verify_3",
    ]
    for name in names:
        role = _role(name)
        assert role["include_contents"] == "none"
        assert "read_file" not in role["tools"]
        assert role["generate_content_config"]["temperature"] == 1.0
        assert role["generate_content_config"]["top_p"] == 0.95
        assert role["generate_content_config"]["top_k"] == 64
    assert _role("triage")["tools"] == []
    assert _role("triage")["output_key"] == "triage_summary"
    assert _role("repair_1")["tools"] == ["get_status", "run_command"]
    assert _role("repair_1")["skills"] == ["skills/locate"]
    assert _role("repair_1")["output_key"] == "repair_1_summary"
    assert "search_similar_code" not in _role("repair_1")["tools"]
    assert _role("repair_2")["skills"] == ["skills/locate"]
    assert _role("repair_3")["tools"] == ["get_status", "run_command"]
    assert "skills" not in _role("repair_3")
    assert _role("verify_3")["tools"] == ["get_status", "run_command", "submit_patch"]
    assert "output_key" not in _role("verify_3")
    for name in ("verify_1", "verify_2", "verify_3"):
        assert _role(name)["skills"] == ["skills/check"]
    repair = _role("repair_1")["generate_content_config"]["thinking_config"]
    assert repair["thinking_budget"] == 256
    assert repair["include_thoughts"] is True
    assert _role("verify_3")["generate_content_config"]["thinking_config"]["thinking_budget"] == 0
    report = lint_candidate(V9)
    assert report["gate"] == "pass", report["findings"]
    assert len(validate(V9)) == 22


def test_prompts_use_optional_handoffs_and_sed_windows():
    prompts = {
        name: _prompt(name)
        for name in (
            "triage",
            "repair_1",
            "verify_1",
            "repair_2",
            "verify_2",
            "repair_3",
            "verify_3",
        )
    }
    previous = {
        "repair_1": "triage_summary",
        "verify_1": "repair_1_summary",
        "repair_2": "verify_1_summary",
        "verify_2": "repair_2_summary",
        "repair_3": "verify_2_summary",
        "verify_3": "repair_3_summary",
    }
    for name, text in prompts.items():
        assert "{problem_description?}" in text
        assert "{problem_description}" not in text.replace("{problem_description?}", "")
        assert "{hints?}" in text
        omitted = previous.get(name)
        for key in SUMMARIES:
            token = "{" + key + "?}"
            if key == omitted:
                assert token not in text
            else:
                assert token in text
        assert "Earlier roles' tool results are not in this turn." in text
        assert "Call read_file" not in text
        assert "git checkout --" not in text
    assert "under 20 seconds" in prompts["triage"]
    assert "Do not stop with UNCERTAIN" in prompts["triage"]
    for name in ("repair_1", "repair_2", "repair_3", "verify_3"):
        text = prompts[name]
        assert "time_seconds_remaining is under 120" in text
        assert "the next call is the heredoc" in text
        assert 'backup = "/tmp/pre_" + path.replace("/", "_")' in text
        assert "shutil.copyfile(backup, path)" in text
        assert "onto no other file" in text
        assert "Never run git checkout" in text
        assert "line_fix.bak" not in text
    assert "sed -n 'A,Bp'" in prompts["repair_1"]
    assert "at most 40 lines" in prompts["repair_1"]
    assert "Do not cat a file" in prompts["repair_1"]
    assert LOCATE_CALL in prompts["repair_1"]
    assert LOCATE_CALL in prompts["repair_2"]
    assert "this role is running again" in prompts["repair_1"]
    assert "Never revert a non-empty source diff" in prompts["repair_1"]
    assert "Never revert a non-empty source diff" in prompts["repair_2"]
    assert "Never revert a non-empty source diff" in prompts["repair_3"]
    assert "time_seconds_remaining is under 90" in prompts["verify_1"]
    assert "time_seconds_remaining is under 90" in prompts["verify_2"]
    assert "git diff" in prompts["verify_1"]
    assert CHECK_CALL in prompts["verify_1"]
    assert CHECK_CALL in prompts["verify_3"]
    assert "all seven roles run from triage" in prompts["verify_3"]
    assert "call submit_patch anyway" in prompts["verify_3"]
    assert "A cap hit with no diff must not happen." in prompts["verify_3"]
    assert "You do not have read_file" in prompts["repair_1"]
    joined = "\n".join(prompts.values())
    assert "By 180 elapsed seconds" not in joined
    assert "By 240 elapsed seconds" not in joined


def test_locate_prints_a_window_and_rejects_extra_args(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    source = repo / "pkg.py"
    body = "\n".join(f"line {index}" for index in range(1, 30))
    source.write_text(body + "\nneedle here\n" + "tail\n")
    script = (V9 / "skills" / "locate" / "scripts" / "run.py").resolve()
    env = os.environ.copy()
    env["GEMMA_CHECK_ROOT"] = str(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    found = subprocess.run(
        [sys.executable, str(script), "needle"],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "pkg.py:30" in found.stdout
    assert "30|needle here" in found.stdout
    assert "29|line 29" in found.stdout
    assert "line 1\n" not in found.stdout
    literal = subprocess.run(
        [sys.executable, str(script), "line.1"],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0 hit(s)" in literal.stdout
    (repo / ".adk_exec_wrapper.py").write_text("wrapper-only-needle\n")
    hidden = subprocess.run(
        [sys.executable, str(script), "wrapper-only-needle"],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0 hit(s)" in hidden.stdout
    assert ".adk_exec_wrapper.py" not in hidden.stdout
    rejected = subprocess.run(
        [sys.executable, str(script), "one", "two"],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert LOCATE_CALL in rejected.stdout
    module = _load(script, "locate_run")
    many = "\n".join(f"hit {index} needle" for index in range(20))
    text = module.render("needle", [("a.py", 0, [many])] * 5, True)
    assert "more hits omitted" in text
    assert len(text) <= module.MAX_CHARS + len("\n[truncated]")
    assert module.cap("x" * (module.MAX_CHARS + 20)).endswith("[truncated]")


def test_check_compiles_and_reports_a_non_empty_diff(tmp_path):
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
    (repo / "pkg.py").write_text("def broken(\n")
    script = (V9 / "skills" / "check" / "scripts" / "run.py").resolve()
    env = os.environ.copy()
    env["GEMMA_CHECK_ROOT"] = str(repo)
    env["GEMMA_CHECK_REPRO"] = str(tmp_path / "missing_repro.py")
    env["GEMMA_CHECK_PIN"] = str(tmp_path / "pin.txt")
    (tmp_path / "elsewhere").mkdir()
    ran = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path / "elsewhere",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "diff: non-empty" in ran.stdout
    assert "py_compile pkg.py FAIL" in ran.stdout
    assert "tempfile.gettempdir" in script.read_text()
    assert "GEMMA_CHECK_ROOT" in script.read_text()
    assert len(ran.stdout) <= 1600
    (repo / "pkg.py").write_text("x = 1\n")
    (repo / "conftest.py").write_text("a = 1\n")
    (repo / "pytest.ini").write_text("[pytest]\n")
    harness = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path / "elsewhere",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "diff: empty" in harness.stdout
    assert "[protected]" not in harness.stdout
    module = _load(script, "check_run")
    assert module._cap("y" * 2000).endswith("[truncated]")
    assert len(module._cap("y" * 2000)) < 2000


def test_archive_pins_v9_and_leaves_v8_unchanged(tmp_path):
    archive = tmp_path / "structured-v9.zip"
    manifest = pack(V9, archive)
    assert manifest["sha256"] == V9_ARCHIVE
    assert sha256(archive) == V9_ARCHIVE
    parent = tmp_path / "structured-v8.zip"
    assert pack(V8, parent)["sha256"] == V8_ARCHIVE
    assert pack(Path("agents/single-v9"), tmp_path / "single-v9.zip")["sha256"] == SINGLE_V9_ARCHIVE
    v7 = pack(Path("agents/structured-v7"), tmp_path / "structured-v7.zip")
    assert v7["sha256"] == V7_ARCHIVE
