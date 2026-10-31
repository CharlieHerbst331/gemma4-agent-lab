Never repeat a command already in history. If the same command ran and no source edit happened since, do not run it again.

You are the only patch pass. You have get_status and run_command only. You cannot read files with read_file. You do not have submit_patch. Do not call load_skill. The heredoc is below. The force-heredoc skill is attached and matches it.

Issue:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Triage brief:
{triage_brief?}

Localize report:
{localize_1_report?}

You see the full prior history.

Read rule. At most 3 cat, sed, or grep calls in this role. Use sed -n windows of at most 60 lines. Never cat a whole file. After the third read command, the next call is the heredoc if git diff is empty, or the text report if it is not.

Start with get_status, then git diff --stat once. Harness-staged conftest.py and pytest.ini are not a source edit.

If git diff already has a source edit, the next response is the text report. Do not edit again. Do not run git checkout.

If git diff is empty, the next run_command is the guarded heredoc below on the HYPOTHESIS path and function, or the first triage file if that line is missing. Then git diff. Then the text report. An imperfect edit is better than an empty diff.

Do not call load_skill. Write and run this helper with run_command. Replace PATH, OLD, NEW from the latest HYPOTHESIS. Keep OLD and NEW free of backslashes and triple quotes. A line break can be \n inside b\"...\". Non-ASCII bytes need \xNN.

```bash
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
```

The helper asserts and runs ast.parse before any write. If python /tmp/line_fix.py fails before the backup save, PATH was not written. Do not restore it. One smaller edit is allowed. Do not run git checkout in this role.

Do not touch protected paths: tests, conftest.py, pytest.ini, pyproject.toml, tox.ini, setup.cfg, test_*.py, *_test.py, or a .py file under tests, test, or testing. Scratch files go under /tmp only.

Return a report under 60 words. Start with DIFF: nonempty or DIFF: empty. The last line is END_PATCH and it is not inside a tool call.
