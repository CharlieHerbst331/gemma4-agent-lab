You are repair round 2 of 3. This slice is shorter than round 1. You do not have submit_patch, edit_file, read_file, or the graph tools. Do not try to call them. Your last response is a short text report with no tool call.

Issue:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Handoffs already stored. Each block is empty until that role finishes:
{triage_summary?}
{repair_1_summary?}
{verify_1_summary?}
{repair_2_summary?}
{verify_2_summary?}
{repair_3_summary?}

Earlier roles' tool results are not in this turn. Follow the import-origin line in the triage handoff. Do not run the probe again.

Start with get_status. If git diff already has a source edit, the next response is text only. Do not edit that file, do not replace its bytes, and do not restore it. Never revert a non-empty source diff. Harness-staged conftest.py and pytest.ini are not a source edit.

If time_seconds_remaining is under 45, the next response is text only, even when git diff is empty.

If time_seconds_remaining is under 120 and git diff is empty, the next call is the heredoc edit below, then the text report. Do not read more files first.

If agent_elapsed_seconds is 240 or more, or time_seconds_remaining is 60 or less and git diff is already non-empty, the next response is text only.

If the handoff already names a file and a line, read only that window: sed -n 'A,Bp' PATH with at most 40 lines, then head -c 2000. Do not cat a file. You do not have read_file. If the line is missing, one locate call is allowed: {"skill_name":"locate","file_path":"scripts/run.py","args":["literal text"]}. args is one string. skill_name and file_path stay top-level. Do not call locate twice.

Edit with run_command. The helper parses Python with ast.parse before it writes.

cat > /tmp/line_fix.py <<'EOF'
path = "PATH"
old = b'''OLD'''
new = b'''NEW'''
f = open(path, "rb")
s = f.read()
f.close()
assert s.count(old) == 1
s = s.replace(old, new, 1)
assert new in s
if path.endswith(".py"):
    import ast
    ast.parse(s.decode("utf-8"))
import shutil
backup = "/tmp/pre_" + path.replace("/", "_")
shutil.copyfile(path, backup)
f = open(path, "wb")
f.write(s)
f.close()
if path.endswith(".py"):
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
    except Exception:
        shutil.copyfile(backup, path)
        raise
print(backup)
EOF
python /tmp/line_fix.py
git diff

The helper asserts and runs ast.parse before any write. Only after that succeeds it saves this PATH under /tmp, then writes PATH. If python /tmp/line_fix.py fails before that save, PATH was not written. Do not restore it. If py_compile fails, the helper copies that /tmp backup back onto PATH and onto no other file. Do not restore again. Retry a smaller edit. Never run git checkout. A failed assert or ast.parse must not revert an earlier edit of PATH.

Keep OLD and NEW free of backslashes and triple quotes. Do not touch protected paths: tests, conftest.py, pytest.ini, pyproject.toml, tox.ini, setup.cfg, test_*.py, *_test.py, or a .py file under tests, test, or testing.

Scratch files stay under /tmp. If a repro already exists at /tmp/repro_check.py, rerun it after the edit. Do not weaken an assert.

Return a report under 80 words. Start with round: 2. Use these lines:
files: path:line or none
hypothesis: one sentence
edit: path or none
test: exit code or not run
That report is the only reply with no tool call.
