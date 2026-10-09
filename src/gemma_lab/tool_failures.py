"""Tool-protocol failure counts for a smoke pair report.

Events come from the existing trace parser (ATIF, the synthetic gemma-lab
trace, or the small ADK-like shape). A failed skill call is ``run_skill_script``
whose output is ``INVALID_ARGUMENTS`` or a check.py usage / corrected-example
error. A failed edit is ``edit_file`` whose output is a missing-parameter error.
"""

from __future__ import annotations

import json
from pathlib import Path

from gemma_lab.hygiene.diffparse import parse_diff
from gemma_lab.hygiene.rules import _is_scratch
from gemma_lab.hygiene.trace import parse_trace

_NOT_APPLICABLE = "not applicable for smoke"


def is_failed_skill(event) -> bool:
    if getattr(event, "tool", "") != "run_skill_script":
        return False
    text = str(getattr(event, "output", "") or "")
    lowered = text.lower()
    if "invalid_arguments" in lowered:
        return True
    if "usage:" in lowered:
        return True
    if "corrected example" in lowered:
        return True
    return False


def is_failed_edit(event) -> bool:
    if getattr(event, "tool", "") != "edit_file":
        return False
    lowered = str(getattr(event, "output", "") or "").lower()
    return "missing-parameter" in lowered or "missing parameter" in lowered


def _recovers(event) -> bool:
    """A later successful skill or edit call ends an unrecovered loop."""
    if is_failed_skill(event) or is_failed_edit(event):
        return False
    return getattr(event, "tool", "") in {"run_skill_script", "edit_file"}


def summarize_events(events) -> dict:
    """Counts, the longest adjacent failure streak, and whether it was recovered."""
    failed_skill = 0
    failed_edit = 0
    submit_patch = 0
    streak = 0
    max_streak = 0
    recovered = False
    for event in events:
        if getattr(event, "tool", "") == "submit_patch":
            submit_patch += 1
        failed = is_failed_skill(event) or is_failed_edit(event)
        if is_failed_skill(event):
            failed_skill += 1
        if is_failed_edit(event):
            failed_edit += 1
        if failed:
            streak += 1
            if streak >= max_streak:
                max_streak = streak
                recovered = False
            continue
        if streak and streak == max_streak and _recovers(event):
            recovered = True
        streak = 0
    return {
        "failed_skill_calls": failed_skill,
        "failed_edit_calls": failed_edit,
        "max_consecutive_failures": max_streak,
        "unrecovered_loop": max_streak >= 2 and not recovered,
        "submit_patch_count": submit_patch,
    }


def patch_kind(text) -> str:
    """``empty``, ``scratch-only``, or ``other``."""
    if text is None or not str(text).strip():
        return "empty"
    try:
        files = parse_diff(str(text))
    except ValueError:
        return "other"
    paths = [item.path for item in files if item.path]
    if not paths:
        return "empty"
    if all(_is_scratch(path) for path in paths):
        return "scratch-only"
    return "other"


def summarize_trace(payload) -> dict:
    view = parse_trace(payload)
    summary = summarize_events(view.events)
    summary["trace_schema"] = view.schema
    return summary


def collect_tool_failures(run_dir) -> list[dict]:
    """One row per arm, repeat, and task found under ``results/``. Never raises."""
    rows = []
    try:
        results = Path(run_dir) / "results"
        if not results.is_dir():
            return rows
        arm_dirs = sorted(path for path in results.iterdir() if path.is_dir())
    except OSError:
        return rows
    for arm_dir in arm_dirs:
        try:
            repeat_dirs = sorted(path for path in arm_dir.iterdir() if path.is_dir())
        except OSError:
            continue
        for repeat_dir in repeat_dirs:
            for task_id in _task_ids(repeat_dir):
                try:
                    rows.append(_task_row(arm_dir.name, repeat_dir, task_id))
                except Exception:
                    continue
    rows.sort(key=lambda item: (item["arm"], item["repeat"], item["task_id"]))
    return rows


def tool_failure_lines(rows) -> list[str]:
    lines = [
        "## Tool-call failures",
        "",
        "| arm | repeat | task | failed skill | failed edit_file | "
        "max streak | unrecovered loop | submit_patch | patch |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    if not rows:
        lines.append("| | | | | | | | | |")
        return lines
    for row in rows:
        lines.append(
            "| {arm} | {repeat} | {task_id} | {failed_skill_calls} | {failed_edit_calls} | "
            "{max_consecutive_failures} | {unrecovered_loop} | {submit_patch_count} | "
            "{patch} |".format(**row)
        )
    return lines


def smoke_not_applicable() -> str:
    return _NOT_APPLICABLE


def _task_row(arm: str, folder: Path, task_id: str) -> dict:
    payload = _read_json(_trace_path(folder, task_id))
    summary = summarize_trace(payload)
    summary.pop("trace_schema", None)
    patch_path = folder / "patches" / f"{task_id.replace('/', '__')}.patch"
    text = patch_path.read_text() if patch_path.is_file() else ""
    return {
        "arm": arm,
        "repeat": folder.name,
        "task_id": task_id,
        "patch": patch_kind(text),
        **summary,
    }


def _task_ids(folder: Path) -> list[str]:
    found = []
    rows = folder / "task_results.jsonl"
    if rows.is_file():
        for line in rows.read_text().splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            task_id = item.get("instance_id") or item.get("task_id")
            if isinstance(task_id, str) and task_id not in found:
                found.append(task_id)
    if found:
        return found
    for directory, suffix in ((folder / "patches", ".patch"), (folder / "traces", ".json")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            name = path.name
            if not name.endswith(suffix):
                continue
            stem = name[: -len(suffix)]
            if suffix == ".json" and stem.startswith("trace_"):
                stem = stem[len("trace_") :]
            if stem and stem not in found:
                found.append(stem)
    return found


def _trace_path(folder: Path, task_id: str) -> Path | None:
    path = folder / "traces" / f"trace_{task_id.replace('/', '__')}.json"
    return path if path.is_file() else None


def _read_json(path: Path | None):
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text())
