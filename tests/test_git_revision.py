"""Packing provenance records a dirty tree and the candidate's own commit."""

import shutil
import subprocess
from pathlib import Path

from gemma_lab.bundle import pack
from gemma_lab.common import MODEL, candidate_source_commit, git_revision


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "repo"
    source = root / "agents" / "demo"
    shutil.copytree(Path("agents/baseline"), source)
    git(root, "init", "-q")
    git(root, "config", "user.email", "revision@example.test")
    git(root, "config", "user.name", "Revision")
    git(root, "add", ".")
    git(root, "commit", "-qm", "add candidate")
    return root, source


def test_clean_and_dirty_revisions(tmp_path):
    root, _source = repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    assert git_revision(root) == head
    (root / "README.md").write_text("uncommitted\n")
    assert git_revision(root) == head + "-dirty"
    assert git_revision(tmp_path / "missing") == "uncommitted"


def test_candidate_source_commit_is_not_the_packing_commit(tmp_path, monkeypatch):
    root, source = repo(tmp_path)
    source_commit = git(root, "rev-parse", "HEAD")
    (root / "README.md").write_text("later docs\n")
    git(root, "add", "README.md")
    git(root, "commit", "-qm", "docs only")
    packing_commit = git(root, "rev-parse", "HEAD")
    assert candidate_source_commit(source, root) == source_commit
    assert git_revision(root) == packing_commit
    assert source_commit != packing_commit
    monkeypatch.chdir(root)
    first = pack(source, tmp_path / "first.zip")
    assert first["packing_commit"] == packing_commit
    assert first["candidate_source_commit"] == source_commit
    assert first["worktree_dirty"] is False
    assert first["candidate_source_dirty"] is False
    (root / "README.md").write_text("dirty docs\n")
    second = pack(source, tmp_path / "second.zip")
    assert second["sha256"] == first["sha256"]
    assert second["git_revision"] == packing_commit + "-dirty"
    assert second["packing_commit"] == packing_commit
    assert second["worktree_dirty"] is True
    assert second["candidate_source_commit"] == source_commit
    assert second["candidate_source_dirty"] is False
    (source / "agent.yaml").write_text(f"name: demo\nmodel: {MODEL}\n")
    assert candidate_source_commit(source, root).endswith("-dirty")


def test_pack_manifest_keeps_archive_bytes_independent_of_provenance(tmp_path, monkeypatch):
    root, source = repo(tmp_path)
    monkeypatch.chdir(root)
    left = pack(source, tmp_path / "left.zip")
    (root / "NOTES.md").write_text("dirty\n")
    right = pack(source, tmp_path / "right.zip")
    assert left["sha256"] == right["sha256"]
    assert left["worktree_dirty"] is False
    assert right["worktree_dirty"] is True
    assert Path(tmp_path / "left.zip").read_bytes() == Path(tmp_path / "right.zip").read_bytes()
