"""structured-v13-1 exempts opening git diff and git status, and never bans get_status."""

from pathlib import Path

from gemma_lab.bundle import load_yaml, pack, validate
from gemma_lab.common import sha256
from gemma_lab.hygiene import lint_candidate

V13 = Path("agents/structured-v13")
V131 = Path("agents/structured-v13-1")
ARCHIVE = "74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe"
ROLES = ("repair_1", "repair_2", "repair_3", "verify_1", "verify_2", "verify_3")
STATUS = "get_status never counts as a repeat and is always allowed."
OPENING = (
    "The first git diff and the first git status when this role starts are allowed "
    "even if an earlier role made that same call and no source edit has happened since."
)
LATER = (
    "A later identical git diff or git status in this role, with no source edit since, "
    "is still banned."
)
BLOCK = f"Opening calls. {STATUS} {OPENING} {LATER}\n\n"


def _prompt(root, name):
    return (root / "sub_agents" / f"{name}.md").read_text()


def test_get_status_is_never_a_repeat_and_diff_status_keep_the_exemption():
    for name in ROLES:
        text = _prompt(V131, name)
        parent = _prompt(V13, name)
        assert text.count(STATUS) == 1
        assert text.count(OPENING) == 1
        assert text.count(LATER) == 1
        assert text.index(STATUS) < text.index(OPENING) < text.index(LATER)
        assert "Opening calls. " + STATUS in text
        assert "git diff" in OPENING and "git status" in OPENING
        assert "git diff" in LATER and "git status" in LATER
        assert "get_status" not in LATER
        assert "A later repeat of that same call" not in text
        assert STATUS not in parent
        assert OPENING not in parent
        assert LATER not in parent


def test_only_the_name_and_opening_exemption_differ_from_v13():
    files = sorted(path.relative_to(V13).as_posix() for path in V13.rglob("*") if path.is_file())
    found = sorted(path.relative_to(V131).as_posix() for path in V131.rglob("*") if path.is_file())
    assert found == files
    changed = []
    for rel in files:
        parent = (V13 / rel).read_bytes()
        child = (V131 / rel).read_bytes()
        if rel == "agent.yaml":
            assert parent.replace(b"name: structured_v13\n", b"name: structured_v13_1\n") == child
            assert child.count(b"structured_v13_1") == 1
            changed.append(rel)
        elif rel in {f"sub_agents/{name}.md" for name in ROLES}:
            assert child.replace(BLOCK.encode(), b"") == parent
            changed.append(rel)
        else:
            assert child == parent
    assert changed == [
        "agent.yaml",
        "sub_agents/repair_1.md",
        "sub_agents/repair_2.md",
        "sub_agents/repair_3.md",
        "sub_agents/verify_1.md",
        "sub_agents/verify_2.md",
        "sub_agents/verify_3.md",
    ]
    assert _prompt(V131, "triage") == _prompt(V13, "triage")
    assert "Opening calls." not in _prompt(V131, "triage")
    root = load_yaml(V131 / "agent.yaml", V131)
    assert root["name"] == "structured_v13_1"
    assert root["agent_class"] == "SequentialAgent"
    budgets = load_yaml(V131 / "eval_config.yaml", V131)["evaluation"]
    parent_budgets = load_yaml(V13 / "eval_config.yaml", V13)["evaluation"]
    assert budgets == parent_budgets
    assert len(validate(V131)) == 20
    report = lint_candidate(V131)
    assert report["gate"] == "pass", report["findings"]
    assert report["findings"] == []


def test_archive_matches_v13_1(tmp_path):
    archive = tmp_path / "structured-v13-1.zip"
    manifest = pack(V131, archive)
    assert manifest["sha256"] == ARCHIVE
    assert sha256(archive) == ARCHIVE
    assert pack(V13, tmp_path / "structured-v13.zip")["sha256"] == (
        "5ff4c0b3671cb1ff32cfbcb714b079e7a6f72177959c72d36c578fee1fb30dde"
    )
