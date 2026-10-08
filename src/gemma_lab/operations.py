import csv
import io
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

from gemma_lab.bundle import validate_archive
from gemma_lab.common import COMPETITION, STARTER, kaggle, now, sha256, write_json


def doctor(online=False):
    result = {
        "python": __import__("sys").version.split()[0],
        "uv": bool(shutil.which("uv")),
        "git": bool(shutil.which("git")),
        "docker": bool(shutil.which("docker")),
        "nvidia_smi": bool(shutil.which("nvidia-smi")),
        "free_disk_gib": round(shutil.disk_usage(".").free / 1024**3, 2),
        "kaggle_token_present": bool(os.getenv("KAGGLE_API_TOKEN"))
        or (Path.home() / ".kaggle/access_token").exists(),
    }
    if online:
        try:
            kaggle("competitions", "files", "-c", COMPETITION, "--page-size", "1")
            result["competition_access"] = "ok"
        except RuntimeError as exc:
            result["competition_access"] = str(exc)
        proc = subprocess.run(
            ["git", "ls-remote", "origin"], capture_output=True, text=True, timeout=30
        )
        result["github_remote_access"] = proc.returncode == 0
    return result


def fetch_starter():
    folder = Path("vendor/official/notebook")
    folder.mkdir(parents=True, exist_ok=True)
    return kaggle("kernels", "pull", STARTER, "-p", folder, "-m")


def fetch_files(names, folder=Path("data/competition")):
    folder.mkdir(parents=True, exist_ok=True)
    logs = []
    for name in names:
        logs.append(kaggle("competitions", "download", COMPETITION, "-f", name, "-p", folder))
    return logs


def research(query, output):
    headers = {"Accept": "application/vnd.github+json"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    response = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "updated", "per_page": 20},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    result = {
        "retrieved_at": now(),
        "query": query,
        "repositories": [
            {
                k: item.get(k)
                for k in [
                    "full_name",
                    "html_url",
                    "description",
                    "updated_at",
                    "stargazers_count",
                    "license",
                ]
            }
            for item in response.json().get("items", [])
        ],
        "competition_sources": [
            f"https://www.kaggle.com/competitions/{COMPETITION}/{section}"
            for section in ["overview", "rules", "discussion", "code", "leaderboard"]
        ],
    }
    for label, args in {
        "notebooks": ["kernels", "list", "--competition", COMPETITION, "--csv"],
        "leaderboard": ["competitions", "leaderboard", "-c", COMPETITION, "--show", "--csv"],
    }.items():
        try:
            result[label] = kaggle(*args)
        except RuntimeError as exc:
            result[label + "_error"] = str(exc)
    write_json(Path(output), result)
    return result


def submissions_today(text, day=None):
    day = day or datetime.now(UTC).date().isoformat()
    text = "\n".join(line for line in text.splitlines() if not line.startswith("Next Page Token ="))
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows and text.strip() and "no submissions" not in text.lower():
        raise ValueError("Unrecognized Kaggle submission history; refusing upload")
    if rows and "date" not in rows[0]:
        raise ValueError("Kaggle history has no date field; refusing upload")
    return [r for r in rows if str(r.get("date", "")).startswith(day)]


def upload_bundle(archive, owner, slug, output, execute=False, version=False):
    """Stage only the validated archive for a private Kaggle dataset."""
    import re

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", owner) or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("Invalid dataset owner or slug")
    validate_archive(archive)
    if output.exists() and list(output.iterdir()):
        raise ValueError("Dataset staging folder must be empty")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, output / f"{slug}.zip")
    write_json(
        output / "dataset-metadata.json",
        {
            "id": f"{owner}/{slug}",
            "title": slug.replace("-", " "),
            "licenses": [{"name": "Apache 2.0"}],
        },
    )
    if not execute:
        return {"dataset": f"{owner}/{slug}", "folder": str(output), "status": "staged"}
    args = ["datasets", "version" if version else "create", "-p", output, "--dir-mode", "skip"]
    if version:
        args += ["-m", "Bundle " + sha256(Path(archive))[:12]]
    return kaggle(*args, timeout=600)


