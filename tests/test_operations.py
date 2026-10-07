import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gemma_lab import operations
from gemma_lab.bundle import pack
from gemma_lab.operations import check_evaluation, submissions_today


def evidence(tmp_path, archive):
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    from gemma_lab.common import sha256

    (evaluation / "run_manifest.json").write_text(
        json.dumps(
            {
                "sha256": sha256(archive),
                "task_ids": ["task"],
            }
        )
    )
    (evaluation / "task_results.jsonl").write_text(
        json.dumps(
            {
                "instance_id": "task",
                "resolved": True,
                "patch_chars": 10,
            }
        )
        + "\n"
    )
    return evaluation


def test_history_parser():
    assert submissions_today("No submissions found\n", "2026-10-06") == []
    text = "Next Page Token = xyz\nref,date,status\n42,2026-10-06 09:00:00,complete\n"
    assert len(submissions_today(text, "2026-10-06")) == 1
    assert submissions_today(text, "2026-10-07") == []
    with pytest.raises(ValueError):
        submissions_today("ref,status\n42,complete\n")


def test_submission_reservation_blocks_retry_after_network_failure(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "submission.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    calls = []

    def api(*args, **kwargs):
        calls.append(args)
        if "submissions" in args:
            return "No submissions found\n"
        raise RuntimeError("connection interrupted during upload")

    monkeypatch.setattr(operations, "kaggle", api)
    with pytest.raises(RuntimeError):
        operations.submit(archive, "test", ledger, execute=True, evaluation=evaluation)
    row = json.loads(ledger.read_text())
    assert row["status"] == "reserved"
    assert row["created_at"].startswith(datetime.now(UTC).date().isoformat())
    with pytest.raises(ValueError, match="reserved"):
        operations.submit(archive, "test", ledger, execute=True, evaluation=evaluation)
    assert sum("submit" in args for args in calls) == 1


def test_plan_has_no_network_side_effects(tmp_path, monkeypatch):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    monkeypatch.setattr(operations, "kaggle", lambda *args, **kwargs: pytest.fail("unexpected API"))
    assert operations.submit(archive, "plan")["status"] == "planned"


def test_evaluation_gate_requires_exact_archive_and_complete_tasks(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    with pytest.raises(ValueError, match="requires --evaluation"):
        check_evaluation(archive, None)
    evaluation = evidence(tmp_path, archive)
    assert check_evaluation(archive, evaluation)["resolved"] == 1
    (evaluation / "task_results.jsonl").write_text("")
    with pytest.raises(ValueError, match="incomplete"):
        check_evaluation(archive, evaluation)
    manifest = evaluation / "run_manifest.json"
    manifest.write_text(json.dumps({"sha256": "wrong", "task_ids": ["task"]}))
    with pytest.raises(ValueError, match="hash"):
        check_evaluation(archive, evaluation)


@pytest.mark.parametrize(
    "detail",
    [
        {"error_message": "Sandbox execution error: ContextWindowExceededError"},
        {
            "error_message": "Agent exceeded session timeout (5.0 min)",
            "test_output": "recursive dependency involving fixture 'httpbin' detected",
        },
    ],
)
def test_evaluation_gate_checks_diagnostics_even_when_rows_omit_errors(tmp_path, detail):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    (evaluation / "results").mkdir()
    (evaluation / "results/task.json").write_text(json.dumps(detail))
    with pytest.raises(ValueError, match="errors before uploading"):
        check_evaluation(archive, evaluation)


def test_older_turn_budget_classification_is_not_an_infrastructure_error(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    rows = evaluation / "task_results.jsonl"
    row = json.loads(rows.read_text())
    row.update(
        resolved=False,
        failure_class="infrastructure_or_harness",
        error="Agent exceeded turns budget (60 turns)",
    )
    raw = json.dumps(row) + "\n"
    rows.write_text(raw)
    metrics = check_evaluation(archive, evaluation)
    assert metrics["agent_budget_failures"] == 1
    assert metrics["infrastructure_failures"] == 0
    assert rows.read_text() == raw


def test_agent_timeout_does_not_hide_a_reported_grading_error(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    rows = evaluation / "task_results.jsonl"
    row = json.loads(rows.read_text())
    row.update(
        resolved=False,
        failure_class="infrastructure_or_harness",
        agent_error="Agent exceeded session timeout (5.0 min)",
        error="Official verification httpbin fixture setup failed",
    )
    rows.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="infrastructure errors"):
        check_evaluation(archive, evaluation)
