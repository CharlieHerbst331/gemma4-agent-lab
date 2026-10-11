"""Wait for a late competition mount before reading tasks.jsonl."""

import ast
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from gemma_lab.notebook import generate_pair, wait_for_tasks_jsonl
from gemma_lab.paired import load_protocol, protocol_schedule, report_from_runs

SMOKE = Path("configs/protocols/v6-vs-single-v2-toolcall-smoke.yaml")
THINK = Path("configs/protocols/single-v5-vs-single-v5-think256-smoke.yaml")


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

    with pytest.raises(FileNotFoundError, match="last check: empty"):
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
    assert "last check: missing" in str(raised.value)
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
    assert 'return "truncated"' in payload
    assert "round(now - start, 1)" in payload


def _advance(clock):
    def sleep(seconds):
        clock.advance(seconds)

    return sleep


def test_partial_line_retries_until_it_is_complete_jsonl(tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"instance_id": "t"}')
    clock = _Clock()
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)
        if clock.now >= 5:
            path.write_text('{"instance_id": "t"}\n')

    waited = wait_for_tasks_jsonl(
        path, interval=5, timeout=300, log_every=30, clock=clock, sleep=sleep
    )

    assert waited == 5.0
    assert sleeps == [5]
    text = capsys.readouterr().out
    assert "waiting for" in text
    assert "tasks.jsonl ready after 5.0s" in text


def test_blank_only_file_is_not_ready(tmp_path):
    path = tmp_path / "tasks.jsonl"
    clock = _Clock()
    for text in ("\n", "\n\n", "  \n"):
        path.write_text(text)
        clock.now = 0.0
        with pytest.raises(FileNotFoundError, match="last check: empty"):
            wait_for_tasks_jsonl(
                path,
                interval=5,
                timeout=10,
                log_every=30,
                clock=clock,
                sleep=_advance(clock),
                runner=lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "", ""),
                probe_path=tmp_path / "probe.txt",
            )


def test_stuck_partial_and_bad_json_name_the_reason(tmp_path):
    path = tmp_path / "tasks.jsonl"
    clock = _Clock()
    cases = (
        ('{"instance_id": "t"}', "truncated"),
        ("{not-json}\n", "unparseable"),
        ('{"instance_id": "t"}\n\n', "unparseable"),
    )
    for text, reason in cases:
        path.write_text(text)
        clock.now = 0.0
        with pytest.raises(FileNotFoundError, match=f"last check: {reason}"):
            wait_for_tasks_jsonl(
                path,
                interval=5,
                timeout=10,
                log_every=30,
                clock=clock,
                sleep=_advance(clock),
                runner=lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "", ""),
                probe_path=tmp_path / "probe.txt",
            )


def test_read_error_counts_as_not_ready(tmp_path, monkeypatch):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"instance_id": "t"}\n')

    def boom(self, *args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", boom)
    clock = _Clock()
    with pytest.raises(FileNotFoundError, match="last check: unreadable"):
        wait_for_tasks_jsonl(
            path,
            interval=5,
            timeout=10,
            log_every=30,
            clock=clock,
            sleep=_advance(clock),
            runner=lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "", ""),
            probe_path=tmp_path / "probe.txt",
        )


def test_present_file_rounds_tiny_wait_to_zero(tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"instance_id": "t"}\n')
    ticks = iter((0.0, 1.2e-6))

    def clock():
        return next(ticks)

    def sleep(seconds):
        raise AssertionError("slept")

    waited = wait_for_tasks_jsonl(path, interval=5, timeout=300, clock=clock, sleep=sleep)
    assert waited == 0.0
    assert "tasks.jsonl ready after 0.0s" in capsys.readouterr().out


def test_late_valid_file_rounds_wait_to_one_decimal(tmp_path):
    path = tmp_path / "tasks.jsonl"
    ticks = iter((0.0, 0.0, 10.06))

    def sleep(seconds):
        path.write_text('{"instance_id": "t"}\n')

    waited = wait_for_tasks_jsonl(
        path, interval=5, timeout=300, clock=lambda: next(ticks), sleep=sleep
    )
    assert waited == 10.1


def _stored_run(root):
    root.mkdir(parents=True)
    rows = []
    for arm in ("A", "B"):
        rows.append(
            {
                "arm": arm,
                "repeat": 1,
                "task_id": "fastapi_14786",
                "resolved": False,
                "wall_seconds": 1,
                "hit_cap": {},
            }
        )
    (root / "pair_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_report_refuses_a_manifest_from_another_protocol(tmp_path):
    smoke = load_protocol(SMOKE)
    think = load_protocol(THINK)
    smoke_schedule = protocol_schedule(smoke)["sha256"]
    think_schedule = protocol_schedule(think)["sha256"]
    assert smoke_schedule == think_schedule
    assert smoke["_sha256"] != think["_sha256"]
    root = tmp_path / "run"
    _stored_run(root)
    (root / "pair_manifest.json").write_text(
        json.dumps(
            {
                "protocol_sha256": think["_sha256"],
                "schedule_sha256": think_schedule,
            }
        )
    )
    with pytest.raises(ValueError, match="does not match protocol") as raised:
        report_from_runs([root], SMOKE, tmp_path / "out")
    text = str(raised.value)
    assert think["_sha256"] in text
    assert smoke["_sha256"] in text
    assert not (tmp_path / "out" / "pair_report.md").exists()


def test_report_accepts_a_matching_protocol_hash(tmp_path):
    smoke = load_protocol(SMOKE)
    root = tmp_path / "run"
    _stored_run(root)
    (root / "pair_manifest.json").write_text(
        json.dumps(
            {
                "protocol_sha256": smoke["_sha256"],
                "schedule_sha256": protocol_schedule(smoke)["sha256"],
            }
        )
    )
    output = tmp_path / "out"
    report_from_runs([root], SMOKE, output)
    saved = json.loads((output / "pair_report.json").read_text())
    assert saved["protocol_sha256"] == smoke["_sha256"]


def test_report_warns_when_an_older_manifest_omits_protocol_hash(tmp_path):
    smoke = load_protocol(SMOKE)
    schedule = protocol_schedule(smoke)["sha256"]
    root = tmp_path / "run"
    _stored_run(root)
    (root / "pair_manifest.json").write_text(json.dumps({"schedule_sha256": schedule}))
    output = tmp_path / "out"
    with pytest.warns(UserWarning, match="no protocol_sha256"):
        report_from_runs([root], SMOKE, output)
    assert (output / "pair_report.md").is_file()

    blank = tmp_path / "blank"
    _stored_run(blank)
    (blank / "pair_manifest.json").write_text(
        json.dumps({"protocol_sha256": "  ", "schedule_sha256": schedule})
    )
    with pytest.warns(UserWarning, match="no protocol_sha256"):
        report_from_runs([blank], SMOKE, tmp_path / "blank-out")
