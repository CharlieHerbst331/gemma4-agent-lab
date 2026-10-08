"""Bounded task-scoped evidence, never a transcript or cross-task answer cache."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def identity(root):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
    ).stdout.strip()
    return hashlib.sha256((str(root.resolve()) + head).encode()).hexdigest()


def _update_locked(root, scratch, action, packet=None):
    root, scratch = Path(root).resolve(), Path(scratch).resolve()
    if not (root / ".git").exists() or not scratch.is_dir() or scratch.is_relative_to(root):
        raise ValueError("Require a Git workspace and scratch outside the workspace")
    path = scratch / "gemma-task-memory.json"
    if path.is_symlink():
        raise ValueError("Memory file must not be a symlink")
    task = identity(root)
    state = {
        "task": task,
        "hypothesis": "",
        "evidence": [],
        "rejected": [],
        "changed": [],
        "checks": [],
        "next_action": "",
        "navigation": [],
    }
    if path.exists():
        if path.stat().st_size > 16000:
            raise ValueError("Oversized ledger; do not load a transcript")
        prior = json.loads(path.read_text())
        if prior.get("task") == task:
            # Revalidate stored evidence as strictly as a new packet.
            if set(prior) != set(state):
                raise ValueError("Malformed stored ledger")
            for key, value in prior.items():
                if key == "task":
                    continue
                limit = {"evidence": 8, "rejected": 4, "changed": 12, "checks": 4, "navigation": 10}
                if key in {"hypothesis", "next_action"}:
                    valid = isinstance(value, str) and len(value) <= 400
                else:
                    valid = (
                        isinstance(value, list)
                        and len(value) <= limit[key]
                        and all(isinstance(x, str) and len(x) <= 240 for x in value)
                    )
                if not valid:
                    raise ValueError("Malformed stored evidence")
            if len(json.dumps(prior, ensure_ascii=True)) > 4200:
                raise ValueError("Stored ledger exceeds context bound")
            state = prior
    if action == "read":
        return state
    if action != "update" or not isinstance(packet, dict):
        raise ValueError("Use read or update with a JSON object packet")
    if set(packet) - (set(state) - {"task"}):
        raise ValueError("Unknown field; no transcript/reasoning/solution fields")
    for key, value in packet.items():
        if key in {"hypothesis", "next_action"}:
            if not isinstance(value, str) or len(value) > 400:
                raise ValueError("Decision text must be at most 400 characters")
            state[key] = value
        else:
            limits = {"evidence": 8, "rejected": 4, "changed": 12, "checks": 4, "navigation": 10}
            if (
                not isinstance(value, list)
                or len(value) > limits[key]
                or any(not isinstance(x, str) or len(x) > 240 for x in value)
            ):
                raise ValueError("Lists must contain bounded factual strings")
            state[key] = list(dict.fromkeys(value))
    payload = json.dumps(state, ensure_ascii=True)
    if len(payload) > 4200:
        raise ValueError("Ledger exceeds 4200 characters; compress evidence")
    fd, temporary = tempfile.mkstemp(prefix="gemma-memory-", dir=scratch)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return state


def update(root, scratch, action, packet=None):
    root, scratch = Path(root).resolve(), Path(scratch).resolve()
    if not scratch.is_dir() or scratch.is_relative_to(root):
        raise ValueError("Scratch must be outside workspace")
    descriptor = os.open(
        scratch / "gemma-task-memory.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _update_locked(root, scratch, action, packet)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["read", "update"], required=True)
    parser.add_argument("--packet", default="{}")
    parser.add_argument("--hypothesis")
    parser.add_argument("--next-action")
    for field in ["evidence", "rejected", "changed", "checks", "navigation"]:
        parser.add_argument("--" + field, action="append")
    parser.add_argument("--workspace", default=os.environ.get("PWD", "/workspace"))
    parser.add_argument("--scratch", default=os.environ.get("TEST_TMPDIR", tempfile.gettempdir()))
    args = parser.parse_args()
    try:
        if len(args.packet) > 12000:
            raise ValueError("Oversized packet")
        packet = json.loads(args.packet)
        if not isinstance(packet, dict):
            raise ValueError("packet must be an object")
        for field in [
            "hypothesis",
            "next_action",
            "evidence",
            "rejected",
            "changed",
            "checks",
            "navigation",
        ]:
            if getattr(args, field) is not None:
                packet[field] = getattr(args, field)
        result = update(args.workspace, args.scratch, args.action, packet)
        print(json.dumps({"ok": True, "memory": result}, ensure_ascii=True))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:500]}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
