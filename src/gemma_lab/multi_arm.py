"""Combined multi-arm smoke notebooks.

The two-arm notebook runtime in ``paired.py`` stays byte-for-byte as it is.
``execute_session`` already walks ``entry["order"]``, so this generator embeds
a schedule whose order lists every arm and reuses that runtime unchanged.
``build_report`` inside the runtime only totals arms A and B, so the generated
notebook rewrites the report after the session.

Two-arm protocols keep using ``notebook-pair``. This module refuses a protocol
with fewer than three arms.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import tempfile
from pathlib import Path

import yaml

from gemma_lab.bundle import pack
from gemma_lab.common import git_revision, now, sha256, write_json
from gemma_lab.notebook import (
    _WHEEL_ANCHOR,
    _WHEEL_INSERT,
    _assert_model_imports_safe,
    _call_span,
    _harness_pin_block,
    _install_declared_model_shim,
    _pin_dataset_sources,
    _record_data_wait,
    _replace_required,
    _require,
    _strip_paired_budget_prelude,
    _wheelhouse_source,
    code_cell,
    data_wait_prelude,
    harness_verified_pairs,
)
from gemma_lab.notebook import (
    DATA_WAIT_TIMEOUT_SECONDS as DATA_WAIT_SECONDS,
)
from gemma_lab.operations import (
    DEFAULT_MODEL_LOAD_SECONDS,
    DEFAULT_SCORER_OVERHEAD_SECONDS,
    PROJECTED_HIDDEN_TASKS,
    PROJECTED_LOAD_LIMIT_SECONDS,
    PROJECTED_PUBLIC_TASKS,
    PROJECTED_RUNTIME_LIMIT_SECONDS,
    WORST_CASE_WARN_SECONDS,
)
from gemma_lab.paired import (
    ORDER_RULE,
    _check_manifest_protocol,
    assert_arms_compatible,
    build_schedule,
    inspect_arm,
    load_grading_pins,
    load_import_origin_repos,
    load_protocol,
    make_pair_id,
    notebook_runtime_source,
    parse_repeats,
    resolve_protocol_task_ids,
    schedule_sha256,
)

LOAD_SECONDS = float(DEFAULT_MODEL_LOAD_SECONDS)
SCORER_OVERHEAD_SECONDS = float(DEFAULT_SCORER_OVERHEAD_SECONDS)
FIRST_PAIR_ESTIMATE_SECONDS = 30.0
KAGGLE_SESSION_SECONDS = WORST_CASE_WARN_SECONDS


def session_cap_seconds(budgets, labels):
    """Session clock is the max of the arm time caps. Per-arm limits stay put."""
    caps = [float(budgets[label]["max_time_minutes"]) * 60.0 for label in labels]
    if not caps:
        raise ValueError("Multi-arm session cap needs at least one arm budget")
    return max(caps)


def pair_fits_minimum_budget(
    n_tasks,
    n_arms,
    session_cap,
    *,
    load_seconds=LOAD_SECONDS,
    pad_seconds=60,
    extra_elapsed=0,
):
    """Smallest session budget that still starts the last task in the worst case.

    ``pair_fits`` charges every remaining arm the session cap. Before any wall
    exists the estimate is 30 seconds. After that, walls equal to the session
    cap make the estimate 0. Elapsed time includes the model load because the
    notebook records ``SESSION_PERF_T0`` before the server starts. ``extra_elapsed``
    is time before ``execute_session`` that is also on that clock, such as the
    tasks.jsonl wait.
    """
    if n_tasks < 1 or n_arms < 1:
        raise ValueError("pair_fits budget needs a positive task and arm count")
    load = float(load_seconds) + float(extra_elapsed)
    cap = float(session_cap)
    pad = float(pad_seconds)
    last = load + n_tasks * n_arms * cap + n_arms * pad
    first = load + n_arms * (cap + FIRST_PAIR_ESTIMATE_SECONDS + pad)
    return max(first, last)


def worst_session_wall_seconds(arm_caps, n_tasks, load_seconds=LOAD_SECONDS):
    """Wall time if every arm hits its own cap, plus one model load."""
    return float(load_seconds) + int(n_tasks) * sum(float(cap) for cap in arm_caps)


def option2_wall_seconds(load_seconds=LOAD_SECONDS):
    """Three pair notebooks: v8 is repeated, and the model loads three times.

    Arms are single-v8 (330 s), single-v8-check (330 s), structured-v7 (360 s),
    and single-v7 (270 s). Each notebook is one repeat of the five tasks.
    """
    load = float(load_seconds)
    v8_vs_check = 5 * (330.0 + 330.0) + load
    v8_vs_structured = 5 * (330.0 + 360.0) + load
    v8_vs_v7 = 5 * (330.0 + 270.0) + load
    return v8_vs_check + v8_vs_structured + v8_vs_v7


def submission_gate_picture(cap_seconds, load_seconds=None, overhead_seconds=None):
    """What the submit/promotion gate would say if a measured mean equaled the cap.

    The cap itself never blocks. The warning uses the cap. The blocks use the
    measured mean. Smoke runs do not apply either one.
    """
    load = float(LOAD_SECONDS if load_seconds is None else load_seconds)
    overhead = float(SCORER_OVERHEAD_SECONDS if overhead_seconds is None else overhead_seconds)
    cap = float(cap_seconds)
    warn = load + PROJECTED_PUBLIC_TASKS * (cap + overhead)
    block_120 = PROJECTED_HIDDEN_TASKS * (cap + overhead)
    block_129 = load + PROJECTED_PUBLIC_TASKS * cap
    return {
        "cap_seconds": cap,
        "warn_seconds": warn,
        "warn": warn > WORST_CASE_WARN_SECONDS,
        "block_120_if_mean_equals_cap": block_120,
        "block_120": block_120 > PROJECTED_RUNTIME_LIMIT_SECONDS,
        "block_129_if_mean_equals_cap": block_129,
        "block_129": block_129 > PROJECTED_LOAD_LIMIT_SECONDS,
        "warn_limit_seconds": WORST_CASE_WARN_SECONDS,
        "block_120_limit_seconds": PROJECTED_RUNTIME_LIMIT_SECONDS,
        "block_129_limit_seconds": PROJECTED_LOAD_LIMIT_SECONDS,
        "overhead_seconds": overhead,
        "load_seconds": load,
    }


def largest_integer_mean_that_passes(overhead_seconds=None):
    """Largest whole-second mean that passes both submit blocks."""
    overhead = float(SCORER_OVERHEAD_SECONDS if overhead_seconds is None else overhead_seconds)
    passing = None
    for mean in range(0, 24 * 60):
        block_120 = PROJECTED_HIDDEN_TASKS * (mean + overhead)
        block_129 = LOAD_SECONDS + PROJECTED_PUBLIC_TASKS * mean
        if (
            block_120 <= PROJECTED_RUNTIME_LIMIT_SECONDS
            and block_129 <= PROJECTED_LOAD_LIMIT_SECONDS
        ):
            passing = mean
        elif passing is not None:
            break
    if passing is None:
        raise ValueError("No mean passes the submit blocks")
    return passing


def build_multi_schedule(task_ids, labels, repeats=1, shuffle_seed=None):
    """Same task order as ``build_schedule``. Arm order is a rotation.

    For two labels this matches ``build_schedule`` exactly, including the hash.
    For more labels the hash changes because ``order`` is part of the hash.
    """
    labels = [str(label) for label in labels]
    if len(labels) < 2 or len(labels) != len(set(labels)):
        raise ValueError("Multi-arm schedule labels must be unique and at least 2")
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
    width = len(labels)
    entries = []
    for repeat in repeat_numbers:
        r0 = repeat - 1
        order_ids = base if r0 % 2 == 0 else list(reversed(base))
        for position, task_id in enumerate(order_ids, start=1):
            p0 = index[task_id]
            start = (p0 + r0) % width
            entries.append(
                {
                    "repeat": repeat,
                    "position": position,
                    "task_id": task_id,
                    "p0": p0,
                    "order": labels[start:] + labels[:start],
                }
            )
    digest = schedule_sha256(entries)
    for entry in entries:
        entry["pair_id"] = make_pair_id(digest, entry["repeat"], entry["task_id"])
    return {"rule": ORDER_RULE, "task_ids": base, "entries": entries, "sha256": digest}


def assert_multi_compatible(inspected, shas, allowed_differences, allow_identical=False):
    """Pairwise arm check. Identical budgets and sampling stay a matched check.

    A budget or sampling difference uses ``matched_pair`` false so the existing
    eval_config.yaml / sampling.yaml / thinking.yaml markers still apply.
    ``matched_pair`` false on those pairs skips only the shared-file check.
    """
    labels = list(inspected)
    allowed = list(allowed_differences or [])
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            budgets_differ = inspected[left]["budgets"] != inspected[right]["budgets"]
            sampling_differ = inspected[left]["sampling"] != inspected[right]["sampling"]
            matched = not (budgets_differ or sampling_differ)
            assert_arms_compatible(
                inspected[left],
                inspected[right],
                allow_identical=bool(allow_identical),
                allowed_differences=allowed,
                sha_a=shas[left],
                sha_b=shas[right],
                matched_pair=matched,
            )
    return True


def _positive_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def load_multi_protocol(path):
    """Load an N-arm smoke protocol. Two-arm files stay on ``load_protocol``."""
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode()) or {}
    if not isinstance(data, dict):
        raise ValueError("Protocol must be a mapping")
    if data.get("multi_arm") is not True:
        raise ValueError("Multi-arm protocols must set multi_arm: true")
    if data.get("purpose") != "smoke":
        raise ValueError("Multi-arm protocols must set purpose: smoke")
    if data.get("order_rule", ORDER_RULE) != ORDER_RULE:
        raise ValueError(
            f"Unsupported order_rule {data.get('order_rule')!r}; expected {ORDER_RULE}"
        )
    arms = data.get("arms") or {}
    if not isinstance(arms, dict):
        raise ValueError("Protocol arms must be a mapping")
    labels = list(arms)
    if len(labels) < 3:
        raise ValueError(
            "Multi-arm protocols need at least 3 arms; two-arm protocols use notebook-pair"
        )
    if any(not re.fullmatch(r"[A-Z]", label) for label in labels):
        raise ValueError("Multi-arm labels must be single letters A-Z, in run order")
    for label, spec in arms.items():
        if not isinstance(spec, dict) or not spec.get("source"):
            raise ValueError(f"Arm {label} needs a source directory")
        name = spec.get("name", Path(spec["source"]).name)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Arm {label} name must be a non-empty string")
        spec["name"] = name.strip()
    if data.get("repeats", 1) != 1:
        raise ValueError("Multi-arm smoke repeats must be 1")
    if data.get("early_stop") not in (None,):
        raise ValueError(
            "Multi-arm smoke early_stop must be null. The embedded early-stop only knows A and B."
        )
    if data.get("matched_pair") is not False:
        raise ValueError("Multi-arm smoke must set matched_pair: false")
    notes = data.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        raise ValueError("matched_pair false is not allowed without notes naming the mismatch")
    data["_path"] = str(path)
    data["_sha256"] = hashlib.sha256(raw).hexdigest()
    data["repeats"] = 1
    data.setdefault("allow_identical", False)
    data.setdefault("allowed_differences", [])
    data.setdefault("shuffle_seed", None)
    data["pair_start_pad_seconds"] = _positive_int(
        int(data.get("pair_start_pad_seconds", 60)), "pair_start_pad_seconds"
    )
    data.setdefault("abort_policy", "round2_v1")
    data.setdefault("pins_mode", "record")
    data.setdefault("exclude_import_origin_risk", True)
    data.setdefault("timing_tier", 2)
    data.setdefault("budget_gate", {})
    if data.get("pins_mode") not in {"record", "enforce"}:
        raise ValueError("pins_mode must be record or enforce")
    if "session_budget_seconds" not in data:
        raise ValueError("session_budget_seconds is required")
    data["session_budget_seconds"] = _positive_int(
        data["session_budget_seconds"], "session_budget_seconds"
    )
    data["_task_ids"] = resolve_protocol_task_ids(data)
    return data


def multi_smoke_report(
    rows,
    *,
    labels,
    names,
    budgets,
    protocol_sha256,
    schedule_sha256,
    task_schedule_sha256,
    session_cap_seconds,
    hygiene="not_computed",
    notes=None,
):
    """N-arm smoke report. One repeat cannot name a winner.

    Helpers are nested so the notebook can embed this function alone.
    """

    def task_key(row):
        return row.get("task_id") or row.get("instance_id")

    def wall_seconds(row):
        if row.get("wall_seconds") is not None:
            return float(row["wall_seconds"])
        if row.get("duration_seconds") is not None:
            return float(row["duration_seconds"])
        return None

    labels = [str(label) for label in labels]
    by_task = {}
    for row in rows:
        key = task_key(row)
        arm = row.get("arm")
        if key is None or arm not in labels:
            continue
        bucket = by_task.setdefault(key, {})
        bucket.setdefault(arm, []).append(row)
    arms = {}
    for label in labels:
        arm_rows = [row for row in rows if row.get("arm") == label]
        walls = [value for value in (wall_seconds(row) for row in arm_rows) if value is not None]
        minutes = float(budgets[label]["max_time_minutes"])
        arms[label] = {
            "name": names[label],
            "rows": len(arm_rows),
            "resolved": sum(bool(row.get("resolved")) for row in arm_rows),
            "mean_wall_seconds": (sum(walls) / len(walls)) if walls else None,
            "max_wall_seconds": max(walls) if walls else None,
            "cap_seconds": minutes * 60.0,
            "max_tool_calls": int(budgets[label]["max_tool_calls"]),
            "max_turns": int(budgets[label]["max_turns"]),
        }
    comparisons = []
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            both = only_left = only_right = neither = incomplete = 0
            for bucket in by_task.values():
                left_rows = bucket.get(left) or []
                right_rows = bucket.get(right) or []
                if not left_rows or not right_rows:
                    incomplete += 1
                    continue
                left_ok = bool(left_rows[0].get("resolved"))
                right_ok = bool(right_rows[0].get("resolved"))
                if left_ok and right_ok:
                    both += 1
                elif left_ok:
                    only_left += 1
                elif right_ok:
                    only_right += 1
                else:
                    neither += 1
            comparisons.append(
                {
                    "left": left,
                    "right": right,
                    "left_name": names[left],
                    "right_name": names[right],
                    "both_resolved": both,
                    "only_left": only_left,
                    "only_right": only_right,
                    "neither": neither,
                    "incomplete": incomplete,
                    "winner": None,
                }
            )
    report = {
        "purpose": "smoke",
        "promotion": "not_eligible",
        "winner": None,
        "rule_winner": None,
        "n_arms": len(labels),
        "n_rows": len(rows),
        "session_cap_seconds": float(session_cap_seconds),
        "protocol_sha256": protocol_sha256,
        "schedule_sha256": schedule_sha256,
        "task_schedule_sha256": task_schedule_sha256,
        "arms": arms,
        "comparisons": comparisons,
        "hygiene": hygiene if hygiene is not None else "not_computed",
        "gates": {
            "promotion": "not_eligible",
            "runtime_gates": "not_applicable",
            "reason": (
                "Smoke is not a promotion run. One repeat cannot name a winner. "
                "Submit and promotion gates are not applied."
            ),
        },
        "embedded_ab_report": (
            "execute_session writes a two-arm report that only totals A and B. "
            "This smoke report replaces it."
        ),
        "cap_note": (
            "The session cap is the max of the arm time caps. Each evaluator "
            "still uses that arm's own max_time_minutes, max_tool_calls, and max_turns."
        ),
    }
    if isinstance(notes, str) and notes.strip():
        report["notes"] = notes.strip()
    return report


def render_multi_smoke_md(report):
    lines = [
        "smoke, not promotion eligible",
        "",
        "# Combined multi-arm smoke",
        "",
        "This run is a smoke. It is not promotion eligible.",
        "One repeat cannot name a winner.",
        "rule_winner: null",
        "Promotion: not_eligible",
        "",
    ]
    notes = report.get("notes")
    if isinstance(notes, str) and notes.strip():
        lines.append(notes.strip())
        lines.append("")
    lines.append(f"Protocol sha256: `{report.get('protocol_sha256')}`")
    lines.append(f"Schedule sha256: `{report.get('schedule_sha256')}`")
    lines.append(
        "Two-arm schedule sha256 for the same tasks and repeat: "
        f"`{report.get('task_schedule_sha256')}`"
    )
    lines.append(
        f"Session cap seconds: {report.get('session_cap_seconds')} (max of the arm time caps)."
    )
    lines.append(report.get("cap_note") or "")
    lines.append("")
    lines.append("## Arms")
    for label, stats in (report.get("arms") or {}).items():
        mean = stats.get("mean_wall_seconds")
        mean_text = "n/a" if mean is None else f"{mean:.1f}s"
        lines.append(
            f"- {label} {stats.get('name')}: resolved {stats.get('resolved')} / "
            f"{stats.get('rows')}, cap {stats.get('cap_seconds')}s, "
            f"calls {stats.get('max_tool_calls')}, turns {stats.get('max_turns')}, "
            f"mean wall {mean_text}"
        )
    lines.append("")
    lines.append("## Comparisons")
    lines.append("Descriptive counts only. They do not name a winner.")
    for item in report.get("comparisons") or []:
        lines.append(
            f"- {item.get('left')} {item.get('left_name')} vs "
            f"{item.get('right')} {item.get('right_name')}: "
            f"both {item.get('both_resolved')}, "
            f"only {item.get('left')} {item.get('only_left')}, "
            f"only {item.get('right')} {item.get('only_right')}, "
            f"neither {item.get('neither')}, incomplete {item.get('incomplete')}"
        )
    lines.append("")
    lines.append("## Gates")
    lines.append((report.get("gates") or {}).get("reason") or "not_applicable")
    mismatch = report.get("protocol_mismatch_warning") or []
    if mismatch:
        lines.append("")
        lines.append("## Protocol hash warning")
        for note in mismatch:
            lines.append(f"- {note}")
    lines.append("")
    hygiene = report.get("hygiene")
    hygiene_text = hygiene if isinstance(hygiene, str) else "recorded"
    lines.append(f"Hygiene: {hygiene_text}")
    return "\n".join(lines) + "\n"


def _arm_payload_setup(label, archive, bundle_dataset):
    if not re.fullmatch(r"[A-Z]", label):
        raise ValueError("Arm payload label must be a single letter A-Z")
    if bundle_dataset:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-z0-9-]+", bundle_dataset):
            raise ValueError("Expected bundle dataset reference owner/slug")
        dataset_slug = bundle_dataset.split("/", 1)[1]
        return (
            f"matches = list(Path('/kaggle/input').rglob('{dataset_slug}.zip'))\n"
            "assert len(matches) == 1, 'Expected exactly one uploaded bundle'\n"
            f"payload_{label} = matches[0].read_bytes()\n"
        )
    if archive.stat().st_size > 5 * 1024**2:
        raise ValueError(
            f"Arm {label} bundle >5 MiB: upload a private bundle dataset and pass --bundle-dataset"
        )
    encoded = __import__("base64").b64encode(archive.read_bytes()).decode()
    return f"payload_{label} = base64.b64decode({encoded!r})\n"


def _multi_payload_cell(
    protocol, packed, cohort_ids, schedule, task_schedule, session_repeats, pins
):
    labels = tuple(packed)
    files = {label: packed[label]["files"] for label in labels}
    budgets = {label: packed[label]["budgets"] for label in labels}
    shas = {label: packed[label]["sha256"] for label in labels}
    names = {label: packed[label]["name"] for label in labels}
    setups = "\n".join(packed[label]["payload_setup"] for label in labels)
    repos = load_import_origin_repos()
    return (
        "import base64, hashlib, importlib.metadata, io, json, zipfile\n"
        "from swegemma.models import load_tasks\n"
        "_ADK_SUBMISSION_VERSION = importlib.metadata.version('adk-submission')\n"
        "assert_adk_submission_version(_ADK_SUBMISSION_VERSION)\n"
        "DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')\n"
        "WORKING_DIR = Path('/kaggle/working')\n"
        "WORKING_DIR.mkdir(parents=True, exist_ok=True)\n"
        f"LABELS = {labels!r}\n"
        f"ARM_SHA = {shas!r}\n"
        f"ARM_FILES = {files!r}\n"
        f"ARM_BUDGETS = {budgets!r}\n"
        f"ARM_NAMES = {names!r}\n"
        "ARM_DIRS = {label: WORKING_DIR / 'candidates' / ARM_SHA[label][:12] for label in LABELS}\n"
        f"{setups}"
        "for _label in LABELS:\n"
        "    install_arm(globals()[f'payload_{_label}'], ARM_SHA[_label], "
        "ARM_DIRS[_label], ARM_FILES[_label])\n"
        "    _zip = WORKING_DIR / 'arms' / _label / 'submission.zip'\n"
        "    _zip.parent.mkdir(parents=True, exist_ok=True)\n"
        "    _zip.write_bytes(globals()[f'payload_{_label}'])\n"
        + data_wait_prelude()
        + "TASKS_PATH = DATA_DIR / 'tasks.jsonl'\n"
        "_data_wait_seconds = wait_for_tasks_jsonl(TASKS_PATH)\n"
        + _record_data_wait()
        + "tasks = load_tasks(TASKS_PATH)\n"
        f"TASK_IDS = {cohort_ids!r}\n"
        "assert set(TASK_IDS) <= {t.instance_id for t in tasks}, 'Unknown task IDs'\n"
        f"REPEATS = {int(protocol['repeats'])!r}\n"
        f"SHUFFLE_SEED = {protocol.get('shuffle_seed')!r}\n"
        f"SCHEDULE_SHA = {schedule['sha256']!r}\n"
        f"TASK_SCHEDULE_SHA = {task_schedule['sha256']!r}\n"
        "# N-arm schedule. build_schedule is the two-arm rule and is not called.\n"
        f"MULTI_SCHEDULE = {schedule['entries']!r}\n"
        "assert [entry['task_id'] for entry in MULTI_SCHEDULE] == list(TASK_IDS)\n"
        "assert schedule_sha256(MULTI_SCHEDULE) == SCHEDULE_SHA\n"
        f"SESSION_REPEATS = {list(session_repeats)!r}\n"
        "SESSION_SCHEDULE = [\n"
        "    entry for entry in MULTI_SCHEDULE if entry['repeat'] in SESSION_REPEATS\n"
        "]\n"
        f"PROTOCOL_SHA = {protocol['_sha256']!r}\n"
        f"PINS_MODE = {protocol['pins_mode']!r}\n"
        f"GRADING_PINS = {pins['files']!r}\n"
        f"PYTEST_LITERALS = {list(pins['pytest_command_literals'])!r}\n"
        f"SRC_LAYOUT_REPOS = {repos!r}\n"
        f"EXCLUDE_IMPORT_ORIGIN = {bool(protocol.get('exclude_import_origin_risk', True))!r}\n"
        f"EARLY_STOP = {protocol.get('early_stop')!r}\n"
        f"SESSION_BUDGET_SECONDS = {int(protocol['session_budget_seconds'])!r}\n"
        f"PAIR_PAD_SECONDS = {int(protocol.get('pair_start_pad_seconds', 60))!r}\n"
        f"TIMING_TIER = {int(protocol.get('timing_tier', 2))!r}\n"
        "TASK_FILE_SHA = hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest()\n"
        f"EXPECTED_TASK_SHA = {protocol['cohort'].get('task_file_sha256')!r}\n"
        "if EXPECTED_TASK_SHA:\n"
        "    assert TASK_FILE_SHA == EXPECTED_TASK_SHA, (TASK_FILE_SHA, EXPECTED_TASK_SHA)\n"
        "IMPORT_ORIGINS = {}\n"
        "for _task in tasks:\n"
        "    if _task.instance_id not in set(TASK_IDS):\n"
        "        continue\n"
        "    _members = None\n"
        "    for _suffix in ('.tar', '.tar.gz', '.tgz'):\n"
        "        _candidate = DATA_DIR / 'snapshots' / f'{_task.instance_id}{_suffix}'\n"
        "        if _candidate.is_file():\n"
        "            _members = list_tar_members(_candidate)\n"
        "            break\n"
        "    IMPORT_ORIGINS[_task.instance_id] = import_origin_risk("
        "        _task.repo, SRC_LAYOUT_REPOS, _members)\n"
        "MANIFEST = {\n"
        "    'protocol_sha256': PROTOCOL_SHA,\n"
        "    'schedule_sha256': SCHEDULE_SHA,\n"
        "    'task_schedule_sha256': TASK_SCHEDULE_SHA,\n"
        "    'order_rule': 'per_task_parity_v1',\n"
        "    'purpose': 'smoke',\n"
        "    'task_ids': TASK_IDS,\n"
        "    'task_file_sha256': TASK_FILE_SHA,\n"
        "    'pins_mode': PINS_MODE,\n"
        "    'grading_pins': GRADING_PINS,\n"
        "    'arms': {label: {'sha256': ARM_SHA[label], 'budgets': ARM_BUDGETS[label], "
        "'name': ARM_NAMES[label]} for label in LABELS},\n"
        "    'session_repeats': SESSION_REPEATS,\n"
        "    'packages': {name: importlib.metadata.version(name) for name in "
        "['swegemma', 'adk-submission', 'adk-eval-core', 'vllm', 'google-adk']},\n"
        "    'adk_submission_version': _ADK_SUBMISSION_VERSION,\n"
        "    'data_wait_seconds': _data_wait_seconds,\n"
        "    'status': 'loaded',\n"
        "}\n"
        "(WORKING_DIR / 'schedule.json').write_text("
        "json.dumps({'sha256': SCHEDULE_SHA, 'task_schedule_sha256': TASK_SCHEDULE_SHA, "
        "'rule': 'per_task_parity_v1', 'entries': MULTI_SCHEDULE}, indent=2, sort_keys=True))\n"
        "(WORKING_DIR / 'pair_manifest.json').write_text("
        "json.dumps(MANIFEST, indent=2, sort_keys=True))\n"
        "print(f'Combined smoke schedule {SCHEDULE_SHA[:12]} tasks={len(TASK_IDS)} "
        "arms={len(LABELS)} repeats={SESSION_REPEATS}')\n"
        "print('smoke, not promotion eligible')\n"
    )


def _multi_server_cell(source):
    source = _install_declared_model_shim(source)
    source = _replace_required(
        source,
        ["declared_model = validate_single_declared_model(AGENT_DIR)\n"],
        (
            "declared_models = [\n"
            "    validate_single_declared_model(ARM_DIRS[label]) for label in LABELS\n"
            "]\n"
            "assert declared_models == [TARGET_MODEL_NAME] * len(LABELS)\n"
            "declared_model = declared_models[0]\n"
        ),
        "declared model",
    )
    source = _replace_required(
        source,
        [
            "adapters = discover_adapters(str(AGENT_DIR), "
            "adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)\n"
        ],
        (
            "adapter_sets = [discover_adapters(str(ARM_DIRS[label]), "
            "adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS) for label in LABELS]\n"
            "def _adapters_empty(manifest):\n"
            "    found = getattr(manifest, 'adapters', manifest)\n"
            "    return not found\n"
            "assert all(_adapters_empty(item) for item in adapter_sets), "
            "'LoRA arms are refused in paired v1'\n"
            "adapters = adapter_sets[0]\n"
        ),
        "adapter discovery",
    )
    pin_block = (
        "import importlib.util\n"
        "_pin_origins = {}\n"
        "for _module_name, _rel in GRADING_MODULES:\n"
        "    _spec = importlib.util.find_spec(_module_name)\n"
        "    if _spec is None or not _spec.origin:\n"
        "        raise PinError(f'missing grading module {_module_name}')\n"
        "    _pin_origins[_module_name] = _spec.origin\n"
        "MANIFEST['grading_observation'] = verify_grading_pins("
        "GRADING_PINS, PINS_MODE, _pin_origins)\n"
        "import swegemma.harness.verification as _verification\n"
        "assert_pytest_command_source("
        "inspect.getsource(_verification.verify_task), PYTEST_LITERALS)\n"
    )
    source = _replace_required(
        source,
        ["server_instance.start()\n"],
        pin_block
        + "_LOAD_T0 = time.perf_counter()\nstart_model_server(server_instance)\n"
        + "MODEL_LOAD_SECONDS = time.perf_counter() - _LOAD_T0\n"
        + "MODEL_READY_SECONDS = MODEL_LOAD_SECONDS\n",
        "server start",
    )
    source += (
        "\nSESSION_OVERHEAD_SECONDS = time.time() - SESSION_WALL_T0\n"
        "MANIFEST.setdefault('session', []).append({\n"
        "    'repeats': list(SESSION_REPEATS),\n"
        "    'model_load_seconds': MODEL_LOAD_SECONDS,\n"
        "    'model_ready_seconds': MODEL_READY_SECONDS,\n"
        "    'session_overhead_seconds': SESSION_OVERHEAD_SECONDS,\n"
        "    'health_blocked_inside_start': True,\n"
        "})\n"
        "MANIFEST['hardware'] = {'gpu_count': torch.cuda.device_count(), "
        "'gpu_names': [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())], "
        "'tensor_parallel_size': tp_size}\n"
        "(WORKING_DIR / 'pair_manifest.json').write_text("
        "json.dumps(MANIFEST, indent=2, sort_keys=True))\n"
        "append_jsonl(WORKING_DIR / 'events.jsonl', "
        "{'event': 'server_ready', 'model_load_seconds': MODEL_LOAD_SECONDS})\n"
        "copy_server_log(server_instance, WORKING_DIR / 'server.log')\n"
        "record_startup_health(server_instance, WORKING_DIR / 'events.jsonl')\n"
    )
    return source


def _multi_eval_cell(source, budgets, labels):
    source = _strip_paired_budget_prelude(source)
    source = source.replace(
        "SAMPLE_TASKS = tasks[:2]",
        "SAMPLE_TASKS = [t for t in tasks if t.instance_id in TASK_IDS]",
    )
    start, end = _call_span(source, "eval_config = EvalConfig(")
    config = source[start:end]
    config = _replace_required(
        config,
        ["results_dir=WORKING_DIR / 'results'", 'results_dir=WORKING_DIR / "results"'],
        "results_dir=results_dir",
        "results_dir",
    )
    config = _replace_required(
        config,
        ["submission_dir=AGENT_DIR"],
        "submission_dir=arm_dir",
        "submission_dir",
    )
    if "sandbox='subprocess'" not in config and 'sandbox="subprocess"' not in config:
        raise ValueError("Official starter structure changed; missing subprocess sandbox")
    frame = source.index("submission_df =", end)
    cap = session_cap_seconds(budgets, labels)
    indented = "\n".join(("    " + line if line.strip() else line) for line in config.splitlines())
    safe_config = indented.replace("{", "{{").replace("}", "}}")
    report_source = inspect.getsource(multi_smoke_report).rstrip() + "\n"
    render_source = inspect.getsource(render_multi_smoke_md).rstrip() + "\n"
    driver = f"""def make_evaluator(label, repeat):
    arm_dir = ARM_DIRS[label]
    results_dir = WORKING_DIR / 'results' / label / f'r{{repeat}}'
    results_dir.mkdir(parents=True, exist_ok=True)
    budgets = ARM_BUDGETS[label]
    disk = read_arm_budgets(arm_dir)
    assert disk == budgets, (label, disk, budgets)
    max_tool_calls = int(budgets['max_tool_calls'])
    max_time_minutes = float(budgets['max_time_minutes'])
    timeout_seconds = int(budgets['timeout_seconds'])
    max_turns = int(budgets['max_turns'])
{safe_config}
    assert eval_config.concurrency == 1
    assert eval_config.max_tool_calls == max_tool_calls
    assert eval_config.max_time_minutes == max_time_minutes
    assert eval_config.sandbox == 'subprocess'
    return Evaluator(eval_config)

