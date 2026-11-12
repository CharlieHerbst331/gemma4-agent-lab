"""Summarize dev-13 GPU runs from their downloaded Kaggle outputs.

Usage:
    uv run python scripts/handoff/analyze_dev13.py RUN_DIR [RUN_DIR ...] [--json out.json]

RUN_DIR is a folder from fetch_dev13.sh (it holds task_results.jsonl, run_manifest.json and
results/traces/trace_<task>.json). Label a run with LABEL=RUN_DIR. Without a label, the folder
name is used. A trailing -s<N> in the label is the seed; runs with the same remaining label
are grouped into one arm.

Per run it reports: resolved, empty diffs, mean / p90 / max wall seconds, context
compactions (prompt tokens dropping below 65% of the previous turn), failed edit_file calls
(missing-parameter parse failures plus other non-ok results), identical repeated calls, loop
tasks (3 or more identical repeats), tool outputs over 4k chars, and turns at the output cap.
Then a per-task R/F/E matrix (resolved / failed / empty diff) and per-arm means.

Gate: the 12 h Kaggle limit over 129 tasks needs a mean wall of about 300 s or less.
Ported from the box notes v22/work/paired.py and metrics.py (Nov 11, 2026).
"""

import collections
import glob
import json
import os
import re
import statistics
import sys

DEV13 = "configs/cohorts/dev-13-environment-screened.json"
FREE_TOOLS = ("get_status", "submit_patch")


def trace_metrics(path: str, output_cap: int) -> dict:
    with open(path) as handle:
        steps = json.load(handle)["steps"]
    calls, prompt_tokens = [], []
    compactions = max_completion = cap_turns = 0
    previous = None
    for step in steps[2:]:
        metrics = step.get("metrics") or {}
        prompt = metrics.get("prompt_tokens")
        completion = metrics.get("completion_tokens") or 0
        max_completion = max(max_completion, completion)
        if completion >= output_cap:
            cap_turns += 1
        if prompt:
            if previous and prompt < 0.65 * previous:
                compactions += 1
            previous = prompt
            prompt_tokens.append(prompt)
        observation = (step.get("observation") or {}).get("content", "")
        for call in step.get("tool_calls") or []:
            args = json.dumps(call.get("arguments"), sort_keys=True)
            calls.append((call["function_name"], args, observation))
    counted = [c for c in calls if c[0] not in FREE_TOOLS]
    seen = collections.Counter(c[0] + c[1] for c in counted)
    first_edit = None
    for index, (name, args, out) in enumerate(counted, 1):
        ok_edit = name in ("edit_file", "write_file") and '"status": "ok"' in out
        ok_heredoc = name == "run_command" and "line_fix.py" in args and "OK" in out
        if ok_edit or ok_heredoc:
            first_edit = index
            break
    return {
        "calls": len(counted),
        "first_edit": first_edit,
        "compactions": compactions,
        "max_prompt_tokens": max(prompt_tokens) if prompt_tokens else 0,
        "identical_repeats": sum(v - 1 for v in seen.values() if v > 1),
        "edit_param_fail": sum(1 for c in calls if "mandatory input parameters" in c[2]),
        "edit_fail": sum(1 for c in calls if c[0] == "edit_file" and '"status": "ok"' not in c[2]),
        "budget_rejected": sum(1 for c in calls if "BudgetExceeded" in c[2]),
        "big_outputs": sum(1 for c in counted if len(c[2]) > 4000),
        "max_completion_tokens": max_completion,
        "cap_turns": cap_turns,
    }


def output_cap(run_dir: str) -> int:
    for path in glob.glob(f"{run_dir}/**/agent.yaml", recursive=True):
        match = re.search(r"max_output_tokens:\s*(\d+)", open(path).read())
        if match:
            return int(match.group(1))
    return 8192


