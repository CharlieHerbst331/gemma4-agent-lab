"""swegemma 0.2.11 notebook compatibility. No real wheels and no Kaggle push."""

import importlib.metadata as metadata
import json
import shutil
import sys
from pathlib import Path

import pytest

from gemma_lab.notebook import _DECLARED_MODEL_SHIM, _harness_pin_block, generate_pair
from gemma_lab.paired import report_from_runs


def _notebook_helpers():
    import importlib.util

    path = Path(__file__).with_name("test_paired_notebook.py")
    spec = importlib.util.spec_from_file_location("paired_notebook_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = Path("configs/protocols/v6-vs-single-v2-toolcall-smoke.yaml")
_VERIFIED_SORTED = "[('0.2.10', '0.2.13'), ('0.2.11', '0.2.13')]"


def _message(installed):
    return f"unverified harness {installed}; verified: {_VERIFIED_SORTED}"


def _purge(modules):
    for name in list(sys.modules):
        if name in modules or any(name.startswith(prefix) for prefix in modules):
            del sys.modules[name]


def _write_stub(root, release):
    (root / "litellm.py").write_text("drop_params = False\n")
    (root / "torch.py").write_text("class cuda:\n    pass\n")
    (root / "adk_submission").mkdir()
    (root / "adk_submission/__init__.py").write_text(
        "class VllmConfig:\n    pass\n\n"
        "class VllmServer:\n    pass\n\n"
        "def discover_adapters(*args, **kwargs):\n    return []\n"
    )
    (root / "adk_submission/discovery.py").write_text(
        "def discover_declared_models(agent_dir, normalize_fn=None):\n    return set()\n"
    )
    package = root / "swegemma"
    (package / "harness").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "graph.py").write_text("def get_graph(**kwargs):\n    return None\n")
    (package / "config.py").write_text(
        "ALLOWED_ADAPTER_EXTENSIONS = ()\n"
        "ALLOWED_SUBMISSION_EXTENSIONS = ()\n"
        "MAX_SUBMISSION_SIZE_BYTES = 1\n"
        "class EvalConfig:\n    pass\n"
        "def build_submission_limits():\n    return {}\n"
    )
    (package / "evaluate.py").write_text("class Evaluator:\n    pass\n")
    (package / "harness/__init__.py").write_text("")
    (package / "harness/verification.py").write_text("def verify_task():\n    return None\n")
    models = package / "models"
    models.mkdir()
    if release == "0.2.10":
        (models / "discovery.py").write_text(
            "def validate_single_declared_model(agent_dir):\n"
            "    return 'from-discovery'\n"
            "def discover_declared_models(*args, **kwargs):\n"
            "    return set()\n"
            "def normalize_model_name(name):\n"
            "    return name\n"
            "def resolve_local_model_path(name):\n"
            "    return name\n"
            "def resolve_swegemma_adapter(name):\n"
            "    return name\n"
        )
        (models / "registry.py").write_text("def setup_gemma_model_registry():\n    return None\n")
        (models / "__init__.py").write_text(
            "from swegemma.models.discovery import (\n"
            "    discover_declared_models,\n"
            "    normalize_model_name,\n"
            "    resolve_local_model_path,\n"
            "    resolve_swegemma_adapter,\n"
            "    validate_single_declared_model,\n"
            ")\n"
            "from swegemma.models.registry import setup_gemma_model_registry\n"
            "def load_tasks(path):\n"
            "    return []\n"
        )
    else:
        (models / "__init__.py").write_text("def load_tasks(path):\n    return []\n")


def _import_lines(notebook):
    found = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for line in "".join(cell["source"]).splitlines():
            if line[:1].isspace():
                continue
            if line.startswith(("from swegemma", "from adk_submission", "import swegemma")):
                found.append(line)
            elif line.startswith("import adk_submission"):
                found.append(line)
    return found


