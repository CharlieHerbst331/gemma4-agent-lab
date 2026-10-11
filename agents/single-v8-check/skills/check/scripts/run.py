"""Zero-argument check. The only call is skill_name plus file_path.

The harness has no custom edit tool. This script does not edit. It pins the
repro the agent already wrote under /tmp, reruns it, and prints git status.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("GEMMA_CHECK_ROOT", "/workspace"))
REPRO = Path(os.environ.get("GEMMA_CHECK_REPRO", "/tmp/repro_check.py"))
PIN = Path(os.environ.get("GEMMA_CHECK_PIN", "/tmp/gemma_check_pin.txt"))
SCRATCH_NAMES = {"repro.py", "fix.py", "repro_check.py"}
PROTECTED_NAMES = {
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "tox.ini",
    "setup.cfg",
    ".pytest.ini",
}


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


def main():
    lines = _repro_lines()
    code, status, err = _run(["git", "status", "--short"], 10)
    if code == 0:
        flagged = []
        for line in status.splitlines():
            text = line.strip()
            if not text:
                continue
            path = text[3:] if len(text) > 3 else text
            flags = _flag(path)
            flagged.append(text + (" [" + ",".join(flags) + "]" if flags else ""))
        lines.append("git status:")
        lines.extend(flagged or ["clean"])
    else:
        lines.append("git status failed: " + err.strip())
    names = _names()
    for name in names:
        flags = _flag(name)
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
