import json
from pathlib import Path

import pytest

from gemma_lab.notebook import generate


def starter(tmp_path):
    root = tmp_path / "vendor/official/notebook"
    root.mkdir(parents=True)
    codes = [
        "x = 1\n",
        "SAMPLE_SUBMISSION_SRC = None\n",
        "x = 2\n",
        "import torch\ntp_size = 4\n",
        "SAMPLE_TASKS = tasks[:2]\nfor idx, task in enumerate(SAMPLE_TASKS):\n"
        "    pass\nsubmission_df = None\n",
        "x = 4\n",
    ]
    cells = [{"cell_type": "code", "source": [code]} for code in codes]
    (root / "getting-started-gemma-4-developer-agent.ipynb").write_text(
        json.dumps({"cells": cells})
    )
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


def test_notebook_pins_candidate_and_preserves_inputs(tmp_path, monkeypatch):
    agent = Path("agents/baseline").resolve()
    starter(tmp_path)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "generated"
    generate(agent, "owner", "experiment-v1", output)
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    code = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert "hashlib.sha256(payload)" in code
    assert code.index("import torch") < code.index("RUN_PROVENANCE['hardware']")
    assert "task_results.jsonl" in code
    assert "SAMPLE_TASKS = [t for t in tasks if t.instance_id in TASK_IDS]" in code
    metadata = json.loads((output / "kernel-metadata.json").read_text())
    assert metadata["enable_internet"] is False
    assert metadata["is_private"] is True
    assert metadata["model_sources"] == ["official/model/2"]
    assert metadata["title"] == "experiment v1"


def test_changed_starter_fails_closed(tmp_path, monkeypatch):
    starter(tmp_path)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb"
    path.write_text(json.dumps({"cells": []}))
    with pytest.raises(ValueError, match="structure changed"):
        generate(Path("unused"), "owner", "experiment", tmp_path / "output")


@pytest.mark.parametrize(
    ("message", "failure_class"),
    [
        ("Sandbox execution error: ContextWindowExceededError", "infrastructure_or_harness"),
        ("Agent exceeded session timeout (5.0 min)", "agent_budget"),
        (None, None),
    ],
)
def test_returned_runner_errors_survive_collection(tmp_path, monkeypatch, message, failure_class):
    from types import SimpleNamespace

    agent = Path("agents/baseline").resolve()
    starter(tmp_path)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "generated"
    generate(agent, "owner", "experiment-v1", output)
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    code = "".join(notebook["cells"][5]["source"])
    loop = code[code.index("results_path =") : code.index("submission_df =")]
    result = SimpleNamespace(
        agent_patch="",
        resolved=False,
        test_exit_code=-1,
        tool_calls=1,
        duration_seconds=2,
        error_message=message,
        test_output="",
    )
    namespace = dict(
        WORKING_DIR=tmp_path,
        SAMPLE_TASKS=[SimpleNamespace(instance_id="task", repo="example/repo")],
        evaluator=SimpleNamespace(evaluate_task=None),
        run_sync=lambda *args, **kwargs: result,
        predictions=[],
        json=json,
    )
    exec(loop, namespace)
    row = json.loads((tmp_path / "task_results.jsonl").read_text())
    assert row.get("failure_class") == failure_class
    assert bool(row.get("error")) == (failure_class == "infrastructure_or_harness")


def test_official_wheelhouse_mount_fallback(tmp_path, monkeypatch):
    agent = Path("agents/baseline").resolve()
    starter(tmp_path)
    starter_path = (
        tmp_path / "vendor/official/notebook/getting-started-gemma-4-developer-agent.ipynb"
    )
    data = json.loads(starter_path.read_text())
    data["cells"][0]["source"] = ["# Remove broken cutlass .pth hooks if present\n"]
    starter_path.write_text(json.dumps(data))
    mounted = tmp_path / "input/alternate/gemma-4-developer-agent-wheelhouse"
    mounted.mkdir(parents=True)
    (mounted / "official.whl").touch()
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "generated"
    generate(agent, "owner", "experiment-v1", output)
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    namespace = dict(
        WHEELHOUSE_DIR=tmp_path / "missing",
        Path=lambda value: tmp_path / "input" if value == "/kaggle/input" else Path(value),
    )
    exec("".join(notebook["cells"][1]["source"]), namespace)
    assert namespace["WHEELHOUSE_DIR"] == mounted
    (mounted / "official.whl").unlink()
    with pytest.raises(AssertionError, match="mounted official wheelhouse"):
        exec("".join(notebook["cells"][1]["source"]), namespace)
