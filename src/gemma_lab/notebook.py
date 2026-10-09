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
    # Kaggle workers may attach datasets under a different mount prefix.
    codes[0] = codes[0].replace(
        "# Remove broken cutlass .pth hooks if present",
        """if not any(WHEELHOUSE_DIR.glob('*.whl')):
    matches = [p for p in Path('/kaggle/input').rglob('gemma-4-developer-agent-wheelhouse')
               if p.is_dir() and any(p.glob('*.whl'))]
    assert len(matches) == 1, ('Expected one mounted official wheelhouse',
                              list(Path('/kaggle/input').iterdir()))
    WHEELHOUSE_DIR = matches[0]

# Remove broken cutlass .pth hooks if present""",
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
    codes[4] = _set_explicit_caps(codes[4], source)
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
        # The evaluator can return status SUCCESS while recording a runner failure.
        runner_error = getattr(result, 'error_message', None)
        if runner_error:
            row['agent_error'] = runner_error
            if any(marker in runner_error.lower() for marker in
                   ['exceeded session timeout', 'exceeded turns budget']):
                row['failure_class'] = 'agent_budget'
            else:
                row['failure_class'] = 'infrastructure_or_harness'
                row['error'] = runner_error
        if ("recursive dependency involving fixture 'httpbin'" in (result.test_output or '')
                and 'b/tests/conftest.py' not in patch):
            row['failure_class'] = 'infrastructure_or_harness'
            row['error'] = 'Official verification httpbin fixture setup failed'
        (WORKING_DIR / 'results' / 'patches').mkdir(parents=True, exist_ok=True)
        (WORKING_DIR / 'results' / 'patches' / f'{task.instance_id}.patch').write_text(patch)
        # Persist the harness result, including available trace and verification diagnostics.
        if hasattr(result, 'model_dump'):
            details = result.model_dump()
        elif hasattr(result, '__dict__'):
            details = vars(result)
        else:
            details = {'result': str(result)}
        def _jsonable(value, _seen=None):
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            if _seen is None:
                _seen = set()
            identity = id(value)
            if identity in _seen:
                return None
            if isinstance(value, dict):
                _seen.add(identity)
                return {str(key): _jsonable(item, _seen) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                _seen.add(identity)
                return [_jsonable(item, _seen) for item in value]
            dump = getattr(value, 'to_dict', None)
            if not callable(dump):
                dump = getattr(value, 'model_dump', None)
            if callable(dump):
                _seen.add(identity)
                try:
                    return _jsonable(dump(), _seen)
                except Exception:
                    pass
            if hasattr(value, '__dict__'):
                _seen.add(identity)
                return _jsonable(vars(value), _seen)
            return str(value)
        # Evaluator record only. The harness writes ATIF to
        # results/traces/trace_<id>.json; this cell must not replace that file.
        (WORKING_DIR / 'results' / f'{task.instance_id}.json').write_text(
            json.dumps(_jsonable(details), indent=2))
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
    codes[3] = _install_declared_model_shim(codes[3])
    codes[3] = (
        "import time as _gemma_lab_time\n"
        "_gemma_lab_model_load_started = _gemma_lab_time.perf_counter()\n" + codes[3]
    )
    codes[3] += (
        "\nRUN_PROVENANCE['model_load_seconds'] = "
        "_gemma_lab_time.perf_counter() - _gemma_lab_model_load_started\n"
        "RUN_PROVENANCE['hardware'] = {'gpu_count': torch.cuda.device_count(), "
        "'gpu_names': [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())], "
        "'tensor_parallel_size': tp_size}\n"
        "(WORKING_DIR / 'run_manifest.json').write_text(json.dumps(RUN_PROVENANCE, indent=2))\n"
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


def _require(source, needle, label):
    if needle not in source:
        raise ValueError(
            "Official starter structure changed; missing "
            f"{label}. Review generator before continuing"
        )
    return source


def _call_span(source, token):
    start = source.index(token)
    paren = source.index("(", start)
    depth = 0
    for index in range(paren, len(source)):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise ValueError("Official starter structure changed; review generator before continuing")


def _replace_required(source, options, replacement, label):
    for option in options:
        if option in source:
            return source.replace(option, replacement, 1)
    raise ValueError(
        f"Official starter structure changed; missing {label}. Review generator before continuing"
    )


_BUDGET_HARDCODE = """# max_tool_calls = int(eval_section.get('max_tool_calls', 100))
max_tool_calls = 100
# max_time_minutes = float(eval_section.get('max_time_minutes', 5.0))
max_time_minutes = 5.0
"""

# max_tool_calls and max_time_minutes are now set explicitly from eval_config;
# previously inherited from the fetched starter.
_LIVE_TOOL_CALLS = re.compile(
    r"^max_tool_calls\s*=\s*int\(eval_section\.get\((['\"])max_tool_calls\1.*\)\)\s*$",
    re.M,
)
_LIVE_TIME_MINUTES = re.compile(
    r"^max_time_minutes\s*=\s*float\(eval_section\.get\((['\"])max_time_minutes\1.*\)\)\s*$",
    re.M,
)
_PRELUDE_STARTS = (
    "# Read evaluation settings from the submission's eval_config.yaml\n",
    "eval_config_file = AGENT_DIR / 'eval_config.yaml'\n",
    'eval_config_file = AGENT_DIR / "eval_config.yaml"\n',
)
_PRELUDE_END = "max_turns = int(turns_raw) if turns_raw is not None else None\n"


def _cap_literals(source):
    from gemma_lab.paired import read_arm_budgets

    budgets = read_arm_budgets(source)
    return str(int(budgets["max_tool_calls"])), repr(float(budgets["max_time_minutes"]))


def _set_explicit_caps(cell, source):
    """Replace starter cap assignments with literals from the agent eval_config."""
    replaced = False
    if _BUDGET_HARDCODE in cell or _LIVE_TOOL_CALLS.search(cell) or _LIVE_TIME_MINUTES.search(cell):
        calls, minutes = _cap_literals(source)
        block = f"max_tool_calls = {calls}\nmax_time_minutes = {minutes}\n"
        if _BUDGET_HARDCODE in cell:
            cell = cell.replace(_BUDGET_HARDCODE, block, 1)
            replaced = True
        if _LIVE_TOOL_CALLS.search(cell) or _LIVE_TIME_MINUTES.search(cell):
            cell, call_count = _LIVE_TOOL_CALLS.subn(f"max_tool_calls = {calls}", cell, count=1)
            cell, minute_count = _LIVE_TIME_MINUTES.subn(
                f"max_time_minutes = {minutes}", cell, count=1
            )
            if call_count != 1 or minute_count != 1:
                raise ValueError(
                    "Official starter structure changed; unrecognized "
                    "max_tool_calls/max_time_minutes. Review generator before continuing"
                )
            replaced = True
    if not replaced and ("max_tool_calls" in cell or "max_time_minutes" in cell):
        raise ValueError(
            "Official starter structure changed; unrecognized "
            "max_tool_calls/max_time_minutes. Review generator before continuing"
        )
    return cell


def _strip_paired_budget_prelude(source):
    """Drop the starter budget prelude. make_evaluator sets each arm's caps."""
    start = -1
    for marker in _PRELUDE_STARTS:
        found = source.find(marker)
        if found >= 0:
            start = found if start < 0 else min(start, found)
    if start >= 0:
        end = source.find(_PRELUDE_END, start)
        if end < 0:
            raise ValueError(
                "Official starter structure changed; missing budget prelude end. "
                "Review generator before continuing"
            )
        source = source[:start] + source[end + len(_PRELUDE_END) :]
    elif _BUDGET_HARDCODE in source:
        source = source.replace(_BUDGET_HARDCODE, "", 1)
    if re.search(r"(?m)^max_tool_calls\s*=|^max_time_minutes\s*=", source):
        raise ValueError(
            "Official starter structure changed; unrecognized budget prelude. "
            "Review generator before continuing"
        )
    return source


WHEELHOUSE_DATASET = "metric/gemma-4-developer-agent-wheelhouse"
# Verified on swegemma 0.2.10 and 0.2.11 with adk-submission 0.2.13.
# swegemma 0.2.11 removed swegemma.models.discovery, swegemma.models.registry,
# and the re-exports discover_declared_models, normalize_model_name,
# resolve_local_model_path, resolve_swegemma_adapter, setup_gemma_model_registry,
# and validate_single_declared_model. Kaggle ignores the /N dataset pin and
# mounts the latest wheelhouse version. The allow-list in the first code cell
# and the installed versions recorded after the run are the real control.
# wheelhouse_version is intent only.
HARNESS_VERIFIED = (
    ("0.2.10", "0.2.13"),
    ("0.2.11", "0.2.13"),
)
_REMOVED_MODEL_NAMES = (
    "discover_declared_models",
    "normalize_model_name",
    "resolve_local_model_path",
    "resolve_swegemma_adapter",
    "setup_gemma_model_registry",
    "validate_single_declared_model",
)
_DECLARED_MODEL_IMPORT = "from swegemma.models.discovery import validate_single_declared_model\n"
_DECLARED_MODEL_SHIM = (
    "try:\n"
    "    from swegemma.models.discovery import validate_single_declared_model\n"
    "except (ImportError, ModuleNotFoundError):\n"
    "    from adk_submission.discovery import discover_declared_models\n"
    "    def _norm(name):\n"
    "        v = name.strip().lower()\n"
    "        for p in ('openai/', 'google/', 'hosted_vllm/', 'custom/'):\n"
    "            if v.startswith(p):\n"
    "                v = v[len(p):]\n"
    "        return v\n"
    "    def validate_single_declared_model(agent_dir):\n"
    "        models = discover_declared_models(agent_dir, normalize_fn=_norm)\n"
    "        if not models:\n"
    '            raise ValueError("No model declared in agent configuration.")\n'
    "        if len(models) > 1:\n"
    "            raise ValueError(\n"
    '                f"Ambiguous model declaration: {sorted(models)}"\n'
    "            )\n"
    "        return next(iter(models))\n"
)

_WHEEL_ANCHOR = "# Remove broken cutlass .pth hooks if present"
_WHEEL_INSERT = """if not any(WHEELHOUSE_DIR.glob('*.whl')):
    matches = [p for p in Path('/kaggle/input').rglob('gemma-4-developer-agent-wheelhouse')
               if p.is_dir() and any(p.glob('*.whl'))]
    assert len(matches) == 1, ('Expected one mounted official wheelhouse',
                              list(Path('/kaggle/input').iterdir()))
    WHEELHOUSE_DIR = matches[0]

# Remove broken cutlass .pth hooks if present"""


def _wheelhouse_source(version):
    """Dataset source accepted by kaggle-api ``validate_dataset_string``.

    The CLI allows ``{username}/{dataset-slug}/{version-number}`` (three
    parts). ``owner/slug/versions/29`` is four parts and is rejected.
    """
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("wheelhouse_version is required and must be a positive integer")
    return f"{WHEELHOUSE_DATASET}/{version}"


def _pin_dataset_sources(sources, version):
    pinned = _wheelhouse_source(version)
    kept = []
    for item in sources or []:
        text = str(item)
        if text == WHEELHOUSE_DATASET or text.startswith(WHEELHOUSE_DATASET + "/"):
            continue
        kept.append(item)
    return [pinned, *kept]


def harness_verified_pairs():
    """Allow-list for the generation-time pair_manifest.json.

    This is not an installed-version pin and not one required pair. The kernel
    has not run yet, so this file does not record installed versions.
    """
    return [{"swegemma": swegemma, "adk-submission": adk} for swegemma, adk in HARNESS_VERIFIED]


def _harness_pin_block():
    verified = "{" + ", ".join(repr(pair) for pair in HARNESS_VERIFIED) + "}"
    return (
        "import importlib.metadata as _pkg_metadata\n"
        "import json as _harness_json\n"
        "from pathlib import Path as _HarnessPath\n"
        f"_VERIFIED = {verified}\n"
        "def _harness_version(name):\n"
        "    try:\n"
        "        return _pkg_metadata.version(name)\n"
        "    except _pkg_metadata.PackageNotFoundError:\n"
        "        raise RuntimeError(\n"
        "            f'{name} is not installed. Refusing to start the model server.'\n"
        "        ) from None\n"
        "installed = (_harness_version('swegemma'), _harness_version('adk-submission'))\n"
        "if installed not in _VERIFIED:\n"
        "    raise RuntimeError(\n"
        "        f'unverified harness {installed}; verified: {sorted(_VERIFIED)}'\n"
        "    )\n"
        "print('Harness verified', installed)\n"
        "RUN_PROVENANCE = {\n"
        "    'harness_verified': installed in _VERIFIED,\n"
        "    'swegemma': installed[0],\n"
        "    'adk-submission': installed[1],\n"
        "}\n"
        "_manifest_path = _HarnessPath('/kaggle/working/run_manifest.json')\n"
        "try:\n"
        "    _saved = {}\n"
        "    if _manifest_path.is_file():\n"
        "        _loaded = _harness_json.loads(_manifest_path.read_text())\n"
        "        if isinstance(_loaded, dict):\n"
        "            _saved = _loaded\n"
        "    _saved['harness_verified'] = RUN_PROVENANCE['harness_verified']\n"
        "    _saved['swegemma'] = installed[0]\n"
        "    _saved['adk-submission'] = installed[1]\n"
        "    _packages = _saved.get('packages')\n"
        "    if not isinstance(_packages, dict):\n"
        "        _packages = {}\n"
        "    _packages['swegemma'] = installed[0]\n"
        "    _packages['adk-submission'] = installed[1]\n"
        "    _saved['packages'] = _packages\n"
        "    _saved['installed_harness'] = {\n"
        "        'swegemma': installed[0],\n"
        "        'adk-submission': installed[1],\n"
        "    }\n"
        "    RUN_PROVENANCE = _saved\n"
        "    _manifest_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    _manifest_path.write_text(_harness_json.dumps(_saved, indent=2) + '\\n')\n"
        "except (OSError, ValueError):\n"
        "    pass\n"
    )


def _install_declared_model_shim(source):
    """Keep the 0.2.10 import, and define the same function when it is gone."""
    if _DECLARED_MODEL_IMPORT not in source:
        return source
    if source.count(_DECLARED_MODEL_IMPORT) != 1:
        raise ValueError("Official starter structure changed; discovery import")
    return source.replace(_DECLARED_MODEL_IMPORT, _DECLARED_MODEL_SHIM, 1)


def _assert_model_imports_safe(source, label):
    """Refuse a generated cell that still needs a swegemma.models name 0.2.11 removed."""
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if "swegemma.models.registry" in stripped:
            raise ValueError(f"{label}:{lineno} imports removed swegemma.models.registry")
        if "swegemma.models.discovery" in stripped:
            if stripped != _DECLARED_MODEL_IMPORT.strip():
                raise ValueError(f"{label}:{lineno} imports removed swegemma.models.discovery")
            continue
        if not stripped.startswith("from swegemma.models import"):
            continue
        imported = stripped.split("import", 1)[1]
        for name in _REMOVED_MODEL_NAMES:
            if re.search(rf"\b{name}\b", imported):
                raise ValueError(f"{label}:{lineno} imports removed swegemma.models.{name}")


def generate_pair(
    protocol_path,
    owner,
    slug,
    output,
    repeats_in_session="1",
    prior_run=None,
    bundle_datasets=None,
    wheelhouse_version=None,
):
    """Generate a two-arm notebook. generate() is not used and its cells stay unchanged."""
    from gemma_lab.paired import (
        ORDER_RULE,
        PYTEST_COMMAND_LITERALS,
        assert_arms_compatible,
        build_schedule,
        inspect_arm,
        load_grading_pins,
        load_protocol,
        notebook_runtime_source,
        parse_repeats,
    )

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", owner) or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("Invalid Kaggle owner or notebook slug")
    wheelhouse_source = _wheelhouse_source(wheelhouse_version)
    protocol = load_protocol(protocol_path)
    if protocol.get("pins_mode") not in {"record", "enforce"}:
        raise ValueError("pins_mode must be record or enforce")
    pins = load_grading_pins()
    if list(pins.get("pytest_command_literals") or []) != list(PYTEST_COMMAND_LITERALS):
        raise ValueError("grading pin pytest literals do not match the runtime constant")
    cohort_ids = list(protocol["_task_ids"])
    repeats = int(protocol["repeats"])
    session_repeats = parse_repeats(repeats_in_session, repeats)
    schedule = build_schedule(
        cohort_ids, repeats=repeats, shuffle_seed=protocol.get("shuffle_seed")
    )
    if schedule["rule"] != ORDER_RULE:
        raise ValueError("Schedule rule drifted from the approved parity rule")
    skipped = None
    if prior_run is not None:
        prior = json.loads((Path(prior_run) / "pair_manifest.json").read_text())
        prior_status = str(prior.get("status") or "")
        for prefix in ("early_stopped:", "aborted_arm:"):
            if prior_status.startswith(prefix):
                skipped = prior_status.split(":", 1)[1]
                if skipped not in {"A", "B"}:
                    raise ValueError(f"Prior run stopped an unknown arm: {prior_status}")
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
    _require(
        codes[5],
        "zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=AGENT_DIR))",
        "archive rebuild",
    )
    datasets = dict(bundle_datasets or {})
    for label, spec in protocol["arms"].items():
        if spec.get("bundle_dataset"):
            datasets.setdefault(label, spec["bundle_dataset"])
    output.mkdir(parents=True, exist_ok=True)
    packed = {}
    with tempfile.TemporaryDirectory() as tmp:
        for label in ("A", "B"):
            archive = Path(tmp) / f"{label}.zip"
            manifest = pack(protocol["arms"][label]["source"], archive)
            expected = protocol["arms"][label].get("expected_sha256")
            if expected and manifest["sha256"] != expected:
                raise ValueError(f"Arm {label} archive {manifest['sha256']} != pinned {expected}")
            manifest["budgets"] = inspect_arm(protocol["arms"][label]["source"])["budgets"]
            manifest["payload_setup"] = _arm_payload_setup(label, archive, datasets.get(label))
            manifest["payload_bytes"] = archive.read_bytes()
            packed[label] = manifest
    inspected = {label: inspect_arm(protocol["arms"][label]["source"]) for label in ("A", "B")}
    assert_arms_compatible(
        inspected["A"],
        inspected["B"],
        allow_identical=bool(protocol.get("allow_identical")),
        allowed_differences=list(protocol.get("allowed_differences") or []),
        sha_a=packed["A"]["sha256"],
        sha_b=packed["B"]["sha256"],
    )
    budgets = {label: packed[label]["budgets"] for label in ("A", "B")}
    wheel_cell = codes[0].replace(_WHEEL_ANCHOR, _WHEEL_INSERT)
    if not wheel_cell.endswith("\n"):
        wheel_cell += "\n"
    codes[0] = (
        "import time\nSESSION_WALL_T0 = time.time()\nSESSION_PERF_T0 = time.perf_counter()\n"
        + wheel_cell
        + _harness_pin_block()
    )
    codes[1] = _pair_payload_cell(protocol, packed, cohort_ids, schedule, session_repeats, pins)
    codes[3] = _pair_server_cell(codes[3], protocol, pins)
    codes[4] = _pair_eval_cell(codes[4], protocol, budgets, skipped)
    codes[5] = (
        "import hashlib\n"
        "for _label, _expected in ARM_SHA.items():\n"
        "    _blob = (WORKING_DIR / 'arms' / _label / 'submission.zip').read_bytes()\n"
        "    assert hashlib.sha256(_blob).hexdigest() == _expected\n"
        "print('Paired archives remain the hash-pinned payloads')\n"
    )
    runtime = notebook_runtime_source()
    compile(runtime, "paired_runtime", "exec")
    notebook["cells"] = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# Gemma 4 Agent Lab — paired offline evaluation\n",
                f"Adapted from the [official starter](https://www.kaggle.com/code/{STARTER}).\n",
                "Two hash-pinned arms share one vLLM server. Grading is the official evaluator. "
                "This private notebook does not submit to the leaderboard.\n",
                "Restart refuses to signal process groups None, 0, -1, 1, and its own group. "
                "Each nvidia-smi poll is capped at 10 s and by the time left in the "
                "60 s release deadline. Only a full 10 s expiry is logged as unknown.\n",
                "Health uses `health_url` when the server has one; otherwise the root is "
                "`base_url` with a trailing `/v1` removed. `/health` and `/metrics` are "
                "requested on that root. Three consecutive failures, 2 s apart, restart "
                "the server once. A dead server process restarts immediately. When the "
                "re-check passes, the same task runs once and no "
                "`model_server_unhealthy` row is written.\n",
                "`events.jsonl` records `health_check_failed` "
                "(`url`, `status`, `error`, `kind`, `attempt`), `health_poll` for the "
                "first three polls after each start (`url`, `status`, `latency_seconds`), "
                "`task_retry`, and `gpu_memory` with `phase` `before_task` or "
                "`after_task` and `gpus` entries of `index`, `memory_used_mib`, "
                "`memory_total_mib`. `server.log` is a best-effort copy of "
                "`server_instance.log_path` after start and on abort or restart.\n",
            ],
        },
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
        "schedule_sha256": schedule["sha256"],
        "order_rule": ORDER_RULE,
        "repeats_in_session": session_repeats,
        "skipped_arm": skipped,
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
        {"sha256": schedule["sha256"], "rule": schedule["rule"], "entries": schedule["entries"]},
    )
    write_json(output / "pair_manifest.json", record)
    return {
        "folder": str(output),
        "kernel": meta["id"],
        "schedule_sha256": schedule["sha256"],
        "arms": {label: packed[label]["sha256"] for label in ("A", "B")},
    }


