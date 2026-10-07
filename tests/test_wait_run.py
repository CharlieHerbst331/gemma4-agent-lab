import json

import pytest

from gemma_lab import operations


def test_complete_run_collected_with_metrics(tmp_path, monkeypatch):
    def api(*args, **kwargs):
        if "status" in args:
            return 'owner/run has status "KernelWorkerStatus.COMPLETE"\n'
        if "output" in args:
            (tmp_path / "task_results.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": "task",
                        "resolved": True,
                        "patch_chars": 42,
                    }
                )
                + "\n"
            )
        return "logs"

    monkeypatch.setattr(operations, "kaggle", api)
    result = operations.wait_for_run("owner/run", tmp_path)
    assert result["metrics"]["resolve_rate"] == 1
    assert (tmp_path / "collection.json").exists()


def test_failed_run_preserves_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(
        operations,
        "kaggle",
        lambda *args, **kwargs: (
            'has status "KernelWorkerStatus.ERROR"' if "status" in args else "failure log"
        ),
    )
    with pytest.raises(RuntimeError, match="Notebook failed"):
        operations.wait_for_run("owner/run", tmp_path)
    assert (tmp_path / "execution.log").read_text() == "failure log"
