import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gemma_lab.notebook import _BUDGET_HARDCODE, generate, generate_pair
from gemma_lab.paired import assert_adk_submission_version

PRE_PAIR_GENERATOR = "abf3c40"
REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "agents" / "baseline"


def _stamp():
    return "2026-01-01T00:00:00+00:00"


def _revision():
    return PRE_PAIR_GENERATOR


def _freeze(monkeypatch, *modules):
    monkeypatch.setattr("gemma_lab.bundle.now", _stamp)
    monkeypatch.setattr("gemma_lab.bundle.git_revision", _revision)
    for module in modules:
        monkeypatch.setattr(module, "now", _stamp)
        monkeypatch.setattr(module, "git_revision", _revision)


def _starter(tmp_path, *, hardcode=False):
    root = tmp_path / "vendor/official/notebook"
    root.mkdir(parents=True)
    loop = _BUDGET_HARDCODE if hardcode else ""
    loop += (
        "SAMPLE_TASKS = tasks[:2]\n"
        "eval_config = EvalConfig(\n"
        "    submission_dir=AGENT_DIR,\n"
        "    results_dir=WORKING_DIR / 'results',\n"
        "    sandbox='subprocess',\n"
        ")\n"
        "for idx, task in enumerate(SAMPLE_TASKS):\n"
        "    pass\n"
        "submission_df = None\n"
    )
    codes = [
        "# Remove broken cutlass .pth hooks if present\n",
        "SAMPLE_SUBMISSION_SRC = None\n",
        "x = 2\n",
        "declared_model = validate_single_declared_model(AGENT_DIR)\n"
        "adapters = discover_adapters(str(AGENT_DIR), "
        "adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)\n"
        "server_instance.start()\n"
        "import torch\n"
        "tp_size = 4\n",
        loop,
        "zip_path = Path(shutil.make_archive(str(zip_base), 'zip', root_dir=AGENT_DIR))\n",
    ]
    cells = [{"cell_type": "code", "source": [code]} for code in codes]
    notebook = root / "getting-started-gemma-4-developer-agent.ipynb"
    notebook.write_text(json.dumps({"cells": cells}))
    (root / "kernel-metadata.json").write_text(
        json.dumps(
            {
                "id_no": 123,
                "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
                "competition_sources": ["gemma-4-developer-agent"],
                "model_sources": ["official/model/2"],
            }
        )
    )


def _load_pre_pair_generate(tmp_path):
    source = subprocess.check_output(
        ["git", "show", f"{PRE_PAIR_GENERATOR}:src/gemma_lab/notebook.py"],
        text=True,
        cwd=REPO_ROOT,
    )
    path = tmp_path / "notebook_pre_pair.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("notebook_pre_pair", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arms(tmp_path):
    left = tmp_path / "arm-a"
    right = tmp_path / "arm-b"
    shutil.copytree(BASELINE, left)
    shutil.copytree(BASELINE, right)
    (right / "prompts" / "system.md").write_text("arm b prompt\n")
    budget = (
        "evaluation:\n"
        "  timeout_seconds: 300\n"
        "  max_tool_calls: 37\n"
        "  max_time_minutes: 7.5\n"
        "  max_turns: 41\n"
    )
    (left / "eval_config.yaml").write_text(budget)
    (right / "eval_config.yaml").write_text(budget)
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps(["fastapi_11194"]))
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(
        "arms:\n"
        f"  A:\n    source: {left}\n"
        f"  B:\n    source: {right}\n"
        "allow_identical: false\n"
        "allowed_differences:\n"
        "  - prompts/*\n"
        "  - eval_config.yaml\n"
        "cohort:\n"
        f"  path: {cohort}\n"
        "repeats: 1\n"
        "order_rule: per_task_parity_v1\n"
        "pins_mode: record\n"
    )
    return protocol


class _FixedPackDir:
    """Keep the archive path embedded in RUN_PROVENANCE stable across generators."""

    def __enter__(self):
        path = Path("/tmp/gemma-lab-single-arm-pack")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir()
        return str(path)

    def __exit__(self, exc_type, exc, tb):
        shutil.rmtree("/tmp/gemma-lab-single-arm-pack", ignore_errors=True)
        return False


