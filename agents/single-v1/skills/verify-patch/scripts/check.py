"""Assert-based scratch repro execution and read-only patch auditing."""

import argparse
import ast
import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

_PROTECTED_NAMES = {"pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"}
_SKIP_MODULES = {"src", "test", "tests", "testing"}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=5)


def is_protected(name):
    """Grading's protected set from the structured-v5 spec.

    Flags nested conftest.py, test_*.py, anything under tests/ or test/, and
    pytest.ini, pyproject.toml, and setup.cfg at any depth.
    """
    path = PurePosixPath(str(name).replace("\\", "/"))
    if path.name in _PROTECTED_NAMES:
        return True
    if path.name.startswith("test_") and path.suffix == ".py":
        return True
    return any(part in {"test", "tests"} for part in path.parts[:-1])


def classify_origin(file_path, workspace):
    if not file_path:
        return "UNKNOWN"
    real = os.path.realpath(file_path)
    root = str(Path(workspace).resolve()) + os.sep
    if real.startswith(root):
        return "WORKSPACE"
    return "INSTALLED-COPY"


def apply_import_origin(result, origins):
    outside = any(item.get("verdict") == "INSTALLED-COPY" for item in origins)
    result["import_origin"] = origins
    result["imports_outside_workspace"] = outside
    if outside:
        result["passed"] = False
    return result


def snapshot(root):
    base = (
        "_swegemma_baseline"
        if git(root, "rev-parse", "--verify", "_swegemma_baseline").returncode == 0
        else "HEAD"
    )
    diff = git(root, "diff", "--binary", base)
    if diff.returncode:
        raise ValueError("Cannot read baseline diff")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked.returncode:
        raise ValueError("Cannot list untracked files")
    names = untracked.stdout.decode().split("\0")
    # Only the exact live official executor wrapper is exempt, never leftover wrappers.
    original = Path(sys.orig_argv[1]).resolve() if len(sys.orig_argv) > 1 else None
    extra = [
        n
        for n in names
        if n
        and not (
            original == (root / n).resolve() and re.fullmatch(r"\.adk_exec_[0-9a-f]{8}\.py", n)
        )
    ]
    digest = hashlib.sha256(diff.stdout)
    for name in sorted(extra):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Untracked symlink/path escapes workspace")
        digest.update(name.encode())
        if path.is_file() and path.stat().st_size <= 1024 * 1024:
            digest.update(path.read_bytes())
        else:
            raise ValueError("Untracked file exceeds audit size limit")
    return base, extra, digest.hexdigest()


def _unique(items):
    return list(dict.fromkeys(items))


def audit(workspace):
    root = Path(workspace).resolve()
    if not (root / ".git").exists():
        raise ValueError("Require a Git workspace")
    base, extra, fingerprint = snapshot(root)
    names = git(root, "diff", "--name-only", "-z", base)
    if names.returncode:
        raise ValueError("Cannot inspect changed paths")
    changed = [n for n in names.stdout.decode().split("\0") if n]
    forbidden = [n for n in changed + extra if is_protected(n)]
    syntax = []
    for name in changed + extra:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            forbidden.append(name)
            continue
        if path.is_file() and path.suffix == ".py":
            if path.stat().st_size > 1024 * 1024:
                syntax.append(name + ": exceeds parse limit")
                continue
            try:
                ast.parse(path.read_text(), filename=name)
            except (SyntaxError, UnicodeError) as exc:
                syntax.append(f"{name}: {exc}"[:300])
    whitespace = git(root, "diff", "--check", base)
    return {
        "kind": "patch-audit",
        "passed": not (extra or forbidden or syntax or whitespace.returncode),
        "behavior_verified": False,
        "patch_sha256": fingerprint,
        "changed_paths": changed[:20],
        "untracked": extra[:20],
        "forbidden": _unique(forbidden)[:10],
        "syntax_errors": syntax[:6],
        "diff_check_exit_code": whitespace.returncode,
        "diff_check_output": whitespace.stdout.decode(errors="replace")[-800:],
    }


