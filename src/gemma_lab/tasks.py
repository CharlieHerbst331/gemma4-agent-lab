"""Frozen group splits and answer-free task exports."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from gemma_lab.common import sha256, write_json

AGENT_FIELDS = {"instance_id", "repo", "base_commit", "problem_statement", "hints_text"}


def read_tasks(path):
    tasks = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    ids = [t["instance_id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate task IDs")
    for task in tasks:
        for field in ["repo", "base_commit", "problem_statement"]:
            if not task.get(field):
                raise ValueError(f"Missing {field}: {task['instance_id']}")
    return tasks


def split_tasks(path, output, seed=42, holdout_repo=None):
    tasks = read_tasks(path)
    partitions = {"train": [], "dev": [], "holdout": []}
    for task in tasks:
        group = f"{task['repo']}@{task['base_commit']}"
        fraction = int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:8], 16) / 2**32
        if holdout_repo:
            bucket = (
                "holdout"
                if task["repo"] == holdout_repo
                else ("train" if fraction < 0.8 else "dev")
            )
        else:
            bucket = "train" if fraction < 0.7 else ("dev" if fraction < 0.85 else "holdout")
        partitions[bucket].append(task["instance_id"])
    if holdout_repo and not partitions["holdout"]:
        raise ValueError(f"Holdout repository not present: {holdout_repo}")
    result = {
        "seed": seed,
        "task_file_sha256": sha256(Path(path)),
        "grouping": "repo+base_commit",
        "holdout_repo": holdout_repo,
        "partitions": {k: sorted(v) for k, v in partitions.items()},
        "repos": dict(Counter(t["repo"] for t in tasks)),
    }
    write_json(Path(output), result)
    return result


def export_tasks(path, splits_path, partition, output, for_agent=True):
    splits = json.loads(Path(splits_path).read_text())
    if sha256(Path(path)) != splits["task_file_sha256"]:
        raise ValueError("Task file changed since split creation; freeze a new split")
    ids = set(splits["partitions"][partition])
    selected = [t for t in read_tasks(path) if t["instance_id"] in ids]
    if for_agent:
        selected = [{k: v for k, v in t.items() if k in AGENT_FIELDS} for t in selected]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("".join(json.dumps(t) + "\n" for t in selected))
    return len(selected)