def _arm_payload_setup(label, archive, bundle_dataset):
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
    encoded = base64.b64encode(archive.read_bytes()).decode()
    return f"payload_{label} = base64.b64decode({encoded!r})\n"


def _pair_payload_cell(protocol, packed, cohort_ids, schedule, session_repeats, pins):
    files = {label: packed[label]["files"] for label in ("A", "B")}
    budgets = {label: packed[label]["budgets"] for label in ("A", "B")}
    shas = {label: packed[label]["sha256"] for label in ("A", "B")}
    setups = "\n".join(packed[label]["payload_setup"] for label in ("A", "B"))
    repos = load_import_repos()
    return (
        "import base64, hashlib, importlib.metadata, io, json, zipfile\n"
        "from swegemma.models import load_tasks\n"
        "_ADK_SUBMISSION_VERSION = importlib.metadata.version('adk-submission')\n"
        "assert_adk_submission_version(_ADK_SUBMISSION_VERSION)\n"
        "DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')\n"
        "WORKING_DIR = Path('/kaggle/working')\n"
        "WORKING_DIR.mkdir(parents=True, exist_ok=True)\n"
        f"ARM_SHA = {shas!r}\n"
        f"ARM_FILES = {files!r}\n"
        f"ARM_BUDGETS = {budgets!r}\n"
        f"ARM_DIRS = {{label: WORKING_DIR / 'candidates' / ARM_SHA[label][:12] "
        f"for label in ('A', 'B')}}\n"
        f"{setups}"
        "for _label in ('A', 'B'):\n"
        "    install_arm(globals()[f'payload_{_label}'], ARM_SHA[_label], "
        "ARM_DIRS[_label], ARM_FILES[_label])\n"
        "    _zip = WORKING_DIR / 'arms' / _label / 'submission.zip'\n"
        "    _zip.parent.mkdir(parents=True, exist_ok=True)\n"
        "    _zip.write_bytes(globals()[f'payload_{_label}'])\n"
        "TASKS_PATH = DATA_DIR / 'tasks.jsonl'\n"
        "tasks = load_tasks(TASKS_PATH)\n"
        f"TASK_IDS = {cohort_ids!r}\n"
        "assert set(TASK_IDS) <= {t.instance_id for t in tasks}, 'Unknown task IDs'\n"
        f"REPEATS = {int(protocol['repeats'])!r}\n"
        f"SHUFFLE_SEED = {protocol.get('shuffle_seed')!r}\n"
        f"SCHEDULE_SHA = {schedule['sha256']!r}\n"
        "RECOMPUTED = build_schedule(TASK_IDS, repeats=REPEATS, shuffle_seed=SHUFFLE_SEED)\n"
        "assert RECOMPUTED['sha256'] == SCHEDULE_SHA\n"
        f"SESSION_REPEATS = {list(session_repeats)!r}\n"
        "SESSION_SCHEDULE = [entry for entry in RECOMPUTED['entries'] "
        "if entry['repeat'] in SESSION_REPEATS]\n"
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
        "    'order_rule': 'per_task_parity_v1',\n"
        "    'task_ids': TASK_IDS,\n"
        "    'task_file_sha256': TASK_FILE_SHA,\n"
        "    'pins_mode': PINS_MODE,\n"
        "    'grading_pins': GRADING_PINS,\n"
        "    'arms': {label: {'sha256': ARM_SHA[label], 'budgets': ARM_BUDGETS[label]} "
        "for label in ('A', 'B')},\n"
        "    'session_repeats': SESSION_REPEATS,\n"
        "    'packages': {name: importlib.metadata.version(name) for name in "
        "['swegemma', 'adk-submission', 'adk-eval-core', 'vllm', 'google-adk']},\n"
        "    'adk_submission_version': _ADK_SUBMISSION_VERSION,\n"
        "    'status': 'loaded',\n"
        "}\n"
        "(WORKING_DIR / 'schedule.json').write_text("
        "json.dumps(RECOMPUTED, indent=2, sort_keys=True))\n"
        "(WORKING_DIR / 'pair_manifest.json').write_text("
        "json.dumps(MANIFEST, indent=2, sort_keys=True))\n"
        "print(f'Paired schedule {SCHEDULE_SHA[:12]} tasks={len(TASK_IDS)} "
        "repeats={SESSION_REPEATS}')\n"
    )


