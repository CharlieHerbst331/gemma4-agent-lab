"""Offline patch hygiene. Controller tooling only; nothing here is packed into an agent."""

import json
import sys
from pathlib import Path

from gemma_lab.hygiene.candidate import lint_tree
from gemma_lab.hygiene.diffparse import parse_diff
from gemma_lab.hygiene.errors import HygieneInputError
from gemma_lab.hygiene.policy import load_policy
from gemma_lab.hygiene.rules import (
    audit_files,
    finalization,
    finalization_findings,
    sort_findings,
)
from gemma_lab.hygiene.trace import parse_trace

CHECKER_VERSION = "0.1.0"
SCHEMA = "gemma-lab/hygiene/v1"

__all__ = [
    "CHECKER_VERSION",
    "HygieneInputError",
    "audit_patch",
    "audit_run",
    "lint_candidate",
    "run_cli",
    "strip_evidence",
]


def audit_patch(text, trace=None, policy=None, *, require_trace=False, policy_sha=None):
    """Audit one unified diff. `trace` is optional result JSON, never inferred."""
    if isinstance(text, Path):
        if not text.is_file():
            raise HygieneInputError(f"Patch not found: {text}")
        text = text.read_text()
    if not isinstance(text, str):
        raise HygieneInputError("Patch text must be a string")
    policy, policy_sha = _policy(policy, policy_sha)
    try:
        files = parse_diff(text)
    except ValueError as exc:
        raise HygieneInputError(str(exc)) from exc
    view = parse_trace(trace)
    if require_trace and not view.recognized:
        raise HygieneInputError("Trace schema is unrecognized")
    supplied = trace is not None
    info = finalization(view, text, trace_was_supplied=supplied)
    findings = audit_files(files, view.events, policy)
    findings.extend(finalization_findings(info))
    findings = sort_findings(findings)
    report = {
        "schema": SCHEMA,
        "checker_version": CHECKER_VERSION,
        "policy_sha256": policy_sha,
        "gate": _gate(findings),
        "finalization": info["finalization"],
        "verifier_reached": info["verifier_reached"],
        "submit_calls": info["submit_calls"],
        "submitting_agents": info["submitting_agents"],
        "evidence_blocked": any(item.get("evidence_blocked") for item in findings),
        "changed_paths": [parsed.path for parsed in files if parsed.path],
        "new_files": [parsed.path for parsed in files if parsed.added and parsed.path],
        "trace_schema": view.schema,
        "findings": findings,
    }
    return report


