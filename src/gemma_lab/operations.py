import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
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
            pair_manifest = output / "pair_manifest.json"
            rows = output / "task_results.jsonl"
            if pair_manifest.exists():
                from gemma_lab.paired import summarize_pair_run

                result["paired"] = summarize_pair_run(output)
            elif rows.exists():
                result["metrics"] = summary(load_results(rows))
            write_json(output / "collection.json", result)
            if "KernelWorkerStatus.COMPLETE" not in status:
                raise RuntimeError(f"Notebook failed; inspect {output / 'execution.log'}")
            return result
        time.sleep(min(interval_seconds, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"Run still pending after {timeout_minutes} minutes: {kernel}")


# Submit/promotion gates use the measured per-task mean. They are not a
# precondition for dev GPU runs, and the per-task cap never blocks.
# Overhead is added only to the 120-task block and the worst-case warning:
#   120 * (mean + overhead) <= 11 h
#   L + 129 * mean <= 10.8 h          (no overhead)
#   L + 129 * (cap_wall + overhead) > 12 h warns only
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
    overhead = float(overhead)
    load, load_source = model_load_seconds(manifest)
    # Blocks use the measured mean. Overhead is not part of the 129-task block.
    projected = (mean + overhead) * PROJECTED_HIDDEN_TASKS
    combined = load + PROJECTED_PUBLIC_TASKS * mean
    cap = cap_wall_seconds(archive)
    # The cap feeds the warning only. It is never compared against a block limit.
    worst = None if cap is None else load + PROJECTED_PUBLIC_TASKS * (cap + overhead)
    return {
        "basis": "measured_mean",
        "applies_at": "submit_or_promotion",
        "dev_gpu_precondition": False,
        "blocks_use_cap_wall": False,
        "mean_seconds": mean,
        "n_tasks": len(durations),
        "L_seconds": load,
        "L_source": load_source,
        "scorer_overhead_seconds_per_task": overhead,
        "overhead_in_120_block": True,
        "overhead_in_129_block": False,
        "overhead_in_worst_case_warn": True,
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
            f"{PROJECTED_PUBLIC_TASKS} × mean {report['mean_seconds']:.2f} s), "
            "which exceeds the 10.8 hour limit"
        )
    if reasons:
        raise ValueError("Refusing upload: " + "; ".join(reasons))
    if report["worst_case_warn"]:
        print(
            "Warning: worst-case runtime "
            f"{report['worst_case_seconds'] / 3600:.2f} h exceeds 12 hours "
            f"(model load {report['L_seconds']:.0f} s + "
            f"{PROJECTED_PUBLIC_TASKS} × (cap {report['cap_wall_seconds']:.0f} s + "
            f"{report['scorer_overhead_seconds_per_task']:g} s scorer overhead)). "
            "The per-task cap does not block the upload.",
            file=sys.stderr,
        )
    return report


def resolve_submission_evaluation(archive, evaluation, arm=None):
    """Select the result folder whose archive hash matches the submission.

    A single-arm directory that already holds ``run_manifest.json`` and
    ``task_results.jsonl`` is used as-is. A pair run root holds
    ``pair_manifest.json`` and one folder per arm at ``results/<arm>/r<k>/``.
    Each of those folders has its own manifest. The folder whose ``sha256``
    equals the archive is the one ``submit --evaluation`` can check. ``arm``
    limits the search to that label.
    """
    evaluation = Path(evaluation)
    if not evaluation.is_dir():
        raise ValueError(f"Evaluation directory does not exist: {evaluation}")
    pair_root = (evaluation / "pair_manifest.json").is_file()
    direct_manifest = evaluation / "run_manifest.json"
    direct_rows = evaluation / "task_results.jsonl"
    if direct_manifest.is_file() and direct_rows.is_file() and not pair_root:
        return evaluation
    results = evaluation / "results"
    if not pair_root and not results.is_dir():
        return evaluation
    digest = sha256(Path(archive))
    matches = []
    if results.is_dir():
        for manifest_path in sorted(results.glob("*/*/run_manifest.json")):
            folder = manifest_path.parent
            if not (folder / "task_results.jsonl").is_file():
                continue
            try:
                recorded = json.loads(manifest_path.read_text())
            except json.JSONDecodeError as exc:
                raise ValueError(f"Unreadable arm manifest: {manifest_path}") from exc
            if not isinstance(recorded, dict) or recorded.get("sha256") != digest:
                continue
            label = str(recorded.get("arm") or folder.parent.name)
            if arm is not None and label != str(arm) and folder.parent.name != str(arm):
                continue
            matches.append(folder)
    if arm is not None and not matches:
        raise ValueError(
            f"No completed results for arm {arm} whose run_manifest sha256 matches the archive"
        )
    if not matches:
        raise ValueError(
            "Pair results have no arm folder whose run_manifest sha256 matches the archive. "
            "Point --evaluation at results/<arm>/r<k>, or pass the pair root with the "
            "archive of the arm that passed."
        )
    if len(matches) > 1:
        listed = ", ".join(str(path.relative_to(evaluation)) for path in matches)
        raise ValueError(
            "Multiple arm result folders match this archive ("
            + listed
            + "). Pass that results/<arm>/r<k> directory as --evaluation."
        )
    return matches[0]


def check_evaluation(
    archive, evaluation, scorer_overhead_seconds=DEFAULT_SCORER_OVERHEAD_SECONDS, *, arm=None
):
    from gemma_lab.metrics import load_results, summary

    if evaluation is None:
        raise ValueError("Actual upload requires --evaluation with completed GPU outputs")
    evaluation = resolve_submission_evaluation(archive, evaluation, arm=arm)
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
        sibling = evaluation / f"{row['instance_id']}.json"
        if not detail_path.is_file() and sibling.is_file():
            detail_path = sibling
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
    result["evaluation_dir"] = str(evaluation)
    if manifest.get("arm"):
        result["arm"] = manifest["arm"]
    result["projection"] = {
        "ok_120": projection["ok_120"],
        "P_ok": projection["P_ok"],
        "worst_case_warn": projection["worst_case_warn"],
    }
    return result


_TIMEOUT_NOTE = (
    "Upload timed out and may have been received. Check Kaggle's submissions list before retrying."
)
_AMBIGUOUS_NOTE = (
    "Upload error is ambiguous and the file may have been received. "
    "Check Kaggle's submissions list before retrying."
)
_MAX_RECORDED_CHARS = 4000
_ENV_LITERAL_NAMES = ("KAGGLE_KEY", "KAGGLE_API_TOKEN", "KAGGLE_USERNAME")
_KGAT_TOKEN = re.compile(r"KGAT_[A-Za-z0-9_-]+")
_URL_QUERY = re.compile(r"(https?://[^\s?#]+)\?[^\s#]*")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=_-]+"),
    re.compile(r"(?i)['\"]Authorization['\"]\s*:\s*['\"](?:Basic\s+)?[^'\"]+['\"]"),
    re.compile(r"(?i)\b(?:Authorization|Proxy-Authorization)\s*:\s*(?:Basic\s+)?\S+"),
    re.compile(r"(?i)\b(?:Cookie|Set-Cookie|X-Api-Key)\s*:\s*\S+"),
    re.compile(
        r"(?im)^[ \t]*(?:authorization|proxy-authorization|cookie|set-cookie"
        r"|x-api-key)\s*:.*$"
    ),
    re.compile(r"KGAT_[A-Za-z0-9_-]+"),
    re.compile(r"ya29\.\S+"),
    re.compile(
        r"""(?i)["'](?:key|api_key|token|access_token|client_secret|password)["']"""
        r"""\s*:\s*["'][^"']*["']"""
    ),
    re.compile(r"(?i)\bclient_secret\s*[=:]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9_.-]{1,64}:[0-9a-fA-F]{32}\b"),
    re.compile(
        r"(?i)\b(?:KAGGLE_(?:API_)?(?:TOKEN|KEY|SECRET)|KAGGLE_USERNAME|"
        r"(?:api[_-]?)?(?:access[_-]?)?token|api[_-]?key|secret|password|"
        r"refresh[_-]?token)\s*[=:]\s*\S+"
    ),
    re.compile(r"(?i)X-Goog-(?:Signature|Credential|Algorithm|Date|Expires|SignedHeaders)=\S+"),
    re.compile(r"(?i)[?&](?:token|access_token|api_key|key|signature|expires)=[^&\s]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[0-9a-fA-F]{32}\b"),
)


