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
        "x = 3\n",
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
