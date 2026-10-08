"""Hash-pinned two-arm evaluation.

The notebook runtime section is copied verbatim into the generated notebook.
Generation-time checks live in this module and are unit-tested locally.
"""

from __future__ import annotations

import hashlib
import json
import re
from fnmatch import fnmatch
from pathlib import Path

import yaml

from gemma_lab.bundle import load_yaml
from gemma_lab.common import MODEL

# <<<NOTEBOOK_RUNTIME>>>
# Copied into the paired notebook. Keep this section limited to the standard
# library plus PyYAML, which the official starter already imports.

import hashlib as _hashlib
import inspect  # noqa: F401  # embedded notebook cell uses inspect.getsource
import io as _io
import json as _json
import os as _os
import signal as _signal
import tarfile as _tarfile
import time as _time
import warnings as _warnings
import zipfile as _zipfile
from pathlib import Path as _Path
from pathlib import PurePosixPath


class PinError(ValueError):
    """A hash, tree, or grading pin check failed closed."""


ORDER_RULE = "per_task_parity_v1"
BUDGET_KEYS = ("timeout_seconds", "max_tool_calls", "max_time_minutes", "max_turns")
BLOCK_THRESHOLD_P = 38880
BLOCK_THRESHOLD_MEAN120 = 11 * 3600
WARN_THRESHOLD_12H = 12 * 3600
PYTEST_COMMAND_LITERALS = (
    (
        "f'cd /workspace && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 "
        "python3 -s -m pytest {test_files_str} '"
    ),
    "f'--junitxml={junit_xml_path} '",
    "'-p no:anyio -o timeout=0 '",
    "'-o python_classes=\"Test* *Test\" -q'",
)
GRADING_MODULES = (
    ("swegemma.harness.verification", "swegemma/harness/verification.py"),
    ("swegemma.harness.container_setup", "swegemma/harness/container_setup.py"),
    ("swegemma.evaluate", "swegemma/evaluate.py"),
    ("swegemma.harness.agent_runner", "swegemma/harness/agent_runner.py"),
    ("swegemma.sandbox.subprocess", "swegemma/sandbox/subprocess.py"),
    ("adk_eval_core.sandbox.subprocess_sandbox", "adk_eval_core/sandbox/subprocess_sandbox.py"),
)
SCHEMA_MARKERS = ("schema", "compil", "invalid tool", "unknown tool", "function call")
CONTEXT_MARKERS = (
    "contextwindow",
    "context window",
    "context-window",
    "context length",
    "maximum context",
)
TOKEN_KEYS = (
    "total_prompt_tokens",
    "total_cached_prompt_tokens",
    "total_completion_tokens",
    "total_tokens",
    "llm_calls",
)


def schedule_document(entries):
    """Canonical JSON for the frozen schedule hash. pair_id is not included."""
    payload = [
        {
            "order": [str(arm) for arm in entry["order"]],
            "p0": int(entry["p0"]),
            "position": int(entry["position"]),
            "repeat": int(entry["repeat"]),
            "task_id": str(entry["task_id"]),
        }
        for entry in entries
    ]
    return _json.dumps(payload, sort_keys=True, separators=(",", ":"))


def schedule_sha256(entries):
    return _hashlib.sha256(schedule_document(entries).encode()).hexdigest()


def make_pair_id(schedule_hash, repeat, task_id):
    raw = f"{schedule_hash}{repeat}{task_id}".encode()
    return _hashlib.sha256(raw).hexdigest()[:16]


def build_schedule(task_ids, repeats=2, shuffle_seed=None):
    """Frozen-order schedule.

    Repeat numbers and positions are 1-based. Repeat 1 keeps the frozen order
    and repeat 2 reverses it. Arm A is first when (frozen index + 0-based
    repeat index) is even, which is the same parity as (1-based position index
    + 1-based repeat number).
    """
    if isinstance(repeats, int):
        repeat_numbers = list(range(1, repeats + 1))
    else:
        repeat_numbers = [int(number) for number in repeats]
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("Schedule task ids must be a nonempty unique list")
    if not repeat_numbers or any(number < 1 for number in repeat_numbers):
        raise ValueError("Repeat numbers must be positive")
    base = [str(task_id) for task_id in task_ids]
    if shuffle_seed is not None:
        import random

        mixer = random.Random(int(shuffle_seed))
        mixer.shuffle(base)
    index = {task_id: pos for pos, task_id in enumerate(base)}
    entries = []
    for repeat in repeat_numbers:
        r0 = repeat - 1
        order_ids = base if r0 % 2 == 0 else list(reversed(base))
        for position, task_id in enumerate(order_ids, start=1):
            p0 = index[task_id]
            first = "A" if (p0 + r0) % 2 == 0 else "B"
            entries.append(
                {
                    "repeat": repeat,
                    "position": position,
                    "task_id": task_id,
                    "p0": p0,
                    "order": [first, "B" if first == "A" else "A"],
                }
            )
    digest = schedule_sha256(entries)
    for entry in entries:
        entry["pair_id"] = make_pair_id(digest, entry["repeat"], entry["task_id"])
    return {"rule": ORDER_RULE, "task_ids": base, "entries": entries, "sha256": digest}


def assert_payload_hash(payload, expected):
    digest = _hashlib.sha256(payload).hexdigest()
    if digest != expected:
        raise PinError(f"pinned-hash mismatch before extraction: {digest} != {expected}")
    return digest


