import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gemma_lab import operations
from gemma_lab.bundle import pack
from gemma_lab.operations import submissions_today


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
    calls = []

    def api(*args, **kwargs):
        calls.append(args)
        if "submissions" in args:
            return "No submissions found\n"
        raise RuntimeError("connection interrupted during upload")

    monkeypatch.setattr(operations, "kaggle", api)
    with pytest.raises(RuntimeError):
        operations.submit(archive, "test", ledger, execute=True)
    row = json.loads(ledger.read_text())
    assert row["status"] == "reserved"
    assert row["created_at"].startswith(datetime.now(UTC).date().isoformat())
    with pytest.raises(ValueError, match="reserved"):
        operations.submit(archive, "test", ledger, execute=True)
    assert sum("submit" in args for args in calls) == 1


def test_plan_has_no_network_side_effects(tmp_path, monkeypatch):
    archive = tmp_path / "submission.zip"
    pack(Path("agents/baseline"), archive)
    monkeypatch.setattr(operations, "kaggle", lambda *args, **kwargs: pytest.fail("unexpected API"))
    assert operations.submit(archive, "plan")["status"] == "planned"
