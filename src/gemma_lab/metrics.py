import json
import math
from collections import defaultdict
from pathlib import Path


def load_results(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    seen = set()
    for row in rows:
        if row["instance_id"] in seen:
            raise ValueError("Duplicate result IDs would bias scores")
        seen.add(row["instance_id"])
        if not isinstance(row.get("resolved"), bool):
            raise ValueError("Every task result needs an explicit boolean resolved")
    return rows


def summary(rows):
    n = len(rows)
    wins = sum(row["resolved"] for row in rows)
    if not n:
        raise ValueError("Cannot score an empty result set")
    p, z = wins / n, 1.96
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    repos = defaultdict(list)
    for row in rows:
        repos[row.get("repo", "unknown")].append(row)
    return {
        "tasks": n,
        "resolved": wins,
        "resolve_rate": p,
        "wilson_95": [center - radius, center + radius],
        "duration_seconds": sum(r.get("duration_seconds", 0) for r in rows),
        "tool_calls": sum(r.get("tool_calls", 0) for r in rows),
        "infrastructure_failures": sum(
            r.get("failure_class") == "infrastructure_or_harness" for r in rows
        ),
        "agent_budget_failures": sum(r.get("failure_class") == "agent_budget" for r in rows),
        "empty_patches": sum(r.get("patch_chars") == 0 for r in rows),
        "tasks_with_patch_measurement": sum("patch_chars" in r for r in rows),
        "by_repo": {
            repo: {"tasks": len(rs), "resolved": sum(r["resolved"] for r in rs)}
            for repo, rs in sorted(repos.items())
        },
    }


def compare(baseline, candidate):
    left = {r["instance_id"]: r for r in baseline}
    right = {r["instance_id"]: r for r in candidate}
    if left.keys() != right.keys():
        raise ValueError("Paired comparison requires identical task sets")
    wins = sorted(k for k in left if right[k]["resolved"] and not left[k]["resolved"])
    losses = sorted(k for k in left if left[k]["resolved"] and not right[k]["resolved"])
    return {
        "baseline": summary(baseline),
        "candidate": summary(candidate),
        "wins": wins,
        "regressions": losses,
        "net_wins": len(wins) - len(losses),
    }