def _cell5_prefix(source):
    lines = source.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "return next(iter(models))" in line:
            return "".join(lines[: index + 1])
    raise AssertionError("declared-model shim not in the server cell")


def _exec_imports(notebook, stub, release):
    modules = ("swegemma", "swegemma.", "adk_submission", "adk_submission.", "litellm", "torch")
    _purge(modules)
    sys.path.insert(0, str(stub))
    try:
        namespace = {}
        prefix = _cell5_prefix("".join(notebook["cells"][5]["source"]))
        exec(prefix, namespace)
        assert callable(namespace["validate_single_declared_model"])
        for line in _import_lines(notebook):
            if release == "0.2.11" and "swegemma.models.discovery" in line:
                with pytest.raises(ModuleNotFoundError):
                    exec(line, {})
                continue
            exec(line, namespace)
    finally:
        sys.path.remove(str(stub))
        _purge(modules)


def test_generated_imports_run_on_both_stub_layouts(tmp_path, monkeypatch):
    helpers = _notebook_helpers()
    helpers._official_starter(tmp_path)
    monkeypatch.chdir(tmp_path)
    generate_pair(
        helpers._arms(tmp_path), "owner", "pair-v1", tmp_path / "paired", wheelhouse_version=30
    )
    notebook, _code, _cells = helpers._notebook_code(tmp_path / "paired" / "evaluation.ipynb")
    server = "".join(notebook["cells"][5]["source"])
    pin = "".join(notebook["cells"][1]["source"])
    assert notebook["cells"][0]["cell_type"] == "markdown"
    assert "('0.2.10', '0.2.13')" in pin
    assert "('0.2.11', '0.2.13')" in pin
    assert "def validate_single_declared_model(agent_dir):" in server
    assert "validate_single_declared_model(ARM_DIRS[label])" in server
    assert "swegemma.models.registry" not in _code
    for release in ("0.2.10", "0.2.11"):
        stub = tmp_path / f"stub-{release}"
        stub.mkdir()
        _write_stub(stub, release)
        _exec_imports(notebook, stub, release)


def _fallback_namespace(discover):
    import types

    adk = types.ModuleType("adk_submission")
    discovery = types.ModuleType("adk_submission.discovery")
    discovery.discover_declared_models = discover
    adk.discovery = discovery
    saved = {}
    for name in ("adk_submission", "adk_submission.discovery", "swegemma"):
        saved[name] = sys.modules.get(name)
    sys.modules["adk_submission"] = adk
    sys.modules["adk_submission.discovery"] = discovery
    sys.modules.pop("swegemma", None)
    namespace = {}
    try:
        exec(_DECLARED_MODEL_SHIM, namespace)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return namespace["validate_single_declared_model"]


def test_shim_strips_prefixes_and_rejects_zero_or_many(tmp_path):
    def discover(agent_dir, normalize_fn=None):
        names = json.loads((Path(agent_dir) / "declared.json").read_text())
        if normalize_fn is None:
            return list(names)
        return [normalize_fn(name) for name in names]

    validate = _fallback_namespace(discover)
    single = tmp_path / "one"
    single.mkdir()
    single.joinpath("declared.json").write_text(json.dumps(["  OpenAI/Gemma "]))
    assert validate(single) == "gemma"
    for raw, expected in (
        ("google/Foo", "foo"),
        ("hosted_vllm/Bar", "bar"),
        ("custom/Baz", "baz"),
        ("openai/Qwen", "qwen"),
    ):
        folder = tmp_path / expected
        folder.mkdir()
        folder.joinpath("declared.json").write_text(json.dumps([raw]))
        assert validate(folder) == expected
    empty = tmp_path / "empty"
    empty.mkdir()
    empty.joinpath("declared.json").write_text("[]")
    with pytest.raises(ValueError, match="No model declared in agent configuration."):
        validate(empty)
    many = tmp_path / "many"
    many.mkdir()
    many.joinpath("declared.json").write_text(json.dumps(["openai/A", "google/B"]))
    with pytest.raises(ValueError, match="Ambiguous model declaration"):
        validate(many)


