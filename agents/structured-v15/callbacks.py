"""Harness gates for structured-v15. Wired as ADK callbacks, not prompt text.

The official compiler drops callback names unless the host registry supplies
them. ``register_callbacks`` fills that registry. Every public callback swallows
its own errors so a ParallelAgent branch cannot take down its siblings.

Shell checks use non-interactive ``bash --noprofile --norc -c``. When
``GEMMA_SANDBOX_CONTAINER`` is set they go through synchronous ``docker exec -i``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path

CAP_SECONDS = 300
REPAIR1_END_SECONDS = 150
REPAIR_PHASE_END_SECONDS = 240
FORCE_EDIT_SECONDS = 120
FORCE_EDIT_CALLS = 30
CHECK_BUDGET_SECONDS = 20
REPAIR_ROLES = {"repair_1", "repair_2", "repair_3"}
STATUS_TOOLS = {"get_status"}
EDIT_TOOLS = {"edit_file", "write_file"}
STAMP = "[elapsed {elapsed}s / remaining {remaining}s]"

_LOCK = threading.Lock()
_STATES = {}
_NOW = time.monotonic


def set_clock(fn):
    global _NOW
    _NOW = fn


def reset_states():
    with _LOCK:
        _STATES.clear()


class GateState:
    def __init__(self):
        self.t0 = None
        self.calls = 0
        self.seen = {}
        self.opened_git = {}
        self.has_edit = False
        self.good_files = None
        self.gate_used = 0.0

    def elapsed(self):
        if self.t0 is None:
            self.t0 = _NOW()
        return max(0, int(_NOW() - self.t0))

    def remaining(self):
        return max(0, CAP_SECONDS - self.elapsed())


def _state_for(ctx):
    key = getattr(ctx, "invocation_id", None) or id(ctx)
    with _LOCK:
        box = _STATES.get(key)
        if box is None:
            box = GateState()
            _STATES[key] = box
        return box


def _agent_name(ctx):
    name = getattr(ctx, "agent_name", None)
    if name:
        return name
    agent = getattr(getattr(ctx, "_invocation_context", None), "agent", None)
    return getattr(agent, "name", "") or ""


def _invocation(ctx):
    return getattr(ctx, "_invocation_context", None)


def command_argv(script, container=None):
    bash = ["bash", "--noprofile", "--norc", "-c", script]
    if container:
        return ["docker", "exec", "-i", container, *bash]
    return bash


def _container():
    return os.environ.get("GEMMA_SANDBOX_CONTAINER") or os.environ.get("DOCKER_CONTAINER") or ""


def run_bash(script, timeout, cwd=None):
    container = _container()
    if container:
        script = "cd /workspace && " + script
        cwd = None
    argv = command_argv(script, container or None)
    try:
        proc = subprocess.run(
            argv,
            cwd=None if container else cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        return 124, stdout, "timeout"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def repo_root():
    """Directory whose git diff the gate reads.

    A container uses its own ``/workspace``. A local checkout is used only when
    ``V15_REPO`` or ``GEMMA_CHECK_ROOT`` is set, so this lab tree is not the
    default target.
    """
    override = os.environ.get("V15_REPO") or os.environ.get("GEMMA_CHECK_ROOT")
    if override:
        return Path(override)
    if _container():
        return Path("/workspace")
    return None


def _command_text(args):
    if not isinstance(args, dict):
        return ""
    for key in ("command", "cmd", "script"):
        value = args.get(key)
        if isinstance(value, list):
            return " ".join(str(part) for part in value)
        if isinstance(value, str):
            return value
    return ""


def _signature(tool_name, args):
    payload = args if isinstance(args, dict) else {}
    if tool_name == "read_file":
        path = payload.get("filepath") or payload.get("path") or payload.get("file_path")
        return (
            "read_file",
            path,
            payload.get("start_line"),
            payload.get("end_line"),
        )
    if tool_name == "run_command":
        return ("run_command", _command_text(payload).strip())
    try:
        blob = json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        blob = str(payload)
    return (tool_name, blob[:500])


def _is_git_status_or_diff(command):
    text = " ".join(command.strip().split())
    return text.startswith("git diff") or text.startswith("git status")


def is_edit_call(tool_name, args):
    if tool_name in EDIT_TOOLS:
        return True
    if tool_name != "run_command":
        return False
    text = _command_text(args)
    markers = ("line_fix", "cat >", "cat>>", "tee ", ">>")
    return any(marker in text for marker in markers)


def _tool_name(tool):
    return getattr(tool, "name", None) or str(tool)


def stamp_text(elapsed, remaining):
    return STAMP.format(elapsed=int(elapsed), remaining=int(remaining))


def stamp_result(result, elapsed, remaining):
    line = stamp_text(elapsed, remaining)
    if isinstance(result, str):
        return result if result.endswith(line) else result + "\n" + line
    if isinstance(result, dict):
        out = dict(result)
        for key in ("output", "stdout", "result", "content", "text"):
            value = out.get(key)
            if isinstance(value, str) and not value.endswith(line):
                out[key] = value + "\n" + line
                return out
        out["v15_clock"] = line
        return out
    return {"result": result, "v15_clock": line}


def _short(text):
    flat = " ".join(str(text).split())
    return flat[:160]


def _result_text(result):
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("output", "stdout", "result", "content", "text"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return str(result)


def _end_role(ctx):
    invocation = _invocation(ctx)
    if invocation is not None:
        invocation.end_invocation = True


def _deadline_hit(role, elapsed):
    if role == "repair_1" and elapsed >= REPAIR1_END_SECONDS:
        return True
    if role in REPAIR_ROLES and elapsed >= REPAIR_PHASE_END_SECONDS:
        return True
    return False


def _deadline_message(role, elapsed):
    return f"{role} ended at {elapsed}s so verify and submit can run"


def source_diff(root, timeout=10):
    code, out, err = run_bash("git diff --name-only -- .", timeout, cwd=root)
    if code != 0:
        return "", err
    names = []
    for line in out.splitlines():
        path = line.strip()
        if not path:
            continue
        base = Path(path).name
        if base in {"conftest.py", "pytest.ini"}:
            continue
        names.append(path)
    return "\n".join(names), ""


def _py_files(diff_names):
    return [name for name in diff_names.splitlines() if name.endswith(".py")]


def py_compile_files(root, paths, timeout=15):
    if not paths:
        return True, ""
    failures = []
    for path in paths:
        script = "python3 -c " + shlex.quote(
            f"import py_compile; py_compile.compile({path!r}, doraise=True)"
        )
        code, out, err = run_bash(script, timeout, cwd=root)
        if code != 0:
            failures.append(path + ": " + (out + err).strip())
    return not failures, "; ".join(failures)


def _import_name(path):
    stem = path[:-3] if path.endswith(".py") else path
    return stem.replace("/", ".").replace("\\", ".")


def _test_paths(root, py_paths):
    found = []
    for path in py_paths:
        stem = Path(path).stem
        if stem.startswith("test_") or stem.endswith("_test"):
            continue
        candidates = [
            root / "tests" / f"test_{stem}.py",
            root / "test" / f"test_{stem}.py",
            root / f"test_{stem}.py",
        ]
        for candidate in candidates:
            if candidate.is_file():
                found.append(candidate.relative_to(root).as_posix())
                break
    return found


def run_targeted_check(root, py_paths, timeout):
    """Import touched modules and run a matching unit test, inside ``timeout``."""
    if not py_paths:
        return True, "no python files"
    imports = [_import_name(path) for path in py_paths if not Path(path).name.startswith("test_")]
    tests = _test_paths(root, py_paths)
    parts = []
    if imports:
        joined = ", ".join(imports)
        parts.append("PYTHONPATH=. python3 -c " + shlex.quote("import " + joined))
    for test in tests:
        parts.append("PYTHONPATH=. python3 " + shlex.quote(test))
    if not parts:
        return True, "nothing to run"
    script = " && ".join(parts)
    code, out, err = run_bash(script, timeout, cwd=root)
    detail = (out + err).strip()
    return code == 0, detail[:500]


def _read_bytes(root, path):
    code, out, err = run_bash(f"git show HEAD:{shlex.quote(path)}", 10, cwd=root)
    if code != 0:
        return None
    # git show is text here; tests are utf-8 source.
    return out.encode("utf-8")


def snapshot_files(root, paths):
    saved = {}
    for path in paths:
        file_path = root / path
        if file_path.is_file():
            saved[path] = file_path.read_bytes()
    return saved


def restore_files(root, saved, current_paths):
    saved = saved or {}
    for path in current_paths:
        dest = root / path
        if path in saved:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(saved[path])
            continue
        blob = _read_bytes(root, path)
        if blob is None:
            if dest.is_file():
                dest.unlink()
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)


def review_tree(root, state, timeout=CHECK_BUDGET_SECONDS):
    """Compile, import, and test. On failure restore the last passing snapshot.

    An empty diff is left alone. Returns (ok, detail).
    """
    names, err = source_diff(root)
    if err and not names:
        return True, "diff unavailable"
    py_paths = _py_files(names)
    if not names.strip():
        return True, "empty diff"
    left = max(1, int(timeout - state.gate_used))
    started = _NOW()
    compiled, compile_detail = py_compile_files(root, py_paths, timeout=min(10, left))
    if not compiled:
        restore_files(root, state.good_files, py_paths or names.splitlines())
        state.gate_used += _NOW() - started
        return False, "compile failed: " + compile_detail
    ok, detail = run_targeted_check(root, py_paths, timeout=left)
    state.gate_used += _NOW() - started
    if ok:
        state.good_files = snapshot_files(root, py_paths)
        state.has_edit = True
        return True, detail or "check passed"
    restore_files(root, state.good_files, py_paths or names.splitlines())
    return False, "check failed, restored last good diff: " + detail


def _remember(state, role, sig, summary):
    state.seen[(role, sig)] = _short(summary)


def _repeat_message(state, role, sig, command):
    if command and _is_git_status_or_diff(command):
        opened = state.opened_git.setdefault(role, set())
        if command not in opened:
            opened.add(command)
            return None
    previous = state.seen.get((role, sig))
    if previous is None:
        return None
    if state.has_edit:
        return None
    return "already seen: " + previous


def _before(tool, args, tool_context):
    state = _state_for(tool_context)
    role = _agent_name(tool_context)
    name = _tool_name(tool)
    args = args if isinstance(args, dict) else {}
    elapsed = state.elapsed()
    if _deadline_hit(role, elapsed):
        if elapsed >= REPAIR_PHASE_END_SECONDS:
            root = repo_root()
            if root is not None and (root / ".git").exists():
                review_tree(root, state)
        _end_role(tool_context)
        return {"result": _deadline_message(role, elapsed)}
    sig = _signature(name, args)
    command = _command_text(args) if name == "run_command" else ""
    if name not in STATUS_TOOLS:
        repeat = _repeat_message(state, role, sig, command.strip())
        if repeat:
            return {"result": repeat}
    force = (
        role in REPAIR_ROLES
        and not state.has_edit
        and (elapsed >= FORCE_EDIT_SECONDS or state.calls >= FORCE_EDIT_CALLS)
    )
    if (
        force
        and name not in STATUS_TOOLS
        and name != "submit_patch"
        and not is_edit_call(name, args)
    ):
        return {"result": "next call must be an edit"}
    if name == "submit_patch":
        root = repo_root()
        if root is not None and (root / ".git").exists():
            had_good = bool(state.good_files)
            ok, detail = review_tree(root, state)
            if not ok and not had_good:
                return {"result": detail}
    if name not in STATUS_TOOLS and name != "submit_patch":
        state.calls += 1
    return None


def _after(tool, args, tool_context, tool_response):
    state = _state_for(tool_context)
    role = _agent_name(tool_context)
    name = _tool_name(tool)
    args = args if isinstance(args, dict) else {}
    text = _result_text(tool_response)
    if name not in STATUS_TOOLS:
        _remember(state, role, _signature(name, args), text)
    if is_edit_call(name, args):
        state.has_edit = True
        state.seen.clear()
        state.opened_git.clear()
    root = repo_root()
    if name == "run_command" and root is not None and (root / ".git").exists():
        names, _err = source_diff(root)
        if names.strip():
            state.has_edit = True
        py_paths = _py_files(names)
        if py_paths and is_edit_call(name, args):
            compiled, detail = py_compile_files(root, py_paths)
            if not compiled:
                text = text + "\ncompile failed: " + detail
                if isinstance(tool_response, dict):
                    tool_response = dict(tool_response)
                    tool_response["result"] = text
                else:
                    tool_response = text
    return stamp_result(tool_response, state.elapsed(), state.remaining())


def before_tool(tool=None, args=None, tool_context=None, **_ignored):
    try:
        if tool is None or tool_context is None:
            return None
        return _before(tool, args or {}, tool_context)
    except Exception:
        return None


def after_tool(tool=None, args=None, tool_context=None, tool_response=None, **_ignored):
    try:
        if tool is None or tool_context is None:
            return None
        return _after(tool, args or {}, tool_context, tool_response)
    except Exception:
        return None


def _final_response(text):
    try:
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))
    except Exception:
        return {"ended": text}


def before_model(callback_context=None, llm_request=None, **_ignored):
    try:
        if callback_context is None:
            return None
        state = _state_for(callback_context)
        role = _agent_name(callback_context)
        elapsed = state.elapsed()
        if not _deadline_hit(role, elapsed):
            return None
        _end_role(callback_context)
        return _final_response(_deadline_message(role, elapsed))
    except Exception:
        return None


def register_callbacks(registry):
    from adk_submission import CallbackType

    registry.register("v15_before_tool", before_tool, {CallbackType.BEFORE_TOOL})
    registry.register("v15_after_tool", after_tool, {CallbackType.AFTER_TOOL})
    registry.register("v15_before_model", before_model, {CallbackType.BEFORE_MODEL})


UNREACHABLE_DEV13 = {"fastapi_14246", "fastapi_14262", "fastapi_14356"}


def dev13_report(rows, traces):
    items = summarize_tasks(rows, traces)
    reachable = [item for item in items if item["instance_id"] not in UNREACHABLE_DEV13]
    return {
        "n": len(items),
        "resolved": sum(1 for item in items if item["resolved"]),
        "reachable_n": len(reachable),
        "reachable_resolved": sum(1 for item in reachable if item["resolved"]),
        "reachable_ceiling": 10,
        "no_edit_runs": sum(1 for item in items if item["no_edit"]),
        "tasks": items,
    }


def summarize_tasks(rows, traces):
    """Dev-13 report fields. ``traces`` maps instance id to a decoded trace."""
    report = []
    for row in rows:
        task_id = row.get("instance_id") or row.get("id")
        calls = _trace_calls(traces.get(task_id) or {})
        edit_at = None
        for index, call in enumerate(calls, start=1):
            if is_edit_call(call.get("name") or "", call.get("args") or {}):
                edit_at = index
                break
        wall = row.get("duration_seconds", row.get("wall_seconds"))
        report.append(
            {
                "instance_id": task_id,
                "resolved": bool(row.get("resolved")),
                "wall_seconds": wall,
                "no_edit": edit_at is None,
                "calls_to_first_edit": edit_at,
            }
        )
    return report


def _trace_calls(trace):
    calls = []
    steps = trace.get("steps") or trace.get("events") or []
    if isinstance(trace.get("tool_calls"), list):
        steps = trace["tool_calls"]
    for step in steps:
        if not isinstance(step, dict):
            continue
        nested = step.get("tool_calls") or step.get("function_calls")
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    calls.append(_call_record(item))
            continue
        if "name" in step or "tool" in step:
            calls.append(_call_record(step))
    return calls


def _call_record(item):
    name = item.get("name") or item.get("tool") or ""
    args = item.get("arguments") or item.get("args") or item.get("input") or {}
    if not isinstance(args, dict):
        args = {"command": str(args)}
    return {"name": name, "args": args}
