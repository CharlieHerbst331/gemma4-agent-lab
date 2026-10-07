import argparse
import json
from pathlib import Path

from gemma_lab import bundle, metrics, operations, tasks
from gemma_lab.common import COMPETITION, kaggle, write_json


def main():
    parser = argparse.ArgumentParser(description="Gemma 4 agent development kit")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Check environment and optional account access")
    doctor.add_argument("--online", action="store_true")
    sub.add_parser("fetch-starter", help="Download official getting-started notebook")
    fetch = sub.add_parser(
        "fetch", help="Download selected competition files (never all by default)"
    )
    fetch.add_argument("files", nargs="+", help="Exact paths from kaggle competitions files")
    fetch.add_argument("--output", type=Path, default=Path("data/competition"))
    for name in ["validate", "pack"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("source", type=Path)
        if name == "pack":
            cmd.add_argument("--output", type=Path, default=Path("artifacts/submission.zip"))
    split = sub.add_parser("split", help="Freeze task groups into train/dev/holdout")
    split.add_argument("tasks", type=Path)
    split.add_argument("--output", type=Path, default=Path("data/splits.json"))
    split.add_argument("--seed", type=int, default=42)
    split.add_argument("--holdout-repo")
    export = sub.add_parser(
        "export-tasks", help="Agent-safe export; labels only with --with-labels"
    )
    export.add_argument("tasks", type=Path)
    export.add_argument("--splits", type=Path, default=Path("data/splits.json"))
    export.add_argument("--partition", choices=["train", "dev", "holdout"], default="dev")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--with-labels", action="store_true")
    report = sub.add_parser("report")
    report.add_argument("results", type=Path)
    report.add_argument("--baseline", type=Path)
    report.add_argument("--output", type=Path)
    research = sub.add_parser("research")
    research.add_argument("--query", default="Gemma coding agent")
    research.add_argument("--output", type=Path, default=Path("runs/research/latest.json"))
    notebook = sub.add_parser("notebook", help="Generate private offline GPU evaluation notebook")
    notebook.add_argument("source", type=Path)
    notebook.add_argument("--owner", required=True)
    notebook.add_argument("--slug", default="gemma4-agent-lab-baseline")
    notebook.add_argument("--task-ids", type=Path, help="JSON array of selected public task IDs")
    notebook.add_argument("--bundle-dataset", help="owner/slug for a private large bundle dataset")
    notebook.add_argument("--output", type=Path, default=Path("notebooks/generated/baseline"))
    push = sub.add_parser("push-notebook", help="Upload and run a prepared private notebook")
    push.add_argument("folder", type=Path)
    push.add_argument("--execute", action="store_true")
    upload = sub.add_parser("upload-bundle", help="Stage/upload a private adapter bundle dataset")
    upload.add_argument("archive", type=Path)
    upload.add_argument("--owner", required=True)
    upload.add_argument("--slug", required=True)
    upload.add_argument("--output", type=Path, required=True)
    upload.add_argument("--execute", action="store_true")
    upload.add_argument("--version", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--kernel", help="owner/notebook-slug")
    output = sub.add_parser("pull-output")
    output.add_argument("kernel")
    output.add_argument("--output", type=Path, default=Path("runs/kaggle"))
    logs = sub.add_parser("logs", help="Read persisted Kaggle notebook logs")
    logs.add_argument("kernel")
    logs.add_argument("--output", type=Path)
    submit = sub.add_parser("submit", help="Plan or upload an archive; enforces one/day")
    submit.add_argument("archive", type=Path)
    submit.add_argument("--message", required=True)
    submit.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        match args.command:
            case "doctor":
                result = operations.doctor(args.online)
            case "fetch-starter":
                result = operations.fetch_starter()
            case "fetch":
                result = operations.fetch_files(args.files, args.output)
            case "validate":
                result = {"files": len(bundle.validate(args.source)), "portable_checks": "passed"}
            case "pack":
                result = bundle.pack(args.source, args.output)
            case "split":
                result = tasks.split_tasks(args.tasks, args.output, args.seed, args.holdout_repo)
            case "export-tasks":
                result = {
                    "exported": tasks.export_tasks(
                        args.tasks, args.splits, args.partition, args.output, not args.with_labels
                    )
                }
            case "report":
                rows = metrics.load_results(args.results)
                result = (
                    metrics.compare(metrics.load_results(args.baseline), rows)
                    if args.baseline
                    else metrics.summary(rows)
                )
                if args.output:
                    write_json(args.output, result)
            case "research":
                result = operations.research(args.query, args.output)
            case "notebook":
                from gemma_lab.notebook import generate

                result = generate(
                    args.source,
                    args.owner,
                    args.slug,
                    args.output,
                    args.task_ids,
                    args.bundle_dataset,
                )
            case "upload-bundle":
                result = operations.upload_bundle(
                    args.archive, args.owner, args.slug, args.output, args.execute, args.version
                )
            case "push-notebook":
                metadata = json.loads((args.folder / "kernel-metadata.json").read_text())
                if not metadata["is_private"] or metadata["enable_internet"]:
                    raise ValueError("Development notebooks must be private and offline")
                result = kaggle("kernels", "push", "-p", args.folder) if args.execute else metadata
            case "status":
                result = (
                    kaggle("kernels", "status", args.kernel)
                    if args.kernel
                    else kaggle("competitions", "submissions", COMPETITION, "--csv")
                )
            case "pull-output":
                result = kaggle("kernels", "output", args.kernel, "-p", args.output)
            case "logs":
                result = kaggle("kernels", "logs", args.kernel)
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(result)
            case "submit":
                result = operations.submit(args.archive, args.message, execute=args.execute)
        print(json.dumps(result, indent=2) if not isinstance(result, str) else result)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
