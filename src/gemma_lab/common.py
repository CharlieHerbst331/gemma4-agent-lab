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


def git_revision():
    proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "uncommitted"
