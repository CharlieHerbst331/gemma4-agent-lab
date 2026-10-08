"""Opt-in smoke against swegemma's synthetic mock repository.

Default `make check` deselects this module. Run it with
``GEMMA_LAB_STUB_SERVER=1 uv run pytest -m stub_server`` once swegemma is installed.
"""

import inspect
import os
import subprocess
import sys

import pytest

from gemma_lab.stub_server import (
    apply_tool_calls,
    is_synthetic_mock,
    mock_task,
    smoke_server_for_candidate,
    write_mock_repo,
)

pytestmark = pytest.mark.stub_server


def _post(server, text):
    import json
    import urllib.request

    body = json.dumps({"messages": [{"role": "user", "content": text}]}).encode()
    request = urllib.request.Request(
        server.openai_base_url + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def test_swegemma_mock_repo_smoke(tmp_path):
    if os.environ.get("GEMMA_LAB_STUB_SERVER") != "1":
        pytest.skip("set GEMMA_LAB_STUB_SERVER=1 to run the harness smoke test")
    pytest.importorskip("swegemma")
    import swegemma.harness.verification as verification

    source = inspect.getsource(verification.verify_task)
    assert "test/mock_repo" in source
    assert "123456" in source
    task = mock_task()
    assert is_synthetic_mock(task)
    root = write_mock_repo(tmp_path / "repo")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    server, marker = smoke_server_for_candidate(candidate, behavior="repair")
    try:
        first = _post(server, marker)
        apply_tool_calls(root, first["choices"][0]["message"])
        second = _post(server, marker)
        name = second["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
        assert name == "submit_patch"
    finally:
        server.close()
    completed = subprocess.run(
        [sys.executable, "-c", "from mockpkg.calc import add; assert add(1, 2) == 3"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
