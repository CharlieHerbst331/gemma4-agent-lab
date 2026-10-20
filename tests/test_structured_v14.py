"""structured-v14 adds a capped map skill and numbered 100-line reads."""

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V131 = Path("agents/structured-v13-1")
V14 = Path("agents/structured-v14")
ARCHIVE = "1fd3227d23da56900cdfca23fc5ff5a73cf9da6a5ffa7d613fbb3b83fc3e9336"
ROLES = ("repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3")
WINDOW = "nl -ba PATH | sed -n 'A,Bp' | head -c 4000, where B is A plus 99"
NARROW = "tail -n 40 | head -c 4000"
STATUS = "get_status never counts as a repeat and is always allowed."
READERS = ("repair_1", "repair_2", "verify_1", "verify_2")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prior
    return module


def _map():
    return _load(V14 / "skills/map/scripts/run.py", "structured_v14_map")


def _prompt(root, name):
    return (root / "sub_agents" / f"{name}.md").read_text()


def _heredoc(text):
    start = text.index("cat > /tmp/line_fix.py <<'EOF'\n")
    end = text.index("\nEOF\n", start)
    return text[start:end]


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_map_stays_inside_the_token_budget_and_is_deterministic(tmp_path):
    module = _map()
    for index in range(200):
        name = f"Class{index:03d}{'X' * 40}"
        _write(
            tmp_path / "pkg" / f"m{index:03d}.py",
            f"class {name}:\n    def run(self):\n        return {index}\n",
        )
    _write(tmp_path / ".secret.py", "class Secret:\n    pass\n")
    _write(tmp_path / ".hidden" / "mod.py", "class Hidden:\n    pass\n")
    _write(tmp_path / "pkg" / ".dot.py", "class Dotted:\n    pass\n")
    _write(tmp_path / "vendor" / "lib.py", "class Vendor:\n    pass\n")
    _write(tmp_path / "third_party" / "lib.py", "class Third:\n    pass\n")
    _write(tmp_path / "tests" / "test_mod.py", "class TestMod:\n    pass\n")
    _write(tmp_path / "docs" / "guide.py", "class Guide:\n    pass\n")
    _write(tmp_path / "docs_src" / "snippet.py", "class Snippet:\n    pass\n")
    first = module.render(tmp_path)
    second = module.render(tmp_path)
    assert first == second
    assert len(first) <= module.CHAR_BUDGET
    assert len(first) / 4 <= 3000
    assert "truncated=1" in first.splitlines()[0]
    assert "Secret" not in first
    assert "Hidden" not in first
    assert "Dotted" not in first
    assert "Vendor" not in first
    assert "Third" not in first
    assert "TestMod" not in first
    assert "Guide" not in first
    assert "Snippet" not in first
    assert "Class000" in first
    started = time.perf_counter()
    module.render(tmp_path)
    assert time.perf_counter() - started < 2.0


def test_map_signatures_and_ignored_args(tmp_path, capsys, monkeypatch):
    module = _map()
    _write(
        tmp_path / "pkg" / "a.py",
        "class Foo:\n"
        "    def bar(self):\n"
        "        return 1\n"
        "    async def baz(self):\n"
        "        return 2\n"
        "\n"
        "def top():\n"
        "    return 3\n",
    )
    text = module.render(tmp_path)
    assert "pkg/a.py: Foo, Foo.bar, async Foo.baz, top" in text
    assert "truncated=0" in text
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setenv("GEMMA_CHECK_ROOT", str(tmp_path))
    assert module.main([]) == 0
    first = capsys.readouterr().out
    assert module.main(["ignored"]) == 0
    second = capsys.readouterr().out
    assert first == second
    assert "Foo.bar" in first


def test_numbered_windows_and_v13_1_guards_stay():
    for name in READERS:
        text = _prompt(V14, name)
        assert WINDOW in text
        assert NARROW in text
        assert "Do not cat a file." in text
        assert "Call read_file with filepath only." not in text
    triage = _prompt(V14, "triage")
    assert triage.index('{"skill_name":"map","file_path":"scripts/run.py"}') < triage.index(
        "Name candidate files and functions from the map before any later role reads."
    )
    assert "Do not pass args." in triage
    for name in ROLES:
        text = _prompt(V14, name)
        parent = _prompt(V131, name)
        assert STATUS in text
        assert "A later identical git diff or git status" in text
        assert "A later repeat of that same call" not in text
        assert STATUS in parent
    for name in ("repair_1", "repair_2", "repair_3", "verify_3"):
        assert _heredoc(_prompt(V14, name)) == _heredoc(_prompt(V131, name))
    for rel in (
        "sub_agents/repair_3.md",
        "sub_agents/verify_3.md",
        "skills/check/SKILL.md",
        "skills/check/scripts/run.py",
        "eval_config.yaml",
    ):
        assert (V14 / rel).read_bytes() == (V131 / rel).read_bytes()
    budgets = load_yaml(V14 / "eval_config.yaml", V14)["evaluation"]
    assert budgets == {
        "timeout_seconds": 300,
        "max_tool_calls": 220,
        "max_time_minutes": 5,
        "max_turns": 320,
    }
    root = load_yaml(V14 / "agent.yaml", V14)
    assert root["name"] == "structured_v14"
    triage_yaml = load_yaml(V14 / "sub_agents/triage.yaml", V14)
    assert triage_yaml["skills"] == ["skills/map"]
    assert triage_yaml["tools"] == []
    assert len(validate(V14)) == 22
    report = lint_candidate(V14)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_map_rank_uses_signatures_the_path_list_misses():
    proxy = _load(Path("scripts/offline_map_hit.py"), "offline_map_hit")
    issue = proxy.tokens("RequestTimeout fires before the client is ready")
    listing = [
        "pkg/before_client.py",
        "pkg/client_ready.py",
        "pkg/models.py",
        "pkg/ready_before.py",
        "pkg/util.py",
    ]
    signatures = {"pkg/models.py": ["RequestTimeout", "fires", "Ready"]}
    baseline = proxy.rank(listing, issue, {})
    mapped = proxy.rank(listing, issue, signatures)
    assert "pkg/models.py" not in baseline
    assert mapped[0] == "pkg/models.py"


def test_archive_matches_v14(tmp_path):
    archive = tmp_path / "structured-v14.zip"
    manifest = pack(V14, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
