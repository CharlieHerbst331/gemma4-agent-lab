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


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=5)


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


def protected_path(name):
    """Paths fresh grading resets, including nested tests and config files."""
    path = PurePosixPath(str(name).replace("\\", "/"))
    if any(part in {"test", "tests"} for part in path.parts[:-1]):
        return True
    base = path.name
    if base in {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg"}:
        return True
    return base.startswith("test_") and base.endswith(".py")


def third_party_modules(code):
    tree = ast.parse(code)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    found = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split(".")[0]]
        for name in names:
            if name.isidentifier() and name not in stdlib and name not in found:
                found.append(name)
            if len(found) == 3:
                return found
    return found


def probe_module(root, module, environment):
    script = (
        "import importlib, os\n"
        f"mod = importlib.import_module({module!r})\n"
        "path = os.path.realpath(getattr(mod, '__file__', '') or '')\n"
        "root = os.path.realpath(os.getcwd())\n"
        "inside = bool(path) and (path == root or path.startswith(root + os.sep))\n"
        "origin = 'WORKSPACE' if inside else ('UNKNOWN' if not path else 'INSTALLED-COPY')\n"
        "print(origin + '\\t' + path)\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return {"module": module, "origin": "UNKNOWN", "error": "probe timeout"}
    line = completed.stdout.splitlines()[-1].strip() if completed.stdout else ""
    origin, sep, path = line.partition("\t")
    known = {"WORKSPACE", "INSTALLED-COPY", "UNKNOWN"}
    if completed.returncode != 0 or not sep or origin not in known:
        detail = (completed.stderr or completed.stdout or "probe failed").strip()
        return {"module": module, "origin": "UNKNOWN", "error": detail[-180:]}
    item = {"module": module, "origin": origin}
    if path:
        item["file"] = path[:300]
    return item


def import_report(root, code, environment):
    modules = third_party_modules(code)
    used = [probe_module(root, name, environment) for name in modules]
    default_env = dict(environment)
    # Sandbox default is the workspace root only. Do not use python -I or -E.
    default_env["PYTHONPATH"] = str(root)
    default = [probe_module(root, name, default_env) for name in modules]
    return used, default


def audit(workspace):
    root = Path(workspace).resolve()
    if not (root / ".git").exists():
        raise ValueError("Require a Git workspace")
    base, extra, fingerprint = snapshot(root)
    names = git(root, "diff", "--name-only", "-z", base)
    if names.returncode:
        raise ValueError("Cannot inspect changed paths")
    changed = [n for n in names.stdout.decode().split("\0") if n]
    forbidden = [n for n in changed if protected_path(n)]
    forbidden.extend(n for n in extra if protected_path(n) and n not in forbidden)
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
        "forbidden": forbidden[:10],
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
    environment["PYTHONPATH"] = os.pathsep.join([str(root), str(root / "src")])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    origins, default_origins = import_report(root, code, environment)
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
        "import_origin": origins,
        "default_import_origin": default_origins,
        "imports_installed_copy": any(item.get("origin") == "INSTALLED-COPY" for item in origins),
    }
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
