import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gemma_lab import operations
from gemma_lab.bundle import pack
from gemma_lab.common import sha256
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


def _ledger_rows(ledger):
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line]


def _install_kaggle(monkeypatch, on_submit):
    calls = []

    def api(*args, **kwargs):
        calls.append(args)
        if "submissions" in args:
            return "No submissions found\n"
        return on_submit(*args, **kwargs)

    monkeypatch.setattr(operations, "kaggle", api)
    return calls


def _submit_calls(calls):
    return [args for args in calls if "submit" in args]


class _UploadError(RuntimeError):
    def __init__(self):
        super().__init__(
            "400 Client Error: Bad Request for url: "
            "https://api.kaggle.com/v1/competitions.CompetitionApiService/CreateSubmission "
            "KAGGLE_API_TOKEN=kg_live_abcdef0123 Authorization: Bearer supersecretvalue"
        )
        self.response = type(
            "Response",
            (),
            {
                "text": '{"message":"file must be named submission.zip"}',
                "headers": {"Authorization": "Bearer kgat_fromheader"},
            },
        )()


def test_execute_uploads_submission_zip_with_source_bytes(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    seen = {}

    def on_submit(*args, **kwargs):
        path = Path(args[args.index("-f") + 1])
        seen["path"] = path
        seen["name"] = path.name
        seen["bytes"] = path.read_bytes()
        seen["timeout"] = kwargs.get("timeout")
        return "Successfully submitted"

    _install_kaggle(monkeypatch, on_submit)
    plan = operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert seen["name"] == "submission.zip"
    assert seen["bytes"] == archive.read_bytes()
    assert seen["timeout"] == 600
    assert not seen["path"].exists()
    assert plan["status"] == "submitted"
    assert plan["sha256"] == sha256(archive)
    assert plan["response"] == "Successfully submitted"
    assert plan["archive"] == str(archive.resolve())
    rows = _ledger_rows(ledger)
    assert [row["status"] for row in rows] == ["reserved", "submitted"]
    assert rows[0]["sha256"] == rows[1]["sha256"] == sha256(archive)
    assert "error" not in rows[1]


def test_submit_failure_records_failed_and_allows_same_day_retry(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    state = {"n": 0}
    seen = {}

    def on_submit(*args, **kwargs):
        path = Path(args[args.index("-f") + 1])
        seen["path"] = path
        seen["name"] = path.name
        seen["bytes"] = path.read_bytes()
        state["n"] += 1
        if state["n"] == 1:
            raise _UploadError()
        return "Successfully submitted"

    calls = _install_kaggle(monkeypatch, on_submit)
    with pytest.raises(RuntimeError, match="400 Client Error") as raised:
        operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert "file must be named submission.zip" in str(raised.value)
    assert not seen["path"].exists()
    failed = _ledger_rows(ledger)
    assert [row["status"] for row in failed] == ["failed"]
    assert failed[0]["sha256"] == sha256(archive)
    assert "400 Client Error" in failed[0]["error"]
    assert "file must be named submission.zip" in failed[0]["error"]
    assert failed[0]["created_at"].startswith(datetime.now(UTC).date().isoformat())
    recorded = ledger.read_text()
    for secret in ("kg_live_abcdef0123", "supersecretvalue", "kgat_fromheader"):
        assert secret not in recorded
        assert secret not in str(raised.value)
    plan = operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert plan["status"] == "submitted"
    assert len(_submit_calls(calls)) == 2
    assert seen["name"] == "submission.zip"
    assert seen["bytes"] == archive.read_bytes()


def test_submit_timeout_stays_reserved_and_blocks_retry(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    seen = {}

    def on_submit(*args, **kwargs):
        path = Path(args[args.index("-f") + 1])
        seen["path"] = path
        seen["name"] = path.name
        raise subprocess.TimeoutExpired(cmd=["kaggle", "competitions", "submit"], timeout=600)

    calls = _install_kaggle(monkeypatch, on_submit)
    with pytest.raises(RuntimeError, match="submissions list") as raised:
        operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert "may have been received" in str(raised.value)
    assert not seen["path"].exists()
    assert seen["name"] == "submission.zip"
    rows = _ledger_rows(ledger)
    assert len(rows) == 1
    assert rows[0]["status"] == "reserved"
    assert "submissions list" in rows[0]["error"]
    assert "may have been received" in rows[0]["error"]
    with pytest.raises(ValueError, match="reserved"):
        operations.submit(archive, "retry", ledger, execute=True, evaluation=evaluation)
    assert len(_submit_calls(calls)) == 1


def test_staged_hash_mismatch_does_not_upload(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)

    def refuse_link(*args, **kwargs):
        raise OSError("cross device")

    def bad_copy(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"not the archive")

    monkeypatch.setattr(operations.os, "link", refuse_link)
    monkeypatch.setattr(operations.shutil, "copyfile", bad_copy)
    calls = _install_kaggle(monkeypatch, lambda *args, **kwargs: pytest.fail("upload attempted"))
    with pytest.raises(RuntimeError, match="does not match"):
        operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert _submit_calls(calls) == []
    assert _ledger_rows(ledger) == []


def test_legacy_submitted_row_without_error_still_blocks(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    day = datetime.now(UTC).date().isoformat()
    ledger.write_text(
        json.dumps(
            {
                "created_at": f"{day}T00:00:00+00:00",
                "status": "submitted",
                "sha256": sha256(archive),
            }
        )
        + "\n"
    )
    calls = _install_kaggle(monkeypatch, lambda *args, **kwargs: pytest.fail("upload attempted"))
    with pytest.raises(ValueError, match="reserved"):
        operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert _submit_calls(calls) == []


def test_legacy_failed_row_without_error_does_not_block(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    day = datetime.now(UTC).date().isoformat()
    ledger.write_text(
        json.dumps(
            {
                "created_at": f"{day}T00:00:00+00:00",
                "status": "failed",
                "sha256": "older-attempt",
            }
        )
        + "\n"
    )

    def on_submit(*args, **kwargs):
        path = Path(args[args.index("-f") + 1])
        assert path.name == "submission.zip"
        return "Successfully submitted"

    _install_kaggle(monkeypatch, on_submit)
    plan = operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert plan["status"] == "submitted"
    assert _ledger_rows(ledger)[0]["status"] == "failed"
    assert "error" not in _ledger_rows(ledger)[0]


_HEX_KEY = "ab" * 16
_SECRET_SAMPLES = [
    "Authorization: Basic dXNlcjpwYXNz",
    "{'Authorization': 'Basic dXNlcjpwYXNz'}",
    "KGAT_fakeTokenValue12345",
    _HEX_KEY,
    f"fakeuser:{_HEX_KEY}",
    '{"username":"fakeuser","key":"jsonkeysecretvalue"}',
    '{"key":"jsonkeysecretvalue"}',
    '{"api_key":"apikeysecretvalue1"}',
    '{"token":"tokensecretvalue123"}',
    '{"access_token":"accesstokensecret99"}',
    "client_secret=clientsecretvalue99",
    "ya29.faketokenvalue12345",
    (
        "PUT https://storage.googleapis.com/b/o?X-Goog-Signature=deadbeefcafe0123"
        "&X-Goog-Credential=svc%40example.iam.gserviceaccount.com"
    ),
]
_SECRET_FRAGMENTS = [
    "dXNlcjpwYXNz",
    "KGAT_fakeTokenValue12345",
    _HEX_KEY,
    "jsonkeysecretvalue",
    "apikeysecretvalue1",
    "tokensecretvalue123",
    "accesstokensecret99",
    "clientsecretvalue99",
    "ya29.faketokenvalue12345",
    "deadbeefcafe0123",
    "svc%40example.iam.gserviceaccount.com",
    "X-Goog-Signature=",
    "X-Goog-Credential=",
]


def test_scrub_secrets_covers_realistic_token_formats():
    text = "\n".join(_SECRET_SAMPLES)
    scrubbed = operations._scrub_secrets(text)
    for fragment in _SECRET_FRAGMENTS:
        assert fragment not in scrubbed
    assert "https://storage.googleapis.com/b/o?[REDACTED]" in scrubbed


def test_scrub_secrets_removes_env_literals_and_ignores_short_values(monkeypatch):
    monkeypatch.setenv("KAGGLE_KEY", "weirdkeyvalue99")
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_fromnamedenv123")
    monkeypatch.setenv("KAGGLE_USERNAME", "ab")
    monkeypatch.setenv("OTHER_TOKEN", "prefix KGAT_fromotherenv456")
    text = "weird<<weirdkeyvalue99>> KGAT_fromnamedenv123 user ab stays KGAT_fromotherenv456"
    scrubbed = operations._scrub_secrets(text)
    assert "weirdkeyvalue99" not in scrubbed
    assert "KGAT_fromnamedenv123" not in scrubbed
    assert "KGAT_fromotherenv456" not in scrubbed
    assert "ab" in scrubbed


def test_scrub_secrets_caps_long_text_and_still_redacts():
    secret = "KGAT_fakeTokenValue12345"
    text = secret + " " + ("A" * 5000)
    scrubbed = operations._scrub_secrets(text)
    assert secret not in scrubbed
    body, _, _note = scrubbed.rpartition("[truncated ")
    assert len(body) == 4000
    assert scrubbed.startswith("[REDACTED]")
    assert scrubbed.endswith(" chars]")


def test_success_response_is_scrubbed_before_it_is_stored_or_returned(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    leak = "uploaded KGAT_fakeTokenValue12345 Authorization: Basic dXNlcjpwYXNz"

    def on_submit(*args, **kwargs):
        return leak

    _install_kaggle(monkeypatch, on_submit)
    plan = operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert plan["status"] == "submitted"
    assert "KGAT_fakeTokenValue12345" not in plan["response"]
    assert "dXNlcjpwYXNz" not in plan["response"]
    assert "KGAT_fakeTokenValue12345" not in ledger.read_text()
    assert "dXNlcjpwYXNz" not in ledger.read_text()


def test_failure_error_is_capped_in_the_ledger_and_the_raised_message(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    huge = "E" * 5000 + "KGAT_fakeTokenValue12345"

    def on_submit(*args, **kwargs):
        raise RuntimeError(huge)

    _install_kaggle(monkeypatch, on_submit)
    with pytest.raises(RuntimeError) as raised:
        operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    message = str(raised.value)
    assert "KGAT_fakeTokenValue12345" not in message
    assert "KGAT_fakeTokenValue12345" not in ledger.read_text()
    assert "[truncated " in message
    assert len(message) < 4100
    row = _ledger_rows(ledger)[-1]
    assert row["status"] == "failed"
    assert row["error"] == message
    assert len(row["error"]) < 4100


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("connection reset by peer"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        TimeoutError("timed out"),
    ],
)
def test_ambiguous_upload_errors_stay_reserved(tmp_path, monkeypatch, error):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)

    def on_submit(*args, **kwargs):
        raise error

    calls = _install_kaggle(monkeypatch, on_submit)
    with pytest.raises(RuntimeError, match="submissions list") as raised:
        operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert "may have been received" in str(raised.value)
    rows = _ledger_rows(ledger)
    assert len(rows) == 1
    assert rows[0]["status"] == "reserved"
    with pytest.raises(ValueError, match="reserved"):
        operations.submit(archive, "retry", ledger, execute=True, evaluation=evaluation)
    assert len(_submit_calls(calls)) == 1


def test_ledger_replace_keeps_the_original_when_the_write_fails(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    original = json.dumps({"status": "submitted", "sha256": "abc"}) + "\n"
    ledger.write_text(original + json.dumps({"status": "reserved"}) + "\n")

    def fail_replace(src, dst):
        raise OSError("killed mid-write")

    monkeypatch.setattr(operations.os, "replace", fail_replace)
    with pytest.raises(OSError, match="mid-write"):
        operations._replace_last_ledger_row(ledger, {"status": "failed", "error": "nope"})
    assert ledger.read_text() == original + json.dumps({"status": "reserved"}) + "\n"
    leftovers = [path for path in tmp_path.iterdir() if path.name.startswith(".ledger.jsonl.")]
    assert leftovers == []


def test_trailing_unparseable_ledger_line_is_skipped(tmp_path, monkeypatch):
    archive, ledger = tmp_path / "single-v6.zip", tmp_path / "ledger.jsonl"
    pack(Path("agents/baseline"), archive)
    evaluation = evidence(tmp_path, archive)
    day = datetime.now(UTC).date().isoformat()
    ledger.write_text(
        json.dumps(
            {
                "created_at": f"{day}T00:00:00+00:00",
                "status": "submitted",
                "sha256": sha256(archive),
            }
        )
        + '\n{"status": "submi'
    )
    calls = _install_kaggle(monkeypatch, lambda *args, **kwargs: pytest.fail("upload attempted"))
    with pytest.warns(UserWarning, match="unparseable trailing"):
        with pytest.raises(ValueError, match="reserved"):
            operations.submit(archive, "ship it", ledger, execute=True, evaluation=evaluation)
    assert _submit_calls(calls) == []


def test_kaggle_cli_capture_replaces_undecodable_bytes(monkeypatch):
    import subprocess

    from gemma_lab.common import kaggle

    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok \ufffd", stderr="")

    monkeypatch.setattr("gemma_lab.common.subprocess.run", fake_run)
    assert kaggle("competitions", "files") == "ok \ufffd"
    assert seen["errors"] == "replace"
    assert seen["text"] is True


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