def rebuild(label, repeat):
    return make_evaluator(label, repeat)

def run_evaluate(evaluator, task, dashboard, task_index, total_tasks):
    return run_sync(evaluator.evaluate_task, task=task, task_index=task_index,
                    total_tasks=total_tasks, slot_id=0, dashboard=dashboard)

def server_health():
    return probe_model_health(server_instance)

def restart_model_server():
    copy_server_log(server_instance, WORKING_DIR / 'server.log')
    _t0 = time.perf_counter()
    _pid = server_process_pid(server_instance)
    _pgid = session_pgid(_pid)
    server_instance.stop()
    _release = release_server_after_stop(_pgid, server_instance.base_url)
    print('server restart waited on', _release)
    _row = {{'event': 'server_restart_release', 'release': _release}}
    if _release.get('kill_refused_reason'):
        _row['kill_refused_pgid'] = _release['kill_refused_pgid']
        _row['kill_refused_reason'] = _release['kill_refused_reason']
    append_jsonl(WORKING_DIR / 'events.jsonl', _row)
    start_model_server(server_instance)
    copy_server_log(server_instance, WORKING_DIR / 'server.log')
    record_startup_health(server_instance, WORKING_DIR / 'events.jsonl')
    return time.perf_counter() - _t0

def read_prefix_cache():
    return read_model_prefix_cache(server_instance)

