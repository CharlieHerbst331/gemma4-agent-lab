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
    selected = _task_ids(directory, task_ids)
    manifest = _read_json(directory / "run_manifest.json")
    tasks = []
    for instance_id in selected:
        patch_path = _patch_file(directory, instance_id)
        patch_text = patch_path.read_text() if patch_path else ""
        # Real runs store an ATIF trajectory here. results/<id>.json stringifies
        # SessionTrace via default=str, so it is not a trace source.
        trace_path = directory / "results" / "traces" / f"trace_{instance_id}.json"
        trace = _read_trace(trace_path)
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
    tasks.sort(key=lambda item: item["instance_id"])
    rate_findings = _rate_findings(tasks, policy)
    candidate_gate = _gate([*rate_findings, *(item for task in tasks for item in task["findings"])])
    schemas = {task["trace_schema"] for task in tasks}
    recognized = schemas - {"absent", "unknown"}
    if len(recognized) == 1 and schemas <= recognized | {"absent"}:
        trace_schema = next(iter(recognized))
    elif len(schemas) == 1:
        trace_schema = next(iter(schemas))
    else:
        trace_schema = "mixed"
    return {
        "schema": SCHEMA,
        "checker_version": CHECKER_VERSION,
        "policy_sha256": policy_sha,
        "run": str(directory),
        "archive_sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
        "trace_schema": trace_schema,
        "gate": candidate_gate,
        "candidate": {
            "gate": candidate_gate,
            "explicit_finalization": _ratio(tasks, lambda task: task["finalization"] == "explicit"),
            "verifier_reached": _verifier_ratio(tasks),
            "scratch_leak_tasks": _ratio(tasks, lambda task: _has(task, "H1.scratch", "block")),
            "test_edit_tasks": _ratio(tasks, lambda task: _has(task, "H2.protected", "block")),
            "debug_print_tasks": _ratio(tasks, lambda task: _has(task, "H4.print", "warn")),
            "reasons": [item["evidence"] for item in rate_findings],
            "findings": rate_findings,
        },
        "tasks": tasks,
    }


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


def _patch_file(directory: Path, instance_id: str) -> Path | None:
    for relative in (
        Path("results/patches") / f"{instance_id}.patch",
        Path("patches") / f"{instance_id}.patch",
    ):
        path = directory / relative
        if path.is_file():
            return path
    return None


def _read_json(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise HygieneInputError(f"Invalid JSON: {path}") from exc


def _read_trace(path: Path):
    """Load one ATIF file. Missing or invalid JSON is unknown, not an exception."""
    if not path.is_file():
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
            lines.append(f"{task['instance_id']} {task['gate']} {task['finalization']} {rules}")
        gate = report["gate"]
        lines.append(f"candidate {gate}")
        return "\n".join(lines)
    rules = ",".join(sorted({item["rule"] for item in report.get("findings", [])})) or "-"
    label = report.get("candidate") or "patch"
    return f"{label} {report.get('gate', 'pass')} {rules}"