def audit_run(directory, policy=None, task_ids=None, *, require_trace=False):
    """Audit a pulled run directory without modifying its raw files."""
    directory = Path(directory)
    if not directory.is_dir():
        raise HygieneInputError(f"Run directory not found: {directory}")
    policy, policy_sha = _policy(policy, None)
    selected = _selected_tasks(directory, task_ids)
    manifest = _read_json(directory / "run_manifest.json")
    tasks = []
    for group, instance_id in selected:
        arm, replicate = _arm_replicate(directory, group)
        patch_path = _patch_file(directory, group, instance_id)
        patch_text = patch_path.read_text() if patch_path else ""
        # Parsed source is the harness ATIF file trace_<id>.json. The notebook
        # may JSON-encode SessionTrace into results/<id>.json; that file is not
        # a trace source. Paired notebooks nest traces at results/<arm>/r<k>/traces/.
        trace = _read_trace(_find_trace(directory, group, instance_id))
        if require_trace and trace is None:
            raise HygieneInputError(f"Missing trace for {instance_id}")
        report = audit_patch(
            patch_text,
            trace=trace,
            policy=policy,
            policy_sha=policy_sha,
            require_trace=require_trace,
        )
        # A missing trace in a run is unknown finalization and a WARN.
        # Patch-only debugging does not warn merely because --trace was omitted.
        if trace is None:
            report["findings"] = sort_findings(
                [
                    *report["findings"],
                    {
                        "rule": "H3.unknown",
                        "severity": "warn",
                        "path": "",
                        "confidence": "high",
                        "evidence": (
                            "result JSON is missing; finalization was not inferred from the patch"
                        ),
                    },
                ]
            )
            report["finalization"] = "unknown"
            report["verifier_reached"] = None
            report["gate"] = _gate(report["findings"])
        tasks.append(
            {
                "arm": arm,
                "replicate": replicate,
                "instance_id": instance_id,
                "gate": report["gate"],
                "finalization": report["finalization"],
                "verifier_reached": report["verifier_reached"],
                "submit_calls": report["submit_calls"],
                "submitting_agents": report["submitting_agents"],
                "evidence_blocked": report["evidence_blocked"],
                "changed_paths": len(report["changed_paths"]),
                "new_files": len(report["new_files"]),
                "trace_schema": report["trace_schema"],
                "findings": report["findings"],
            }
        )
    tasks.sort(key=lambda item: (item["arm"] or "", item["replicate"] or "", item["instance_id"]))
    arm_reports = _arm_reports(tasks, policy)
    multi_arm = len(arm_reports) > 1
    if multi_arm:
        rate_findings = _tagged_arm_rates(arm_reports)
        candidate_gate = _gate(
            [*rate_findings, *(item for task in tasks for item in task["findings"])]
        )
        candidate = {
            "gate": candidate_gate,
            "explicit_finalization": None,
            "verifier_reached": None,
            "scratch_leak_tasks": None,
            "test_edit_tasks": None,
            "debug_print_tasks": None,
            "reasons": _gate_reasons(tasks, rate_findings, candidate_gate, prefix_arm=True),
            "findings": rate_findings,
        }
    else:
        candidate = _cohort(tasks, policy)
        candidate_gate = candidate["gate"]
    schemas = {task["trace_schema"] for task in tasks}
    recognized = schemas - {"absent", "unknown"}
    if len(recognized) == 1 and schemas <= recognized | {"absent"}:
        trace_schema = next(iter(recognized))
    elif len(schemas) == 1:
        trace_schema = next(iter(schemas))
    else:
        trace_schema = "mixed"
    report = {
        "schema": SCHEMA,
        "checker_version": CHECKER_VERSION,
        "policy_sha256": policy_sha,
        "run": str(directory),
        "archive_sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
        "trace_schema": trace_schema,
        "gate": candidate_gate,
        "candidate": candidate,
        "tasks": tasks,
    }
    if arm_reports:
        report["arms"] = arm_reports
    return report


def lint_candidate(directory, policy=None):
    """Static pre-GPU lint of an agent directory. Does not edit the candidate."""
    directory = Path(directory)
    policy, policy_sha = _policy(policy, None)
    findings = sort_findings(lint_tree(directory, policy))
    return {
        "schema": SCHEMA,
        "checker_version": CHECKER_VERSION,
        "policy_sha256": policy_sha,
        "candidate": str(directory),
        "gate": _gate(findings),
        "findings": findings,
    }


def strip_evidence(report):
    """Drop private evidence snippets. Public exports must use this view."""

    def walk(value):
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items() if key != "evidence"}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(report)


def run_cli(args):
    policy_path = getattr(args, "policy", None)
    fail_on = getattr(args, "fail_on", "block")
    require_trace = getattr(args, "require_trace", False)
    command = args.hygiene_command
    if command == "candidate":
        report = lint_candidate(args.source, policy_path)
    elif command == "run":
        report = audit_run(
            args.directory,
            policy_path,
            args.task_ids,
            require_trace=require_trace,
        )
    elif command == "patch":
        trace = _read_json(args.trace) if getattr(args, "trace", None) else None
        if getattr(args, "trace", None) and trace is None:
            raise HygieneInputError(f"Trace not found: {args.trace}")
        report = audit_patch(
            args.patch_file,
            trace=trace,
            policy=policy_path,
            require_trace=require_trace,
        )
    else:
        raise HygieneInputError(f"Unknown hygiene command: {command}")
    output = getattr(args, "output", None)
    if output is None:
        if command == "run":
            output = Path(args.directory) / "hygiene.json"
        else:
            output = Path("hygiene.json")
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = _summary(report)
    if summary:
        print(summary, file=sys.stderr)
    return report, _exit_code(report, fail_on)