def _env_literals() -> list[str]:
    """Secret strings currently in the environment. Values under 4 characters are ignored."""
    found: list[str] = []
    for name in _ENV_LITERAL_NAMES:
        value = os.environ.get(name) or ""
        if len(value) >= 4:
            found.append(value)
    for value in os.environ.values():
        if not value:
            continue
        found.extend(match for match in _KGAT_TOKEN.findall(value) if len(match) >= 4)
    return sorted(set(found), key=len, reverse=True)


def _cap_text(text: str) -> str:
    if len(text) <= _MAX_RECORDED_CHARS:
        return text
    omitted = len(text) - _MAX_RECORDED_CHARS
    return text[:_MAX_RECORDED_CHARS] + f"[truncated {omitted} chars]"


def _scrub_secrets(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    for literal in _env_literals():
        text = text.replace(literal, "[REDACTED]")
    text = _URL_QUERY.sub(r"\1?[REDACTED]", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return _cap_text(text)


def _failure_text(exc: BaseException) -> str:
    """Scrubbed submit error, including an HTTP body when the client exposes one."""
    parts = [str(exc).strip()]
    response = getattr(exc, "response", None)
    body = getattr(response, "text", None) if response is not None else None
    if isinstance(body, str) and body.strip() and body.strip() not in parts[0]:
        parts.append(body.strip())
    return _scrub_secrets("\n".join(part for part in parts if part)) or "submit failed"


_HTTP_CODE = r"[45]\d{2}"
# Code in an HTTP-error shape. A reason phrase alone is not a status.
_HTTP_STATUS_PATTERNS = (
    re.compile(rf"\b({_HTTP_CODE})\s+(?:Client|Server)\s+Error\b"),
    re.compile(rf"\bHTTP/1\.[0-9]\s+({_HTTP_CODE})\b"),
    re.compile(rf"\bstatus[\s_-]*code\s*[:=]\s*({_HTTP_CODE})\b"),
    re.compile(rf"""["']code["']\s*:\s*({_HTTP_CODE})\b"""),
    re.compile(rf"\(({_HTTP_CODE})\)\s*Reason\s*:"),
)
# One phrase per code for 400-431 and 451, skipping unassigned codes. 29 in all.
_CLIENT_REASONS: tuple[tuple[int, str], ...] = (
    (400, "Bad Request"),
    (401, "Unauthorized"),
    (402, "Payment Required"),
    (403, "Forbidden"),
    (404, "Not Found"),
    (405, "Method Not Allowed"),
    (406, "Not Acceptable"),
    (407, "Proxy Authentication Required"),
    (408, "Request Timeout"),
    (409, "Conflict"),
    (410, "Gone"),
    (411, "Length Required"),
    (412, "Precondition Failed"),
    (413, "Payload Too Large"),
    (414, "URI Too Long"),
    (415, "Unsupported Media Type"),
    (416, "Range Not Satisfiable"),
    (417, "Expectation Failed"),
    (418, "I'm a Teapot"),
    (421, "Misdirected Request"),
    (422, "Unprocessable Entity"),
    (423, "Locked"),
    (424, "Failed Dependency"),
    (425, "Too Early"),
    (426, "Upgrade Required"),
    (428, "Precondition Required"),
    (429, "Too Many Requests"),
    (431, "Request Header Fields Too Large"),
    (451, "Unavailable For Legal Reasons"),
)
# Older and current registry names for the same codes.
_CLIENT_REASON_ALIASES: tuple[tuple[int, str], ...] = (
    (413, "Request Entity Too Large"),
    (413, "Content Too Large"),
    (414, "Request-URI Too Long"),
    (416, "Requested Range Not Satisfiable"),
    (418, "I'm a teapot"),
)
_SERVER_REASONS: tuple[tuple[int, str], ...] = (
    (500, "Internal Server Error"),
    (501, "Not Implemented"),
    (502, "Bad Gateway"),
    (503, "Service Unavailable"),
    (504, "Gateway Timeout"),
    (505, "HTTP Version Not Supported"),
    (506, "Variant Also Negotiates"),
    (507, "Insufficient Storage"),
    (508, "Loop Detected"),
    (510, "Not Extended"),
    (511, "Network Authentication Required"),
)
# Start of a line (leading whitespace allowed), or after HTTP, status, error:, or
# failed:. The anchor is case-insensitive; the reason phrase is not. A code merely
# near a reason word is not a status, so "Error 404 Not Found in log line" does not match.
_HTTP_ERROR_ANCHOR = (
    r"(?im)(?:^\s*"
    r"|\bHTTP(?:/1\.[0-9]|/2)?(?:\s+Error)?\s+"
    r"|\bstatus(?:[\s_-]*code)?\s*[:=]?\s*"
    r"|\b(?:error|failed)\s*:\s*"
    r")"
)


def _code_reason_pattern(code_class: str, phrases: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(set(phrases), key=len, reverse=True)
    alternation = "|".join(re.escape(phrase) for phrase in ordered)
    phrase = rf"\b({code_class})(?!\d)\s*[-:]?\s*(?:{alternation})\b"
    return re.compile(_HTTP_ERROR_ANCHOR + "(?-i:" + phrase + ")")


_SERVER_CODE_PHRASE = _code_reason_pattern(
    r"5\d{2}", tuple(phrase for _code, phrase in _SERVER_REASONS)
)
_CLIENT_CODE_PHRASE = _code_reason_pattern(
    r"4\d{2}",
    tuple(phrase for _code, phrase in (*_CLIENT_REASONS, *_CLIENT_REASON_ALIASES)),
)
# Orphan mkstemp files from a SIGKILL. A few minutes avoids deleting a live write.
_LEDGER_TEMP_AGE_SECONDS = 180
_LEDGER_TEMP_SUFFIX = re.compile(r"^[A-Za-z0-9_]{8}$")


def _cli_text(exc: BaseException) -> str:
    parts = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        body = getattr(response, "text", None)
        if isinstance(body, str):
            parts.append(body)
    for attr in ("stderr", "stdout", "output"):
        value = getattr(exc, attr, None)
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return "\n".join(parts)


def _response_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else None
    if isinstance(status, int) and 400 <= status <= 599:
        return status
    return None


def _statuses_in_text(text: str) -> list[int]:
    """Status codes in HTTP-error form. 5xx phrases are collected first."""
    found: list[int] = []
    for match in _SERVER_CODE_PHRASE.finditer(text):
        found.append(int(match.group(1)))
    for pattern in _HTTP_STATUS_PATTERNS:
        for match in pattern.finditer(text):
            found.append(int(match.group(1)))
    for match in _CLIENT_CODE_PHRASE.finditer(text):
        found.append(int(match.group(1)))
    return found


def _http_class(exc: BaseException) -> str | None:
    """``4xx``, ``5xx``, or None. A response status wins over the message text.

    Any recognised 5xx is reserved, even when a 4xx reason also appears.
    """
    status = _response_status(exc)
    if status is None:
        found = _statuses_in_text(_cli_text(exc))
        if any(500 <= code <= 599 for code in found):
            return "5xx"
        if any(400 <= code <= 499 for code in found):
            return "4xx"
        return None
    if 500 <= status <= 599:
        return "5xx"
    if 400 <= status <= 499:
        return "4xx"
    return None


def _definite_submit_failure(exc: BaseException) -> bool:
    """True only for an HTTP 4xx client error.

    5xx stays reserved: the upload may already have been received. So do a
    connection error, a traceback, an unknown error, and a number that is not
    an HTTP status.
    """
    if isinstance(
        exc, (subprocess.TimeoutExpired, UnicodeDecodeError, ConnectionError, TimeoutError)
    ):
        return False
    if isinstance(exc, requests.RequestException) and not isinstance(exc, requests.HTTPError):
        return False
    return _http_class(exc) == "4xx"


def _ambiguous_note(exc: BaseException) -> str:
    prefix = _TIMEOUT_NOTE if isinstance(exc, subprocess.TimeoutExpired) else _AMBIGUOUS_NOTE
    return _scrub_secrets(f"{prefix} {exc}")


def _corrupt_block_reasons(line: str, digest: str | None, today: str) -> list[str]:
    reasons = []
    if "submitted" in line:
        reasons.append('"submitted"')
    if "reserved" in line:
        reasons.append('"reserved"')
    if today and today in line:
        reasons.append(f"today's UTC date {today}")
    prefix = (digest or "")[:12]
    if len(prefix) >= 12 and prefix in line:
        reasons.append(f"archive sha256 prefix {prefix}")
    return reasons


def _corrupt_ledger_message(ledger: Path, line_number: int, reasons: list[str]) -> str:
    where = f"Unparseable ledger line {line_number} in {ledger}."
    if reasons:
        why = ", ".join(reasons)
        return (
            f"{where} It blocks because it contains {why}. Repair the line before retrying. "
            "--allow-corrupt-ledger does not skip a line that contains "
            '"submitted", "reserved", today\'s UTC date, or this archive\'s sha256 prefix.'
        )
    return (
        f"{where} Repair the line, or rerun with --allow-corrupt-ledger. "
        "That flag still refuses a line that contains "
        '"submitted", "reserved", today\'s UTC date, or this archive\'s sha256 prefix.'
    )


def _read_ledger(
    ledger: Path, *, allow_corrupt: bool = False, digest: str | None = None
) -> list[dict]:
    """Parse the ledger. An unparseable line fails closed unless explicitly allowed.

    With ``allow_corrupt``, a line is still an error when it contains
    ``submitted``, ``reserved``, today's UTC date, or the archive sha256 prefix.
    Corrupt lines are never rewritten or deleted.
    """
    if not ledger.exists():
        return []
    today = datetime.now(UTC).date().isoformat()
    rows = []
    # Invalid bytes become U+FFFD so the repair hint can name the line. A raw
    # UnicodeDecodeError would hide that hint. A line that still contains
    # U+FFFD is unparseable: "subm\ufffditted" would otherwise load as JSON
    # and slip past the daily guard.
    # Known limitation: JSON truncated mid-string is unparseable, but if the
    # cut removes "submitted", "reserved", today's UTC date, and the sha256
    # prefix, --allow-corrupt-ledger skips that line.
    text = ledger.read_text(encoding="utf-8", errors="replace")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        unparseable = "\ufffd" in line
        item = None
        if not unparseable:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                unparseable = True
        if unparseable:
            reasons = _corrupt_block_reasons(line, digest, today)
            if reasons or not allow_corrupt:
                raise ValueError(_corrupt_ledger_message(ledger, line_number, reasons)) from None
            warnings.warn(
                f"Skipping unparseable ledger line {line_number} in {ledger} "
                "because --allow-corrupt-ledger was set",
                stacklevel=2,
            )
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _fsync_directory(directory: Path) -> None:
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            warnings.warn(f"Could not fsync directory {directory}: {exc}", stacklevel=2)
    finally:
        os.close(dir_fd)


def _is_own_ledger_temp(name: str, ledger_name: str) -> bool:
    """True for this tool's mkstemp files, ``.{ledger}.{8 chars}``, and nothing else."""
    prefix = f".{ledger_name}."
    if not name.startswith(prefix):
        return False
    return _LEDGER_TEMP_SUFFIX.fullmatch(name[len(prefix) :]) is not None


def _cleanup_old_ledger_temps(path: Path) -> None:
    """Remove SIGKILL leftovers that match this ledger's mkstemp names."""
    directory = path.parent
    if not directory.is_dir():
        return
    cutoff = time.time() - _LEDGER_TEMP_AGE_SECONDS
    for candidate in directory.iterdir():
        if not candidate.is_file() or not _is_own_ledger_temp(candidate.name, path.name):
            continue
        try:
            if candidate.stat().st_mtime > cutoff:
                continue
            candidate.unlink()
        except OSError:
            continue


def _append_ledger(ledger: Path, row: dict) -> None:
    _cleanup_old_ledger_temps(ledger)
    prefix = ""
    if ledger.exists() and ledger.stat().st_size:
        with ledger.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                prefix = "\n"
    with ledger.open("a") as handle:
        handle.write(prefix + json.dumps(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(ledger.parent)


def _atomic_write(path: Path, text: str | bytes) -> None:
    """Write ``text`` via a same-directory temp file, then replace the target."""
    data = text.encode("utf-8") if isinstance(text, str) else text
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup_old_ledger_temps(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(directory)


def _same_ledger_row(item: dict, row: dict) -> bool:
    row_id = row.get("id")
    if row_id:
        return item.get("id") == row_id
    created_at = row.get("created_at")
    digest = row.get("sha256")
    if not created_at or not digest:
        return False
    return item.get("created_at") == created_at and item.get("sha256") == digest


def _replace_ledger_row(ledger: Path, row: dict) -> None:
    """Replace the row with the same id. Other lines, including garbage, stay."""
    raw_lines = ledger.read_bytes().splitlines() if ledger.exists() else []
    target = None
    for index, raw_line in enumerate(raw_lines):
        line = raw_line.decode("utf-8", errors="replace")
        if not line.strip() or "\ufffd" in line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and _same_ledger_row(item, row):
            target = index
            break
    if target is None:
        raise ValueError(
            f"Ledger row id={row.get('id')!r} created_at={row.get('created_at')!r} "
            f"sha256={row.get('sha256')!r} was not found in {ledger}. "
            "The reserved line was not rewritten."
        )
    raw_lines[target] = json.dumps(row).encode("utf-8")
    _atomic_write(ledger, b"\n".join(raw_lines) + b"\n")


def submit(
    archive,
    message,
    ledger=Path("runs/submissions.jsonl"),
    execute=False,
    evaluation=None,
    scorer_overhead_seconds=DEFAULT_SCORER_OVERHEAD_SECONDS,
    allow_corrupt_ledger=False,
    arm=None,
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
        archive, evaluation, scorer_overhead_seconds=scorer_overhead_seconds, arm=arm
    )
    # Reserve before upload so a timeout, where the file may already have been received,
    # cannot cause an automatic duplicate. A definite submit error is recorded as failed
    # and does not consume the local daily slot. The local lock serializes this user's
    # processes; Kaggle remains authoritative for team usage.
    import fcntl

    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = kaggle("competitions", "submissions", COMPETITION, "--csv")
        if submissions_today(history):
            raise ValueError("Kaggle daily submission slot already used")
        previous = _read_ledger(ledger, allow_corrupt=allow_corrupt_ledger, digest=digest)
        day = datetime.now(UTC).date().isoformat()
        if any(
            r["created_at"].startswith(day) and r["status"] in {"reserved", "submitted"}
            for r in previous
        ):
            raise ValueError("Local daily slot reserved/used; reconcile history before retrying")
        if any(r.get("sha256") == digest and r["status"] == "submitted" for r in previous):
            raise ValueError("Identical archive already submitted")
        # Kaggle CreateSubmission rejects uploads whose file name is not submission.zip.
        with tempfile.TemporaryDirectory(prefix="gemma-lab-submit-") as temp_name:
            staged = Path(temp_name) / "submission.zip"
            try:
                os.link(archive, staged)
            except OSError:
                shutil.copyfile(archive, staged)
            if sha256(staged) != digest:
                raise RuntimeError("staged submission.zip hash does not match the source archive")
            plan["id"] = uuid.uuid4().hex
            plan["status"] = "reserved"
            _append_ledger(ledger, plan)
            try:
                output = kaggle(
                    "competitions",
                    "submit",
                    COMPETITION,
                    "-f",
                    staged,
                    "-m",
                    message,
                    timeout=600,
                )
            except Exception as exc:
                if _definite_submit_failure(exc):
                    text = _failure_text(exc)
                    plan = {**plan, "status": "failed", "error": text}
                    try:
                        _replace_ledger_row(ledger, plan)
                    except ValueError as missing:
                        raise RuntimeError(f"{text}\n{missing}") from exc
                    raise RuntimeError(text) from exc
                note = _ambiguous_note(exc)
                plan = {**plan, "status": "reserved", "error": note}
                try:
                    _replace_ledger_row(ledger, plan)
                except ValueError as missing:
                    raise RuntimeError(f"{note}\n{missing}") from exc
                raise RuntimeError(note) from exc
            plan = {**plan, "status": "submitted", "response": _scrub_secrets(output or "")}
            _append_ledger(ledger, plan)
    return plan