def load_import_repos():
    from gemma_lab.paired import load_import_origin_repos

    return load_import_origin_repos()


def _pair_server_cell(source, protocol, pins):
    source = _install_declared_model_shim(source)
    source = _replace_required(
        source,
        ["declared_model = validate_single_declared_model(AGENT_DIR)\n"],
        (
            "declared_models = [validate_single_declared_model(ARM_DIRS[label]) "
            "for label in ('A', 'B')]\n"
            "assert declared_models[0] == declared_models[1] == TARGET_MODEL_NAME\n"
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
            "adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS) for label in ('A', 'B')]\n"
            "def _adapters_empty(manifest):\n"
            "    found = getattr(manifest, 'adapters', manifest)\n"
            "    return not found\n"
            "assert _adapters_empty(adapter_sets[0]) and _adapters_empty(adapter_sets[1]), "
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


def _pair_eval_cell(source, protocol, budgets, skipped):
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
    cap = float(budgets["A"]["max_time_minutes"]) * 60.0
    indented = "\n".join(("    " + line if line.strip() else line) for line in config.splitlines())
    safe_config = indented.replace("{", "{{").replace("}", "}}")
    skipped_literal = repr([] if not skipped else [skipped])
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
    for label in ('A', 'B')
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
    initial_stopped={skipped_literal},
)
predictions = []
"""
    result = source[:start] + driver + source[frame:]
    if "AGENT_DIR" in result:
        raise ValueError(
            "Paired eval cell still references AGENT_DIR. Review generator before continuing"
        )
    return result