def assertion_code(code):
    if len(code) > 12000:
        raise ValueError("Repro exceeds 12000 characters")
    tree = ast.parse(code)
    if not any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
        raise ValueError("A direct repro must contain assertions")
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            types = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            if any(
                x is None
                or (
                    isinstance(x, ast.Name)
                    and x.id in {"AssertionError", "Exception", "BaseException"}
                )
                for x in types
            ):
                raise ValueError("Do not catch assertion failures or broad exceptions")
    return code


def child_limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def _lives_in_workspace(root, name):
    candidates = [
        root / name / "__init__.py",
        root / f"{name}.py",
        root / "src" / name / "__init__.py",
        root / "src" / f"{name}.py",
        root / name,
        root / "src" / name,
    ]
    return any(path.exists() for path in candidates)


def _remember(found, name):
    if len(found) >= 4:
        return
    module = name.split(".")[0]
    if (
        module.isidentifier()
        and module not in sys.stdlib_module_names
        and module not in _SKIP_MODULES
        and module not in found
    ):
        found.append(module)


def candidate_modules(root, code, changed):
    found = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _remember(found, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            _remember(found, node.module)
    for rel in changed:
        path = PurePosixPath(rel)
        if path.suffix != ".py" or not path.parts:
            continue
        parts = path.parts
        if parts[0] == "src" and len(parts) >= 3:
            _remember(found, parts[1])
        elif len(parts) >= 2 and parts[0] not in _SKIP_MODULES:
            _remember(found, parts[0])
    return [name for name in found if _lives_in_workspace(root, name)][:4]


def changed_names(root):
    try:
        base, _, _ = snapshot(root)
    except (ValueError, OSError, subprocess.SubprocessError):
        return []
    listed = git(root, "diff", "--name-only", "-z", base)
    if listed.returncode:
        return []
    return [n for n in listed.stdout.decode().split("\0") if n]


def _origin_script():
    tab = "\t"
    return (
        "import importlib, os, sys\n"
        "for name in sys.argv[1:]:\n"
        "    try:\n"
        "        mod = importlib.import_module(name)\n"
        "        raw = getattr(mod, '__file__', None) or ''\n"
        "        path = os.path.realpath(raw) if raw else ''\n"
        f"        print('ORIGIN{tab}' + name + '{tab}' + path + '{tab}OK')\n"
        "    except Exception:\n"
        f"        print('ORIGIN{tab}' + name + '{tab}{tab}ERROR')\n"
    )


def _parse_origin_line(line, workspace):
    if not line.startswith("ORIGIN\t"):
        return None
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    name, path, status = parts[1], parts[2], parts[3]
    if status != "OK":
        return {"module": name, "file": "", "verdict": "ERROR"}
    return {"module": name, "file": path[:300], "verdict": classify_origin(path, workspace)}


def collect_import_origin(root, code):
    modules = candidate_modules(root, code, changed_names(root))
    if not modules:
        return []
    env = dict(os.environ)
    # Spec prefix: src then workspace root. cwd remains on sys.path ahead of this.
    env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), str(root)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _origin_script(), *modules],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (subprocess.TimeoutExpired, OSError):
        return [{"module": name, "file": "", "verdict": "ERROR"} for name in modules]
    rows = []
    for line in proc.stdout.splitlines():
        row = _parse_origin_line(line, root)
        if row:
            rows.append(row)
    if not rows:
        return [{"module": name, "file": "", "verdict": "ERROR"} for name in modules]
    return rows[:4]


