import json
import zipfile
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


def _set_rows(evaluation, rows, *, model_load=None):
    manifest = json.loads((evaluation / "run_manifest.json").read_text())
    manifest["task_ids"] = [row["instance_id"] for row in rows]
    if model_load is not None:
        manifest["model_load_seconds"] = model_load
    (evaluation / "run_manifest.json").write_text(json.dumps(manifest))
    (evaluation / "task_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_projected_runtime_boundary(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    # Measured load 180s and overhead 0: 180 + 129*300 = 38880, the P ceiling.
    # 120*300 stays under 11 hours.
    row = {
        "instance_id": "task",
        "resolved": True,
        "patch_chars": 10,
        "duration_seconds": 300,
    }
    _set_rows(evaluation, [row], model_load=180)
    assert check_evaluation(archive, evaluation, scorer_overhead_seconds=0)["resolved"] == 1
    _set_rows(evaluation, [row], model_load=181)
    with pytest.raises(ValueError, match="10.8 hour limit") as raised:
        check_evaluation(archive, evaluation, scorer_overhead_seconds=0)
    assert "Refusing upload" in str(raised.value)
    assert "overhead" not in str(raised.value)
    # Equality on the 120-task gate is not enough when the load gate fails.
    row["duration_seconds"] = 330
    _set_rows(evaluation, [row], model_load=0)
    report = operations.runtime_projection([row], {"model_load_seconds": 0}, archive, overhead=0)
    assert report["ok_120"] is True
    assert report["projected_120_seconds"] == 39600
    assert report["P_ok"] is False
    with pytest.raises(ValueError, match="10.8 hour limit") as raised:
        check_evaluation(archive, evaluation, scorer_overhead_seconds=0)
    assert "overhead" not in str(raised.value)


def test_projected_runtime_uses_the_mean_of_every_task(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    # 200 and 220 average 210. Default overhead 70 applies only to the 120-task
    # block: 120 * 280 = 33600. The 129-task block is 900 + 129 * 210.
    rows = [
        {"instance_id": "fast", "resolved": True, "patch_chars": 10, "duration_seconds": 200},
        {"instance_id": "slow", "resolved": False, "patch_chars": 10, "duration_seconds": 220},
    ]
    _set_rows(evaluation, rows)
    assert check_evaluation(archive, evaluation)["tasks"] == 2
    # 260 and 280 average 270. 120 * (270 + 70) exceeds 11 hours. The 129-task
    # block uses the measured mean alone and still passes.
    rows[0]["duration_seconds"] = 260
    rows[1]["duration_seconds"] = 280
    _set_rows(evaluation, rows)
    with pytest.raises(ValueError, match="11 hour limit") as raised:
        check_evaluation(archive, evaluation)
    assert "10.8 hour limit" not in str(raised.value)
    projection = json.loads((evaluation / "projection.json").read_text())
    assert projection["basis"] == "measured_mean"
    assert projection["ok_120"] is False
    assert projection["P_ok"] is True
    assert projection["overhead_in_129_block"] is False


def test_simple_v3_dev13_mean_is_refused(tmp_path):
    # evidence simple-v3-dev13: 3873.680346899002 / 13 = 297.98 s.
    # 120 * 297.98 is under 11 h; adding the default 70 s overhead refuses it.
    archive = tmp_path / "submission.zip"
    pack(Path("agents/simple-v3"), archive)
    evaluation = evidence(tmp_path, archive)
    row = {
        "instance_id": "task",
        "resolved": True,
        "patch_chars": 10,
        "duration_seconds": 297.98,
    }
    _set_rows(evaluation, [row])
    with pytest.raises(ValueError, match="11 hour limit") as raised:
        check_evaluation(archive, evaluation)
    assert "Refusing upload" in str(raised.value)
    projection = json.loads((evaluation / "projection.json").read_text())
    assert projection["mean_seconds"] == 297.98
    assert projection["scorer_overhead_seconds_per_task"] == 70
    assert projection["L_seconds"] == 900
    assert projection["L_source"] == "default"
    assert projection["ok_120"] is False
    assert projection["P_ok"] is False
    assert projection["P_limit"] == 38880
    assert projection["limit_120"] == 39600
    assert projection["basis"] == "measured_mean"
    assert projection["applies_at"] == "submit_or_promotion"
    assert projection["dev_gpu_precondition"] is False
    assert projection["blocks_use_cap_wall"] is False
    assert projection["overhead_in_120_block"] is True
    assert projection["overhead_in_129_block"] is False
    assert projection["overhead_in_worst_case_warn"] is True


def test_structured_v4_10m_diagnostic_mean_is_refused(tmp_path):
    # evidence structured-v4-10m-diagnostic-v1: 1468.5390718619997 / 3 = 489.5 s.
    archive = tmp_path / "submission.zip"
    pack(Path("agents/structured-v4-10m"), archive)
    evaluation = evidence(tmp_path, archive)
    mean = 1468.5390718619997 / 3
    row = {
        "instance_id": "task",
        "resolved": True,
        "patch_chars": 10,
        "duration_seconds": mean,
    }
    _set_rows(evaluation, [row])
    with pytest.raises(ValueError, match="Refusing upload"):
        check_evaluation(archive, evaluation)
    projection = json.loads((evaluation / "projection.json").read_text())
    assert projection["ok_120"] is False
    assert projection["n_tasks"] == 1


def test_scorer_overhead_flag_changes_the_gate(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    row = {
        "instance_id": "task",
        "resolved": True,
        "patch_chars": 10,
        "duration_seconds": 280,
    }
    _set_rows(evaluation, [row])
    assert check_evaluation(archive, evaluation, scorer_overhead_seconds=0)["resolved"] == 1
    with pytest.raises(ValueError, match="11 hour limit"):
        check_evaluation(archive, evaluation, scorer_overhead_seconds=70)
    projection = json.loads((evaluation / "projection.json").read_text())
    assert projection["ok_120"] is False
    assert projection["P_ok"] is True
    # 250s with the default 70s overhead still passes both measured-mean blocks.
    row["duration_seconds"] = 250
    _set_rows(evaluation, [row])
    assert check_evaluation(archive, evaluation, scorer_overhead_seconds=70)["resolved"] == 1


def test_cap_wall_warns_and_does_not_block(tmp_path, capsys):
    archive = tmp_path / "submission.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("eval_config.yaml", "evaluation:\n  max_time_minutes: 4.5\n")
    evaluation = evidence(tmp_path, archive)
    result = check_evaluation(archive, evaluation)
    assert result["resolved"] == 1
    assert result["projection"]["worst_case_warn"] is True
    assert result["projection"]["ok_120"] is True
    assert result["projection"]["P_ok"] is True
    projection = json.loads((evaluation / "projection.json").read_text())
    assert projection["basis"] == "measured_mean"
    assert projection["dev_gpu_precondition"] is False
    assert projection["blocks_use_cap_wall"] is False
    assert projection["cap_wall_seconds"] == 270
    assert projection["ok_120"] is True
    assert projection["P_ok"] is True
    assert projection["worst_case_warn"] is True
    assert projection["worst_case_seconds"] == 900 + 129 * (270 + 70)
    assert "does not block" in capsys.readouterr().err


def test_cli_forwards_scorer_overhead(tmp_path, monkeypatch):
    seen = {}

    def fake_submit(*args, **kwargs):
        seen["overhead"] = kwargs.get("scorer_overhead_seconds")
        return {"status": "planned"}

    monkeypatch.setattr(operations, "submit", fake_submit)
    from gemma_lab.cli import main

    main(
        [
            "submit",
            str(tmp_path / "missing.zip"),
            "--message",
            "plan",
            "--scorer-overhead-seconds",
            "12.5",
        ]
    )
    assert seen["overhead"] == 12.5


def test_nan_duration_is_refused(tmp_path):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    row = json.loads((evaluation / "task_results.jsonl").read_text())
    row["duration_seconds"] = float("nan")
    (evaluation / "task_results.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duration_seconds"):
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