def wait_for_run(kernel, output, timeout_minutes=45, interval_seconds=45):
    """Collect one existing run; no scheduling, retries of uploads, or new GPU launches."""
    import time

    from gemma_lab.metrics import load_results, summary

    if timeout_minutes <= 0 or interval_seconds < 10:
        raise ValueError("Positive timeout and polling interval >=10 seconds required")
    output.mkdir(parents=True, exist_ok=True)
    deadline, previous = time.monotonic() + timeout_minutes * 60, None
    while time.monotonic() < deadline:
        status = kaggle("kernels", "status", kernel)
        if status != previous:
            print(status.strip(), flush=True)
            previous = status
        if any(
            f"KernelWorkerStatus.{state}" in status
            for state in ["COMPLETE", "ERROR", "CANCEL_ACKNOWLEDGED"]
        ):
            kaggle("kernels", "output", kernel, "-p", output, timeout=600)
            (output / "execution.log").write_text(kaggle("kernels", "logs", kernel))
            result = {
                "kernel": kernel,
                "observed_at": now(),
                "status": status.strip(),
                "output": str(output),
            }
            rows = output / "task_results.jsonl"
            if rows.exists():
                result["metrics"] = summary(load_results(rows))
            write_json(output / "collection.json", result)
            if "KernelWorkerStatus.COMPLETE" not in status:
                raise RuntimeError(f"Notebook failed; inspect {output / 'execution.log'}")
            return result
        time.sleep(min(interval_seconds, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"Run still pending after {timeout_minutes} minutes: {kernel}")


# Two blocks, both using mean duration plus hosted scorer overhead:
# 120 hidden tasks stay at or under 11 hours, and model load plus 129 public
# tasks stay at or under 10.8 hours. A cap-based 12 hour worst case warns only.
PROJECTED_HIDDEN_TASKS = 120
PROJECTED_PUBLIC_TASKS = 129
PROJECTED_RUNTIME_LIMIT_SECONDS = 11 * 60 * 60
PROJECTED_LOAD_LIMIT_SECONDS = 38_880
WORST_CASE_WARN_SECONDS = 12 * 60 * 60
DEFAULT_MODEL_LOAD_SECONDS = 900
DEFAULT_SCORER_OVERHEAD_SECONDS = 70


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def task_durations(rows):
    if not rows:
        raise ValueError(
            "Refusing upload: evaluation has no task rows, so projected runtime cannot be checked"
        )
    missing = []
    durations = []
    for row in rows:
        value = row.get("duration_seconds")
        if not _finite_number(value):
            missing.append(row.get("instance_id", "?"))
        else:
            durations.append(float(value))
    if missing:
        raise ValueError(
            "Refusing upload: evaluation is missing duration_seconds for "
            + ", ".join(str(item) for item in missing)
            + ", so the projected total runtime cannot be checked"
        )
    return durations


def model_load_seconds(manifest):
    if not isinstance(manifest, dict) or "model_load_seconds" not in manifest:
        return float(DEFAULT_MODEL_LOAD_SECONDS), "default"
    value = manifest.get("model_load_seconds")
    if not _finite_number(value) or value < 0:
        raise ValueError(
            "Refusing upload: run_manifest.json model_load_seconds must be a non-negative number"
        )
    return float(value), "measured"


def cap_wall_seconds(archive):
    """Per-task wall cap from the packed eval_config, in seconds."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            text = bundle.read("eval_config.yaml").decode()
    except (KeyError, OSError, zipfile.BadZipFile, UnicodeError):
        return None
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        return None
    section = loaded.get("evaluation", loaded)
    if not isinstance(section, dict):
        return None
    minutes = section.get("max_time_minutes")
    if not _finite_number(minutes) or minutes < 0:
        return None
    return float(minutes) * 60


def runtime_projection(rows, manifest, archive, overhead):
    if not _finite_number(overhead) or overhead < 0:
        raise ValueError(
            "Refusing upload: scorer overhead must be a non-negative number of seconds"
        )
    durations = task_durations(rows)
    mean = sum(durations) / len(durations)
    adjusted = mean + float(overhead)
    load, load_source = model_load_seconds(manifest)
    projected = adjusted * PROJECTED_HIDDEN_TASKS
    combined = load + PROJECTED_PUBLIC_TASKS * adjusted
    cap = cap_wall_seconds(archive)
    worst = None if cap is None else load + PROJECTED_PUBLIC_TASKS * cap
    return {
        "mean_seconds": mean,
        "n_tasks": len(durations),
        "L_seconds": load,
        "L_source": load_source,
        "scorer_overhead_seconds_per_task": float(overhead),
        "P_seconds": combined,
        "P_limit": PROJECTED_LOAD_LIMIT_SECONDS,
        "P_ok": combined <= PROJECTED_LOAD_LIMIT_SECONDS,
        "projected_120_seconds": projected,
        "limit_120": PROJECTED_RUNTIME_LIMIT_SECONDS,
        "ok_120": projected <= PROJECTED_RUNTIME_LIMIT_SECONDS,
        "cap_wall_seconds": cap,
        "worst_case_seconds": worst,
        "worst_case_warn": worst is not None and worst > WORST_CASE_WARN_SECONDS,
    }


def check_projected_runtime(rows, manifest, archive, evaluation, overhead):
    report = runtime_projection(rows, manifest, archive, overhead)
    write_json(Path(evaluation) / "projection.json", report)
    reasons = []
    if not report["ok_120"]:
        reasons.append(
            "projected total runtime is "
            f"{report['projected_120_seconds'] / 3600:.2f} h "
            f"((mean {report['mean_seconds']:.2f} s/task + "
            f"{report['scorer_overhead_seconds_per_task']:g} s scorer overhead) "
            f"× {PROJECTED_HIDDEN_TASKS} tasks), which exceeds the 11 hour limit "
            "(1 hour margin under the 12 hour competition cap)"
        )
    if not report["P_ok"]:
        reasons.append(
            "projected load-adjusted runtime is "
            f"{report['P_seconds'] / 3600:.2f} h "
            f"(model load {report['L_seconds']:.0f} s [{report['L_source']}] + "
            f"{PROJECTED_PUBLIC_TASKS} × (mean {report['mean_seconds']:.2f} s + "
            f"{report['scorer_overhead_seconds_per_task']:g} s overhead)), "
            "which exceeds the 10.8 hour limit"
        )
    if reasons:
        raise ValueError("Refusing upload: " + "; ".join(reasons))
    if report["worst_case_warn"]:
        print(
            "Warning: worst-case runtime "
            f"{report['worst_case_seconds'] / 3600:.2f} h exceeds 12 hours "
            f"(model load {report['L_seconds']:.0f} s + "
            f"{PROJECTED_PUBLIC_TASKS} × cap {report['cap_wall_seconds']:.0f} s). "
            "This does not block the upload.",
            file=sys.stderr,
        )
    return report


def check_evaluation(archive, evaluation, scorer_overhead_seconds=DEFAULT_SCORER_OVERHEAD_SECONDS):
    from gemma_lab.metrics import load_results, summary

    if evaluation is None:
        raise ValueError("Actual upload requires --evaluation with completed GPU outputs")
    evaluation = Path(evaluation)
    manifest = json.loads((evaluation / "run_manifest.json").read_text())
    if manifest["sha256"] != sha256(Path(archive)):
        raise ValueError("Evaluation archive hash does not match submission")
    rows = load_results(evaluation / "task_results.jsonl")
    if {r["instance_id"] for r in rows} != set(manifest["task_ids"]):
        raise ValueError("Evaluation task set is incomplete or mismatched")
    # Normalize an older collector's turn-budget classification without changing raw files.
    for row in rows:
        message = row.get("error") or row.get("agent_error") or ""
        if any(
            marker in message.lower()
            for marker in ["exceeded session timeout", "exceeded turns budget"]
        ):
            row["failure_class"] = "agent_budget"
            row.pop("error", None)
    if any(r.get("error") or r.get("failure_class") == "infrastructure_or_harness" for r in rows):
        raise ValueError("Resolve evaluation infrastructure errors before uploading")
    # Also inspect official diagnostics: older collectors omitted returned failures.
    for row in rows:
        detail_path = evaluation / "results" / f"{row['instance_id']}.json"
        if detail_path.exists():
            detail = json.loads(detail_path.read_text())
            runner_error = detail.get("error_message") or ""
            if runner_error and not any(
                marker in runner_error.lower()
                for marker in ["exceeded session timeout", "exceeded turns budget"]
            ):
                raise ValueError(
                    "Resolve returned evaluation infrastructure errors before uploading"
                )
            if "recursive dependency involving fixture 'httpbin'" in (
                detail.get("test_output") or ""
            ) and "b/tests/conftest.py" not in (detail.get("agent_patch") or ""):
                raise ValueError(
                    "Resolve official verification httpbin fixture errors before uploading"
                )
    projection = check_projected_runtime(
        rows, manifest, archive, evaluation, scorer_overhead_seconds
    )
    result = summary(rows)
    result["projection"] = {
        "ok_120": projection["ok_120"],
        "P_ok": projection["P_ok"],
        "worst_case_warn": projection["worst_case_warn"],
    }
    return result


def submit(
    archive,
    message,
    ledger=Path("runs/submissions.jsonl"),
    execute=False,
    evaluation=None,
    scorer_overhead_seconds=DEFAULT_SCORER_OVERHEAD_SECONDS,
):
    archive = Path(archive).resolve()
    validate_archive(archive)
    digest = sha256(archive)
    plan = {
        "competition": COMPETITION,
        "archive": str(archive),
        "sha256": digest,
        "message": message,
        "created_at": now(),
        "status": "planned",
    }
    if not execute:
        return plan
    plan["evaluation"] = check_evaluation(
        archive, evaluation, scorer_overhead_seconds=scorer_overhead_seconds
    )
    # Reserve before upload so an interrupted upload cannot cause an automatic duplicate.
    # The local lock serializes this user's processes; Kaggle remains authoritative for team usage.
    import fcntl

    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = kaggle("competitions", "submissions", COMPETITION, "--csv")
        if submissions_today(history):
            raise ValueError("Kaggle daily submission slot already used")
        previous = (
            [json.loads(line) for line in ledger.read_text().splitlines()]
            if ledger.exists()
            else []
        )
        day = datetime.now(UTC).date().isoformat()
        if any(
            r["created_at"].startswith(day) and r["status"] in {"reserved", "submitted"}
            for r in previous
        ):
            raise ValueError("Local daily slot reserved/used; reconcile history before retrying")
        if any(r.get("sha256") == digest and r["status"] == "submitted" for r in previous):
            raise ValueError("Identical archive already submitted")
        plan["status"] = "reserved"
        with ledger.open("a") as handle:
            handle.write(json.dumps(plan) + "\n")
        output = kaggle(
            "competitions", "submit", COMPETITION, "-f", archive, "-m", message, timeout=600
        )
        plan = {**plan, "status": "submitted", "response": output}
        with ledger.open("a") as handle:
            handle.write(json.dumps(plan) + "\n")
    return plan