def repro(workspace, scratch, phase, code=None, timeout=20):
    root, scratch = Path(workspace).resolve(), Path(scratch).resolve()
    if (
        not (root / ".git").exists()
        or not scratch.is_dir()
        or scratch.is_relative_to(root)
        or not 1 <= timeout <= 30
    ):
        raise ValueError("Require Git workspace, external scratch, and timeout 1-30s")
    if phase not in ["before", "after", "verify", "read", "probe"]:
        raise ValueError("Use before, after, verify, read, or probe")
    path = scratch / ("gemma-agent-probe.py" if phase == "probe" else "gemma-agent-repro.py")
    contract_path = scratch / "gemma-agent-repro-contract.json"
    if contract_path.is_symlink():
        raise ValueError("Repro contract must not be a symlink")
    head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    task = hashlib.sha256((str(root) + head).encode()).hexdigest()
    contract = {}
    if contract_path.exists():
        if contract_path.stat().st_size > 2000:
            raise ValueError("Oversized repro contract")
        contract = json.loads(contract_path.read_text())
    if phase in ["after", "verify"]:
        if contract.get("task") != task or not path.exists():
            raise ValueError("Run the before check first for this task")
        proposed = code if code is not None else path.read_text()
        if hashlib.sha256(proposed.encode()).hexdigest() != contract.get("repro_sha256"):
            raise ValueError("Baseline repro changed; preserve the same assertions")
    if path.is_symlink():
        raise ValueError("Scratch repro must not be a symlink")
    if code is not None:
        code = assertion_code(code)
        path.write_text(code)
    else:
        if path.stat().st_size > 12000:
            raise ValueError("Oversized repro")
        code = assertion_code(path.read_text())
    if phase == "read":
        return {
            "kind": "repro-source",
            "path": str(path),
            "code": code[:3000],
            "truncated": len(code) > 3000,
        }
    if phase == "before":
        contract_path.write_text(
            json.dumps({"task": task, "repro_sha256": hashlib.sha256(code.encode()).hexdigest()})
        )
    _, _, fingerprint = snapshot(root)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(root / "src"), str(root)])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    output_path = scratch / "gemma-agent-repro.log"
    if output_path.is_symlink():
        raise ValueError("Repro log must not be a symlink")
    timed_out = False
    with output_path.open("w+b") as output:
        process = subprocess.Popen(
            [sys.executable, str(path)],
            cwd=root,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=child_limits,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        finally:
            # Tests can spawn child processes; leave no surviving process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        output.seek(0, os.SEEK_END)
        output.seek(max(0, output.tell() - 3000))
        tail = output.read().decode("utf-8", errors="replace")
    origins = collect_import_origin(root, code)
    _, _, after_fingerprint = snapshot(root)
    changed = after_fingerprint != fingerprint
    blocked = process.returncode != 0 and any(
        s in tail for s in ["ModuleNotFoundError:", "ImportError:"]
    )
    result = {
        "kind": "behavior-check",
        "phase": phase,
        "path": str(path),
        "passed": process.returncode == 0 and not timed_out and not changed,
        "workspace_changed": changed,
        "output_limited": (
            process.returncode == -signal.SIGXFSZ or output_path.stat().st_size >= 1024 * 1024
        ),
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "blocked": blocked,
        "patch_sha256": fingerprint,
        "repro_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "output_tail": tail[-2400:],
    }
    apply_import_origin(result, origins)
    record = scratch / "gemma-agent-checks.json"
    if record.is_symlink():
        raise ValueError("Check history must not be a symlink")
    history = []
    if record.exists() and record.stat().st_size <= 20000:
        history = json.loads(record.read_text())
    record.write_text(json.dumps((history + [result])[-4:]))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["audit", "repro"], required=True)
    parser.add_argument("--workspace", default=os.environ.get("PWD", "/workspace"))
    parser.add_argument("--scratch", default=os.environ.get("TEST_TMPDIR", tempfile.gettempdir()))
    parser.add_argument("--phase", default="verify")
    parser.add_argument("--code")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    try:
        result = (
            audit(args.workspace)
            if args.mode == "audit"
            else repro(args.workspace, args.scratch, args.phase, args.code, args.timeout)
        )
        print(json.dumps(result, ensure_ascii=True))
        if result.get("passed") is False:
            raise SystemExit(1)
    except (ValueError, OSError, SyntaxError, subprocess.SubprocessError) as exc:
        print(json.dumps({"passed": False, "blocked": True, "error": str(exc)[:500]}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