def _safe_extract(payload, dest):
    dest.mkdir(parents=True, exist_ok=False)
    with _zipfile.ZipFile(_io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            rel = PurePosixPath(info.filename)
            if rel.is_absolute() or ".." in rel.parts or "\\" in info.filename:
                raise PinError(f"Unsafe archive entry: {info.filename}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PinError("Archive symlinks are forbidden")
        archive.extractall(dest)


def verify_extracted_tree(root, manifest_files):
    """Re-hash extracted files. Refuse on a mismatch, an extra file, or a missing file."""
    root = _Path(root)
    found = {}
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise PinError(f"Extracted symlink is forbidden: {path}")
            if path.is_file():
                digest = _hashlib.sha256(path.read_bytes()).hexdigest()
                found[path.relative_to(root).as_posix()] = digest
    missing = sorted(set(manifest_files) - set(found))
    extra = sorted(set(found) - set(manifest_files))
    changed = sorted(
        name for name, digest in manifest_files.items() if found.get(name) not in {None, digest}
    )
    if missing or extra or changed:
        raise PinError(
            f"candidate tree mismatch: missing={missing} extra={extra} changed={changed}"
        )


def install_arm(payload, expected_sha256, dest, manifest_files):
    """Hash the packed bytes, then extract, then re-hash the tree."""
    assert_payload_hash(payload, expected_sha256)
    _safe_extract(payload, _Path(dest))
    verify_extracted_tree(dest, manifest_files)


def normalize_budgets(raw):
    if not isinstance(raw, dict):
        raise ValueError("eval_config budgets must be a mapping")
    missing = [key for key in BUDGET_KEYS if key not in raw]
    if missing:
        raise ValueError(f"eval_config is missing {missing}; refusing starter defaults")
    return {
        "timeout_seconds": int(raw["timeout_seconds"]),
        "max_tool_calls": int(raw["max_tool_calls"]),
        "max_time_minutes": float(raw["max_time_minutes"]),
        "max_turns": int(raw["max_turns"]),
    }


def read_arm_budgets(arm_dir):
    import yaml as _yaml

    text = (_Path(arm_dir) / "eval_config.yaml").read_text()
    loaded = _yaml.safe_load(text) or {}
    section = loaded.get("evaluation", loaded) if isinstance(loaded, dict) else loaded
    return normalize_budgets(section)


def src_layout_from_names(names):
    """True when src/<pkg>/__init__.py exists and <pkg>/__init__.py does not."""
    src_pkgs = set()
    root_pkgs = set()
    for name in names:
        parts = [part for part in str(name).split("/") if part not in {"", "."}]
        if len(parts) == 3 and parts[0] == "src" and parts[2] == "__init__.py":
            src_pkgs.add(parts[1])
        elif len(parts) == 2 and parts[1] == "__init__.py":
            root_pkgs.add(parts[0])
    flagged = sorted(pkg for pkg in src_pkgs if pkg not in root_pkgs)
    return bool(flagged), flagged


def list_tar_members(path):
    """Read tar member names only. Never extract."""
    with _tarfile.open(path, "r:*") as archive:
        return [member.name for member in archive.getmembers()]


def import_origin_risk(repo, repo_list, member_names=None):
    listed = repo in set(repo_list or [])
    listing = None
    packages = []
    if member_names is not None:
        listing, packages = src_layout_from_names(member_names)
        src_layout = listing
        source = "snapshot_listing"
    else:
        src_layout = listed
        source = "repo_list"
    record = {
        "src_layout": bool(src_layout),
        "source": source,
        "grading_origin": "host-likely" if src_layout else "workspace",
        "repo_list_src_layout": bool(listed),
        "snapshot_src_layout": listing,
        "snapshot_packages": packages,
        "disagreement": listing is not None and bool(listing) != bool(listed),
    }
    return record


def percentile(values, pct):
    xs = sorted(float(value) for value in values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    rank = (len(xs) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(xs) - 1)
    weight = rank - low
    return xs[low] * (1 - weight) + xs[high] * weight


def round2_scenario_seconds(
    load_seconds, n, fraction_at_cap, cap_seconds, delta_seconds, early_seconds=190.0
):
    """Round-2 runtime model: L + N * (f*(cap+Δ) + (1-f)*min(early, cap+Δ))."""
    at_cap = cap_seconds + delta_seconds
    per_task = fraction_at_cap * at_cap + (1 - fraction_at_cap) * min(early_seconds, at_cap)
    return load_seconds + n * per_task


def _mean(values):
    vals = [float(value) for value in values]
    if not vals:
        return None
    return sum(vals) / len(vals)


class TimingDashboard:
    """Recorder dashboard. The harness uses it for console routing only."""

    def __init__(self):
        self.context = None
        self.attached = False
        self.completed = None

    def attach_context(self, slot_id, context):
        self.context = context
        self.attached = True

    def task_completed(self, slot_id, resolved, duration, error, agent_duration=None):
        self.completed = {
            "slot_id": slot_id,
            "resolved": resolved,
            "duration": duration,
            "error": error,
            "agent_duration": agent_duration,
        }


def trace_summary(trace):
    if trace is None:
        return None
    for name in ("summary", "summarize"):
        method = getattr(trace, name, None)
        if callable(method):
            data = method()
            if isinstance(data, dict):
                return data
    return None


def trace_entries(trace):
    entries = getattr(trace, "entries", None)
    if entries is None:
        entries = getattr(trace, "_entries", None)
    return list(entries or [])


def token_fields(trace):
    summary = trace_summary(trace)
    if summary is None:
        return {key: None for key in TOKEN_KEYS}
    return {key: summary[key] if key in summary else None for key in TOKEN_KEYS}


ADK_SUBMISSION_MINIMUM = "0.2.11"
ADK_SUBMISSION_WARN_BELOW = "0.2.12"


def parse_version(text):
    """Numeric prefix of a version, missing pieces treated as zero."""
    parts = []
    for piece in str(text).split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def assert_adk_submission_version(version, minimum=ADK_SUBMISSION_MINIMUM):
    """Refuse adk-submission older than 0.2.11.

    Below 0.2.12 a thinking_budget ablation would not be honored.
    """
    found = parse_version(version)
    need = parse_version(minimum)
    if found < need:
        raise RuntimeError(
            f"adk-submission {version} is too old; this notebook requires "
            f"adk-submission>={minimum}."
        )
    if found < parse_version(ADK_SUBMISSION_WARN_BELOW):
        message = (
            f"adk-submission {version} is below {ADK_SUBMISSION_WARN_BELOW}; "
            "a thinking_budget ablation would not be honored."
        )
        print(message)
        _warnings.warn(message, UserWarning, stacklevel=2)
    return found


def timing_from_context(context, wall_seconds, cap_seconds, pre_call_overhead=0.0):
    setup = context.agent_start_time - context.task_start_time
    agent = float(context.agent_elapsed_seconds)
    spanned = context.agent_end_time - context.task_start_time
    post = wall_seconds - spanned - pre_call_overhead
    return _timing_record(wall_seconds, setup, agent, post, cap_seconds, source="dashboard")


def timing_from_trace(wall_seconds, t0_epoch, t1_epoch, trace, cap_seconds):
    entries = trace_entries(trace)
    stamps = []
    for entry in entries:
        stamp = getattr(entry, "timestamp", None)
        if stamp is None and isinstance(entry, dict):
            stamp = entry.get("timestamp")
        if stamp is not None:
            stamps.append(float(stamp))
    if not stamps:
        return _timing_record(wall_seconds, None, None, None, cap_seconds, source="trace_missing")
    first, last = stamps[0], stamps[-1]
    return _timing_record(
        wall_seconds,
        first - t0_epoch,
        last - first,
        t1_epoch - last,
        cap_seconds,
        source="trace",
    )


def _timing_record(wall, setup, agent, post, cap, source):
    agent_over = None if agent is None else max(0.0, agent - cap)
    wall_over = None if wall is None else wall - cap
    return {
        "timing_source": source,
        "timing_tier": 2 if source == "dashboard" else 1,
        "wall_seconds": wall,
        "setup_seconds": setup,
        "agent_seconds": agent,
        "post_agent_seconds": post,
        "grading_seconds": post,
        "overshoot_seconds": {"agent": agent_over, "wall": wall_over},
    }


def hit_cap_fields(wall_seconds, cap_seconds, error_text):
    text = (error_text or "").lower()
    return {
        "wall": wall_seconds is not None and wall_seconds >= cap_seconds,
        "marker": "exceeded session timeout" in text,
    }


def choose_timing(dashboard, wall, cap, pre_call, t0_epoch, t1_epoch, trace, requested_tier):
    if (
        requested_tier == 2
        and dashboard is not None
        and dashboard.attached
        and dashboard.context is not None
    ):
        context = dashboard.context
        if context.agent_start_time is not None and context.agent_end_time is not None:
            return timing_from_context(context, wall, cap, pre_call)
    if trace is not None and trace_entries(trace):
        return timing_from_trace(wall, t0_epoch, t1_epoch, trace, cap)
    return _timing_record(wall, None, None, None, cap, source="wall_only")


def parse_prefix_cache_metrics(text):
    samples = {}
    if not text:
        return samples
    for line in text.splitlines():
        if not line or line.startswith("#") or "prefix_cache" not in line:
            continue
        name, _, rest = line.partition(" ")
        metric = name.split("{", 1)[0]
        try:
            samples[metric] = float(rest.split()[0])
        except (ValueError, IndexError):
            continue
    return samples


def base_result_row(task, result):
    """Single-arm row fields. Keep this aligned with notebook.generate's loop."""
    patch = result.agent_patch or ""
    row = {
        "instance_id": task.instance_id,
        "repo": task.repo,
        "resolved": bool(result.resolved),
        "test_exit_code": result.test_exit_code,
        "patch_chars": len(patch),
        "tool_calls": result.tool_calls,
        "duration_seconds": result.duration_seconds,
    }
    runner_error = getattr(result, "error_message", None)
    if runner_error:
        row["agent_error"] = runner_error
        if any(
            marker in runner_error.lower()
            for marker in ("exceeded session timeout", "exceeded turns budget")
        ):
            row["failure_class"] = "agent_budget"
        else:
            row["failure_class"] = "infrastructure_or_harness"
            row["error"] = runner_error
    test_output = getattr(result, "test_output", None) or ""
    if (
        "recursive dependency involving fixture 'httpbin'" in test_output
        and "b/tests/conftest.py" not in patch
    ):
        row["failure_class"] = "infrastructure_or_harness"
        row["error"] = "Official verification httpbin fixture setup failed"
    return row, patch


def crash_row(task, exc):
    return {
        "instance_id": task.instance_id,
        "repo": getattr(task, "repo", None),
        "resolved": False,
        "error": repr(exc)[:500],
        "failure_class": "infrastructure_or_harness",
        "crashed": True,
    }


def _error_text(row):
    return " ".join(
        str(row.get(key) or "") for key in ("error", "agent_error", "test_output")
    ).lower()


def _is_infra(row):
    return row.get("failure_class") == "infrastructure_or_harness"


def _is_nonbudget_infra(row):
    return _is_infra(row)


def abort_code(arm_rows, cap_seconds, arm):
    """Round-2 abort predicates. Returns a status string or None.

    (a) and (b) abort the session. (c) and (d) stop only this arm.
    """
    if any(
        (row.get("wall_seconds") is not None) and row["wall_seconds"] > cap_seconds + 120
        for row in arm_rows
    ):
        return "aborted:budget_anomaly"
    infra = [row for row in arm_rows if _is_nonbudget_infra(row)]
    if len(infra) >= 2:
        return "aborted:infra"
    first = arm_rows[:4]
    if len(arm_rows) >= 4:
        texts = [_error_text(row) for row in first]
        empty = all(row.get("patch_chars") == 0 for row in first)
        schema = any(any(marker in text for marker in SCHEMA_MARKERS) for text in texts)
        if empty and schema:
            return f"aborted_arm:{arm}"
        window = sum(any(marker in text for marker in CONTEXT_MARKERS) for text in texts)
        if window >= 2:
            return f"aborted_arm:{arm}"
    return None


def repeat_is_valid(graded_without_infra, n_tasks):
    """At least 12 of 13 tasks graded without an infrastructure error.

    For a cohort of size N the same rule allows one miss: graded >= N - 1.
    """
    if n_tasks <= 0:
        return False
    return graded_without_infra >= n_tasks - 1


def early_stop_loser(rows_by_arm, n_tasks):
    """After a 13-task repeat, stop an arm that is 0/13 while the other is >= 3/13."""
    if n_tasks != 13 or set(rows_by_arm) != {"A", "B"}:
        return None
    for rows in rows_by_arm.values():
        if len(rows) != n_tasks or any(_is_infra(row) for row in rows):
            return None
    resolved = {
        arm: sum(bool(row.get("resolved")) for row in rows) for arm, rows in rows_by_arm.items()
    }
    if resolved["A"] == 0 and resolved["B"] >= 3:
        return "A"
    if resolved["B"] == 0 and resolved["A"] >= 3:
        return "B"
    return None


def pair_fits(elapsed, n_arms, cap_seconds, p90_delta, session_budget_seconds, pad_seconds):
    """True when every arm of the pair can finish inside the remaining session."""
    if n_arms <= 0:
        return True
    estimate = 30.0 if p90_delta is None else float(p90_delta)
    return elapsed + n_arms * (cap_seconds + estimate + pad_seconds) <= session_budget_seconds


def append_jsonl(path, row):
    path = _Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _json.dumps(row, sort_keys=True, default=str) + "\n"
    with path.open("a") as handle:
        handle.write(line)
        handle.flush()
        _os.fsync(handle.fileno())


def write_json_fsync(path, value):
    path = _Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        handle.write(payload)
        handle.flush()
        _os.fsync(handle.fileno())
    temporary.replace(path)


def _sandbox_names_in_path(text):
    names = []
    for part in str(text).split("/"):
        if part.startswith("swegemma_sandbox_"):
            names.append(part)
    return names


def collect_live_sandbox_names(evaluators=None, proc_root="/proc"):
    """Sandbox directory names still registered or held open by a process."""
    names = set()
    for item in (evaluators or {}).values():
        evaluator = item[1] if isinstance(item, tuple) and len(item) == 2 else item
        sandbox = getattr(evaluator, "sandbox", None)
        sandboxes = getattr(sandbox, "_sandboxes", None) or {}
        records = sandboxes.values() if isinstance(sandboxes, dict) else sandboxes
        for record in records:
            root = record.get("root") if isinstance(record, dict) else getattr(record, "root", None)
            if root is None:
                continue
            names.update(_sandbox_names_in_path(root))
            names.add(_Path(str(root)).name)
    proc = _Path(proc_root)
    if proc.is_dir():
        for pid in proc.iterdir():
            if not pid.name.isdigit():
                continue
            targets = [pid / "cwd"]
            fd_dir = pid / "fd"
            if fd_dir.is_dir():
                try:
                    targets.extend(fd_dir.iterdir())
                except OSError:
                    pass
            for candidate in targets:
                try:
                    target = _os.readlink(candidate)
                except OSError:
                    continue
                names.update(_sandbox_names_in_path(target))
    return names


def clean_stray_sandboxes(root, session_start_epoch, live_names=()):
    """Delete leftover swegemma sandbox directories, including this session's.

    ``session_start_epoch`` stays in the signature so existing callers keep working.
    A directory is kept only when its name is in ``live_names``.
    """
    del session_start_epoch
    root = _Path(root)
    if not root.is_dir():
        return []
    removed = []
    live = set(live_names or ())
    for path in root.glob("swegemma_sandbox_*"):
        if not path.is_dir() or path.name in live:
            continue
        import shutil

        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def _jsonable(value, seen=None):
    """JSON-ready copy of a trace object. Cycles become a marker."""
    if seen is None:
        seen = set()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    identity = id(value)
    if identity in seen:
        return "<cycle>"
    if isinstance(value, dict):
        seen.add(identity)
        return {str(key): _jsonable(item, seen) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        seen.add(identity)
        return [_jsonable(item, seen) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        seen.add(identity)
        try:
            dumped = dump()
        except Exception:
            dumped = None
        if dumped is not None:
            return _jsonable(dumped, seen)
    data = getattr(value, "__dict__", None)
    if isinstance(data, dict):
        seen.add(identity)
        return _jsonable(data, seen)
    return str(value)


def trace_artifact_stem(instance_id):
    """Match the harness: '/' in a task id becomes '__'."""
    return "trace_" + str(instance_id).replace("/", "__")


def _invoke_trace_save(save, path):
    try:
        signature = inspect.signature(save)
    except (TypeError, ValueError):
        save(path)
        return
    positional = False
    keyword_only = []
    for param in signature.parameters.values():
        if param.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        }:
            positional = True
        elif param.kind == inspect.Parameter.KEYWORD_ONLY:
            keyword_only.append(param.name)
    if positional:
        save(path)
        return
    if keyword_only:
        save(**{keyword_only[0]: str(path)})
        return
    save()


def write_trace_artifact(folder, instance_id, trace_obj):
    """Keep a harness ATIF trace. Never replace that file with a raw dump.

    A missing file is written with ``trace.save()`` when the object has one.
    Otherwise the raw dump goes to ``trace_<id>.raw.json``.
    """
    if trace_obj is None:
        return None
    trace_dir = _Path(folder) / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    stem = trace_artifact_stem(instance_id)
    harness_path = trace_dir / f"{stem}.json"
    if harness_path.is_file():
        return harness_path
    save = getattr(trace_obj, "save", None)
    if callable(save):
        _invoke_trace_save(save, harness_path)
        if harness_path.is_file():
            return harness_path
    raw_path = trace_dir / f"{stem}.raw.json"
    raw_path.write_text(_json.dumps(_jsonable(trace_obj), indent=2, sort_keys=True) + "\n")
    return raw_path


def _record_digest(field):
    import base64

    if not field or not field.startswith("sha256="):
        return None
    raw = field[len("sha256=") :]
    padded = raw + ("=" * (-len(raw) % 4))
    try:
        return base64.urlsafe_b64decode(padded)
    except Exception:
        return None


def record_sha256_for(origin):
    """Return the hex digest recorded for this installed file, or None."""
    origin = _Path(origin)
    for parent in origin.parents:
        records = list(parent.glob("*.dist-info/RECORD"))
        if not records:
            continue
        rel = origin.relative_to(parent).as_posix()
        for record in records:
            for line in record.read_text(errors="replace").splitlines():
                parts = line.split(",")
                if len(parts) >= 2 and parts[0] == rel:
                    digest = _record_digest(parts[1])
                    if digest is None:
                        return None
                    return digest.hex()
        return None
    return None


def verify_grading_pins(pins, mode, origins):
    """Hash installed harness files.

    record mode refuses only when a file does not match its dist-info RECORD.
    enforce mode also refuses when the hex digest differs from the pinned hash.
    """
    if mode not in {"record", "enforce"}:
        raise PinError(f"Unknown pins_mode: {mode}")
    observed = {}
    for module_name, rel in GRADING_MODULES:
        origin = origins.get(module_name)
        if origin is None:
            raise PinError(f"Installed grading file not found: {module_name}")
        origin = _Path(origin)
        actual = _hashlib.sha256(origin.read_bytes()).hexdigest()
        recorded = record_sha256_for(origin)
        if recorded is None or recorded != actual:
            raise PinError(f"RECORD mismatch for {rel}")
        pinned = pins.get(rel) or pins.get(module_name)
        if mode == "enforce" and pinned != actual:
            raise PinError(f"grading pin mismatch for {rel}: {actual} != {pinned}")
        observed[rel] = {"sha256": actual, "record_sha256": recorded, "origin": str(origin)}
    return observed


def assert_pytest_command_source(source, literals=PYTEST_COMMAND_LITERALS):
    missing = [literal for literal in literals if literal not in source]
    if missing:
        raise PinError("verify_task pytest command literal is not the pinned command")
    return True


def grading_mutation_findings(source):
    """Static scan for harness monkeypatching in generated notebook source."""
    import re

    patterns = (
        (r"\bsetattr\s*\(", "setattr"),
        (r"\bverify_task\s*=", "verify_task assignment"),
        (r"\bEvaluator\.\w+\s*=", "Evaluator method assignment"),
        (r"\bimport\s+builtins\b", "import builtins"),
        (r"\bsys\.modules\s*\[", "sys.modules write"),
        (r"\bimport\s+(mock|unittest\.mock)\b", "mock import"),
        (r"\bfrom\s+(mock|unittest\.mock)\s+import\b", "mock import"),
        (r"\b(swegemma|adk_eval_core)(?:\.\w+)+\s*=", "harness attribute assignment"),
    )
    findings = []
    for pattern, label in patterns:
        if re.search(pattern, source):
            findings.append(label)
    return findings


def _check(name, formula, inputs, value, threshold, severity):
    passed = value is not None and value <= threshold
    return {
        "name": name,
        "formula": formula,
        "inputs": inputs,
        "value": value,
        "threshold": threshold,
        "passed": bool(passed),
        "severity": severity,
    }


def projection_for_arm(
    rows, *, arm_sha256, cap_seconds, model_load_seconds, session_overhead_seconds, l_default=900
):
    walls = [float(row["wall_seconds"]) for row in rows if row.get("wall_seconds") is not None]
    mean_wall = _mean(walls)
    if model_load_seconds is not None:
        load, source = float(model_load_seconds), "model_load"
    elif session_overhead_seconds is not None:
        load, source = float(session_overhead_seconds), "session_overhead"
    else:
        load, source = float(l_default), "default"
    deltas = [wall - cap_seconds for wall in walls]
    p90_delta = percentile(deltas, 90) if deltas else None
    inputs_common = {
        "L": load,
        "L_source": source,
        "mean_wall": mean_wall,
        "cap_seconds": cap_seconds,
        "p90_delta": p90_delta,
        "model_load_seconds": model_load_seconds,
        "session_overhead_seconds": session_overhead_seconds,
    }
    p_value = None if mean_wall is None else load + 129 * mean_wall
    mean120 = None if mean_wall is None else mean_wall * 120
    checks = {
        "round2_load_plus_129_mean": _check(
            "round2_load_plus_129_mean",
            "L + 129 * mean_wall",
            {**inputs_common, "n": 129},
            p_value,
            BLOCK_THRESHOLD_P,
            "block",
        ),
        "coordinator_mean_times_120": _check(
            "coordinator_mean_times_120",
            "mean_wall * 120",
            {"mean_wall": mean_wall, "n": 120},
            mean120,
            BLOCK_THRESHOLD_MEAN120,
            "block",
        ),
    }
    for n in (129, 120):
        worst = None if p90_delta is None else load + n * (cap_seconds + p90_delta)
        checks[f"worst_case_12h_n{n}"] = _check(
            f"worst_case_12h_n{n}",
            "L + n * (cap + p90_delta)",
            {**inputs_common, "n": n},
            worst,
            WARN_THRESHOLD_12H,
            "warn",
        )
    blocked = any(check["severity"] == "block" and not check["passed"] for check in checks.values())
    marker_hits = sum(bool((row.get("hit_cap") or {}).get("marker")) for row in rows)
    wall_hits = sum(bool((row.get("hit_cap") or {}).get("wall")) for row in rows)
    counted = len(rows)
    return {
        "arm_sha256": arm_sha256,
        "n_task_runs": counted,
        "mean_wall": mean_wall,
        "p50": percentile(walls, 50) if walls else None,
        "p90": percentile(walls, 90) if walls else None,
        "max": max(walls) if walls else None,
        "f_cap": {
            "wall": (wall_hits / counted) if counted else None,
            "marker": (marker_hits / counted) if counted else None,
        },
        "L": load,
        "L_source": source,
        "cap_seconds": cap_seconds,
        "checks": checks,
        "blocked": blocked,
        "warnings": [
            name
            for name, check in checks.items()
            if check["severity"] == "warn" and not check["passed"]
        ],
    }


def build_projection(
    rows, arms, cap_seconds, model_load_seconds, session_overhead_seconds, l_default=900
):
    by_arm = {}
    for label, meta in arms.items():
        arm_rows = [row for row in rows if row.get("arm") == label]
        by_arm[label] = projection_for_arm(
            arm_rows,
            arm_sha256=meta.get("sha256"),
            cap_seconds=cap_seconds,
            model_load_seconds=model_load_seconds,
            session_overhead_seconds=session_overhead_seconds,
            l_default=l_default,
        )
    return {"arms": by_arm, "blocked": any(item["blocked"] for item in by_arm.values())}


def _resolved_count(rows):
    return sum(bool(row.get("resolved")) for row in rows)


def paired_table(rows):
    """Per-task paired outcomes. A repeat-task with infra or a missing arm is dropped."""
    grouped = {}
    for row in rows:
        grouped.setdefault((row.get("repeat"), row.get("task_id")), {})[row.get("arm")] = row
    kept = []
    dropped = []
    for key in sorted(grouped, key=lambda item: (item[0] or 0, str(item[1]))):
        arms = grouped[key]
        if set(arms) != {"A", "B"} or any(_is_infra(row) for row in arms.values()):
            dropped.append({"repeat": key[0], "task_id": key[1]})
            continue
        kept.append(
            {
                "repeat": key[0],
                "task_id": key[1],
                "a": bool(arms["A"].get("resolved")),
                "b": bool(arms["B"].get("resolved")),
            }
        )
    return kept, dropped


def _task_margins(kept):
    per_task = {}
    for item in kept:
        bucket = per_task.setdefault(item["task_id"], {"a": 0, "b": 0})
        bucket["a"] += int(item["a"])
        bucket["b"] += int(item["b"])
    wins = sorted(task for task, score in per_task.items() if score["a"] > score["b"])
    losses = sorted(task for task, score in per_task.items() if score["a"] < score["b"])
    ties = sorted(task for task, score in per_task.items() if score["a"] == score["b"])
    return {
        "a_t": {k: v["a"] for k, v in sorted(per_task.items())},
        "b_t": {k: v["b"] for k, v in sorted(per_task.items())},
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }


def _order_effect(rows, field):
    first, second = [], []
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        if row.get("arm") == row.get("first_arm"):
            first.append(float(value))
        else:
            second.append(float(value))
    if not first or not second:
        return None
    return _mean(first) - _mean(second)


def _primary_rows(rows, exclude_import_origin):
    if not exclude_import_origin:
        return list(rows)
    kept = []
    for row in rows:
        risk = row.get("import_origin_risk") or {}
        if risk.get("src_layout"):
            continue
        kept.append(row)
    return kept


def decision_rule(primary_rows, projection):
    """Mechanical round-2 decision. This never declares promotion."""
    repeats = sorted({row.get("repeat") for row in primary_rows if row.get("repeat") is not None})
    k = len(repeats)
    sums = {
        label: _resolved_count([row for row in primary_rows if row.get("arm") == label])
        for label in ("A", "B")
    }
    kept, _dropped = paired_table(primary_rows)
    margins = _task_margins(kept)
    breadth = len(margins["wins"]) - len(margins["losses"])
    required = 2 if k == 2 else 3 if k >= 3 else None
    margin_pass = required is not None and (sums["A"] - sums["B"]) >= required
    breadth_pass = required is not None and breadth >= required
    arms = projection.get("arms", {}) if projection else {}
    mean_a = (arms.get("A") or {}).get("mean_wall")
    mean_b = (arms.get("B") or {}).get("mean_wall")
    p_a = (
        ((arms.get("A") or {}).get("checks") or {})
        .get("round2_load_plus_129_mean", {})
        .get("value")
    )
    budget_pass = (
        p_a is not None
        and p_a <= BLOCK_THRESHOLD_P
        and mean_a is not None
        and mean_b not in (None, 0)
        and mean_a <= 1.10 * mean_b
    )
    hygiene = "not_computed"
    conditions = {
        "margin": {
            "pass": bool(margin_pass),
            "sum_a": sums["A"],
            "sum_b": sums["B"],
            "required": required,
        },
        "paired_breadth": {"pass": bool(breadth_pass), "w_minus_lo": breadth, "required": required},
        "budget": {"pass": bool(budget_pass), "p_a_n129": p_a, "mean_a": mean_a, "mean_b": mean_b},
        "hygiene": {"pass": None, "status": hygiene},
    }
    # Evaluate B as the candidate as well, without treating a pass as promotion.
    reverse_margin = required is not None and (sums["B"] - sums["A"]) >= required
    reverse_breadth = required is not None and -breadth >= required
    p_b = (
        ((arms.get("B") or {}).get("checks") or {})
        .get("round2_load_plus_129_mean", {})
        .get("value")
    )
    reverse_budget = (
        p_b is not None
        and p_b <= BLOCK_THRESHOLD_P
        and mean_b is not None
        and mean_a not in (None, 0)
        and mean_b <= 1.10 * mean_a
    )
    rule_winner = None
    if (
        all(conditions[name]["pass"] for name in ("margin", "paired_breadth", "budget"))
        and hygiene == "not_computed"
    ):
        rule_winner = None
    if hygiene != "not_computed" and margin_pass and breadth_pass and budget_pass:
        rule_winner = "A"
    if hygiene != "not_computed" and reverse_margin and reverse_breadth and reverse_budget:
        rule_winner = "B"
    return {
        "applied_to": "primary",
        "k": k,
        "conditions": conditions,
        "b_as_candidate": {
            "margin": bool(reverse_margin),
            "paired_breadth": bool(reverse_breadth),
            "budget": bool(reverse_budget),
        },
        "rule_winner": rule_winner,
        "promotion": "not_declared",
        "tie_break_recommended": k == 2 and abs(sums["A"] - sums["B"]) <= 1,
        "note": (
            "Hygiene is not_computed unless a hygiene sidecar is present. "
            "Verification signs off; this report does not promote."
        ),
    }


def _arm_stats(rows):
    walls = [float(row["wall_seconds"]) for row in rows if row.get("wall_seconds") is not None]
    return {
        "rows": len(rows),
        "resolved": _resolved_count(rows),
        "empty_patches": sum(row.get("patch_chars") == 0 for row in rows),
        "infra_errors": sum(_is_infra(row) for row in rows),
        "hit_cap_wall": sum(bool((row.get("hit_cap") or {}).get("wall")) for row in rows),
        "hit_cap_marker": sum(bool((row.get("hit_cap") or {}).get("marker")) for row in rows),
        "wall_mean": _mean(walls),
        "wall_p50": percentile(walls, 50) if walls else None,
        "wall_p90": percentile(walls, 90) if walls else None,
        "wall_max": max(walls) if walls else None,
        "setup_mean": _mean(
            [row["setup_seconds"] for row in rows if row.get("setup_seconds") is not None]
        ),
        "agent_mean": _mean(
            [row["agent_seconds"] for row in rows if row.get("agent_seconds") is not None]
        ),
        "grading_mean": _mean(
            [row["grading_seconds"] for row in rows if row.get("grading_seconds") is not None]
        ),
        "order_effect_agent_seconds": _order_effect(rows, "agent_seconds"),
        "order_effect_cached_tokens": _order_effect(rows, "total_cached_prompt_tokens"),
    }


def build_report(
    rows,
    *,
    projection,
    exclude_import_origin=True,
    hygiene=None,
    protocol_sha256=None,
    schedule_sha256=None,
):
    primary = _primary_rows(rows, exclude_import_origin)
    flagged = [
        row.get("task_id") or row.get("instance_id")
        for row in rows
        if (row.get("import_origin_risk") or {}).get("src_layout")
    ]
    repeats = sorted({row.get("repeat") for row in rows if row.get("repeat") is not None})
    per_repeat = {}
    for repeat in repeats:
        raw_rows = [row for row in rows if row.get("repeat") == repeat]
        primary_rows = [row for row in primary if row.get("repeat") == repeat]
        kept, dropped = paired_table(primary_rows)
        per_repeat[str(repeat)] = {
            "raw": {
                label: _arm_stats([row for row in raw_rows if row.get("arm") == label])
                for label in ("A", "B")
            },
            "primary": {
                label: _arm_stats([row for row in primary_rows if row.get("arm") == label])
                for label in ("A", "B")
            },
            "paired": {**_task_margins(kept), "dropped_for_infra": dropped},
        }
    kept, dropped = paired_table(primary)
    report = {
        "protocol_sha256": protocol_sha256,
        "schedule_sha256": schedule_sha256,
        "exclude_import_origin_risk": exclude_import_origin,
        "raw_totals": {
            label: _arm_stats([row for row in rows if row.get("arm") == label])
            for label in ("A", "B")
        },
        "primary_totals": {
            label: _arm_stats([row for row in primary if row.get("arm") == label])
            for label in ("A", "B")
        },
        "paired": {**_task_margins(kept), "dropped_for_infra": dropped},
        "per_repeat": per_repeat,
        "import_origin_flagged_tasks": sorted(set(flagged)),
        "projection": projection,
        "hygiene": hygiene if hygiene is not None else "not_computed",
        "prefix_cache_note": (
            "The vLLM prefix cache is shared across arms and is not flushed. "
            "Alternating which arm goes first balances carryover in expectation. "
            "Per-arm-run cache samples are on the timing rows when the metrics endpoint answers."
        ),
        "decision_rule": decision_rule(primary, projection),
        "promotion": "not_declared",
    }
    return report


def render_report_md(report):
    lines = ["# Paired evaluation report", ""]
    lines.append(f"Protocol sha256: `{report.get('protocol_sha256')}`")
    lines.append(f"Schedule sha256: `{report.get('schedule_sha256')}`")
    lines.append("")
    lines.append("## Raw totals")
    for label, stats in (report.get("raw_totals") or {}).items():
        lines.append(f"- {label}: resolved {stats.get('resolved')} / {stats.get('rows')}")
    lines.append("")
    lines.append("## Primary totals")
    lines.append("Src-layout tasks are excluded from these numbers when the protocol says so.")
    for label, stats in (report.get("primary_totals") or {}).items():
        lines.append(
            f"- {label}: resolved {stats.get('resolved')} / {stats.get('rows')}, "
            f"infra {stats.get('infra_errors')}, empty patches {stats.get('empty_patches')}"
        )
    paired = report.get("paired") or {}
    lines.append("")
    lines.append("## Paired table")
    lines.append(
        f"Wins (A over B): {len(paired.get('wins') or [])}. "
        f"Losses: {len(paired.get('losses') or [])}. "
        f"Ties: {len(paired.get('ties') or [])}. "
        f"Dropped: {len(paired.get('dropped_for_infra') or [])}."
    )
    flagged = report.get("import_origin_flagged_tasks") or []
    lines.append("")
    lines.append("## Import-origin flagged tasks")
    lines.append(", ".join(flagged) if flagged else "None.")
    projection = report.get("projection") or {}
    lines.append("")
    lines.append("## Projection")
    lines.append(f"Blocked: {projection.get('blocked')}.")
    for label, arm in (projection.get("arms") or {}).items():
        lines.append(f"### {label}")
        for name, check in (arm.get("checks") or {}).items():
            lines.append(
                f"- {name} [{check.get('severity')}]: value={check.get('value')} "
                f"threshold={check.get('threshold')} passed={check.get('passed')}"
            )
    lines.append("")
    lines.append(report.get("prefix_cache_note") or "")
    lines.append("")
    lines.append("## Decision rule")
    lines.append("Each condition is pass/fail. This report does not declare promotion.")
    decision = report.get("decision_rule") or {}
    for name, condition in (decision.get("conditions") or {}).items():
        lines.append(f"- {name}: {condition}")
    lines.append(f"Hygiene: {report.get('hygiene')}")
    lines.append(f"Promotion: {report.get('promotion')}")
    return "\n".join(lines) + "\n"


def _load_hygiene(output_dir):
    found = {}
    results = _Path(output_dir) / "results"
    if not results.is_dir():
        return None
    for path in sorted(results.glob("*/*/hygiene.json")):
        found[path.relative_to(output_dir).as_posix()] = _json.loads(path.read_text())
    return found or None


def _session_stopped(status):
    """Session-ending statuses use the aborted: prefix. aborted_arm: stops one arm."""
    return str(status).startswith("aborted:") or status == "truncated_by_budget"


def execute_session(
    *,
    schedule,
    tasks,
    rebuild,
    run_evaluate,
    output_dir,
    arms,
    schedule_sha256,
    cap_seconds,
    session_budget_seconds,
    clock,
    session_start,
    health=None,
    restart_server=None,
    import_origins=None,
    early_stop=None,
    prefix_cache=None,
    model_load_seconds=None,
    session_overhead_seconds=None,
    l_default=900,
    pair_pad_seconds=60,
    manifest=None,
    after_row=None,
    sandbox_tmp=None,
    session_start_epoch=None,
    exclude_import_origin=True,
    protocol_sha256=None,
    requested_tier=2,
    initial_stopped=None,
):
    output_dir = _Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    health = health or (lambda: True)
    import_origins = import_origins or {}
    manifest = dict(manifest or {})
    manifest.setdefault("schedule_sha256", schedule_sha256)
    manifest.setdefault("protocol_sha256", protocol_sha256)
    manifest["status"] = "running"
    evaluators = {}
    rows = []
    walls = []
    restarts = 0
    post_restart = False
    stopped_arms = set(initial_stopped or ())
    status = "running"
    unrun = []
    prefix_previous = None
    events = output_dir / "events.jsonl"
    pair_results = output_dir / "pair_results.jsonl"
    timing_path = output_dir / "timing.jsonl"
    append_jsonl(events, {"event": "session_start", "t": clock() - session_start})

    def sweep_sandboxes():
        if sandbox_tmp is None:
            return []
        live = collect_live_sandbox_names(evaluators)
        return clean_stray_sandboxes(sandbox_tmp, session_start_epoch, live)

    def event(payload):
        payload = {"t": clock() - session_start, **payload}
        append_jsonl(events, payload)

    def persist():
        manifest["status"] = status
        manifest["unrun_pairs"] = [
            {"repeat": item["repeat"], "task_id": item["task_id"], "position": item["position"]}
            for item in unrun
        ]
        manifest["restarts"] = restarts
        write_json_fsync(output_dir / "pair_manifest.json", manifest)

    def arm_dir(label, repeat):
        return output_dir / "results" / label / f"r{repeat}"

    def rewrite_run_manifest(label, repeat):
        attempted = [
            row["instance_id"]
            for row in rows
            if row.get("arm") == label and row.get("repeat") == repeat
        ]
        write_json_fsync(
            arm_dir(label, repeat) / "run_manifest.json",
            {
                "sha256": arms[label]["sha256"],
                "task_ids": attempted,
                "arm": label,
                "repeat": repeat,
                "model_load_seconds": model_load_seconds,
            },
        )

    index = 0
    while index < len(schedule):
        pair = schedule[index]
        if _session_stopped(status):
            unrun.extend(schedule[index:])
            break
        planned = [arm for arm in pair["order"] if arm not in stopped_arms]
        if not planned:
            unrun.append(pair)
            index += 1
            continue
        elapsed = clock() - session_start
        p90_delta = percentile([wall - cap_seconds for wall in walls], 90) if walls else None
        if not pair_fits(
            elapsed, len(planned), cap_seconds, p90_delta, session_budget_seconds, pair_pad_seconds
        ):
            status = "truncated_by_budget"
            unrun.extend(schedule[index:])
            event({"event": "truncated_by_budget", "unrun": len(schedule) - index})
            break
        for arm in planned:
            task = tasks[pair["task_id"]]
            repeat = pair["repeat"]
            folder = arm_dir(arm, repeat)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "patches").mkdir(exist_ok=True)
            meta = arms[arm]
            event(
                {"event": "arm_run_start", "arm": arm, "repeat": repeat, "task_id": pair["task_id"]}
            )
            try:
                verify_extracted_tree(meta["root"], meta["files"])
            except PinError as exc:
                row = crash_row(task, exc)
                row["error"] = "candidate_tree_mismatch"
                row["arm"] = arm
                row["crashed"] = True
                _finish_row(
                    rows,
                    row,
                    pair,
                    meta,
                    post_restart,
                    planned,
                    pair["order"],
                    arm,
                    import_origins,
                    events,
                    pair_results,
                    timing_path,
                    folder,
                )
                rewrite_run_manifest(arm, repeat)
                status = "aborted:candidate_tree_mismatch"
                event({"event": "abort", "status": status})
                break
            if not health():
                recovered = False
                if restarts < 1 and restart_server is not None:
                    try:
                        load_seconds = restart_server()
                    except Exception as exc:
                        event({"event": "server_restart_failed", "error": repr(exc)[:500]})
                    else:
                        restarts += 1
                        post_restart = True
                        event({"event": "server_restart", "load_seconds": load_seconds})
                        recovered = bool(health())
                row = crash_row(task, RuntimeError("model_server_unhealthy"))
                row["error"] = "model_server_unhealthy"
                _finish_row(
                    rows,
                    row,
                    pair,
                    meta,
                    post_restart,
                    planned,
                    pair["order"],
                    arm,
                    import_origins,
                    events,
                    pair_results,
                    timing_path,
                    folder,
                )
                rewrite_run_manifest(arm, repeat)
                if after_row is not None:
                    _after(after_row, row, event)
                if not recovered:
                    status = "aborted:model_server"
                    event({"event": "abort", "status": status})
                    break
                code = abort_code(
                    [item for item in rows if item.get("arm") == arm], cap_seconds, arm
                )
                if code:
                    status, stopped_arms = _apply_abort(code, arm, stopped_arms, event)
                    if _session_stopped(status):
                        break
                continue
            if arm not in evaluators or evaluators[arm][0] != repeat:
                evaluators[arm] = (repeat, rebuild(arm, repeat))
            sweep_sandboxes()
            dashboard = TimingDashboard()
            t0 = clock()
            t0_epoch = _time.time()
            try:
                result = run_evaluate(
                    evaluators[arm][1], task, dashboard, pair["position"], len(schedule)
                )
                t1 = clock()
                wall = t1 - t0
                row, patch = base_result_row(task, result)
                row["test_output"] = (getattr(result, "test_output", None) or "")[:500]
                timing = choose_timing(
                    dashboard,
                    wall,
                    cap_seconds,
                    (
                        max(0.0, getattr(dashboard.context, "task_start_time", t0) - t0)
                        if dashboard.attached
                        else 0.0
                    ),
                    t0_epoch,
                    _time.time(),
                    getattr(result, "trace", None),
                    requested_tier,
                )
                if timing["timing_source"] == "dashboard" and dashboard.context is not None:
                    calls = getattr(dashboard.context, "llm_calls_used", None)
                    if timing.get("agent_seconds") is not None and calls is not None:
                        row.setdefault("llm_calls_from_context", calls)
                tokens = token_fields(getattr(result, "trace", None))
                if tokens.get("llm_calls") is None and dashboard.attached:
                    calls = getattr(dashboard.context, "llm_calls_used", None)
                    if calls is not None:
                        tokens["llm_calls"] = calls
                error_text = row.get("error") or row.get("agent_error") or ""
                row.update(timing)
                row.update(tokens)
                row["hit_cap"] = hit_cap_fields(wall, cap_seconds, error_text)
                details = (
                    result.model_dump()
                    if hasattr(result, "model_dump")
                    else {"result": str(result)}
                )
                (folder / f"{task.instance_id}.json").write_text(
                    _json.dumps(details, default=str, indent=2, sort_keys=True) + "\n"
                )
                write_trace_artifact(folder, task.instance_id, getattr(result, "trace", None))
                (folder / "patches" / f"{task.instance_id}.patch").write_text(patch)
                walls.append(wall)
            except (KeyboardInterrupt, SystemExit):
                event({"event": "interrupted", "arm": arm, "task_id": pair["task_id"]})
                persist()
                raise
            except Exception as exc:
                wall = clock() - t0
                row = crash_row(task, exc)
                row["wall_seconds"] = wall
                row["hit_cap"] = hit_cap_fields(wall, cap_seconds, row.get("error"))
                row["timing_source"] = "exception"
                row["timing_tier"] = 1
                walls.append(wall)
                evaluators.pop(arm, None)
                try:
                    evaluators[arm] = (repeat, rebuild(arm, repeat))
                except Exception:
                    evaluators.pop(arm, None)
                sweep_sandboxes()
            cache = None
            if prefix_cache is not None:
                try:
                    cache = prefix_cache()
                except Exception:
                    cache = None
            delta = None
            if isinstance(cache, dict) and isinstance(prefix_previous, dict):
                delta = {}
                for key, value in cache.items():
                    previous = prefix_previous.get(key)
                    if isinstance(value, (int, float)) and isinstance(previous, (int, float)):
                        delta[key] = value - previous
            prefix_previous = cache if isinstance(cache, dict) else prefix_previous
            row["prefix_cache"] = {"cumulative": cache, "delta": delta}
            _finish_row(
                rows,
                row,
                pair,
                meta,
                post_restart,
                planned,
                pair["order"],
                arm,
                import_origins,
                events,
                pair_results,
                timing_path,
                folder,
            )
            # details sidecar metadata
            sidecar = {
                "pair_id": pair["pair_id"],
                "first_arm": pair["order"][0],
                "timing_tier": row.get("timing_tier"),
                "timing_source": row.get("timing_source"),
                "import_origin_risk": row.get("import_origin_risk"),
                "post_restart": post_restart,
                "unpaired": planned != pair["order"],
            }
            (folder / f"{task.instance_id}.pair.json").write_text(
                _json.dumps(sidecar, indent=2, sort_keys=True) + "\n"
            )
            rewrite_run_manifest(arm, repeat)
            if after_row is not None:
                _after(after_row, row, event)
            code = abort_code([item for item in rows if item.get("arm") == arm], cap_seconds, arm)
            if code:
                status, stopped_arms = _apply_abort(code, arm, stopped_arms, event)
                if _session_stopped(status):
                    break
        if _session_stopped(status):
            unrun.extend(schedule[index + 1 :])
            break
        sweep_sandboxes()
        # Early stop is evaluated only between repeats.
        upcoming = schedule[index + 1]["repeat"] if index + 1 < len(schedule) else None
        if early_stop == "round2" and upcoming != pair["repeat"]:
            repeat_rows = {}
            for label in ("A", "B"):
                repeat_rows[label] = [
                    row
                    for row in rows
                    if row.get("arm") == label and row.get("repeat") == pair["repeat"]
                ]
            n_tasks = sum(1 for item in schedule if item["repeat"] == pair["repeat"])
            loser = early_stop_loser(repeat_rows, n_tasks)
            if loser and loser not in stopped_arms:
                stopped_arms.add(loser)
                status = f"early_stopped:{loser}"
                event({"event": "early_stop", "arm": loser, "repeat": pair["repeat"]})
        index += 1
    sweep_sandboxes()
    if status == "running":
        status = "complete"
    # Preserve an early-stop status when the remaining unpaired work finished.
    if status.startswith("early_stopped") and not unrun:
        pass
    projection = build_projection(
        rows,
        arms,
        cap_seconds,
        model_load_seconds,
        session_overhead_seconds,
        l_default,
    )
    validity = {}
    for label in arms:
        validity[label] = {}
        for repeat in sorted({item["repeat"] for item in schedule}):
            n_tasks = sum(1 for item in schedule if item["repeat"] == repeat)
            graded = sum(
                1
                for row in rows
                if row.get("arm") == label and row.get("repeat") == repeat and not _is_infra(row)
            )
            validity[label][str(repeat)] = {
                "graded_without_infra": graded,
                "tasks": n_tasks,
                "valid": repeat_is_valid(graded, n_tasks),
            }
    manifest["validity"] = validity
    manifest["status"] = status
    hygiene = _load_hygiene(output_dir)
    report = build_report(
        rows,
        projection=projection,
        exclude_import_origin=exclude_import_origin,
        hygiene=hygiene if hygiene is not None else "not_computed",
        protocol_sha256=protocol_sha256,
        schedule_sha256=schedule_sha256,
    )
    write_json_fsync(output_dir / "projection.json", projection)
    write_json_fsync(output_dir / "pair_report.json", report)
    (output_dir / "pair_report.md").write_text(render_report_md(report))
    persist()
    return {
        "status": status,
        "rows": rows,
        "unrun": unrun,
        "restarts": restarts,
        "projection": projection,
        "report": report,
        "validity": validity,
    }


def _apply_abort(code, arm, stopped_arms, event):
    event({"event": "abort", "status": code, "arm": arm})
    if code.startswith("aborted_arm:"):
        stopped_arms.add(arm)
    return code, stopped_arms


def _after(after_row, row, event):
    try:
        after_row(row)
    except (KeyboardInterrupt, SystemExit):
        event({"event": "interrupted", "arm": row.get("arm"), "task_id": row.get("task_id")})
        raise


def _finish_row(
    rows,
    row,
    pair,
    meta,
    post_restart,
    planned,
    full_order,
    arm,
    import_origins,
    events,
    pair_results,
    timing_path,
    folder,
):
    row["arm"] = arm
    row["arm_sha256"] = meta["sha256"]
    row["repeat"] = pair["repeat"]
    row["position"] = pair["position"]
    row["task_id"] = pair["task_id"]
    row["p0"] = pair["p0"]
    row["first_arm"] = full_order[0]
    row["pair_id"] = pair["pair_id"]
    row["post_restart"] = bool(post_restart)
    row["unpaired"] = list(planned) != list(full_order)
    row["import_origin_risk"] = (import_origins or {}).get(pair["task_id"])
    single = {
        key: row[key]
        for key in (
            "instance_id",
            "repo",
            "resolved",
            "test_exit_code",
            "patch_chars",
            "tool_calls",
            "duration_seconds",
            "agent_error",
            "failure_class",
            "error",
        )
        if key in row
    }
    append_jsonl(folder / "task_results.jsonl", single)
    append_jsonl(pair_results, row)
    append_jsonl(
        timing_path,
        {
            key: row.get(key)
            for key in (
                "arm",
                "arm_sha256",
                "repeat",
                "task_id",
                "pair_id",
                "wall_seconds",
                "setup_seconds",
                "agent_seconds",
                "post_agent_seconds",
                "grading_seconds",
                "overshoot_seconds",
                "hit_cap",
                "timing_tier",
                "timing_source",
                "total_prompt_tokens",
                "total_cached_prompt_tokens",
                "total_completion_tokens",
                "total_tokens",
                "llm_calls",
                "prefix_cache",
                "duration_seconds",
            )
        },
    )
    append_jsonl(
        events,
        {
            "event": "arm_run_end",
            "arm": row.get("arm"),
            "task_id": pair["task_id"],
            "repeat": pair["repeat"],
        },
    )
    rows.append(row)


# The helper above references import origins from the caller. Patch it in by
# storing origins on the arm meta before execute_session. See _attach_origins.
def _attach_import_origins(arms, origins):
    for meta in arms.values():
        meta["import_origin"] = origins
    return arms


SERVER_RELEASE_TIMEOUT_SECONDS = 60.0
NVIDIA_SMI_POLL_TIMEOUT_SECONDS = 10.0
PORT_POLL_TIMEOUT_SECONDS = 0.2
GPU_MEMORY_UNKNOWN = "unknown"


def server_process_pid(server):
    for name in ("process", "_process", "proc", "_proc", "_server_process"):
        proc = getattr(server, name, None)
        pid = getattr(proc, "pid", None)
        if isinstance(pid, int) and pid > 0:
            return pid
    pid = getattr(server, "pid", None)
    if isinstance(pid, int) and pid > 0:
        return pid
    return None


def start_model_server(server):
    """Call ``server.start()`` with subprocesses in their own session."""
    import subprocess
    import sys

    original = subprocess.Popen

    def patched(*args, **kwargs):
        kwargs["start_new_session"] = True
        return original(*args, **kwargs)

    restored = []
    subprocess.Popen = patched
    for module in list(sys.modules.values()):
        if module is None:
            continue
        if getattr(module, "Popen", None) is original:
            module.Popen = patched
            restored.append(module)
        nested = getattr(module, "subprocess", None)
        if nested is not None and getattr(nested, "Popen", None) is original:
            nested.Popen = patched
            restored.append(nested)
    try:
        return server.start()
    finally:
        subprocess.Popen = original
        for module in restored:
            module.Popen = original


def session_pgid(pid):
    """Group id of a ``start_new_session`` leader. Equals ``pid``.

    Call this before ``stop()``. Once that call reaps the leader, ``getpgid``
    fails, but the id still names the group and ``killpg`` reaches children
    that remain in it.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        return _os.getpgid(pid)
    except OSError:
        return pid


def _refuse_kill_reason(pgid):
    """Why ``pgid`` must not be signaled, or None when ``killpg`` is safe."""
    if not isinstance(pgid, int) or pgid <= 0 or pgid == 1:
        return (
            f"Refusing to kill process group {pgid!r}: "
            "not a server process group (refusing None, 0, -1, and 1)."
        )
    try:
        own = _os.getpgrp()
    except OSError:
        own = None
    if own is not None and pgid == own:
        return f"Refusing to kill process group {pgid}: it is the notebook's own process group."
    return None


def _call_with_timeout(fn, timeout, *args):
    """Call ``fn``, passing ``timeout`` only when that parameter exists."""
    try:
        accepts = "timeout" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        accepts = False
    if accepts:
        return fn(*args, timeout=timeout)
    return fn(*args)


def kill_process_group(pgid, grace=0.2, sleep=None, killpg=None):
    """SIGTERM ``pgid``, then SIGKILL after ``grace`` seconds.

    ``pgid`` is the id recorded before ``stop()``. This does not call
    ``getpgid``. The notebook's own group, and None, 0, -1, and 1, are not
    signaled. A group that is already gone raises ``ProcessLookupError``
    and is ignored.
    """
    reason = _refuse_kill_reason(pgid)
    if reason is not None:
        _warnings.warn(reason, UserWarning, stacklevel=2)
        return None
    if killpg is None:
        killpg = _os.killpg
    if sleep is None:
        sleep = _time.sleep
    try:
        killpg(pgid, _signal.SIGTERM)
    except ProcessLookupError:
        return pgid
    except OSError:
        pass
    if grace:
        sleep(grace)
    try:
        killpg(pgid, _signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    return pgid


def port_from_base_url(url):
    from urllib.parse import urlparse

    return urlparse(str(url or "")).port


def port_is_open(port, host="127.0.0.1", timeout=PORT_POLL_TIMEOUT_SECONDS):
    import socket

    if not port:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(max(0.0, float(timeout)))
    try:
        return sock.connect_ex((host, int(port))) == 0
    except OSError:
        return False
    finally:
        sock.close()


def process_group_pids(pgid, proc_root="/proc"):
    if pgid is None:
        return []
    found = []
    root = _Path(proc_root)
    if not root.is_dir():
        return found
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if _os.getpgid(int(entry.name)) == int(pgid):
                found.append(int(entry.name))
        except OSError:
            continue
    return found


def nvidia_smi_gpu_pids(timeout=NVIDIA_SMI_POLL_TIMEOUT_SECONDS):
    """Pids holding GPU compute memory.

    Returns None when nvidia-smi is absent. Returns ``"unknown"`` when the
    query exceeds ``timeout``, so a hung nvidia-smi cannot stall the notebook.
    """
    import shutil
    import subprocess

    if shutil.which("nvidia-smi") is None:
        return None
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _warnings.warn(
            "nvidia-smi timed out; GPU memory state is unknown and will not be waited on",
            UserWarning,
            stacklevel=2,
        )
        return GPU_MEMORY_UNKNOWN
    pids = []
    for line in completed.stdout.splitlines():
        piece = line.strip().split(",")[0].strip()
        if piece.isdigit():
            pids.append(int(piece))
    return pids


def wait_for_server_release(
    port,
    pgid,
    timeout=SERVER_RELEASE_TIMEOUT_SECONDS,
    sleep=None,
    clock=None,
    port_open=None,
    gpu_pids=None,
    group_pids=None,
    nvidia_smi_present=None,
):
    """Wait until the port is free and this group holds no GPU memory.

    ``timeout`` is a deadline for every poll. Each port and nvidia-smi call
    is capped at the time remaining. A timed-out nvidia-smi query is logged
    as unknown and GPU memory is no longer waited on.
    """
    if sleep is None:
        sleep = _time.sleep
    if clock is None:
        clock = _time.monotonic
    if port_open is None:
        port_open = port_is_open
    if group_pids is None:
        group_pids = process_group_pids
    if nvidia_smi_present is None:
        import shutil

        nvidia_smi_present = shutil.which("nvidia-smi") is not None
    if gpu_pids is None:
        gpu_pids = nvidia_smi_gpu_pids
    started = clock()
    waited_on = []
    seen_gpu = []
    timed_out = False
    gpu_memory = None

    def remaining():
        return timeout - (clock() - started)

    while True:
        if remaining() <= 0:
            timed_out = True
            break
        busy_port = False
        if port:
            left = remaining()
            if left <= 0:
                timed_out = True
                break
            busy_port = bool(
                _call_with_timeout(port_open, min(PORT_POLL_TIMEOUT_SECONDS, left), port)
            )
        holders = []
        if nvidia_smi_present and pgid is not None and gpu_memory != GPU_MEMORY_UNKNOWN:
            left = remaining()
            if left <= 0:
                timed_out = True
                break
            current = _call_with_timeout(gpu_pids, min(NVIDIA_SMI_POLL_TIMEOUT_SECONDS, left))
            if current == GPU_MEMORY_UNKNOWN:
                gpu_memory = GPU_MEMORY_UNKNOWN
            else:
                members = set(group_pids(pgid))
                holders = [item for item in (current or []) if item in members]
        if not busy_port and not holders:
            break
        if busy_port and "port" not in waited_on:
            waited_on.append("port")
        for item in holders:
            if item not in seen_gpu:
                seen_gpu.append(item)
        if holders and "gpu" not in waited_on:
            waited_on.append("gpu")
        left = remaining()
        if left <= 0:
            timed_out = True
            break
        sleep(min(0.25, left))
    return {
        "waited_on": waited_on,
        "port": port,
        "pgid": pgid,
        "nvidia_smi": bool(nvidia_smi_present),
        "gpu_pids": seen_gpu,
        "gpu_memory": gpu_memory,
        "timed_out": timed_out,
        "seconds": clock() - started,
    }


def release_server_after_stop(pgid, base_url, **kwargs):
    """Kill the group recorded before ``stop()``, then wait for port and GPU."""
    grace = kwargs.pop("grace", 0.2)
    killed = kill_process_group(pgid, grace=grace, sleep=kwargs.get("sleep"))
    return wait_for_server_release(port_from_base_url(base_url), killed, **kwargs)


# <<<END_NOTEBOOK_RUNTIME>>>


def notebook_runtime_source():
    text = Path(__file__).read_text()
    start = text.index("# <<<NOTEBOOK_RUNTIME>>>\n")
    end = text.index("# <<<END_NOTEBOOK_RUNTIME>>>\n")
    body = text[start:end]
    # Drop the marker line. The embedded cell redefines the helpers.
    return body.split("\n", 1)[1]


def _path_allowed(rel, patterns):
    for pattern in patterns:
        if fnmatch(rel, pattern):
            return True
        if pattern.endswith("/*") and (rel == pattern[:-2] or rel.startswith(pattern[:-1])):
            return True
    return False


def _walk(value, on_dict):
    if isinstance(value, dict):
        on_dict(value)
        for child in value.values():
            _walk(child, on_dict)
    elif isinstance(value, list):
        for child in value:
            _walk(child, on_dict)


_SETTINGS_INCLUDE = re.compile(
    r"(?m)^[ \t]*(?:thinking_config|generate_content_config)\s*:\s*!include\s+(\S+)"
)


def settings_include_paths(source):
    """Paths pulled in for thinking or sampling. Compared by resolved value, not path."""
    source = Path(source).resolve()
    found = set()
    for path in sorted(source.rglob("*")):
        if path.suffix not in {".yaml", ".yml"} or not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(source).parts):
            continue
        for match in _SETTINGS_INCLUDE.finditer(path.read_text()):
            target = match.group(1).strip("'\"")
            included = (path.parent / target).resolve()
            if included.is_relative_to(source):
                found.add(included.relative_to(source).as_posix())
    return found


def _agent_documents(source):
    """Root agent plus config_path children, with !include already expanded."""
    pending = [source / "agent.yaml"]
    seen = set()
    documents = []
    while pending:
        path = pending.pop()
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        loaded = load_yaml(path, source)
        documents.append(loaded)

        def collect(node, base=path.parent):
            if isinstance(node, dict):
                target = node.get("config_path")
                if isinstance(target, str):
                    pending.append(base / target)
                for child in node.values():
                    collect(child, base)
            elif isinstance(node, list):
                for child in node:
                    collect(child, base)

        collect(loaded)
    return documents


def _resolved_sampling(documents):
    """Unique temperature, top_p, and thinking settings after includes expand.

    Agent count is structure. A single agent and several roles that resolve to the
    same knobs are the same settings, even when thinking.yaml lives at different paths.
    """
    found = set()
    for document in documents:

        def visit(node):
            gcc = node.get("generate_content_config")
            if isinstance(gcc, dict):
                thinking = gcc.get("thinking_config") or {}
                if not isinstance(thinking, dict):
                    thinking = {}
                found.add(
                    (
                        gcc.get("temperature"),
                        gcc.get("top_p"),
                        thinking.get("thinking_budget"),
                        thinking.get("include_thoughts"),
                    )
                )

        _walk(document, visit)
    return sorted(found, key=lambda item: json.dumps(item))


def _yaml_compare_value(source, rel):
    """Resolved YAML, or a bytes sentinel when the file does not parse."""
    path = Path(source) / rel
    try:
        return ("yaml", load_yaml(path, source))
    except Exception:
        return ("bytes", hashlib.sha256(path.read_bytes()).hexdigest())


def inspect_arm(source):
    source = Path(source).resolve()
    files = {}
    yaml_values = {}
    for path in sorted(source.rglob("*")):
        if path.is_file() and not any(
            part.startswith(".") for part in path.relative_to(source).parts
        ):
            rel = path.relative_to(source).as_posix()
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.suffix in {".yaml", ".yml"}:
                yaml_values[rel] = _yaml_compare_value(source, rel)
    documents = _agent_documents(source)
    models, adapters = [], []
    for document in documents:

        def visit(node, found_models=models, found_adapters=adapters):
            if "model" in node and isinstance(node["model"], str):
                found_models.append(node["model"])
            if "adapter" in node and isinstance(node["adapter"], str):
                found_adapters.append(node["adapter"])

        _walk(document, visit)
    adapter_root = source / "adapters"
    if adapter_root.exists():
        for path in sorted(adapter_root.rglob("*")):
            if path.is_file():
                adapters.append(path.relative_to(source).as_posix())
    return {
        "source": str(source),
        "files": files,
        "models": sorted(set(models)),
        "sampling": _resolved_sampling(documents),
        "adapters": sorted(set(adapters)),
        "budgets": normalize_budgets_from_disk(source),
        "settings_includes": sorted(settings_include_paths(source)),
        "yaml_values": yaml_values,
    }


def normalize_budgets_from_disk(source):
    return read_arm_budgets(source)


def unexpected_file_diffs(files_a, files_b, allowed, ignored=(), yaml_a=None, yaml_b=None):
    """YAML files compare as resolved values. Other files compare as bytes."""
    ignored = set(ignored or ())
    yaml_a = yaml_a or {}
    yaml_b = yaml_b or {}
    bad = []
    for rel in sorted(set(files_a) | set(files_b)):
        if rel in ignored or _path_allowed(rel, allowed or []):
            continue
        if rel.endswith((".yaml", ".yml")):
            # Identical bytes cannot be a comment-only or value change in this file.
            # Included documents are compared on their own paths.
            if rel in files_a and files_a.get(rel) == files_b.get(rel):
                continue
            left = yaml_a.get(rel)
            right = yaml_b.get(rel)
            if left is None or right is None or left != right:
                bad.append(rel)
            continue
        if files_a.get(rel) != files_b.get(rel):
            bad.append(rel)
    return bad


def assert_arms_compatible(arm_a, arm_b, *, allow_identical, allowed_differences, sha_a, sha_b):
    if sha_a == sha_b and not allow_identical:
        raise ValueError(
            "Refusing identical arm archives; set allow_identical for an A/A noise run"
        )
    if arm_a["adapters"] or arm_b["adapters"]:
        raise ValueError("LoRA adapters are refused in paired v1")
    if arm_a["models"] != arm_b["models"] or arm_a["models"] != [MODEL]:
        raise ValueError(f"Arms must declare the same single model {MODEL}")
    if arm_a["budgets"] != arm_b["budgets"]:
        raise ValueError(f"Arm budgets differ: {arm_a['budgets']} != {arm_b['budgets']}")
    if arm_a["sampling"] != arm_b["sampling"]:
        raise ValueError(
            "Resolved generation settings differ in temperature, top_p, or thinking_budget: "
            f"{arm_a['sampling']} != {arm_b['sampling']}"
        )
    ignored = set(arm_a.get("settings_includes") or ()) | set(arm_b.get("settings_includes") or ())
    diffs = unexpected_file_diffs(
        arm_a["files"],
        arm_b["files"],
        allowed_differences,
        ignored,
        arm_a.get("yaml_values"),
        arm_b.get("yaml_values"),
    )
    if diffs:
        raise ValueError("Settings differ outside allowed_differences: " + ", ".join(diffs))
    return True


def load_protocol(path):
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode()) or {}
    if not isinstance(data, dict):
        raise ValueError("Protocol must be a mapping")
    if data.get("order_rule", ORDER_RULE) != ORDER_RULE:
        raise ValueError(
            f"Unsupported order_rule {data.get('order_rule')!r}; expected {ORDER_RULE}"
        )
    arms = data.get("arms") or {}
    if set(arms) != {"A", "B"}:
        raise ValueError("Protocol arms must be exactly A and B")
    cohort = data.get("cohort") or {}
    if "path" not in cohort:
        raise ValueError("Protocol cohort.path is required")
    data["_path"] = str(path)
    data["_sha256"] = hashlib.sha256(raw).hexdigest()
    data.setdefault("allow_identical", False)
    data.setdefault("allowed_differences", [])
    data.setdefault("repeats", 2)
    data.setdefault("shuffle_seed", None)
    data.setdefault("session_budget_seconds", 40200)
    data.setdefault("pair_start_pad_seconds", 60)
    data.setdefault("abort_policy", "round2_v1")
    data.setdefault("early_stop", None)
    data.setdefault("pins_mode", "record")
    data.setdefault("exclude_import_origin_risk", True)
    data.setdefault("timing_tier", 2)
    data.setdefault("budget_gate", {})
    return data


def load_cohort_ids(path):
    ids = json.loads(Path(path).read_text())
    if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
        raise ValueError("Cohort must be a nonempty JSON array of unique task ids")
    return [str(item) for item in ids]


def parse_repeats(text, available):
    numbers = [int(part.strip()) for part in str(text).split(",") if part.strip()]
    if not numbers or numbers != sorted(set(numbers)):
        raise ValueError("repeats-in-session must be a unique ascending list such as 1 or 1,2")
    if any(number < 1 or number > available for number in numbers):
        raise ValueError(f"repeats-in-session must be within 1..{available}")
    return numbers


def repo_root():
    return Path(__file__).resolve().parents[2]


def load_grading_pins(path=None):
    path = Path(path) if path is not None else repo_root() / "configs/paired/grading_pins.json"
    return json.loads(path.read_text())


def load_import_origin_repos(path=None):
    path = Path(path) if path is not None else repo_root() / "configs/paired/import_origin.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    return list(data.get("src_layout_repos") or [])


def summarize_pair_run(output_dir):
    """Additive wait-run summary. Each arm/repeat folder is a single-arm result set."""
    from gemma_lab.metrics import load_results, summary

    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / "pair_manifest.json").read_text())
    arms = {}
    results = output_dir / "results"
    if results.is_dir():
        for label_dir in sorted(path for path in results.iterdir() if path.is_dir()):
            for repeat_dir in sorted(path for path in label_dir.iterdir() if path.is_dir()):
                rows_path = repeat_dir / "task_results.jsonl"
                key = f"{label_dir.name}/{repeat_dir.name}"
                if rows_path.exists():
                    arms[key] = summary(load_results(rows_path))
    return {
        "status": manifest.get("status"),
        "schedule_sha256": manifest.get("schedule_sha256"),
        "protocol_sha256": manifest.get("protocol_sha256"),
        "arms": arms,
        "unrun_pairs": manifest.get("unrun_pairs") or [],
        "validity": manifest.get("validity"),
    }


def report_from_runs(run_dirs, protocol_path, output):
    """Regenerate pair_report.json and pair_report.md for one or more sessions."""
    from gemma_lab.common import write_json

    protocol = load_protocol(protocol_path)
    schedule = build_schedule(
        load_cohort_ids(protocol["cohort"]["path"]),
        repeats=int(protocol["repeats"]),
        shuffle_seed=protocol.get("shuffle_seed"),
    )
    protocol["_schedule_sha256"] = schedule["sha256"]
    cap = None
    arm_meta = {"A": {"sha256": None}, "B": {"sha256": None}}
    for label, spec in protocol["arms"].items():
        source = Path(spec["source"])
        if source.is_dir():
            info = inspect_arm(source)
            cap = float(info["budgets"]["max_time_minutes"]) * 60.0
            arm_meta[label]["sha256"] = None
    for run_dir in run_dirs:
        manifest_path = Path(run_dir) / "pair_manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        for label, meta in (manifest.get("arms") or {}).items():
            if not isinstance(meta, dict):
                continue
            if meta.get("sha256"):
                arm_meta.setdefault(label, {})["sha256"] = meta["sha256"]
            if cap is None and meta.get("budgets"):
                cap = float(meta["budgets"]["max_time_minutes"]) * 60.0
    protocol["_cap_seconds"] = 0 if cap is None else cap
    protocol["_arm_meta"] = arm_meta
    report = combine_pair_reports(run_dirs, protocol)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "pair_report.json", report)
    (output / "pair_report.md").write_text(render_report_md(report))
    blocked = (report.get("projection") or {}).get("blocked")
    return {"output": str(output), "promotion": report.get("promotion"), "blocked": blocked}


def combine_pair_reports(run_dirs, protocol):
    rows = []
    loads = []
    overheads = []
    for run_dir in run_dirs:
        path = Path(run_dir) / "pair_results.jsonl"
        if not path.exists():
            raise ValueError(f"Missing pair_results.jsonl in {run_dir}")
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
        manifest_path = Path(run_dir) / "pair_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            for session in manifest.get("session") or []:
                if session.get("model_load_seconds") is not None:
                    loads.append(session["model_load_seconds"])
                if session.get("session_overhead_seconds") is not None:
                    overheads.append(session["session_overhead_seconds"])
            if manifest.get("schedule_sha256") and protocol.get("_schedule_sha256"):
                if manifest["schedule_sha256"] != protocol["_schedule_sha256"]:
                    raise ValueError("Run schedule hash does not match the protocol schedule")
    cap_seconds = protocol.get("_cap_seconds")
    if cap_seconds is None:
        cap_seconds = 0
    arm_meta = protocol.get("_arm_meta") or {"A": {"sha256": None}, "B": {"sha256": None}}
    projection = build_projection(
        rows,
        arm_meta,
        cap_seconds,
        _mean(loads) if loads else None,
        _mean(overheads) if overheads else None,
        (protocol.get("budget_gate") or {}).get("L_default", 900),
    )
    hygiene = None
    for run_dir in run_dirs:
        found = _load_hygiene(run_dir)
        if found:
            hygiene = {**(hygiene or {}), **found}
    return build_report(
        rows,
        projection=projection,
        exclude_import_origin=bool(protocol.get("exclude_import_origin_risk", True)),
        hygiene=hygiene if hygiene is not None else "not_computed",
        protocol_sha256=protocol.get("_sha256"),
        schedule_sha256=protocol.get("_schedule_sha256"),
    )
