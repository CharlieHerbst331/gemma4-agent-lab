"""Offline file-hit proxy for structured-v14's map skill.

Train IDs come from configs/splits/public-v1.json. Gold files are every .py
path in the public GitHub pull request. Nothing is dropped because of a
directory name. This is not a model triage and not a competition score.

The zero-arg map does not receive the issue, so this run does not pass
keywords. Signature priority is top-level package files. Triage may name any
path the directory summary covers, so both arms rank the full Python listing.
The map arm also adds signature-token overlap for lines the map printed.
A hit means one gold .py file is in those three paths.
"""

from __future__ import annotations

import importlib.util
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPLIT = ROOT / "configs" / "splits" / "public-v1.json"
MAP_SCRIPT = ROOT / "agents" / "structured-v14" / "skills" / "map" / "scripts" / "run.py"
CACHE = Path("/tmp/map-hit-cache")
CLONES = Path("/tmp/map-repos")
WORK = Path("/tmp/map-work")
REPOS = {
    "fastapi": "fastapi/fastapi",
    "rich": "Textualize/rich",
    "requests": "psf/requests",
    "httpx": "encode/httpx",
}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
TOP_K = 3


def _map_module():
    spec = importlib.util.spec_from_file_location("structured_v14_map", MAP_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tokens(text):
    return {item.lower() for item in IDENT.findall(text or "")}


def path_tokens(path):
    return {item.lower() for item in re.split(r"[/_.]", path) if len(item) >= 3}


def parse_map(text):
    rows = {}
    dirs = []
    section = ""
    for line in text.splitlines():
        if line == "summary:":
            section = "summary"
            continue
        if line == "signatures:":
            section = "signatures"
            continue
        if section == "summary" and " files=" in line:
            dirs.append(line.split(" ", 1)[0])
            continue
        if section != "signatures" or ": " not in line:
            continue
        path, sig = line.split(": ", 1)
        names = []
        for part in sig.split(","):
            name = part.strip()
            if name and not name.startswith("["):
                names.append(name)
        rows[path] = names
    return rows, dirs


def mcnemar_p(left, right):
    """Two-sided exact McNemar p for discordant counts left vs right."""
    total = left + right
    if total == 0:
        return 1.0
    smaller = min(left, right)
    tail = sum(_comb(total, index) for index in range(smaller + 1))
    return min(1.0, 2 * tail / (2**total))


def _comb(total, choose):
    value = 1
    for index in range(choose):
        value = value * (total - index) // (index + 1)
    return value


def _covered(path, dirs):
    parent = path.rsplit("/", 1)[0] if "/" in path else "."
    for directory in dirs:
        if parent == directory or parent.startswith(directory + "/"):
            return True
    return False


def rank(paths, issue, signatures, k=TOP_K):
    scored = []
    for path in paths:
        sig_tokens = tokens(" ".join(signatures.get(path, [])))
        score = len(path_tokens(path) & issue) + len(sig_tokens & issue)
        scored.append((-score, path))
    scored.sort()
    return [path for _score, path in scored[:k]]


def _gh(path):
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / (path.replace("/", "_").replace("?", "_") + ".json")
    if cache.is_file():
        return json.loads(cache.read_text())
    proc = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        cache.write_text("null\n")
        return None
    cache.write_text(proc.stdout)
    return json.loads(proc.stdout)


def _gold(files):
    gold = []
    for item in files or []:
        name = item.get("filename") or ""
        if name.endswith(".py"):
            gold.append(name)
    return gold


def _ensure_tree(slug, sha):
    dest = WORK / slug.split("/")[-1] / sha
    marker = dest / ".map-ready"
    if marker.is_file():
        return dest
    clone = CLONES / slug.split("/")[-1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        subprocess.run(
            ["git", "-C", str(clone), "worktree", "remove", "--force", str(dest)],
            check=False,
        )
    fetch = subprocess.run(
        ["git", "-C", str(clone), "fetch", "--filter=blob:none", "origin", sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode != 0:
        raise RuntimeError(fetch.stderr.strip() or "fetch failed")
    add = subprocess.run(
        ["git", "-C", str(clone), "worktree", "add", "--detach", str(dest), sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or "worktree failed")
    marker.write_text("ok\n")
    return dest


def evaluate():
    module = _map_module()
    split = json.loads(SPLIT.read_text())
    rows = []
    trees = {}
    for task_id in split["partitions"]["train"]:
        prefix, number = task_id.split("_", 1)
        slug = REPOS[prefix]
        pull = _gh(f"repos/{slug}/pulls/{number}")
        files = _gh(f"repos/{slug}/pulls/{number}/files?per_page=100")
        if not isinstance(pull, dict) or not isinstance(files, list):
            rows.append({"id": task_id, "status": "no-pr"})
            continue
        gold = _gold(files)
        if not gold:
            rows.append({"id": task_id, "status": "no-py"})
            continue
        sha = pull["base"]["sha"]
        key = (slug, sha)
        if key not in trees:
            try:
                dest = _ensure_tree(slug, sha)
            except RuntimeError as exc:
                trees[key] = {"error": str(exc)}
            else:
                module.render(dest)
                started = time.perf_counter()
                mapped = module.render(dest)
                elapsed = time.perf_counter() - started
                listing = [path.relative_to(dest).as_posix() for path in module.python_files(dest)]
                trees[key] = {
                    "map": mapped,
                    "listing": listing,
                    "seconds": elapsed,
                    "chars": len(mapped),
                }
        tree = trees[key]
        if "error" in tree:
            rows.append({"id": task_id, "status": "checkout-failed", "error": tree["error"]})
            continue
        issue = tokens(f"{pull.get('title') or ''}\n{pull.get('body') or ''}")
        signatures, dirs = parse_map(tree["map"])
        baseline = rank(tree["listing"], issue, {})
        mapped = rank(tree["listing"], issue, signatures)
        row = {
            "id": task_id,
            "status": "scored",
            "gold": gold,
            "baseline_hit": any(path in baseline for path in gold),
            "map_hit": any(path in mapped for path in gold),
            "dir_hit": any(_covered(path, dirs) for path in gold),
            "baseline": baseline,
            "mapped": mapped,
        }
        rows.append(row)
        print(
            f"{task_id} baseline={int(row['baseline_hit'])} map={int(row['map_hit'])}",
            file=sys.stderr,
            flush=True,
        )
    scored = [row for row in rows if row["status"] == "scored"]
    times = [item["seconds"] for item in trees.values() if "seconds" in item]
    summary = {
        "train_ids": len(split["partitions"]["train"]),
        "scored": len(scored),
        "skipped": {
            status: sum(row["status"] == status for row in rows)
            for status in ("no-pr", "no-py", "checkout-failed")
        },
        "baseline_hits": sum(row["baseline_hit"] for row in scored),
        "map_hits": sum(row["map_hit"] for row in scored),
        "dir_hits": sum(row["dir_hit"] for row in scored),
        "both": sum(row["baseline_hit"] and row["map_hit"] for row in scored),
        "baseline_only": sum(row["baseline_hit"] and not row["map_hit"] for row in scored),
        "map_only": sum(row["map_hit"] and not row["baseline_hit"] for row in scored),
        "neither": sum(not row["baseline_hit"] and not row["map_hit"] for row in scored),
        "mcnemar_p": mcnemar_p(
            sum(row["map_hit"] and not row["baseline_hit"] for row in scored),
            sum(row["baseline_hit"] and not row["map_hit"] for row in scored),
        ),
        "unique_trees": len(times),
        "map_seconds_median": statistics.median(times) if times else None,
        "map_seconds_max": max(times) if times else None,
        "map_seconds_mean": statistics.fmean(times) if times else None,
        "map_chars_max": max(
            (item["chars"] for item in trees.values() if "chars" in item), default=None
        ),
    }
    return {"summary": summary, "rows": rows}


def main():
    report = evaluate()
    json.dump(report["summary"], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
