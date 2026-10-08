import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

COMPETITION = "gemma-4-developer-agent"
MODEL = "gemma-4-31b-it-qat-w4a16-ct"
STARTER = "ryanholbrook/getting-started-gemma-4-developer-agent"


def now():
    return datetime.now(UTC).isoformat()


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def kaggle(*args, timeout=120):
    # Use this environment's installed CLI, and let it handle authentication.
    proc = subprocess.run(
        [sys.executable, "-m", "kaggle", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def _git(args, cwd=None):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except OSError:
        return subprocess.CompletedProcess(["git", *args], 1, "", "")


def git_revision(cwd=None):
    """HEAD used for packing. Appends '-dirty' when `git status --porcelain` is non-empty."""
    head = _git(["rev-parse", "HEAD"], cwd)
    if head.returncode != 0 or not head.stdout.strip():
        return "uncommitted"
    revision = head.stdout.strip()
    status = _git(["status", "--porcelain"], cwd)
    if status.returncode == 0 and status.stdout.strip():
        return revision + "-dirty"
    return revision


def candidate_source_commit(source, cwd=None):
    """Last commit that changed `source`, independent of the commit used for packing.

    Appends '-dirty' when that path itself has porcelain changes.
    """
    log = _git(["log", "-1", "--format=%H", "--", str(source)], cwd)
    if log.returncode != 0 or not log.stdout.strip():
        return "uncommitted"
    commit = log.stdout.strip()
    status = _git(["status", "--porcelain", "--", str(source)], cwd)
    if status.returncode == 0 and status.stdout.strip():
        return commit + "-dirty"
    return commit
