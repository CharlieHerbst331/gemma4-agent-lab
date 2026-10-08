"""Publish allowlisted observations, never raw tasks, patches, traces, or logs."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

REPOS = {"fastapi/fastapi", "Textualize/rich", "psf/requests", "encode/httpx"}
STATES = ["COMPLETE", "ERROR", "CANCEL_ACKNOWLEDGED", "RUNNING", "QUEUED"]


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def digest(value, size=64):
    return (
        value
        if isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(size) + "}", value)
        else None
    )


def number(value):
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def task_row(row):
    identifier = row.get("instance_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9]+_[0-9]+", identifier):
        raise ValueError("Unrecognized task identifier; refuse arbitrary text export")
    if row.get("repo") not in REPOS or not isinstance(row.get("resolved"), bool):
        raise ValueError("Unrecognized repository/result")
    result = {"instance_id": identifier, "repo": row["repo"], "resolved": row["resolved"]}
    for field in ["tool_calls", "duration_seconds", "patch_chars", "test_exit_code"]:
        if number(row.get(field)) is not None:
            result[field] = row[field]
    failure = row.get("failure_class")
    if failure in {"agent_budget", "infrastructure_or_harness"}:
        result["recorded_failure_class"] = failure
    # Only record presence: raw errors can contain grading-patch code or tracebacks.
    result["runner_error_recorded"] = bool(row.get("agent_error") or row.get("error"))
    return result


def export_run(folder):
    collection = read_json(folder / "collection.json")
    manifest = read_json(folder / "run_manifest.json")
    sdk = read_json(folder / "sdk_preflight.json")
    rows_path = folder / "task_results.jsonl"
    rows = (
        [task_row(json.loads(line)) for line in rows_path.read_text().splitlines() if line.strip()]
        if rows_path.exists()
        else []
    )
    identifiers = [r["instance_id"] for r in rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate task results")
    status = str(collection.get("status", ""))
    result = {
        "run_id": folder.name,
        "kind": "official-task-evaluation" if rows else "infrastructure-preflight",
        "collection_state": next(
            (s for s in STATES if "KernelWorkerStatus." + s in status), "UNKNOWN"
        ),
        "archive_sha256": digest(manifest.get("sha256")),
        "source_git_revision": digest(manifest.get("git_revision"), 40),
        "task_source_sha256": digest(manifest.get("task_file_sha256")),
        "task_results": rows,
    }
    kernel = collection.get("kernel")
    if isinstance(kernel, str) and re.fullmatch(r"[a-zA-Z0-9_-]+/[a-z0-9-]+", kernel):
        result["kaggle_notebook_url"] = "https://www.kaggle.com/code/" + kernel
    if rows:
        result["summary"] = {
            "tasks": len(rows),
            "resolved": sum(r["resolved"] for r in rows),
            "duration_seconds": sum(r.get("duration_seconds", 0) for r in rows),
            "counted_tool_calls": sum(r.get("tool_calls", 0) for r in rows),
            "recorded_agent_budget_failures": sum(
                r.get("recorded_failure_class") == "agent_budget" for r in rows
            ),
            "recorded_infrastructure_failures": sum(
                r.get("recorded_failure_class") == "infrastructure_or_harness" for r in rows
            ),
        }
    packages = manifest.get("packages", {})
    result["packages"] = {
        k: v
        for k, v in packages.items()
        if k in {"swegemma", "adk-submission", "adk-eval-core", "google-adk", "vllm"}
        and isinstance(v, str)
        and re.fullmatch(r"[0-9A-Za-z.+-]{1,40}", v)
    }
    hardware = manifest.get("hardware", {})
    if isinstance(hardware.get("gpu_count"), int):
        result["hardware"] = {
            "gpu_count": hardware["gpu_count"],
            "gpu_names": [n for n in hardware.get("gpu_names", []) if n == "NVIDIA L4"],
            "tensor_parallel_size": number(hardware.get("tensor_parallel_size")),
        }
    if sdk:
        result["sdk_preflight"] = {
            k: sdk[k]
            for k in ["compile_ok", "model_inference", "competition_tasks", "all_checks_passed"]
            if isinstance(sdk.get(k), bool)
        }
    # Bind public observations to private raw evidence without disclosing contents.
    result["private_evidence_hashes"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [rows_path, folder / "run_manifest.json", folder / "sdk_preflight.json"]
        if p.exists()
    }
    return result


def export(source, output):
    runs = [export_run(p) for p in sorted(Path(source).iterdir()) if p.is_dir()]
    result = {
        "schema_version": 1,
        "scope": (
            "Own evaluation observations and provenance only. No dataset, issue text, "
            "repository snapshot, reference/test patch, generated patch, trace, log, "
            "credential, weight or archive contents."
        ),
        "metric_caveat": (
            "Recorded error classes are historical collector labels; see RUN_CATALOG.md "
            "for diagnosed omissions and misclassifications. These small dev cohorts "
            "are not leaderboard scores."
        ),
        "runs": runs,
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return len(runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="runs/kaggle")
    parser.add_argument("--output", default="evidence/run-results.json")
    args = parser.parse_args()
    print("Exported", export(args.source, args.output), "redacted run summaries")