def _policy(policy, policy_sha):
    if isinstance(policy, dict):
        return policy, policy_sha or ""
    return load_policy(policy)


def _gate(findings) -> str:
    if any(item["severity"] == "block" for item in findings):
        return "block"
    if any(item["severity"] == "warn" for item in findings):
        return "warn"
    return "pass"


def _exit_code(report, fail_on: str) -> int:
    gate = report.get("gate") or "pass"
    if fail_on == "warn" and gate in {"warn", "block"}:
        return 1
    if gate == "block":
        return 1
    return 0


def _blocking_reason(item, instance_id) -> str:
    """Name the finding that blocked the gate. Rate shortfalls are not included."""
    rule = item.get("rule") or "finding"
    path = item.get("path") or ""
    if rule == "H1.scratch":
        return f"H1 scratch file {path or '?'} in {instance_id}"
    if path:
        return f"{rule} {path} in {instance_id}"
    evidence = item.get("evidence") or ""
    if evidence:
        return f"{rule} in {instance_id}: {evidence}"
    return f"{rule} in {instance_id}"


def _gate_reasons(tasks, rate_findings, gate, *, prefix_arm=False) -> list[str]:
    """Blocking findings first. WARN rate shortfalls are not the cause of a block."""
    blocking = []
    for task in tasks:
        instance_id = task.get("instance_id") or "?"
        prefix = ""
        if prefix_arm and task.get("arm"):
            prefix = f"{task['arm']}: "
        for item in task.get("findings") or []:
            if item.get("severity") != "block":
                continue
            blocking.append(prefix + _blocking_reason(item, instance_id))
    if gate == "block":
        return blocking
    return [*blocking, *[item["evidence"] for item in rate_findings]]


def _cohort(tasks, policy) -> dict:
    rate_findings = _rate_findings(tasks, policy)
    gate = _gate([*rate_findings, *(item for task in tasks for item in task["findings"])])
    return {
        "gate": gate,
        "explicit_finalization": _ratio(tasks, lambda task: task["finalization"] == "explicit"),
        "verifier_reached": _verifier_ratio(tasks),
        "scratch_leak_tasks": _ratio(tasks, lambda task: _has(task, "H1.scratch", "block")),
        "test_edit_tasks": _ratio(tasks, lambda task: _has(task, "H2.protected", "block")),
        "debug_print_tasks": _ratio(tasks, lambda task: _has(task, "H4.print", "warn")),
        "reasons": _gate_reasons(tasks, rate_findings, gate),
        "findings": rate_findings,
    }


def _arm_reports(tasks, policy) -> list[dict]:
    names = sorted({task["arm"] for task in tasks if task.get("arm")})
    reports = []
    for arm in names:
        arm_tasks = [task for task in tasks if task.get("arm") == arm]
        summary = _cohort(arm_tasks, policy)
        summary["arm"] = arm
        replicates = []
        labels = sorted({task.get("replicate") or "" for task in arm_tasks})
        for label in labels:
            subset = [task for task in arm_tasks if (task.get("replicate") or "") == label]
            replicate = _cohort(subset, policy)
            replicate["replicate"] = label or None
            replicates.append(replicate)
        summary["replicates"] = replicates
        reports.append(summary)
    return reports


def _tagged_arm_rates(arm_reports: list[dict]) -> list[dict]:
    """Rate findings stay inside an arm. Replicates of one arm may pool; arms do not."""
    found = []
    for arm in arm_reports:
        for item in arm["findings"]:
            tagged = dict(item)
            tagged["path"] = arm["arm"]
            prefix = f"{arm['arm']}: "
            if not tagged["evidence"].startswith(prefix):
                tagged["evidence"] = prefix + tagged["evidence"]
            found.append(tagged)
    return sort_findings(found)


