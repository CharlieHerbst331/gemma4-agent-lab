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
                "duration_seconds": 30,
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


def test_projected_runtime_boundary(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    rows = evaluation / "task_results.jsonl"
    limit = operations.PROJECTED_RUNTIME_LIMIT_SECONDS / operations.PROJECTED_HIDDEN_TASKS
    row = json.loads(rows.read_text())
    row["duration_seconds"] = limit
    rows.write_text(json.dumps(row) + "\n")
    assert check_evaluation(archive, evaluation)["resolved"] == 1
    row["duration_seconds"] = limit + 1
    rows.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="11 hour limit") as raised:
        check_evaluation(archive, evaluation)
    message = str(raised.value)
    assert "120 tasks" in message
    assert "Refusing upload" in message


def test_projected_runtime_uses_the_mean_of_every_task(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    manifest = json.loads((evaluation / "run_manifest.json").read_text())
    manifest["task_ids"] = ["fast", "slow"]
    (evaluation / "run_manifest.json").write_text(json.dumps(manifest))
    # 300 and 360 average to the 330s ceiling (330 * 120 = 11h). 362 pushes the mean over.
    rows = [
        {"instance_id": "fast", "resolved": True, "patch_chars": 10, "duration_seconds": 300},
        {"instance_id": "slow", "resolved": False, "patch_chars": 10, "duration_seconds": 360},
    ]
    path = evaluation / "task_results.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert check_evaluation(archive, evaluation)["tasks"] == 2
    rows[1]["duration_seconds"] = 362
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="projected total runtime"):
        check_evaluation(archive, evaluation)


def test_projected_runtime_refuses_a_missing_duration(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    row = json.loads((evaluation / "task_results.jsonl").read_text())
    row.pop("duration_seconds")
    (evaluation / "task_results.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duration_seconds"):
        check_evaluation(archive, evaluation)


def test_execute_refuses_over_budget_before_any_upload(tmp_path, monkeypatch):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    row = json.loads((evaluation / "task_results.jsonl").read_text())
    row["duration_seconds"] = 400
    (evaluation / "task_results.jsonl").write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(
        operations, "kaggle", lambda *args, **kwargs: pytest.fail("upload attempted")
    )
    with pytest.raises(ValueError, match="exceeds the 11 hour limit"):
        operations.submit(archive, "too slow", tmp_path / "ledger.jsonl", True, evaluation)


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