ARMS = {{
    label: {{'sha256': ARM_SHA[label], 'root': ARM_DIRS[label], 'files': ARM_FILES[label]}}
    for label in LABELS
}}
TASKS = {{task.instance_id: task for task in tasks if task.instance_id in set(TASK_IDS)}}
SESSION_RESULT = execute_session(
    schedule=SESSION_SCHEDULE,
    tasks=TASKS,
    rebuild=rebuild,
    run_evaluate=run_evaluate,
    output_dir=WORKING_DIR,
    arms=ARMS,
    schedule_sha256=SCHEDULE_SHA,
    cap_seconds={cap!r},
    session_budget_seconds=SESSION_BUDGET_SECONDS,
    clock=time.perf_counter,
    session_start=SESSION_PERF_T0,
    health=server_health,
    restart_server=restart_model_server,
    capture_server_log=lambda: copy_server_log(server_instance, WORKING_DIR / 'server.log'),
    import_origins=IMPORT_ORIGINS,
    early_stop=EARLY_STOP,
    prefix_cache=read_prefix_cache,
    model_load_seconds=MODEL_LOAD_SECONDS,
    session_overhead_seconds=SESSION_OVERHEAD_SECONDS,
    pair_pad_seconds=PAIR_PAD_SECONDS,
    manifest=MANIFEST,
    sandbox_tmp=Path('/tmp'),
    session_start_epoch=SESSION_WALL_T0,
    exclude_import_origin=EXCLUDE_IMPORT_ORIGIN,
    protocol_sha256=PROTOCOL_SHA,
    requested_tier=TIMING_TIER,
    initial_stopped=[],
)
"""
    tail = f"""