def p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, -(-9 * len(ordered) // 10) - 1)]


def analyze(label: str, run_dir: str, tasks: list[str]) -> dict | None:
    found = glob.glob(f"{run_dir}/**/task_results.jsonl", recursive=True)
    if not found:
        print(f"- {label}: no task_results.jsonl under {run_dir}", file=sys.stderr)
        return None
    rows = {}
    for line in open(found[0]):
        if line.strip():
            row = json.loads(line)
            rows[row.get("instance_id") or row.get("task_id")] = row
    manifest_paths = glob.glob(f"{run_dir}/**/run_manifest.json", recursive=True)
    sha = json.load(open(manifest_paths[0])).get("sha256", "?") if manifest_paths else "?"
    cap = output_cap(run_dir)
    per_task = {}
    for path in glob.glob(f"{run_dir}/**/traces/trace_*.json", recursive=True):
        per_task[os.path.basename(path)[6:-5]] = trace_metrics(path, cap)
    walls = [float(rows[t].get("duration_seconds") or 0) for t in tasks if t in rows]
    status = {}
    for task in tasks:
        row = rows.get(task)
        if row is None:
            status[task] = "?"
        elif row.get("resolved"):
            status[task] = "R"
        elif row.get("patch_chars", 1) == 0:
            status[task] = "E"
        else:
            status[task] = "F"
    total = lambda key: sum(m[key] for m in per_task.values())  # noqa: E731
    first_edits = [m["first_edit"] for m in per_task.values() if m["first_edit"]]
    return {
        "run": label,
        "dir": run_dir,
        "sha256": sha,
        "tasks_present": len(walls),
        "resolved": sum(1 for s in status.values() if s == "R"),
        "empty": sum(1 for s in status.values() if s == "E"),
        "mean_wall": statistics.mean(walls) if walls else 0.0,
        "p90_wall": p90(walls) if walls else 0.0,
        "max_wall": max(walls) if walls else 0.0,
        "compactions": total("compactions"),
        "failed_edits": total("edit_fail"),
        "edit_param_fail": total("edit_param_fail"),
        "identical_repeats": total("identical_repeats"),
        "loop_tasks": sum(1 for m in per_task.values() if m["identical_repeats"] >= 3),
        "big_outputs": total("big_outputs"),
        "cap_turns": total("cap_turns"),
        "median_first_edit": statistics.median(first_edits) if first_edits else None,
        "status": status,
        "per_task": per_task,
    }


def main(argv: list[str]) -> int:
    json_out = None
    if "--json" in argv:
        index = argv.index("--json")
        json_out = argv[index + 1]
        argv = argv[:index] + argv[index + 2 :]
    if not argv:
        print(__doc__)
        return 2
    tasks = json.load(open(DEV13))
    results = []
    for arg in argv:
        label, _, path = arg.rpartition("=") if "=" in arg else ("", "", arg)
        label = label or os.path.basename(os.path.normpath(path))
        result = analyze(label, path, tasks)
        if result:
            results.append(result)
    if not results:
        return 1
    print(
        "| run | sha | resolved | empty | mean wall | p90 wall | max wall | compactions |"
        " failed edits (param) | identical repeats | loop tasks | outputs >4k | cap turns |"
    )
    print("|---" * 13 + "|")
    for r in results:
        incomplete = "" if r["tasks_present"] == len(tasks) else f" ({r['tasks_present']} tasks)"
        print(
            f"| {r['run']} | {r['sha256'][:8]} | {r['resolved']}/{len(tasks)}{incomplete} |"
            f" {r['empty']} | {r['mean_wall']:.0f}s | {r['p90_wall']:.0f}s | {r['max_wall']:.0f}s"
            f" | {r['compactions']} | {r['failed_edits']} ({r['edit_param_fail']}) |"
            f" {r['identical_repeats']} | {r['loop_tasks']} | {r['big_outputs']} |"
            f" {r['cap_turns']} |"
        )
    print("\n| task | " + " | ".join(r["run"] for r in results) + " |")
    print("|---" * (len(results) + 1) + "|")
    for task in tasks:
        print(f"| {task} | " + " | ".join(r["status"][task] for r in results) + " |")
    arms: dict[str, list[dict]] = {}
    for r in results:
        arms.setdefault(re.sub(r"-s\d+$", "", r["run"]), []).append(r)
    print()
    for arm, runs in arms.items():
        solved = [r["resolved"] for r in runs]
        means = [r["mean_wall"] for r in runs]
        sd = statistics.stdev(solved) if len(solved) > 1 else 0.0
        gate = "PASS" if statistics.mean(means) <= 300 else "FAIL"
        print(
            f"- {arm}: seeds={len(runs)} resolved {solved} mean {statistics.mean(solved):.2f}"
            f" sd {sd:.2f} | mean wall {statistics.mean(means):.0f}s"
            f" (runs {[round(m) for m in means]}) | 300 s gate {gate}"
        )
    if json_out:
        with open(json_out, "w") as handle:
            json.dump(results, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
