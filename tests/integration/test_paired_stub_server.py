"""Opt-in Evaluator run against the stub model server and synthetic mock repo.

Default ``make check`` deselects this module. Run it with
``GEMMA_LAB_STUB_SERVER=1 uv run pytest -m stub_server`` once swegemma is installed.
"""

import asyncio
import inspect
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from gemma_lab.stub_server import (
    ScriptedResponder,
    StubModelServer,
    is_synthetic_mock,
    mock_task,
    repair_turns,
    write_mock_repo,
)

pytestmark = pytest.mark.stub_server

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "agents" / "baseline"


def _invoke(fn, /, **kwargs):
    signature = inspect.signature(fn)
    parameters = signature.parameters
    if any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        accepted = kwargs
    else:
        accepted = {key: value for key, value in kwargs.items() if key in parameters}
    result = fn(**accepted)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return result


def _snapshot(repo, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as archive:
        for path in repo.rglob("*"):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(repo).as_posix())


def test_evaluator_repairs_mock_repo(tmp_path):
    if os.environ.get("GEMMA_LAB_STUB_SERVER") != "1":
        pytest.skip("set GEMMA_LAB_STUB_SERVER=1 to run the harness smoke test")
    pytest.importorskip("swegemma")
    pytest.importorskip("google.adk")
    pytest.importorskip("litellm")
    from swegemma.config import EvalConfig
    from swegemma.evaluate import Evaluator
    from swegemma.models import load_tasks
    from swegemma.models.registry import setup_gemma_model_registry

    instance_id = "mock-calc-001"
    repo = write_mock_repo(tmp_path / "repo")
    _snapshot(repo, tmp_path / "snapshots" / f"{instance_id}.tgz")
    task_row = mock_task(instance_id)
    task_row["FAIL_TO_PASS"] = ["tests/test_calc.py::test_add"]
    task_row["PASS_TO_PASS"] = []
    task_row["test_patch"] = ""
    tasks_path = tmp_path / "tasks.jsonl"
    tasks_path.write_text(json.dumps(task_row) + "\n")
    task = load_tasks(tasks_path)[0]
    assert is_synthetic_mock(task)

    submission = tmp_path / "candidate"
    shutil.copytree(BASELINE, submission)
    server = StubModelServer(ScriptedResponder({"": repair_turns()}))
    server.start()
    try:
        registered = setup_gemma_model_registry(api_base=server.openai_base_url, api_key="EMPTY")
        models = registered if registered is not None else ["gemma-4-31b-it-qat-w4a16-ct"]
        config = _invoke(
            EvalConfig,
            tasks_path=tasks_path,
            snapshots_dir=tmp_path / "snapshots",
            results_dir=tmp_path / "results",
            submission_dir=submission,
            models=models,
            sandbox="subprocess",
            timeout_seconds=120,
            max_time_minutes=2.0,
            max_tool_calls=8,
            max_turns=4,
            verbose=False,
        )
        evaluator = Evaluator(config)
        result = _invoke(
            evaluator.evaluate_task,
            task=task,
            task_index=1,
            total_tasks=1,
        )
    finally:
        server.close()
    assert bool(getattr(result, "resolved", False))
    assert server.responder.requests
