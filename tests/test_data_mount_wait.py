"""Wait for a late competition mount before reading tasks.jsonl."""

import ast
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from gemma_lab.notebook import generate_pair, wait_for_tasks_jsonl


def _helpers():
    path = Path(__file__).with_name("test_paired_notebook.py")
    spec = importlib.util.spec_from_file_location("paired_notebook_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_ready_file_returns_immediately_without_sleep(tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"instance_id": "t"}\n')
    clock = _Clock()
    slept = []

    waited = wait_for_tasks_jsonl(
        path, interval=5, timeout=300, log_every=30, clock=clock, sleep=slept.append
    )

    assert waited == 0
    assert slept == []
    text = capsys.readouterr().out
    assert "tasks.jsonl ready after 0.0s" in text
    assert "waiting for" not in text


def test_empty_file_is_not_ready(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_bytes(b"")
    clock = _Clock()

    def sleep(seconds):
        clock.advance(seconds)

    with pytest.raises(FileNotFoundError, match="was not ready after"):
        wait_for_tasks_jsonl(
            path,
            interval=5,
            timeout=10,
            log_every=30,
            clock=clock,
            sleep=sleep,
            runner=lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "", ""),
            probe_path=tmp_path / "probe.txt",
        )


def test_waits_until_a_delayed_file_appears(tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    clock = _Clock()
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)
        if clock.now >= 10:
            path.write_text('{"instance_id": "t"}\n')

    waited = wait_for_tasks_jsonl(
        path, interval=5, timeout=300, log_every=30, clock=clock, sleep=sleep
    )

    assert waited == 10
    assert sleeps == [5, 5]
    text = capsys.readouterr().out
    assert "waiting for" in text
    assert "0s elapsed" in text
    assert "tasks.jsonl ready after 10.0s" in text


def test_timeout_runs_mount_diagnostics(tmp_path, monkeypatch, capsys):
    path = tmp_path / "tasks.jsonl"
    clock = _Clock()
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append((list(cmd), timeout))
        if cmd[0] == "ls":
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, stdout="found-none\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    def sleep(seconds):
        clock.advance(seconds)

    probe = tmp_path / "probe.txt"
    with pytest.raises(FileNotFoundError, match="limit 15") as raised:
        wait_for_tasks_jsonl(
            path,
            interval=5,
            timeout=15,
            log_every=30,
            probe_timeout=7,
            clock=clock,
            sleep=sleep,
            probe_path=probe,
        )
    assert "Probe output:" in str(raised.value)
    assert str(probe) in str(raised.value)
    assert [cmd[0] for cmd, _timeout in calls] == ["ls", "find"]
    assert calls[0][0] == ["ls", "-la", "/kaggle/input", "/kaggle/input/competitions"]
    assert calls[1][0] == [
        "find",
        "/kaggle/input",
        "-maxdepth",
        "4",
        "-name",
        "tasks.jsonl",
    ]
    assert all(timeout == 7 for _cmd, timeout in calls)
    saved = probe.read_text()
    assert "probe failed:" in saved
    assert "found-none" in saved
    assert "ls -la /kaggle/input" in capsys.readouterr().out


def test_generated_payload_cell_compiles_and_names_resolve(tmp_path, monkeypatch):
    helpers = _helpers()
    helpers._official_starter(tmp_path)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "paired"
    generate_pair(helpers._arms(tmp_path), "owner", "pair-v1", output, wheelhouse_version=30)
    notebook = json.loads((output / "evaluation.ipynb").read_text())
    cells = []
    for cell in notebook["cells"]:
        source = cell["source"]
        text = "".join(source) if isinstance(source, list) else source
        cells.append(text)
    code_cells = [
        text
        for cell, text in zip(notebook["cells"], cells, strict=True)
        if cell["cell_type"] == "code"
    ]
    payload = cells[3]
    compile(payload, "generated_notebook", "exec")
    assert "DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')" in payload
    assert "TASKS_PATH = DATA_DIR / 'tasks.jsonl'" in payload
    assert "tasks = load_tasks(TASKS_PATH)" in payload
    assert "DATA_WAIT_INTERVAL_SECONDS = 5" in payload
    assert "DATA_WAIT_TIMEOUT_SECONDS = 300" in payload
    assert "_data_wait_seconds = wait_for_tasks_jsonl(TASKS_PATH)" in payload
    assert "'data_wait_seconds': _data_wait_seconds" in payload
    assert helpers.undefined_names("\n".join(code_cells)) == []
    tree = ast.parse(payload)
    defined = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert "wait_for_tasks_jsonl" in defined
    for index, cell in enumerate(cells):
        if index != 3:
            assert "wait_for_tasks_jsonl" not in cell
    assert "tasks.jsonl" not in cells[1]
    assert "MODEL_PATH" not in payload
