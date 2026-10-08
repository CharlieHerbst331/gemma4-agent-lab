"""Synthetic hygiene fixtures only. No competition tasks, patches, or grading output."""

import json
import subprocess
from pathlib import Path

import pytest

from gemma_lab.cli import main
from gemma_lab.hygiene import audit_patch, audit_run, lint_candidate, strip_evidence
from gemma_lab.hygiene.diffparse import parse_diff


def added(path, body="x = 1\n", mode="100644"):
    body_lines = body.splitlines() or [""]
    hunk = "\n".join(f"+{line}" for line in body_lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"new file mode {mode}\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(body_lines)} @@\n"
        f"{hunk}\n"
    )


def modified(path, added_line="VALUE = 2"):
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,2 +1,3 @@\n"
        " def ready():\n"
        f"+    {added_line}\n"
        "     return 1\n"
    )


def rules(report, rule):
    return [item for item in report["findings"] if item["rule"] == rule]


def trace(events):
    return {"schema": "gemma-lab/trace/v1", "events": events}


def command(agent, tool, text, output=""):
    return {"agent": agent, "tool": tool, "args": {"command": text}, "output": output}


@pytest.mark.parametrize(
    "path",
    [
        "repro.py",
        "reproduce_issue.py",
        "comprehensive_repro.py",
        "helper_repro.py",
        "debug_session.py",
        "scratch_notes.py",
        "tmp_probe.py",
        "test_issue_1.py",
        "test_fix.py",
        "check_now.py",
        "verify_now.py",
        "notes.md",
        "out.txt",
        ".adk_exec_deadbeef.py",
        "gemma-agent-repro.py",
        "gemma-agent-probe.py",
        "gemma-agent-checks.json",
        "edit.orig",
        "pkg/run.log",
        "pkg/__pycache__/mod.py",
        ".pytest_cache/v/cache",
        "pkg/demo.egg-info/PKG-INFO",
        "nohup.out",
    ],
)
def test_h1_scratch_names_block(path):
    report = audit_patch(added(path))
    assert rules(report, "H1.scratch")
    assert rules(report, "H1.scratch")[0]["severity"] == "block"
    assert report["gate"] == "block"


@pytest.mark.parametrize("path", ["src/pkg/check_utils.py", "src/pkg/debug.py", "pkg/readme.txt"])
def test_h1_non_root_names_are_unexplained_warnings(path):
    report = audit_patch(added(path, "VALUE = 1\n"))
    assert not rules(report, "H1.scratch")
    assert rules(report, "H1.unexplained")
    assert rules(report, "H1.unexplained")[0]["severity"] == "warn"
    assert report["gate"] == "warn"


def test_h1_existing_edit_and_explained_module_do_not_warn():
    assert not any(
        item["rule"].startswith("H1.") for item in audit_patch(modified("pkg/core.py"))["findings"]
    )
    patch = modified("pkg/core.py", "from pkg.extra import EXTRA").replace(
        "+    from pkg.extra import EXTRA", "+from pkg.extra import EXTRA"
    )
    patch += added("pkg/extra.py", "EXTRA = 1\n")
    events = [
        {"agent": "repair", "tool": "edit_file", "args": {"path": "pkg/extra.py"}, "output": "ok"}
    ]
    report = audit_patch(patch, trace(events))
    assert rules(report, "H1.explained")
    assert rules(report, "H1.explained")[0]["severity"] == "info"
    assert not rules(report, "H1.unexplained")
    unexplained = audit_patch(patch)
    assert rules(unexplained, "H1.unexplained")


def test_h1_binary_and_symlink_block():
    text = (
        "diff --git a/pkg/data.bin b/pkg/data.bin\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "Binary files /dev/null and b/pkg/data.bin differ\n"
        "diff --git a/pkg/link b/pkg/link\n"
        "new file mode 120000\n"
        "--- /dev/null\n"
        "+++ b/pkg/link\n"
        "@@ -0,0 +1 @@\n"
        "+../outside\n"
    )
    report = audit_patch(text)
    assert {item["rule"] for item in report["findings"]} >= {"H1.binary", "H1.symlink"}
    assert report["gate"] == "block"