_SMOKE_REPORT = multi_smoke_report(
    SESSION_RESULT['rows'],
    labels=LABELS,
    names=ARM_NAMES,
    budgets=ARM_BUDGETS,
    protocol_sha256=PROTOCOL_SHA,
    schedule_sha256=SCHEDULE_SHA,
    task_schedule_sha256=TASK_SCHEDULE_SHA,
    session_cap_seconds={cap!r},
    hygiene=(SESSION_RESULT.get('report') or {{}}).get('hygiene', 'not_computed'),
)
_SMOKE_REPORT['notes'] = PROTOCOL_NOTES
assert _SMOKE_REPORT['winner'] is None
assert _SMOKE_REPORT['promotion'] == 'not_eligible'
assert _SMOKE_REPORT['purpose'] == 'smoke'
assert _SMOKE_REPORT['n_arms'] == len(LABELS)
_SMOKE_MD = render_multi_smoke_md(_SMOKE_REPORT)
write_json_fsync(WORKING_DIR / 'multi_report.json', _SMOKE_REPORT)
write_json_fsync(WORKING_DIR / 'pair_report.json', _SMOKE_REPORT)
(WORKING_DIR / 'multi_report.md').write_text(_SMOKE_MD)
(WORKING_DIR / 'pair_report.md').write_text(_SMOKE_MD)
print('smoke, not promotion eligible')
print('winner', _SMOKE_REPORT['winner'])
predictions = []
"""
    driver = driver + report_source + render_source + tail
    result = source[:start] + driver + source[frame:]
    if "AGENT_DIR" in result:
        raise ValueError(
            "Multi-arm eval cell still references AGENT_DIR. Review generator before continuing"
        )
    return result


def _markdown_cell(n_arms):
    return [
        "# Gemma 4 Agent Lab — combined multi-arm smoke\n",
        "\n",
        "smoke, not promotion eligible. One repeat cannot name a winner.\n",
        "\n",
        f"{n_arms} hash-pinned arms share one vLLM server and one model load. ",
        "Adapted from the official starter. This private notebook does not submit ",
        "to the leaderboard.\n",
        "\n",
        "The embedded runtime is the two-arm runtime, unchanged. `build_schedule` ",
        "is not used. The notebook embeds an N-arm schedule and `execute_session` ",
        "walks every label in `order`. After the session, the notebook replaces ",
        "`pair_report.json` because the embedded report only totals arms A and B.\n",
        "\n",
        "The session `cap_seconds` is the max of the arm time caps. Each evaluator ",
        "uses that arm's own `eval_config.yaml` limits.\n",
        "\n",
        "Restart refuses to signal process groups None, 0, -1, 1, and its own group. ",
        "Each nvidia-smi poll is capped at 10 s and by the time left in the ",
        "60 s release deadline. Only a full 10 s expiry is logged as unknown.\n",
        "Health uses `health_url` when the server has one; otherwise the root is ",
        "`base_url` with a trailing `/v1` removed. `/health` and `/metrics` are ",
        "requested on that root. Three consecutive failures, 2 s apart, restart ",
        "the server once. A dead server process restarts immediately. When the ",
        "re-check passes, the same task runs once and no ",
        "`model_server_unhealthy` row is written.\n",
    ]


def generate_multi(
    protocol_path,
    owner,
    slug,
    output,
    repeats_in_session="1",
    bundle_datasets=None,
    wheelhouse_version=None,
):
    """Generate one combined smoke notebook. Does not call ``generate_pair``."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", owner) or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("Invalid Kaggle owner or notebook slug")
    # Two-arm loader must keep refusing this file. That is the separation.
    try:
        load_protocol(protocol_path)
    except ValueError as exc:
        if "exactly A and B" not in str(exc):
            raise
    else:
        raise ValueError("Refusing to generate a multi-arm notebook from a two-arm protocol")
    protocol = load_multi_protocol(protocol_path)
    from gemma_lab.paired import PYTEST_COMMAND_LITERALS

    pins = load_grading_pins()
    if list(pins.get("pytest_command_literals") or []) != list(PYTEST_COMMAND_LITERALS):
        raise ValueError("grading pin pytest literals do not match the runtime constant")
    labels = list(protocol["arms"])
    cohort_ids = list(protocol["_task_ids"])
    repeats = int(protocol["repeats"])
    session_repeats = parse_repeats(repeats_in_session, repeats)
    schedule = build_multi_schedule(
        cohort_ids,
        labels,
        repeats=repeats,
        shuffle_seed=protocol.get("shuffle_seed"),
    )
    task_schedule = build_schedule(
        cohort_ids, repeats=repeats, shuffle_seed=protocol.get("shuffle_seed")
    )
    if schedule["rule"] != ORDER_RULE or task_schedule["rule"] != ORDER_RULE:
        raise ValueError("Schedule rule drifted from the approved parity rule")
    wheelhouse_source = _wheelhouse_source(wheelhouse_version)
    starter = Path("vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb")
    metadata = Path("vendor/official/notebook/kernel-metadata.json")
    if not starter.exists():
        raise ValueError("Run gemma-lab fetch-starter first")
    notebook = json.loads(starter.read_text())
    codes = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    if len(codes) != 6 or "SAMPLE_SUBMISSION_SRC" not in codes[1]:
        raise ValueError("Official starter structure changed; review generator before continuing")
    _require(codes[0], _WHEEL_ANCHOR, "wheelhouse anchor")
    _require(codes[3], "server_instance.start()", "server start")
    _require(codes[3], "validate_single_declared_model(AGENT_DIR)", "single-model validation")
    _require(codes[3], "discover_adapters(str(AGENT_DIR)", "adapter discovery")
    _require(codes[4], "SAMPLE_TASKS = tasks[:2]", "sample task anchor")
    _require(codes[4], "eval_config = EvalConfig(", "EvalConfig")
    _require(codes[4], "for idx, task in enumerate", "task loop")
    _require(codes[4], "submission_df =", "submission frame")
    _require(codes[4], "sandbox='subprocess'", "subprocess sandbox")
    datasets = dict(bundle_datasets or {})
    for label, spec in protocol["arms"].items():
        if spec.get("bundle_dataset"):
            datasets.setdefault(label, spec["bundle_dataset"])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    packed = {}
    with tempfile.TemporaryDirectory() as tmp:
        for label in labels:
            archive = Path(tmp) / f"{label}.zip"
            manifest = pack(protocol["arms"][label]["source"], archive)
            expected = protocol["arms"][label].get("expected_sha256")
            if expected and manifest["sha256"] != expected:
                raise ValueError(f"Arm {label} archive {manifest['sha256']} != pinned {expected}")
            info = inspect_arm(protocol["arms"][label]["source"])
            manifest["budgets"] = info["budgets"]
            manifest["name"] = protocol["arms"][label]["name"]
            manifest["payload_setup"] = _arm_payload_setup(label, archive, datasets.get(label))
            manifest["payload_bytes"] = archive.read_bytes()
            packed[label] = manifest
            packed[label]["inspected"] = info
    inspected = {label: packed[label]["inspected"] for label in labels}
    shas = {label: packed[label]["sha256"] for label in labels}
    assert_multi_compatible(
        inspected,
        shas,
        list(protocol.get("allowed_differences") or []),
        allow_identical=bool(protocol.get("allow_identical")),
    )
    budgets = {label: packed[label]["budgets"] for label in labels}
    cap = session_cap_seconds(budgets, labels)
    minimum = pair_fits_minimum_budget(
        len(cohort_ids),
        len(labels),
        cap,
        pad_seconds=int(protocol["pair_start_pad_seconds"]),
        extra_elapsed=DATA_WAIT_SECONDS,
    )
    if int(protocol["session_budget_seconds"]) < minimum:
        raise ValueError(
            "session_budget_seconds "
            f"{protocol['session_budget_seconds']} is under the worst-case pair_fits "
            f"budget {minimum:.0f} (load {LOAD_SECONDS:.0f}s, data wait {DATA_WAIT_SECONDS}s, "
            f"session cap {cap:.0f}s)"
        )
    wheel_cell = codes[0].replace(_WHEEL_ANCHOR, _WHEEL_INSERT)
    if not wheel_cell.endswith("\n"):
        wheel_cell += "\n"
    codes[0] = (
        "import time\nSESSION_WALL_T0 = time.time()\nSESSION_PERF_T0 = time.perf_counter()\n"
        + wheel_cell
        + _harness_pin_block()
    )
    codes[1] = _multi_payload_cell(
        protocol, packed, cohort_ids, schedule, task_schedule, session_repeats, pins
    )
    codes[3] = _multi_server_cell(codes[3])
    codes[4] = _multi_eval_cell(codes[4], budgets, labels)
    # Protocol notes are a notebook constant, set next to the report call.
    notes_line = f"PROTOCOL_NOTES = {protocol['notes'].strip()!r}\n"
    marker = "_SMOKE_REPORT['notes'] = PROTOCOL_NOTES\n"
    if marker not in codes[4]:
        raise ValueError("Multi-arm eval cell is missing the protocol notes assignment")
    codes[4] = codes[4].replace(marker, notes_line + marker, 1)
    codes[5] = (
        "import hashlib\n"
        "for _label, _expected in ARM_SHA.items():\n"
        "    _blob = (WORKING_DIR / 'arms' / _label / 'submission.zip').read_bytes()\n"
        "    assert hashlib.sha256(_blob).hexdigest() == _expected\n"
        "print('Multi-arm archives remain the hash-pinned payloads')\n"
    )
    runtime = notebook_runtime_source()
    compile(runtime, "paired_runtime", "exec")
    notebook["cells"] = [
        {"cell_type": "markdown", "metadata": {}, "source": _markdown_cell(len(labels))},
        code_cell(codes[0]),
        code_cell(runtime),
        code_cell(codes[1]),
        code_cell(codes[2]),
        code_cell(codes[3]),
        code_cell(codes[4]),
        code_cell(codes[5]),
        code_cell("server_instance.stop()\n"),
    ]
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        _assert_model_imports_safe(source, f"notebook cell {index}")
        compile(source, "generated_notebook", "exec")
    write_json(output / "evaluation.ipynb", notebook)
    meta = json.loads(metadata.read_text())
    meta.update(
        {
            "id": f"{owner}/{slug}",
            "title": slug.replace("-", " "),
            "code_file": "evaluation.ipynb",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": False,
        }
    )
    meta.pop("id_no", None)
    meta["dataset_sources"] = _pin_dataset_sources(meta.get("dataset_sources"), wheelhouse_version)
    for dataset in datasets.values():
        if dataset not in meta["dataset_sources"]:
            meta["dataset_sources"].append(dataset)
    write_json(output / "kernel-metadata.json", meta)
    arm_provenance = {}
    for label, manifest in packed.items():
        arm_provenance[label] = {
            "name": manifest["name"],
            "sha256": manifest["sha256"],
            "budgets": manifest["budgets"],
            "files": manifest["files"],
            "source": manifest["source"],
            "git_revision": manifest["git_revision"],
        }
    record = {
        "generated_at": now(),
        "git_revision": git_revision(),
        "starter_sha256": sha256(starter),
        "protocol_sha256": protocol["_sha256"],
        "protocol_path": protocol["_path"],
        "purpose": "smoke",
        "schedule_sha256": schedule["sha256"],
        "task_schedule_sha256": task_schedule["sha256"],
        "order_rule": ORDER_RULE,
        "session_cap_seconds": cap,
        "repeats_in_session": session_repeats,
        "pins_mode": protocol["pins_mode"],
        "wheelhouse_dataset": wheelhouse_source,
        "wheelhouse_version": wheelhouse_version,
        "harness_verified_pairs": harness_verified_pairs(),
        "arms": arm_provenance,
        "status": "generated",
    }
    write_json(output / "provenance.json", record)
    write_json(
        output / "schedule.json",
        {
            "sha256": schedule["sha256"],
            "task_schedule_sha256": task_schedule["sha256"],
            "rule": schedule["rule"],
            "entries": schedule["entries"],
        },
    )
    write_json(output / "pair_manifest.json", record)
    return {
        "folder": str(output),
        "kernel": meta["id"],
        "schedule_sha256": schedule["sha256"],
        "task_schedule_sha256": task_schedule["sha256"],
        "session_cap_seconds": cap,
        "n_task_runs": len(cohort_ids) * len(labels),
        "arms": {label: packed[label]["sha256"] for label in labels},
    }


