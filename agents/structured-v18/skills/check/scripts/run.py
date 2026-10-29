"""Zero-argument check. The only call is skill_name plus file_path.

The harness has no custom edit tool. This script does not edit. It pins the
repro the agent already wrote, reruns it, and prints git status.

The subprocess sandbox rewrites /tmp and /workspace only inside command
strings. The script therefore uses the process temp directory (TMPDIR) and
finds the repo from GEMMA_CHECK_ROOT, then /workspace, then PYTHONPATH.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _root():
    candidates = [os.environ.get("GEMMA_CHECK_ROOT"), "/workspace"]
    candidates.extend(os.environ.get("PYTHONPATH", "").split(os.pathsep))
    for cand in candidates:
        if cand and (Path(cand) / ".git").exists():
            return Path(cand)
    return Path("/workspace")


ROOT = _root()
TMP = Path(tempfile.gettempdir())
REPRO = Path(os.environ.get("GEMMA_CHECK_REPRO") or TMP / "repro_check.py")
PIN = Path(os.environ.get("GEMMA_CHECK_PIN") or TMP / "gemma_check_pin.txt")
SCRATCH_NAMES = {"repro.py", "fix.py", "repro_check.py"}
PROTECTED_NAMES = {
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "tox.ini",
    "setup.cfg",
    ".pytest.ini",
}
# The harness stages these before any agent edit. Do not call them protected
# when they are the only changes.
HARNESS_STAGED = {"conftest.py", "pytest.ini"}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _run(argv, timeout):
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, _text(completed.stdout), _text(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        return 124, _text(exc.stdout), _text(exc.stderr) + "\ntimeout"
    except OSError as exc:
        return 127, "", str(exc)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repro_lines():
    if not REPRO.is_file():
        return ["before: PASS (repro does not fail yet; write one that fails)"]
    digest = _hash(REPRO)
    short = digest[:4]
    if PIN.is_file():
        pinned = PIN.read_text().strip()
        label = "after"
        changed = pinned != digest
    else:
        PIN.parent.mkdir(parents=True, exist_ok=True)
        PIN.write_text(digest + "\n")
        label = "before"
        changed = False
    code, _out, _err = _run([sys.executable, str(REPRO)], 20)
    status = "FAIL" if code else "PASS"
    lines = [f"{label}: {status} exit={code} (hash {short})"]
    if changed:
        lines.append("repro changed since pinned (weakening?)")
    return lines


def _names():
    code, out, _err = _run(["git", "diff", "--name-only", "HEAD"], 10)
    if code not in {0, 1}:
        code, out, _err = _run(["git", "diff", "--name-only"], 10)
    if code not in {0, 1}:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _flag(path):
    parts = Path(path).parts
    name = parts[-1] if parts else path
    flags = []
    if name in SCRATCH_NAMES or "tmp" in parts:
        flags.append("scratch")
    protected_dir = any(part.lower() in {"tests", "test", "testing"} for part in parts)
    if name in PROTECTED_NAMES or protected_dir:
        flags.append("protected")
    return flags


def _status_path(line):
    raw = line.rstrip()
    if len(raw) >= 4 and raw[2] == " ":
        path = raw[3:]
    else:
        path = raw.strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip().strip('"')


def _harness_only(paths):
    cleaned = [path.lstrip("./") for path in paths if path.strip()]
    return bool(cleaned) and all(path in HARNESS_STAGED for path in cleaned)


def _pytest_line(names):
    for name in names:
        path = Path(name)
        if path.suffix != ".py" or path.name.startswith("test_"):
            continue
        matches = list(ROOT.glob(f"**/test_{path.stem}.py"))[:1]
        if not matches:
            continue
        rel = matches[0].relative_to(ROOT).as_posix()
        code, out, err = _run(
            [sys.executable, "-m", "pytest", rel, "-x", "-q", "-p", "no:cacheprovider"],
            15,
        )
        tail = (out or err).strip().splitlines()
        last = tail[-1] if tail else ""
        return f"pytest {rel} exit={code} {last}".strip()
    return "pytest: no mapped test"


def _visible_flags(path, harness_only):
    flags = _flag(path)
    if harness_only and path.lstrip("./") in HARNESS_STAGED:
        flags = [flag for flag in flags if flag != "protected"]
    return flags


def main():
    lines = _repro_lines()
    code, status, err = _run(["git", "status", "--short"], 10)
    status_lines = []
    if code == 0:
        status_lines = [line for line in status.splitlines() if line.strip()]
    names = _names()
    harness_only = _harness_only([_status_path(line) for line in status_lines] + names)
    if code == 0:
        flagged = []
        for line in status_lines:
            text = line.strip()
            flags = _visible_flags(_status_path(line), harness_only)
            flagged.append(text + (" [" + ",".join(flags) + "]" if flags else ""))
        lines.append("git status:")
        lines.extend(flagged or ["clean"])
    else:
        lines.append("git status failed: " + err.strip())
    for name in names:
        flags = _visible_flags(name, harness_only)
        if flags:
            lines.append(f"diff {name} [{','.join(flags)}]")
    _code, stat, _err = _run(["git", "diff", "--stat"], 10)
    lines.append("git diff --stat:")
    lines.append(stat.strip() or "empty")
    lines.append(_pytest_line(names))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