@pytest.mark.parametrize(
    "path",
    [
        "conftest.py",
        "pkg/conftest.py",
        "nested/deep/conftest.py",
        "test_foo.py",
        "pkg/foo_test.py",
        "tests/test_pkg.py",
        "pkg/tests/test_nested.py",
        "test/test_pkg.py",
        "pytest.ini",
        "pkg/pytest.ini",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
    ],
)
def test_h2_protected_paths_block(path):
    report = audit_patch(modified(path))
    assert rules(report, "H2.protected")
    assert report["gate"] == "block"


@pytest.mark.parametrize(
    "path",
    [
        "fastapi/testclient.py",
        "pkg/testing/helper.py",
        "src/pkg/core.py",
        "docs_src/tutorial.py",
        "noxfile.py",
        "setup.py",
    ],
)
def test_h2_does_not_flag_unprotected_paths(path):
    report = audit_patch(modified(path))
    assert not rules(report, "H2.protected")
    assert report["gate"] == "pass"


@pytest.mark.parametrize(
    "line",
    [
        "breakpoint()",
        "import pdb",
        "pdb.set_trace()",
        '__import__("pdb")',
        "code.interact(local=locals())",
    ],
)
def test_h4_debugger_blocks(line):
    report = audit_patch(modified("pkg/core.py", line))
    assert rules(report, "H4.debug")
    assert rules(report, "H4.debug")[0]["severity"] == "block"
    assert report["gate"] == "block"


@pytest.mark.parametrize(
    "line",
    [
        "console.print(renderable)",
        "self.print(row)",
        'text = "print(debug)"',
        "# print(debug)",
        "# breakpoint()",
    ],
)
def test_h4_debugger_and_print_do_not_flag_safe_lines(line):
    report = audit_patch(modified("pkg/core.py", line))
    assert not rules(report, "H4.debug")
    assert not rules(report, "H4.print")
    assert report["gate"] == "pass"


def test_h4_bare_print_warns():
    report = audit_patch(modified("pkg/core.py", 'print("DEBUG value", x)'))
    assert rules(report, "H4.print")
    assert rules(report, "H4.print")[0]["severity"] == "warn"
    assert report["gate"] == "warn"


@pytest.mark.parametrize(
    "path",
    [
        "lib/python3.11/site-packages/fastapi/routing.py",
        ".venv/lib/python3.12/site-packages/fastapi/__init__.py",
        "build/lib/pkg/core.py",
    ],
)
def test_h5a_paths_block(path):
    report = audit_patch(modified(path))
    assert rules(report, "H5a.path")
    assert report["gate"] == "block"


@pytest.mark.parametrize(
    "path", ["pkg/core.py", "venv/lib/pkg.py", "build/lib64/pkg.py", "dist-packages/pkg.py"]
)
def test_h5a_paths_do_not_flag_workspace_or_unlisted_copies(path):
    report = audit_patch(modified(path))
    assert not rules(report, "H5a.path")


@pytest.mark.parametrize(
    "line",
    [
        'sys.path.insert(0, "/workspace")',
        'sys.path.append("/tmp")',
        "sys.path += ['/workspace/src']",
        'site.addsitedir("/opt/extra")',
    ],
)
def test_h5a_sys_path_hacks_block(line):
    report = audit_patch(modified("pkg/__init__.py", line))
    assert rules(report, "H5a.sys_path")
    assert report["gate"] == "block"


@pytest.mark.parametrize(
    "line",
    [
        "note = \"sys.path.insert(0, '/tmp')\"",
        '# sys.path.append("/tmp")',
        "os.environ['PYTHONPATH'] = '/workspace'",
    ],
)
def test_h5a_sys_path_does_not_flag_strings_comments_or_pythonpath(line):
    report = audit_patch(modified("pkg/__init__.py", line))
    assert not rules(report, "H5a.sys_path")
    assert report["gate"] == "pass"