def _exec_pin(versions, monkeypatch, source):
    def version(name):
        if name not in versions:
            raise metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(metadata, "version", version)
    namespace = {}
    exec(source, namespace)
    return namespace


def test_allow_list_accepts_verified_pairs_and_rejects_the_rest(tmp_path, monkeypatch):
    source = _harness_pin_block().replace("/kaggle/working", str(tmp_path))
    (tmp_path / "run_manifest.json").write_text(
        json.dumps({"model_load_seconds": 3, "task_ids": ["fastapi_14786"]})
    )
    for pair in (("0.2.10", "0.2.13"), ("0.2.11", "0.2.13")):
        namespace = _exec_pin({"swegemma": pair[0], "adk-submission": pair[1]}, monkeypatch, source)
        assert namespace["RUN_PROVENANCE"]["harness_verified"] is True
        assert namespace["installed"] == pair
    saved = json.loads((tmp_path / "run_manifest.json").read_text())
    assert saved["model_load_seconds"] == 3
    assert saved["task_ids"] == ["fastapi_14786"]
    assert saved["harness_verified"] is True
    assert saved["packages"]["swegemma"] == "0.2.11"
    assert saved["packages"]["adk-submission"] == "0.2.13"
    rejected = (
        ("0.2.12", "0.2.13"),
        ("0.2.10", "0.2.12"),
        ("0.2.7", "0.2.13"),
    )
    for pair in rejected:
        with pytest.raises(RuntimeError) as raised:
            _exec_pin({"swegemma": pair[0], "adk-submission": pair[1]}, monkeypatch, source)
        assert str(raised.value) == _message(pair)


def _session(root, swegemma, adk):
    root.mkdir(parents=True)
    rows = []
    for arm in ("A", "B"):
        rows.append(
            {
                "arm": arm,
                "repeat": 1,
                "task_id": "fastapi_14786",
                "resolved": False,
                "wall_seconds": 1,
                "hit_cap": {},
            }
        )
    (root / "pair_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (root / "pair_manifest.json").write_text(
        json.dumps({"packages": {"swegemma": swegemma, "adk-submission": adk}})
    )


def test_report_header_shows_versions_and_mixed_flag(tmp_path):
    one = tmp_path / "one"
    _session(one, "0.2.11", "0.2.13")
    shutil.copytree(one, tmp_path / "same")
    output = tmp_path / "same-report"
    report_from_runs([one, tmp_path / "same"], SMOKE, output)
    saved = json.loads((output / "pair_report.json").read_text())
    text = (output / "pair_report.md").read_text()
    assert saved["harness_mixed"] is False
    assert "Harness: swegemma 0.2.11, adk-submission 0.2.13" in text
    assert "mixed harness versions" not in text
    other = tmp_path / "other"
    _session(other, "0.2.10", "0.2.13")
    mixed_out = tmp_path / "mixed-report"
    report_from_runs([one, other], SMOKE, mixed_out)
    mixed = json.loads((mixed_out / "pair_report.json").read_text())
    mixed_text = (mixed_out / "pair_report.md").read_text()
    assert mixed["harness_mixed"] is True
    assert "Harness: swegemma 0.2.11, adk-submission 0.2.13" in mixed_text
    assert "swegemma 0.2.10, adk-submission 0.2.13" in mixed_text
    assert "WARNING: mixed harness versions across joined sessions, repeats, or prior runs." in (
        mixed_text
    )


def test_wheelhouse_version_help_records_intent_only(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gemma-lab", "notebook-pair", "--help"])
    from gemma_lab.cli import main

    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "Positive integer Kaggle wheelhouse dataset version" in text
    assert "kernel-metadata.json" in text
    assert "pair_manifest.json" in text
    assert "Kaggle ignores the /N pin" in text
    assert "records intent only" in text
