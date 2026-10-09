import json
import subprocess
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from gemma_lab.stub_server import (
    MOCK_BASE_COMMIT,
    MOCK_REPO,
    ScriptedResponder,
    StubModelServer,
    apply_tool_calls,
    candidate_marker,
    empty_submit_turns,
    is_synthetic_mock,
    mock_task,
    repair_turns,
    smoke_server_for_candidate,
    write_mock_repo,
)


def _post(server, text):
    body = json.dumps({"messages": [{"role": "user", "content": text}]}).encode()
    request = urllib.request.Request(
        server.openai_base_url + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def test_stub_server_health_metrics_and_tool_calls():
    server = StubModelServer(ScriptedResponder({"": repair_turns()}))
    with server:
        with urllib.request.urlopen(server.health_url) as response:
            assert json.load(response)["status"] == "ok"
        with pytest.raises(urllib.error.HTTPError) as wrong:
            urllib.request.urlopen(server.base_url + "/health")
        assert wrong.value.code == 404
        with urllib.request.urlopen(server.openai_base_url + "/models") as response:
            assert json.load(response)["data"][0]["id"] == "stub-model"
        first = _post(server, "fix the calculator")
        message = first["choices"][0]["message"]
        assert message["tool_calls"][0]["function"]["name"] == "edit_file"
        assert first["choices"][0]["finish_reason"] == "tool_calls"
        second = _post(server, "fix the calculator")
        submitted = second["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
        assert submitted == "submit_patch"
        with urllib.request.urlopen(server.root_url + "/metrics") as response:
            metrics = response.read().decode()
        with pytest.raises(urllib.error.HTTPError) as metrics_wrong:
            urllib.request.urlopen(server.base_url + "/metrics")
        assert metrics_wrong.value.code == 404
        assert "vllm:prefix_cache_hits_total 2" in metrics
        assert "vllm:prefix_cache_queries_total 2" in metrics


def test_marker_routes_repair_and_empty_scripts(tmp_path):
    source = tmp_path / "candidates" / "demo-agent"
    source.mkdir(parents=True)
    server, marker = smoke_server_for_candidate(source, behavior="repair")
    try:
        other = _post(server, "no marker here")
        assert other["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "submit_patch"
        routed = _post(server, f"system {marker}")
        assert routed["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "edit_file"
    finally:
        server.close()
    assert candidate_marker(source) == "GEMMA_LAB_CANDIDATE=demo-agent"
    assert empty_submit_turns()[0]["tool_calls"][0]["function"]["name"] == "submit_patch"


def test_repair_turn_fixes_mock_repo(tmp_path):
    root = write_mock_repo(tmp_path / "repo")
    task = mock_task()
    assert task["repo"] == MOCK_REPO
    assert task["base_commit"] == MOCK_BASE_COMMIT
    assert is_synthetic_mock(task)
    assert is_synthetic_mock(SimpleNamespace(repo=MOCK_REPO, base_commit=MOCK_BASE_COMMIT))
    assert not is_synthetic_mock({"repo": "psf/requests", "base_commit": MOCK_BASE_COMMIT})
    turn = repair_turns()[0]
    assert apply_tool_calls(root, turn) == ["mockpkg/calc.py"]
    assert (root / ".git").is_dir()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    assert len(head.stdout.strip()) == 40
    completed = subprocess.run(
        [sys.executable, "-c", "from mockpkg.calc import add; assert add(1, 2) == 3"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
