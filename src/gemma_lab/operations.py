import csv
import io
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import requests

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


def submit(archive, message, ledger=Path("runs/submissions.jsonl"), execute=False):
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
