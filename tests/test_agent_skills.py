"""Exercise submitted helpers on trusted synthetic repos, never competition snapshots."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gemma_lab.bundle import load_yaml, validate


def skill_candidates():
    """Every agent that ships skills, each from its own directory."""
    found = []
    for path in sorted(item for item in Path("agents").iterdir() if item.is_dir()):
        skills = path / "skills"
        needed = [
            skills / "task-memory/scripts/ledger.py",
            skills / "source-lookup/scripts/lookup.py",
            skills / "verify-patch/scripts/check.py",
        ]
        if all(item.is_file() for item in needed):
            found.append(path.resolve())
    if len(found) < 2:
        raise RuntimeError("expected more than one candidate with its own skills directory")
    return found


def module(candidate, skill, filename):
    path = candidate / "skills" / skill / "scripts" / filename
    spec = importlib.util.spec_from_file_location(
        f"{candidate.name}_{skill.replace('-', '_')}_{filename[:-3]}", path
    )
    result = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(result)
    finally:
        sys.dont_write_bytecode = prior
    return result


CANDIDATE = None
memory = None
lookup = None
check = None


@pytest.fixture(params=skill_candidates(), ids=lambda path: path.name)
def candidate(request):
    return request.param


@pytest.fixture(autouse=True)
def _bind_candidate_skills(candidate, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "CANDIDATE", candidate)
    monkeypatch.setattr(
        sys.modules[__name__], "memory", module(candidate, "task-memory", "ledger.py")
    )
    monkeypatch.setattr(
        sys.modules[__name__], "lookup", module(candidate, "source-lookup", "lookup.py")
    )
    monkeypatch.setattr(
        sys.modules[__name__], "check", module(candidate, "verify-patch", "check.py")
    )


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def workspace(tmp_path):
    root, scratch = tmp_path / "workspace", tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg/__init__.py").write_text("VALUE = 1\n")
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "conftest.py").write_text("# baseline config\n")
    (root / "tests").mkdir()
    (root / "tests/test_pkg.py").write_text("def test_value():\n    assert True\n")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Skill fixture")
    git(root, "config", "user.email", "fixture@example.test")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture baseline")
    git(root, "tag", "_swegemma_baseline")
    return root, scratch


def test_triage_has_no_exploration_or_skill_loop():
    config = load_yaml(CANDIDATE / "sub_agents/triage.yaml", CANDIDATE)
    assert config["tools"] == []
    assert not config.get("skills") and not config.get("sub_agents")
    for name in ["repair", "verify"]:
        role = load_yaml(CANDIDATE / f"sub_agents/{name}.yaml", CANDIDATE)
        assert role["include_contents"] == "none"
    assert len(validate(CANDIDATE)) >= 14


def test_memory_roundtrip_dedup_and_baseline_isolation(workspace):
    root, scratch = workspace
    result = memory.update(
        root,
        scratch,
        "update",
        {
            "hypothesis": "VALUE mishandles zero",
            "evidence": ["pkg:1", "pkg:1"],
            "rejected": ["Unrelated callers"],
            "navigation": ["query-1"],
        },
    )
    assert result["evidence"] == ["pkg:1"]
    assert memory.update(root, scratch, "read")["rejected"] == ["Unrelated callers"]
    (root / "pkg/__init__.py").write_text("VALUE = 2\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "new task baseline")
    assert memory.update(root, scratch, "read")["hypothesis"] == ""
    assert not (root / "gemma-task-memory.json").exists()


def test_invalid_memory_does_not_destroy_evidence(workspace):
    root, scratch = workspace
    memory.update(root, scratch, "update", {"hypothesis": "original"})
    original = (scratch / "gemma-task-memory.json").read_bytes()
    for packet in [{"reasoning": "essay"}, {"evidence": ["x"] * 9}, {"hypothesis": "x" * 401}]:
        with pytest.raises(ValueError):
            memory.update(root, scratch, "update", packet)
    assert (scratch / "gemma-task-memory.json").read_bytes() == original


def test_memory_rejects_workspace_scratch_and_symlink(workspace):
    root, scratch = workspace
    with pytest.raises(ValueError):
        memory.update(root, root, "update", {})
    (scratch / "gemma-task-memory.json").symlink_to(root / "pkg/__init__.py")
    with pytest.raises(ValueError):
        memory.update(root, scratch, "read")


def test_literal_lookup_windows_and_bounded_output(workspace):
    root, _ = workspace
    (root / "pkg/big.py").write_text(
        "VALUE = 1 # " + "x" * 250 + "\n" + ("VALUE = 2 # " + "y" * 250 + "\n") * 100
    )
    hits = lookup.lookup(root, ["VALUE"], ["pkg"])
    assert hits["hits"] and hits["bounded"]
    assert len(json.dumps(hits)) <= 4000
    window = lookup.lookup(root, filepath="pkg/big.py", start=1, end=80)
    assert window["truncated"]
    assert window["end_line"] == len(window["content"].splitlines())
    assert window["content"].startswith("1: VALUE")


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", ".git/config"])
def test_lookup_rejects_forbidden_paths(workspace, path):
    root, _ = workspace
    with pytest.raises(ValueError):
        lookup.lookup(root, filepath=path)


def test_lookup_rejects_symlink_and_invalid_ranges(workspace, tmp_path):
    root, _ = workspace
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 1\n")
    (root / "pkg/link.py").symlink_to(outside)
    with pytest.raises(ValueError):
        lookup.lookup(root, filepath="pkg/link.py")
    assert all(h["path"] != "pkg/link.py" for h in lookup.lookup(root, ["SECRET"], ["pkg"])["hits"])
    for start, end in [(0, 1), (5, 2), (1, 81)]:
        with pytest.raises(ValueError):
            lookup.lookup(root, filepath="pkg/__init__.py", start=start, end=end)


def test_same_repro_before_after_and_freshness(workspace):
    root, scratch = workspace
    code = (
        "import pkg\nassert pkg.VALUE == 2\nassert pkg.__file__.startswith("
        + repr(str(root))
        + ")\n"
    )
    before = check.repro(root, scratch, "before", code)
    assert not before["passed"] and before["exit_code"] != 0 and not before["blocked"]
    (root / "pkg/__init__.py").write_text("VALUE = 2\n")
    after = check.repro(root, scratch, "after")
    assert after["passed"] and before["repro_sha256"] == after["repro_sha256"]
    audit = check.audit(root)
    assert audit["passed"] and not audit["behavior_verified"]
    assert audit["patch_sha256"] == after["patch_sha256"]
    (root / "pkg/__init__.py").write_text("VALUE = 3\n")
    assert check.audit(root)["patch_sha256"] != after["patch_sha256"]
    assert not any(p.name.startswith("gemma-agent") for p in root.iterdir())


@pytest.mark.parametrize(
    "code",
    [
        'print("passed")',
        'try:\n    assert False\nexcept AssertionError:\n    print("passed")',
        'try:\n    assert False\nexcept Exception:\n    print("passed")',
        "try:\n    assert False\nexcept:\n    pass",
    ],
)
def test_repro_rejects_false_pass_patterns(workspace, code):
    root, scratch = workspace
    with pytest.raises(ValueError):
        check.repro(root, scratch, "before", code)
    assert not (scratch / "gemma-agent-repro.py").exists()


def test_import_failure_timeout_and_unicode_logs(workspace):
    root, scratch = workspace
    blocked = check.repro(
        root, scratch, "before", "import unavailable_fixture_dep_xyz\nassert True\n"
    )
    assert blocked["blocked"] and not blocked["passed"]
    timed = check.repro(root, scratch, "probe", "while True:\n    pass\nassert True\n", timeout=1)
    assert timed["timed_out"] and not timed["passed"]
    unicode = check.repro(root, scratch, "probe", 'print("é" * 10000)\nassert True\n')
    assert unicode["passed"] and len(unicode["output_tail"]) <= 2400


def test_repro_cannot_pass_after_mutating_the_patch(workspace):
    root, scratch = workspace
    result = check.repro(
        root,
        scratch,
        "before",
        "from pathlib import Path\n"
        'Path("pkg/__init__.py").write_text("VALUE = 9\\n")\nassert True\n',
    )
    assert result["workspace_changed"] and not result["passed"]


def test_audit_flags_protected_tests_scratch_syntax_and_whitespace(workspace):
    root, _ = workspace
    assert check.audit(root)["passed"]
    (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    (root / "tests/test_pkg.py").write_text("assert True\n")
    (root / "pkg/__init__.py").write_text("VALUE = (  \n")
    (root / "reproduce_issue.py").write_text('print("debug")\n')
    result = check.audit(root)
    assert not result["passed"]
    assert set(result["forbidden"]) == {"pytest.ini", "tests/test_pkg.py"}
    assert result["syntax_errors"] and result["diff_check_exit_code"] != 0
    assert result["untracked"] == ["reproduce_issue.py"]


def test_audit_exempts_only_live_official_wrapper(workspace, monkeypatch):
    root, _ = workspace
    current, leftover = root / ".adk_exec_1234abcd.py", root / ".adk_exec_deadbeef.py"
    current.write_text("# executing wrapper\n")
    monkeypatch.setattr(sys, "orig_argv", ["python3", str(current)])
    assert check.audit(root)["passed"]
    leftover.write_text("# leftover wrapper\n")
    assert check.audit(root)["untracked"] == [leftover.name]


def test_skill_cli_discovers_workspace_from_sandbox_env_not_materialization_cwd(
    workspace, tmp_path
):
    root, scratch = workspace
    materialized = tmp_path / "skill-files"
    materialized.mkdir()
    environment = dict(os.environ, PWD=str(root), TEST_TMPDIR=str(scratch))
    script = CANDIDATE / "skills/task-memory/scripts/ledger.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--action",
            "update",
            "--packet",
            '{"hypothesis":"from sandbox"}',
        ],
        cwd=materialized,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["memory"]["hypothesis"] == "from sandbox"
    assert (scratch / "gemma-task-memory.json").exists()
    assert list(materialized.iterdir()) == []


def test_concurrent_memory_updates_preserve_disjoint_evidence(workspace):
    from concurrent.futures import ThreadPoolExecutor

    root, scratch = workspace
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(memory.update, root, scratch, "update", {"hypothesis": "cause"})
        right = pool.submit(memory.update, root, scratch, "update", {"evidence": ["pkg:1"]})
        left.result()
        right.result()
    state = memory.update(root, scratch, "read")
    assert state["hypothesis"] == "cause" and state["evidence"] == ["pkg:1"]


def test_memory_read_rejects_manually_corrupted_context(workspace):
    root, scratch = workspace
    memory.update(root, scratch, "update", {})
    path = scratch / "gemma-task-memory.json"
    state = json.loads(path.read_text())
    state["hypothesis"] = "x" * 2000
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="stored evidence"):
        memory.update(root, scratch, "read")


def test_repro_log_has_a_hard_file_size_limit(workspace):
    root, scratch = workspace
    result = check.repro(root, scratch, "probe", 'print("x" * 2000000)\nassert True\n')
    assert not result["passed"]
    assert (scratch / "gemma-agent-repro.log").stat().st_size <= 1024 * 1024


def test_flat_skill_arguments_avoid_nested_json_escaping(workspace):
    root, scratch = workspace
    environment = dict(os.environ, PWD=str(root), TEST_TMPDIR=str(scratch))
    ledger = CANDIDATE / "skills/task-memory/scripts/ledger.py"
    result = subprocess.run(
        [
            sys.executable,
            str(ledger),
            "--action",
            "update",
            "--hypothesis",
            "VALUE",
            "--evidence",
            "pkg:1",
            "--evidence",
            "caller:2",
        ],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["memory"]["evidence"] == ["pkg:1", "caller:2"]
    navigation = CANDIDATE / "skills/source-lookup/scripts/lookup.py"
    result = subprocess.run(
        [sys.executable, str(navigation), "--term", "VALUE", "--scope", "pkg"],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["hits"][0]["path"] == "pkg/__init__.py"


def test_explicit_scope_can_search_legitimate_data_source(workspace):
    root, _ = workspace
    (root / "data").mkdir()
    (root / "data/parser.py").write_text("VALUE = 7\n")
    assert not any(h["path"].startswith("data/") for h in lookup.lookup(root, ["VALUE"])["hits"])
    assert lookup.lookup(root, ["VALUE"], ["data"])["hits"][0]["path"] == "data/parser.py"


def test_skill_modules_load_from_this_candidates_directory():
    assert Path(memory.__file__).resolve().is_relative_to(CANDIDATE / "skills" / "task-memory")
    assert Path(lookup.__file__).resolve().is_relative_to(CANDIDATE / "skills" / "source-lookup")
    assert Path(check.__file__).resolve().is_relative_to(CANDIDATE / "skills" / "verify-patch")
    ledgers = [path / "skills/task-memory/scripts/ledger.py" for path in skill_candidates()]
    assert len({item.resolve() for item in ledgers}) == len(ledgers)
    assert {path.name for path in skill_candidates()} >= {"structured-v4", "structured-v4-10m"}


def test_baseline_contract_rejects_changed_assertions_but_allows_extra_probe(workspace):
    root, scratch = workspace
    check.repro(root, scratch, "before", "import pkg\nassert pkg.VALUE == 2\n")
    original = (scratch / "gemma-agent-repro.py").read_text()
    with pytest.raises(ValueError, match="repro changed"):
        check.repro(root, scratch, "after", "assert True\n")
    assert (scratch / "gemma-agent-repro.py").read_text() == original
    (scratch / "gemma-agent-repro.py").write_text("assert True\n")
    with pytest.raises(ValueError, match="repro changed"):
        check.repro(root, scratch, "verify")
    probe = check.repro(root, scratch, "probe", "assert 2 + 2 == 4\n")
    assert probe["passed"] and probe["path"].endswith("gemma-agent-probe.py")