def test_h5b_host_site_packages_blocks_evidence_and_warns_the_task():
    output = 'File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 10, in route'
    report = audit_patch(
        "", trace([command("repair", "run_command", "python -c 'import fastapi'", output)])
    )
    found = rules(report, "H5b.host_import")
    assert found and found[0]["severity"] == "warn" and found[0]["evidence_blocked"] is True
    assert report["evidence_blocked"] is True
    assert report["gate"] == "warn"


def test_h5b_workspace_traceback_is_clean():
    output = 'File "/tmp/swegemma_sandbox/workspace/fastapi/routing.py", line 10, in route'
    report = audit_patch(
        "", trace([command("repair", "run_command", "python -c 'import fastapi'", output)])
    )
    assert not rules(report, "H5b.host_import")
    assert report["evidence_blocked"] is False
    assert report["gate"] == "pass"


@pytest.mark.parametrize(
    "text",
    [
        "pip show fastapi",
        "pip list",
        "pip freeze",
        "python -m pip show fastapi",
        "python -c \"import importlib.metadata as meta; print(meta.version('fastapi'))\"",
        (
            'python -c "import pkg_resources; '
            "print(pkg_resources.get_distribution('fastapi').location)\""
        ),
    ],
)
def test_h5c_host_metadata_warns(text):
    report = audit_patch("", trace([command("repair", "run_command", text)]))
    assert rules(report, "H5c.host_metadata")
    assert rules(report, "H5c.host_metadata")[0]["severity"] == "warn"
    assert report["gate"] == "warn"


def test_h5c_import_file_probe_does_not_warn():
    text = 'cd /workspace && python3 -c "import fastapi; print(fastapi.__file__)"'
    report = audit_patch(
        "", trace([command("repair", "run_command", text, "/workspace/fastapi/__init__.py")])
    )
    assert not rules(report, "H5c.host_metadata")
    assert report["gate"] == "pass"


@pytest.mark.parametrize(
    "text",
    ["python -I -c 'import fastapi'", "python3 -E -c 'import fastapi'", "python -Ic 'print(1)'"],
)
def test_h5d_isolated_python_warns(text):
    report = audit_patch("", trace([command("repair", "run_command", text)]))
    assert rules(report, "H5d.python_flags")
    assert report["gate"] == "warn"


@pytest.mark.parametrize(
    "text",
    [
        "python -c 'import fastapi'",
        "python -P -c 'import fastapi'",
        "python -s -m pytest -q",
        "python -W ignore -c 'print(1)'",
    ],
)
def test_h5d_grading_flags_do_not_warn(text):
    report = audit_patch("", trace([command("verify", "run_command", text)]))
    assert not rules(report, "H5d.python_flags")


def test_unrecognized_trace_is_unknown_and_not_fallback():
    report = audit_patch(modified("pkg/core.py"), {"mystery": True})
    assert report["finalization"] == "unknown"
    assert rules(report, "H3.unknown")
    assert not rules(report, "H3.fallback")


def test_recognized_trace_without_submit_is_fallback():
    report = audit_patch(
        modified("pkg/core.py"), trace([command("repair", "run_command", "python -c 'print(1)'")])
    )
    assert report["finalization"] == "fallback"
    assert rules(report, "H3.fallback")
    assert report["gate"] == "warn"


def test_adk_like_submit_is_explicit():
    payload = {
        "events": [
            {
                "author": "verify",
                "content": {
                    "parts": [
                        {"function_call": {"name": "submit_patch", "args": {}}},
                        {"function_response": {"name": "submit_patch", "response": "ok"}},
                    ]
                },
            }
        ]
    }
    report = audit_patch(modified("pkg/core.py"), payload)
    assert report["trace_schema"] == "adk-like"
    assert report["finalization"] == "explicit"
    assert report["verifier_reached"] is True
    assert report["gate"] == "pass"