def _load_pair_rows(run_dir):
    path = Path(run_dir) / "pair_results.jsonl"
    if not path.is_file():
        raise ValueError(f"Missing pair_results.jsonl in {run_dir}")
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def multi_report_from_runs(run_dirs, protocol_path, output, allow_protocol_mismatch=False):
    """Regenerate the smoke report. Refuses a protocol_sha256 mismatch."""
    protocol = load_multi_protocol(protocol_path)
    labels = list(protocol["arms"])
    schedule = build_multi_schedule(
        protocol["_task_ids"],
        labels,
        repeats=int(protocol["repeats"]),
        shuffle_seed=protocol.get("shuffle_seed"),
    )
    task_schedule = build_schedule(
        protocol["_task_ids"],
        repeats=int(protocol["repeats"]),
        shuffle_seed=protocol.get("shuffle_seed"),
    )
    names = {label: protocol["arms"][label]["name"] for label in labels}
    budgets = {}
    for label in labels:
        source = Path(protocol["arms"][label]["source"])
        if not source.is_dir():
            raise ValueError(f"Arm {label} source is not a directory: {source}")
        budgets[label] = inspect_arm(source)["budgets"]
    rows = []
    mismatch_notes = []
    for run_dir in run_dirs:
        manifest_path = Path(run_dir) / "pair_manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            note = _check_manifest_protocol(
                manifest,
                protocol,
                run_dir,
                allow_mismatch=allow_protocol_mismatch,
            )
            if note:
                mismatch_notes.append(note)
            recorded = manifest.get("schedule_sha256")
            if recorded and recorded != schedule["sha256"]:
                raise ValueError("Run schedule hash does not match the protocol schedule")
        rows.extend(_load_pair_rows(run_dir))
    report = multi_smoke_report(
        rows,
        labels=labels,
        names=names,
        budgets=budgets,
        protocol_sha256=protocol["_sha256"],
        schedule_sha256=schedule["sha256"],
        task_schedule_sha256=task_schedule["sha256"],
        session_cap_seconds=session_cap_seconds(budgets, labels),
        notes=protocol.get("notes"),
    )
    if mismatch_notes:
        report["protocol_mismatch_warning"] = mismatch_notes
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "multi_report.json", report)
    (output / "multi_report.md").write_text(render_multi_smoke_md(report))
    return {
        "output": str(output),
        "promotion": report["promotion"],
        "winner": report["winner"],
        "n_arms": report["n_arms"],
    }
