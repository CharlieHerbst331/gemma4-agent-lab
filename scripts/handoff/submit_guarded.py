"""Guarded competition submission. The only sanctioned way to spend a daily slot.

Usage:
    uv run python scripts/handoff/submit_guarded.py ARCHIVE --evaluation RUN_DIR \
        [--evaluation RUN_DIR ...] --message "structured-v22-1 main <commit> ..." [--execute]

Without --execute it only checks and prints the plan. With --execute it calls
`gemma-lab submit --execute`, which adds its own checks: one upload per UTC day (Kaggle
history plus the local ledger runs/submissions.jsonl), complete task results with no
infrastructure errors, and a 129-task runtime projection.

This script refuses before that when:
  1. the archive sha256 is listed in handoff/scored-archives.json (already submitted), or
     its first 8 hex chars appear in any Kaggle submission description;
  2. no --evaluation folder is a complete dev-13 run of this exact archive (run_manifest
     sha256 matches and all 13 dev task IDs are present);
  3. no such run has a mean wall time of 300 s or less per task (the 12 h limit over 129
     tasks plus model load). Every matching run is printed so a lucky seed is visible.

The message always gets "sha <first 8>" appended if missing, so guard 1 keeps working.
After a successful upload, add the archive to handoff/scored-archives.json in a PR.
"""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPETITION = "gemma-4-developer-agent"
DEV13 = ROOT / "configs/cohorts/dev-13-environment-screened.json"
LEDGER = ROOT / "handoff/scored-archives.json"
MEAN_GATE_SECONDS = 300.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kaggle_env() -> dict:
    """Same token handling as kaggle_env.sh: a KGAT_ token must be in KAGGLE_API_TOKEN."""
    env = dict(os.environ)
    home = Path(env.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
    if not env.get("KAGGLE_API_TOKEN") and env.get("KAGGLE_KEY", "").startswith("KGAT_"):
        env["KAGGLE_API_TOKEN"] = env["KAGGLE_KEY"]
    access = home / "access_token"
    config = home / "kaggle.json"
    has_access = access.is_file() and access.stat().st_size > 0
    if not env.get("KAGGLE_API_TOKEN") and not has_access and config.is_file():
        key = json.loads(config.read_text()).get("key", "")
        if key.startswith("KGAT_"):
            env["KAGGLE_API_TOKEN"] = key
    if env.get("KAGGLE_API_TOKEN") or has_access:
        env.pop("KAGGLE_KEY", None)
    return env


def kaggle_history(env: dict) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "kaggle", "competitions", "submissions", COMPETITION, "--csv"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"REFUSED: cannot read Kaggle submission history: {proc.stderr[-400:]}")
    return proc.stdout


def check_runs(digest: str, folders: list[str]) -> list[tuple[str, float, int]]:
    tasks = set(json.loads(DEV13.read_text()))
    good = []
    for folder in folders:
        base = Path(folder)
        manifests = sorted(base.glob("**/run_manifest.json"))
        if not manifests:
            print(f"  {folder}: no run_manifest.json")
            continue
        manifest = json.loads(manifests[0].read_text())
        if manifest.get("sha256") != digest:
            print(f"  {folder}: different archive ({str(manifest.get('sha256'))[:8]})")
            continue
        results = manifests[0].parent / "task_results.jsonl"
        rows = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
        seen = {r.get("instance_id") for r in rows}
        if not tasks <= seen:
            print(f"  {folder}: missing dev-13 tasks {sorted(tasks - seen)}")
            continue
        walls = [float(r.get("duration_seconds") or 0) for r in rows if r["instance_id"] in tasks]
        mean = statistics.mean(walls)
        solved = sum(1 for r in rows if r["instance_id"] in tasks and r.get("resolved"))
        print(f"  {folder}: resolved {solved}/13, mean wall {mean:.0f}s, max {max(walls):.0f}s")
        good.append((folder, mean, solved))
    return good


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("archive")
    parser.add_argument("--evaluation", action="append", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    archive = Path(args.archive).resolve()
    digest = sha256(archive)
    print(f"archive {archive}\nsha256  {digest}")

    listed = [r for r in json.loads(LEDGER.read_text())["archives"] if r["sha256"] == digest]
    if listed:
        raise SystemExit(f"REFUSED: archive already submitted: {listed[0]}")
    env = kaggle_env()
    history = kaggle_history(env)
    if digest[:8] in history:
        raise SystemExit("REFUSED: this sha prefix appears in Kaggle submission history")
    print("guard 1 ok: archive never submitted")

    print("dev-13 runs of this archive:")
    runs = check_runs(digest, args.evaluation)
    if not runs:
        raise SystemExit("REFUSED: no complete dev-13 run of this exact archive")
    passing = [r for r in runs if r[1] <= MEAN_GATE_SECONDS]
    if not passing:
        raise SystemExit(f"REFUSED: no dev-13 run has mean wall <= {MEAN_GATE_SECONDS:.0f}s")
    arm_mean = statistics.mean(r[1] for r in runs)
    print(
        f"guard 2 ok: {len(passing)}/{len(runs)} runs under the gate; all-seed mean {arm_mean:.0f}s"
    )
    if arm_mean > MEAN_GATE_SECONDS:
        print("WARNING: the mean across all seeds is over the gate. Expect a 12 h timeout risk.")

    message = args.message if digest[:8] in args.message else f"{args.message} sha {digest[:8]}"
    evaluation = min(passing, key=lambda r: r[1])[0]
    command = [
        "uv", "run", "gemma-lab", "submit", str(archive),
        "--message", message, "--evaluation", evaluation,
    ]  # fmt: skip
    if not args.execute:
        print("PLAN ONLY (add --execute to upload):\n  " + " ".join(command + ["--execute"]))
        return 0
    proc = subprocess.run(command + ["--execute"], env=env, cwd=ROOT)
    if proc.returncode == 0:
        print(f"Submitted. Now add {digest} to handoff/scored-archives.json in a PR.")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