def _ratio(tasks, predicate) -> list[int]:
    return [sum(1 for task in tasks if predicate(task)), len(tasks)]


def _verifier_ratio(tasks):
    if not tasks or all(task["verifier_reached"] is None for task in tasks):
        return None
    return [sum(task["verifier_reached"] is True for task in tasks), len(tasks)]


def _has(task, rule, severity) -> bool:
    return any(item["rule"] == rule and item["severity"] == severity for item in task["findings"])


def _rate_findings(tasks, policy) -> list[dict]:
    count = len(tasks)
    if not count:
        return []
    explicit = sum(task["finalization"] == "explicit" for task in tasks)
    severity = policy.get("rate_severity", "warn")
    if severity != "info":
        # Coordinator decision: these rates are WARN until a baseline exists.
        severity = "warn"
    minimum_explicit = float(policy.get("explicit_submit_min_rate", 1.0))
    minimum_reached = float(policy.get("verifier_reach_min_rate", 1.0))
    found = []
    if explicit / count < minimum_explicit:
        found.append(
            {
                "rule": "R.explicit_submit_rate",
                "severity": severity,
                "path": "",
                "confidence": "high",
                "evidence": (
                    f"explicit submit_patch {explicit}/{count} is below {minimum_explicit:g}"
                ),
            }
        )
    # Single-agent runs never author verify/verifier. Skip the rate when every
    # task is null so that absence is not a permanent warning. A mix still counts
    # null as not reached.
    if any(task["verifier_reached"] is not None for task in tasks):
        reached = sum(task["verifier_reached"] is True for task in tasks)
        if reached / count < minimum_reached:
            found.append(
                {
                    "rule": "R.verifier_reach_rate",
                    "severity": severity,
                    "path": "",
                    "confidence": "high",
                    "evidence": f"verifier reached {reached}/{count} is below {minimum_reached:g}",
                }
            )
    return sort_findings(found)


def _arm_replicate(directory: Path, group: Path) -> tuple[str | None, str | None]:
    """results/<arm>/<replicate> relative to the audited directory, or the directory itself."""
    try:
        relative = group.resolve().relative_to(directory.resolve())
    except ValueError:
        relative = Path()
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == "results":
        return parts[1], parts[2]
    absolute = group.resolve().parts
    if len(absolute) >= 3 and absolute[-3] == "results":
        return absolute[-2], absolute[-1]
    return None, None


def _trace_name(instance_id: str) -> str:
    return "trace_" + instance_id.replace("/", "__") + ".json"


def _group_has_tasks(path: Path) -> bool:
    return any(
        candidate.exists()
        for candidate in (
            path / "task_results.jsonl",
            path / "patches",
            path / "traces",
            path / "results" / "patches",
            path / "results" / "traces",
        )
    )


def _run_groups(directory: Path) -> list[Path]:
    groups = []
    if _group_has_tasks(directory):
        groups.append(directory)
    results = directory / "results"
    if results.is_dir():
        for arm in sorted(path for path in results.iterdir() if path.is_dir()):
            for replicate in sorted(path for path in arm.iterdir() if path.is_dir()):
                if _group_has_tasks(replicate):
                    groups.append(replicate)
    return groups


def _ids_from_jsonl(path: Path) -> list[str]:
    identifiers = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "instance_id" not in row:
            raise HygieneInputError(f"{path} row has no instance_id")
        identifiers.append(row["instance_id"])
    return identifiers


def _ids_in_group(group: Path) -> list[str]:
    rows_path = group / "task_results.jsonl"
    if rows_path.is_file():
        return _ids_from_jsonl(rows_path)
    for patch_dir in (group / "results" / "patches", group / "patches"):
        if patch_dir.is_dir():
            names = sorted(path.stem for path in patch_dir.glob("*.patch") if path.is_file())
            if names:
                return names
    return []