def _explicit(agent="verify"):
    return trace([{"agent": agent, "tool": "submit_patch", "args": {}, "output": "ok"}])


def test_run_rates_warn_when_submit_or_verifier_is_missing(tmp_path):
    _write_run(
        tmp_path,
        [
            ("ok_task", modified("pkg/core.py"), _explicit()),
            (
                "missed_task",
                modified("pkg/core.py"),
                trace([command("repair", "run_command", "python -c 'print(1)'")]),
            ),
        ],
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    report = audit_run(tmp_path)
    assert rules(report["candidate"], "R.explicit_submit_rate")
    assert rules(report["candidate"], "R.verifier_reach_rate")
    assert all(item["severity"] == "warn" for item in report["candidate"]["findings"])
    assert report["candidate"]["explicit_finalization"] == [1, 2]
    assert report["candidate"]["verifier_reached"] == [1, 2]
    assert report["gate"] == "warn"
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after


def test_run_rates_do_not_fire_when_every_task_submits(tmp_path):
    _write_run(
        tmp_path,
        [
            ("alpha", modified("pkg/core.py"), _explicit()),
            ("beta", "", _explicit("verifier")),
        ],
    )
    report = audit_run(tmp_path)
    assert not report["candidate"]["findings"]
    assert report["candidate"]["explicit_finalization"] == [2, 2]
    assert report["candidate"]["verifier_reached"] == [2, 2]
    assert report["gate"] == "pass"


def test_policy_cannot_promote_rate_shortfalls_to_block(tmp_path):
    _write_run(tmp_path, [("only", "", trace([]))])
    report = audit_run(tmp_path, {"explicit_submit_min_rate": 0.5, "rate_severity": "block"})
    assert rules(report["candidate"], "R.explicit_submit_rate")[0]["severity"] == "warn"


def test_evidence_snippets_are_omitted_from_the_public_view():
    report = audit_patch(modified("pkg/core.py", 'print("DEBUG value", x)'))
    public = strip_evidence(report)
    assert "evidence" not in public["findings"][0]
    assert "DEBUG value" not in json.dumps(public)
    assert public["evidence_blocked"] is False


def test_cli_exit_codes(tmp_path, capsys):
    clean = tmp_path / "clean.patch"
    clean.write_text(modified("pkg/core.py"))
    main(["hygiene", "patch", str(clean)])
    assert json.loads(capsys.readouterr().out)["gate"] == "pass"
    blocked = tmp_path / "blocked.patch"
    blocked.write_text(modified("pkg/core.py", "breakpoint()"))
    with pytest.raises(SystemExit) as caught:
        main(["hygiene", "patch", str(blocked)])
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out)["gate"] == "block"
    warning = tmp_path / "warn.patch"
    warning.write_text(modified("pkg/core.py", 'print("DEBUG value", x)'))
    main(["hygiene", "patch", str(warning)])
    assert json.loads(capsys.readouterr().out)["gate"] == "warn"
    with pytest.raises(SystemExit) as caught:
        main(["hygiene", "patch", str(warning), "--fail-on", "warn"])
    assert caught.value.code == 1
    with pytest.raises(SystemExit) as caught:
        main(["hygiene", "patch", str(tmp_path / "missing.patch")])
    assert caught.value.code == 2
    bad = tmp_path / "trace.json"
    bad.write_text('{"mystery": true}')
    with pytest.raises(SystemExit) as caught:
        main(["hygiene", "patch", str(clean), "--trace", str(bad), "--require-trace"])
    assert caught.value.code == 2


