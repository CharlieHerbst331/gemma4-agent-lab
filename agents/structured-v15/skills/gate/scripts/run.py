"""Pre-submit gate. The model must call this script. It does not wrap other tools.

The skill runner chdirs into a temp copy of this skill, so the repo is found
with git rev-parse from the process cwd, its parents, and PYTHONPATH. Those
are the sandbox paths. /workspace is not a fallback.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CHECK_BUDGET_SECONDS = 20


def _run(argv, cwd, timeout):
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\ntimeout"
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return subprocess.CompletedProcess(argv, 124, stdout, stderr)
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _toplevel(path):
    if not path.is_dir():
        return None
    proc = _run(["git", "rev-parse", "--show-toplevel"], path, 5)
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    if not text:
        return None
    return Path(text)


def repo_root():
    """Return the git root from cwd, its parents, or PYTHONPATH."""
    candidates = []
    here = Path.cwd()
    candidates.append(here)
    candidates.extend(here.parents)
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry))
    pwd = os.environ.get("PWD")
    if pwd:
        candidates.append(Path(pwd))
    seen = set()
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        found = _toplevel(resolved)
        if found is not None:
            return found
    return None


def _tmp_dirs():
    found = []
    for raw in (tempfile.gettempdir(), "/tmp"):
        path = Path(raw).resolve()
        if path not in found:
            found.append(path)
    return found


def is_tmp_path(root, rel):
    """True for scratch paths. A repo that itself lives under a temp dir still counts."""
    path = Path(rel)
    try:
        root_resolved = root.resolve()
    except OSError:
        return True
    if path.is_absolute():
        try:
            resolved = path.resolve()
        except OSError:
            return True
        return resolved != root_resolved and root_resolved not in resolved.parents
    if not path.parts or path.parts[0] in {"tmp", "temp"}:
        return True
    try:
        resolved = (root / path).resolve()
    except OSError:
        return True
    return resolved != root_resolved and root_resolved not in resolved.parents


def changed_paths(root):
    names = []
    diff = _run(["git", "diff", "--name-only", "HEAD"], root, 10)
    if diff.returncode not in {0, 1}:
        return None
    names.extend(line.strip() for line in diff.stdout.splitlines() if line.strip())
    status = _run(["git", "status", "--porcelain"], root, 10)
    if status.returncode not in {0, 1}:
        return None
    for line in status.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        name = line[3:].strip()
        path = root / name
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    names.append(child.relative_to(root).as_posix())
        elif name:
            names.append(name)
    ordered = []
    seen = set()
    for name in names:
        if name in seen or is_tmp_path(root, name):
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def backup_file(rel):
    leaf = "pre_" + rel.replace("/", "_").replace("\\", "_")
    for directory in _tmp_dirs():
        path = directory / leaf
        if path.is_file():
            return path
    return None


def _py_files(root, names):
    files = []
    for name in names:
        if name.endswith(".py") and (root / name).is_file():
            files.append(name)
    return files


def _compile_one(root, rel):
    path = root / rel
    proc = _run(
        [
            sys.executable,
            "-c",
            "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)",
            str(path),
        ],
        root,
        CHECK_BUDGET_SECONDS,
    )
    return proc.returncode == 0


def _restore(root, rel):
    backup = backup_file(rel)
    if backup is None:
        return False
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(backup.read_bytes())
    return True


def _import_names(rel):
    dotted = rel[:-3].replace("/", ".").replace("\\", ".")
    names = [dotted]
    if dotted.startswith("src."):
        names.append(dotted[len("src.") :])
    return names


def _pythonpath(root):
    parts = [str(root)]
    src = root / "src"
    if src.is_dir():
        parts.insert(0, str(src))
    return os.pathsep.join(parts)


def _import_one(root, rel):
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in _import_names(rel):
        try:
            proc = subprocess.run(
                [sys.executable, "-c", f"import {name}"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=CHECK_BUDGET_SECONDS,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return name
    return None


def _test_file(root, rel):
    stem = Path(rel).stem
    for cand in (
        root / "tests" / f"test_{stem}.py",
        root / "test" / f"test_{stem}.py",
        root / f"test_{stem}.py",
    ):
        if cand.is_file():
            return cand
    return None


def _pytest_available():
    proc = _run([sys.executable, "-c", "import pytest"], Path("."), 10)
    return proc.returncode == 0


def _run_test(root, test_path):
    """Run pytest -x -q. None means pytest is missing and the test is a no-op."""
    if not _pytest_available():
        return None
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cache = Path(tempfile.gettempdir()) / "v15-pytest-cache"
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-x",
                "-q",
                str(test_path),
                "-o",
                f"cache_dir={cache}",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=CHECK_BUDGET_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124
    except OSError:
        return 127
    return proc.returncode


def handle():
    root = repo_root()
    if root is None:
        return "FAIL no repo"
    names = changed_paths(root)
    if names is None:
        return "FAIL git"
    if not names:
        return "PASS empty"
    lines = []
    failed = False
    compiled = []
    for rel in _py_files(root, names):
        if _compile_one(root, rel):
            lines.append(f"compile PASS {rel}")
            compiled.append(rel)
            continue
        failed = True
        if _restore(root, rel):
            lines.append(f"compile FAIL {rel} restored")
            if _compile_one(root, rel):
                compiled.append(rel)
        else:
            lines.append(f"compile FAIL {rel} left")
    imported = []
    if compiled:
        for rel in compiled:
            name = _import_one(root, rel)
            if name is None:
                failed = True
                lines.append(f"import FAIL {rel}")
            else:
                lines.append(f"import PASS {name}")
                imported.append(rel)
    else:
        lines.append("import PASS none")
    tested = False
    for rel in imported:
        test_path = _test_file(root, rel)
        if test_path is None:
            continue
        tested = True
        code = _run_test(root, test_path)
        shown = test_path.relative_to(root).as_posix()
        if code is None:
            lines.append(f"test NOOP pytest missing {shown}")
        elif code == 0:
            lines.append(f"test PASS {shown}")
        else:
            failed = True
            lines.append(f"test FAIL {shown} exit={code}")
    if not tested:
        lines.append("test PASS none")
    lines.append("FAIL" if failed else "PASS")
    return "\n".join(lines)


def main(argv=None):
    argparse.ArgumentParser(description="Compile, import, and test the diff.").parse_args(argv)
    try:
        print(handle())
    except Exception as exc:
        print(f"FAIL gate error: {exc}")


if __name__ == "__main__":
    main()