def _selected_tasks(directory: Path, task_ids) -> list[tuple[Path, str]]:
    if task_ids:
        return [(directory, instance_id) for instance_id in _task_ids(directory, task_ids)]
    nested = []
    root_ids: list[str] = []
    for group in _run_groups(directory):
        identifiers = _ids_in_group(group)
        if group == directory:
            root_ids = identifiers
        else:
            nested.extend((group, instance_id) for instance_id in identifiers)
    nested_ids = {instance_id for _, instance_id in nested}
    selected = [
        (directory, instance_id) for instance_id in root_ids if instance_id not in nested_ids
    ]
    selected.extend(nested)
    if not selected:
        raise HygieneInputError("Run directory has no task_results.jsonl, patches, or --task-ids")
    return selected


def _task_ids(directory: Path, task_ids) -> list[str]:
    if task_ids:
        path = Path(task_ids)
        if not path.is_file():
            raise HygieneInputError(f"Task id file not found: {path}")
        loaded = json.loads(path.read_text())
        if isinstance(loaded, dict):
            loaded = loaded.get("task_ids", loaded.get("ids"))
        if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
            raise HygieneInputError("--task-ids must be a JSON list of strings")
        return loaded
    rows_path = directory / "task_results.jsonl"
    if rows_path.is_file():
        identifiers = []
        for line in rows_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "instance_id" not in row:
                raise HygieneInputError("task_results.jsonl row has no instance_id")
            identifiers.append(row["instance_id"])
        if identifiers:
            return identifiers
    patch_dir = directory / "results" / "patches"
    if patch_dir.is_dir():
        names = sorted(path.stem for path in patch_dir.glob("*.patch"))
        if names:
            return names
    raise HygieneInputError("Run directory has no task_results.jsonl, patches, or --task-ids")


def _patch_names(instance_id: str) -> list[str]:
    names = [f"{instance_id}.patch"]
    safe = instance_id.replace("/", "__")
    if safe != instance_id:
        names.append(f"{safe}.patch")
    return names


def _patch_file(directory: Path, group: Path, instance_id: str) -> Path | None:
    names = _patch_names(instance_id)
    roots = [
        group / "results" / "patches",
        group / "patches",
        directory / "results" / "patches",
        directory / "patches",
    ]
    for root in roots:
        for name in names:
            path = root / name
            if path.is_file():
                return path
    results = directory / "results"
    if results.is_dir():
        for name in names:
            matches = sorted(path for path in results.glob(f"*/*/patches/{name}") if path.is_file())
            if matches:
                return matches[0]
    return None


def _find_trace(directory: Path, group: Path, instance_id: str) -> Path | None:
    name = _trace_name(instance_id)
    candidates = [
        group / "traces" / name,
        group / "results" / "traces" / name,
        directory / "results" / "traces" / name,
        directory / "traces" / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    # A replicate group must not borrow another arm's trace. The glob is only
    # for a root task list whose traces live under results/<arm>/<replicate>/.
    if group == directory:
        results = directory / "results"
        if results.is_dir():
            matches = sorted(path for path in results.glob(f"*/*/traces/{name}") if path.is_file())
            if matches:
                return matches[0]
    return None


def _read_json(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise HygieneInputError(f"Invalid JSON: {path}") from exc


def _read_trace(path: Path | None):
    """Load one ATIF file. Missing or invalid JSON is unknown, not an exception."""
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"schema_version": "unparseable"}


def _summary(report) -> str:
    if "tasks" in report:
        lines = ["instance_id gate finalization rules"]
        for task in report["tasks"]:
            rules = ",".join(sorted({item["rule"] for item in task["findings"]})) or "-"
            label = task["instance_id"]
            if task.get("arm"):
                label = f"{task['arm']}/{task.get('replicate') or '-'}/{label}"
            lines.append(f"{label} {task['gate']} {task['finalization']} {rules}")
        gate = report["gate"]
        lines.append(f"candidate {gate}")
        return "\n".join(lines)
    rules = ",".join(sorted({item["rule"] for item in report.get("findings", [])})) or "-"
    label = report.get("candidate") or "patch"
    return f"{label} {report.get('gate', 'pass')} {rules}"