def test_cli_run_writes_only_the_requested_sidecar(tmp_path, capsys):
    _write_run(tmp_path, [("alpha", modified("pkg/core.py"), _explicit())])
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    destination = tmp_path / "hygiene.json"
    main(
        [
            "hygiene",
            "run",
            str(tmp_path),
            "--output",
            str(destination),
            "--workspace-root",
            str(tmp_path),
        ]
    )
    assert json.loads(capsys.readouterr().out)["gate"] == "pass"
    written = json.loads(destination.read_text())
    assert written["schema"] == "gemma-lab/hygiene/v1"
    after = {
        path: path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and path != destination
    }
    assert before == after


def test_candidate_lint_blocks_and_passes(tmp_path):
    blocked = _candidate(tmp_path / "blocked", tools_verify=["read_file"], extra_tool="write_file")
    report = lint_candidate(blocked)
    assert rules(report, "G0.missing_submit")
    assert rules(report, "G0.write_file")
    assert report["gate"] == "block"
    clean = _candidate(tmp_path / "clean", tools_verify=["read_file", "submit_patch"])
    report = lint_candidate(clean)
    assert report["gate"] == "pass"
    assert not report["findings"]


def test_structured_candidates_have_no_hygiene_block():
    for name in ("structured-v4", "structured-v4-10m"):
        source = Path("agents") / name
        before = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))
        report = lint_candidate(source)
        after = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))
        assert after == before
        blocked = [item for item in report["findings"] if item["severity"] == "block"]
        assert blocked == []
        assert any(item["rule"] == "G0.handoff_ratio" for item in report["findings"])
        assert report["gate"] == "warn"


def test_parser_reads_a_real_git_diff(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "hygiene@example.test")
    _git(root, "config", "user.name", "Hygiene")
    (root / "pkg file.py").write_text("VALUE = 1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    (root / "pkg file.py").write_text("VALUE = 2\n")
    (root / "repro.py").write_text("print(1)\n")
    _git(root, "add", "-N", "repro.py")
    diff = subprocess.run(
        ["git", "diff", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    parsed = parse_diff(diff.stdout)
    paths = {item.path for item in parsed}
    assert "pkg file.py" in paths
    assert "repro.py" in paths
    report = audit_patch(diff.stdout)
    assert rules(report, "H1.scratch")[0]["path"] == "repro.py"


def _write_run(directory, tasks):
    (directory / "results" / "patches").mkdir(parents=True)
    identifiers = [task_id for task_id, _, _ in tasks]
    (directory / "run_manifest.json").write_text(
        json.dumps({"sha256": "ab" * 32, "task_ids": identifiers})
    )
    rows = []
    for task_id, patch, payload in tasks:
        (directory / "results" / "patches" / f"{task_id}.patch").write_text(patch)
        (directory / "results" / f"{task_id}.json").write_text(json.dumps(payload))
        rows.append({"instance_id": task_id, "resolved": False, "duration_seconds": 1})
    (directory / "task_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


def _candidate(root, tools_verify, extra_tool=None):
    (root / "sub_agents").mkdir(parents=True)
    (root / "agent.yaml").write_text(
        "agent_class: SequentialAgent\nname: demo\nsub_agents:\n"
        "- config_path: sub_agents/repair.yaml\n"
        "- config_path: sub_agents/verify.yaml\n"
    )
    repair_tools = ["read_file", "edit_file"]
    if extra_tool:
        repair_tools.append(extra_tool)
    _role(root, "repair", repair_tools, "Keep scratch in /tmp.\n")
    _role(root, "verify", tools_verify, "Keep scratch in /tmp. Call submit_patch last.\n")
    return root


def _role(root, name, tools, prompt):
    (root / "sub_agents" / f"{name}.md").write_text(prompt)
    body = (
        "agent_class: LlmAgent\n"
        f"name: {name}\n"
        "model: gemma-4-31b-it-qat-w4a16-ct\n"
        f"instruction: !include {name}.md\n"
        "tools:\n"
    )
    body += "".join(f"- {tool}\n" for tool in tools)
    (root / "sub_agents" / f"{name}.yaml").write_text(body)


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
