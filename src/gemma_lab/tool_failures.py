"""Tool-protocol failure counts for a smoke pair report.

Events come from the existing trace parser (ATIF, the synthetic gemma-lab
trace, or the small ADK-like shape). A failed skill call is ``run_skill_script``
whose output is ``INVALID_ARGUMENTS`` or a check.py usage / corrected-example
error. A failed edit is ``edit_file`` whose output contains the harness sentence
``mandatory input parameters`` (``Invoking `edit_file()` failed as the following
mandatory input parameters are not present``) or a ``missing-parameter`` error.
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
    if "mandatory input parameters" in lowered:
        return True
    return "missing-parameter" in lowered or "missing parameter" in lowered


def _failed(event) -> bool:
    return is_failed_skill(event) or is_failed_edit(event)


def summarize_events(events) -> dict:
    """Counts, the longest adjacent failure streak, and the tail streak.

    ``max_consecutive_failures`` is the longest run of adjacent failures.
    A later success does not shrink it. ``tail_streak`` is the run of
    failures at the end of the event list.
    """
    failed_skill = 0
    failed_edit = 0
    submit_patch = 0
    streak = 0
    max_streak = 0
    for event in events:
        if getattr(event, "tool", "") == "submit_patch":
            submit_patch += 1
        if is_failed_skill(event):
            failed_skill += 1
        if is_failed_edit(event):
            failed_edit += 1
        if _failed(event):
            streak += 1
            if streak > max_streak:
                max_streak = streak
            continue
        streak = 0
    tail = 0
    for event in reversed(list(events)):
        if not _failed(event):
            break
        tail += 1
    return {
        "failed_skill_calls": failed_skill,
        "failed_edit_calls": failed_edit,
        "max_consecutive_failures": max_streak,
        "tail_streak": tail,
        "submit_patch_count": submit_patch,
    }


def unrecovered_loop(summary, patch, hit_cap) -> bool:
    """True when the tool-failure loop was not recovered.

    A later successful skill or edit call does not clear the flag. The run
    is unrecovered when it hit the cap (timed out, or it never called
    ``submit_patch``), when the saved patch is empty or scratch-only, or
    when the tail streak is at least 3. The streak column stays the max.
    """
    if hit_cap or summary["submit_patch_count"] == 0:
        return True
    if patch in {"empty", "scratch-only"}:
        return True
    return summary["tail_streak"] >= 3


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
                    rows.append(_task_row(Path(run_dir), arm_dir.name, repeat_dir, task_id))
                except Exception:
                    continue
    rows.sort(key=lambda item: (item["arm"], item["repeat"], item["task_id"]))
    return rows


def tool_failure_lines(rows) -> list[str]:
    lines = [
        "## Tool-call failures",
        "",
        "unrecovered loop is true when the run hit the cap (timed out or never "
        "called submit_patch), or the saved patch is empty or scratch-only, or "
        "the tail streak of failed skill or edit_file calls at the end of the "
        "run is at least 3. max streak is the longest adjacent failure streak.",
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


def _task_row(run_dir: Path, arm: str, folder: Path, task_id: str) -> dict:
    payload = _read_json(_trace_path(folder, task_id))
    summary = summarize_trace(payload)
    summary.pop("trace_schema", None)
    patch_path = folder / "patches" / f"{task_id.replace('/', '__')}.patch"
    text = patch_path.read_text() if patch_path.is_file() else ""
    kind = patch_kind(text)
    hit_cap = _task_hit_cap(run_dir, arm, folder, task_id)
    return {
        "arm": arm,
        "repeat": folder.name,
        "task_id": task_id,
        "patch": kind,
        **summary,
        "unrecovered_loop": unrecovered_loop(summary, kind, hit_cap),
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


def _task_hit_cap(run_dir: Path, arm: str, folder: Path, task_id: str) -> bool:
    """Timed out, or the pair row says the wall or session cap was hit."""
    for row in _iter_jsonl(folder / "task_results.jsonl"):
        row_id = row.get("instance_id") or row.get("task_id")
        if row_id == task_id and _cap_row(row):
            return True
    repeat = _repeat_number(folder.name)
    for name in ("pair_results.jsonl", "timing.jsonl"):
        for row in _iter_jsonl(run_dir / name):
            if _same_run_row(row, arm, repeat, task_id) and _cap_row(row):
                return True
    return False


def _cap_row(row: dict) -> bool:
    hit = row.get("hit_cap")
    if isinstance(hit, dict) and (hit.get("wall") or hit.get("marker")):
        return True
    if str(row.get("failure_class") or "") == "agent_budget":
        return True
    text = " ".join(str(row.get(key) or "") for key in ("error", "agent_error", "error_message"))
    lowered = text.lower()
    return "exceeded session timeout" in lowered or "exceeded turns budget" in lowered


def _same_run_row(row: dict, arm: str, repeat: int | None, task_id: str) -> bool:
    row_task = row.get("task_id") or row.get("instance_id")
    if row_task != task_id or row.get("arm") != arm:
        return False
    if repeat is None:
        return True
    return row.get("repeat") in (repeat, f"r{repeat}")


def _repeat_number(name: str) -> int | None:
    if name.startswith("r") and name[1:].isdigit():
        return int(name[1:])
    if name.isdigit():
        return int(name)
    return None


def _iter_jsonl(path: Path):
    if not path.is_file():
        return
    try:
        text = path.read_text()
    except OSError:
        return
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            yield item
