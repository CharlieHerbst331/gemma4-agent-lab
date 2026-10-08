import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "public_findings", Path("scripts/export_public_findings.py")
)
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)


def test_public_export_drops_raw_competition_material_and_credentials(tmp_path):
    folder = tmp_path / "source/example"
    folder.mkdir(parents=True)
    sentinel = "PRIVATE_GRADING_PATCH_AND_CREDENTIAL_SENTINEL"
    row = {
        "instance_id": "fastapi_123",
        "repo": "fastapi/fastapi",
        "resolved": False,
        "tool_calls": 3,
        "duration_seconds": 8,
        "patch_chars": 40,
        "test_exit_code": 1,
        "failure_class": "agent_budget",
        "error": sentinel,
        "problem_statement": sentinel,
        "patch": sentinel,
        "test_patch": sentinel,
        "trace": sentinel,
        "credential": sentinel,
    }
    (folder / "task_results.jsonl").write_text(json.dumps(row) + "\n")
    (folder / "run_manifest.json").write_text(
        json.dumps(
            {
                "sha256": "a" * 64,
                "archive": sentinel,
                "source": sentinel,
                "packages": {"swegemma": "0.2.7", "secret": sentinel},
            }
        )
    )
    (folder / "execution.log").write_text(sentinel)
    output = tmp_path / "public.json"
    assert public.export(tmp_path / "source", output) == 1
    text = output.read_text()
    assert sentinel not in text
    result = json.loads(text)["runs"][0]
    assert result["archive_sha256"] == "a" * 64
    assert result["task_results"][0]["recorded_failure_class"] == "agent_budget"
    assert result["task_results"][0]["runner_error_recorded"] is True
    assert "execution.log" not in result["private_evidence_hashes"]


def test_dirty_packing_revision_still_exports_the_commit(tmp_path):
    folder = tmp_path / "source/example"
    folder.mkdir(parents=True)
    commit = "ab" * 20
    (folder / "run_manifest.json").write_text(
        json.dumps({"sha256": "c" * 64, "git_revision": commit + "-dirty"})
    )
    output = tmp_path / "public.json"
    public.export(tmp_path / "source", output)
    result = json.loads(output.read_text())["runs"][0]
    assert result["source_git_revision"] == commit


def test_public_export_refuses_arbitrary_identifier_text():
    with pytest.raises(ValueError):
        public.task_row(
            {"instance_id": "SECRET_PRIVATE_TEXT", "repo": "fastapi/fastapi", "resolved": True}
        )
