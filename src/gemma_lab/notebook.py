"""Adapt the official notebook instead of maintaining a competing GPU harness."""

import base64
import json
import re
import tempfile
from pathlib import Path

from gemma_lab.bundle import pack
from gemma_lab.common import STARTER, git_revision, now, sha256, write_json


def code_cell(source):
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def generate(source, owner, slug, output, task_ids=None, bundle_dataset=None):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", owner) or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("Invalid Kaggle owner or notebook slug")
    starter = Path("vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb")
    metadata = Path("vendor/official/notebook/kernel-metadata.json")
    if not starter.exists():
        raise ValueError("Run gemma-lab fetch-starter first")
    notebook = json.loads(starter.read_text())
    codes = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    if len(codes) != 6 or "SAMPLE_SUBMISSION_SRC" not in codes[1]:
        raise ValueError("Official starter structure changed; review generator before continuing")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "submission.zip"
        provenance = pack(source, archive)
        if bundle_dataset:
            if not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-z0-9-]+", bundle_dataset):
                raise ValueError("Expected bundle dataset reference owner/slug")
            dataset_slug = bundle_dataset.split("/", 1)[1]
            payload_setup = (
                f"matches = list(Path('/kaggle/input').rglob('{dataset_slug}.zip'))\n"
                "assert len(matches) == 1, 'Expected exactly one uploaded bundle'\n"
                "payload = matches[0].read_bytes()\n"
            )
        else:
            if archive.stat().st_size > 5 * 1024**2:
                raise ValueError(
                    "Bundle >5 MiB: upload a private bundle dataset and use --bundle-dataset"
                )
            payload_setup = (
                f"payload = base64.b64decode({base64.b64encode(archive.read_bytes()).decode()!r})\n"
            )
    ids = json.loads(task_ids.read_text()) if task_ids else None
    if ids is not None and (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))):
        raise ValueError("Task IDs must be a nonempty JSON array with unique IDs")
    codes[1] = (
        "import base64, hashlib, importlib.metadata, io, json, zipfile\n"
        "from swegemma.models import load_tasks\n"
        "DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')\n"
        "WORKING_DIR = Path('/kaggle/working')\n"
        "AGENT_DIR = WORKING_DIR / 'candidate'\n"
        "AGENT_DIR.mkdir(parents=True, exist_ok=False)\n"
        + payload_setup
        + f"assert hashlib.sha256(payload).hexdigest() == {provenance['sha256']!r}\n"
        "with zipfile.ZipFile(io.BytesIO(payload)) as zf:\n"
        "    zf.extractall(AGENT_DIR)  # Locally validated, hash-pinned payload\n"
        "TASKS_PATH = DATA_DIR / 'tasks.jsonl'\n"
        "tasks = load_tasks(TASKS_PATH)\n"
        f"TASK_IDS = {ids!r}\n"
        "if TASK_IDS is None:\n"
        "    TASK_IDS = [t.instance_id for t in tasks[:2]]\n"
        "assert set(TASK_IDS) <= {t.instance_id for t in tasks}, 'Unknown task IDs'\n"
        f"RUN_PROVENANCE = {provenance!r}\n"
        "RUN_PROVENANCE['task_ids'] = TASK_IDS\n"
        "RUN_PROVENANCE['packages'] = {name: importlib.metadata.version(name) "
        "for name in ['swegemma', 'adk-submission', 'adk-eval-core', 'vllm', 'google-adk']}\n"
        "RUN_PROVENANCE['task_file_sha256'] = hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest()\n"
        "(WORKING_DIR / 'run_manifest.json').write_text(json.dumps(RUN_PROVENANCE, indent=2))\n"
        "print(f'Loaded {len(tasks)} tasks; evaluating {len(TASK_IDS)} selected tasks')\n"
    )
    codes[4] = codes[4].replace(
        "SAMPLE_TASKS = tasks[:2]", "SAMPLE_TASKS = [t for t in tasks if t.instance_id in TASK_IDS]"
    )
    start = codes[4].index("for idx, task in enumerate")
    end = codes[4].index("submission_df =", start)
    codes[4] = (
        codes[4][:start]
        + """results_path = WORKING_DIR / 'task_results.jsonl'
for idx, task in enumerate(SAMPLE_TASKS, start=1):
    print(f'[{idx}/{len(SAMPLE_TASKS)}] {task.instance_id}')
    try:
        result = run_sync(evaluator.evaluate_task, task=task, task_index=idx,
                          total_tasks=len(SAMPLE_TASKS))
        patch = result.agent_patch or ''
        row = {'instance_id': task.instance_id, 'repo': task.repo,
               'resolved': bool(result.resolved), 'test_exit_code': result.test_exit_code,
               'patch_chars': len(patch), 'tool_calls': result.tool_calls,
               'duration_seconds': result.duration_seconds}
        (WORKING_DIR / 'results' / 'patches').mkdir(parents=True, exist_ok=True)
        (WORKING_DIR / 'results' / 'patches' / f'{task.instance_id}.patch').write_text(patch)
        # Persist the harness result, including available trace and verification diagnostics.
        if hasattr(result, 'model_dump'):
            details = result.model_dump()
        elif hasattr(result, '__dict__'):
            details = vars(result)
        else:
            details = {'result': str(result)}
        (WORKING_DIR / 'results' / f'{task.instance_id}.json').write_text(
            json.dumps(details, default=str, indent=2))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        patch = ''
        row = {'instance_id': task.instance_id, 'repo': task.repo, 'resolved': False,
               'error': repr(exc), 'failure_class': 'infrastructure_or_harness'}
    with results_path.open('a') as handle:
        handle.write(json.dumps(row) + '\\n')
    predictions.append({'id': task.instance_id, 'prediction': patch})
    print(row)

"""
        + codes[4][end:]
    )
    codes[5] = codes[5].replace(
        "zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=AGENT_DIR))",
        "zip_path = WORKING_DIR / 'submission.zip'\nzip_path.write_bytes(payload)",
    )
    # Explicitly select the evaluation subprocess sandbox only on disposable Kaggle workers.
    # The original notebook already configures sandbox='subprocess'.
    notebook["cells"] = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# Gemma 4 Agent Lab — offline evaluation\n",
                f"Adapted from the [official starter](https://www.kaggle.com/code/{STARTER}).\n",
                "This private notebook evaluates selected public tasks and emits submission.zip, "
                "task_results.jsonl, patches, and provenance. "
                "It does not submit to the leaderboard.\n",
            ],
        },
        *[code_cell(code) for code in codes],
        code_cell("server_instance.stop()\n"),
    ]
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "generated_notebook", "exec")
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
    if bundle_dataset:
        meta["dataset_sources"].append(bundle_dataset)
    write_json(output / "kernel-metadata.json", meta)
    write_json(
        output / "provenance.json",
        {
            "generated_at": now(),
            "git_revision": git_revision(),
            "starter_sha256": sha256(starter),
            "bundle": provenance,
        },
    )
    return {"folder": str(output), "kernel": meta["id"], "bundle_sha256": provenance["sha256"]}