def test_generate_matches_pre_pair_notebook_bytes(tmp_path, monkeypatch):
    agent = BASELINE
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    previous = _load_pre_pair_generate(tmp_path)
    import gemma_lab.notebook as current

    _freeze(monkeypatch, current, previous)
    monkeypatch.setattr(current.tempfile, "TemporaryDirectory", _FixedPackDir)
    monkeypatch.setattr(previous.tempfile, "TemporaryDirectory", _FixedPackDir)
    left = tmp_path / "left"
    right = tmp_path / "right"
    again = tmp_path / "again"
    generate(agent, "owner", "experiment-v1", left)
    generate(agent, "owner", "experiment-v1", again)
    previous.generate(agent, "owner", "experiment-v1", right)
    first = (left / "evaluation.ipynb").read_bytes()
    assert first == (again / "evaluation.ipynb").read_bytes()
    assert first == (right / "evaluation.ipynb").read_bytes()
    # Provenance includes the absolute agent path, so the digest is evidence for
    # this checkout rather than a portable golden file.
    assert len(hashlib.sha256(first).hexdigest()) == 64


def test_single_arm_keeps_starter_budget_hardcodes(tmp_path, monkeypatch):
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "generated"
    generate(BASELINE, "owner", "experiment-v1", output)
    code = "\n".join(
        "".join(cell["source"])
        for cell in json.loads((output / "evaluation.ipynb").read_text())["cells"]
        if cell["cell_type"] == "code"
    )
    assert "max_tool_calls = 100\n" in code
    assert "max_time_minutes = 5.0\n" in code
    assert "assert_adk_submission_version" not in code


def test_pair_notebook_sets_configured_budgets_and_adk_floor(tmp_path, monkeypatch):
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    protocol = _arms(tmp_path)
    output = tmp_path / "paired"
    generate_pair(protocol, "owner", "pair-v1", output)
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert "'max_tool_calls': 37" in code
    assert "'max_time_minutes': 7.5" in code
    assert "'max_turns': 41" in code
    assert "max_tool_calls = int(budgets['max_tool_calls'])" in code
    assert "max_time_minutes = float(budgets['max_time_minutes'])" in code
    assert "cap_seconds=450.0" in code
    assert "max_tool_calls = 100" not in code
    assert "max_time_minutes = 5.0" not in code
    assert "assert_adk_submission_version(importlib.metadata.version('adk-submission'))" in code
    assert_adk_submission_version("0.2.12")
    with pytest.raises(RuntimeError, match="0.2.12"):
        assert_adk_submission_version("0.2.11")
    with pytest.raises(RuntimeError, match="thinking_budget"):
        assert_adk_submission_version("0.2.11")
    metadata = json.loads((output / "kernel-metadata.json").read_text())
    assert metadata["is_private"] is True
    assert metadata["enable_internet"] is False
    assert metadata["enable_gpu"] is True
    assert metadata["id"] == "owner/pair-v1"


def test_pair_starter_drift_fails_closed(tmp_path, monkeypatch):
    _starter(tmp_path, hardcode=True)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb"
    path.write_text(json.dumps({"cells": []}))
    with pytest.raises(ValueError, match="structure changed"):
        generate_pair(_arms(tmp_path), "owner", "pair-v1", tmp_path / "output")


def test_pair_schedule_cli_does_not_pack(tmp_path, monkeypatch, capsys):
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps(["t1", "t2"]))
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(
        "arms:\n"
        "  A:\n    source: agents/missing-a\n"
        "  B:\n    source: agents/missing-b\n"
        "cohort:\n"
        f"  path: {cohort}\n"
        "repeats: 2\n"
        "order_rule: per_task_parity_v1\n"
    )
    destination = tmp_path / "schedule.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gemma-lab",
            "pair-schedule",
            "--protocol",
            str(protocol),
            "--output",
            str(destination),
        ],
    )
    from gemma_lab.cli import main

    main()
    saved = json.loads(destination.read_text())
    assert saved["rule"] == "per_task_parity_v1"
    assert len(saved["entries"]) == 4
    printed = json.loads(capsys.readouterr().out)
    assert printed["schedule_sha256"] == saved["schedule_sha256"]
