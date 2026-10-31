Never repeat a command already in history. If the same command ran and no source edit happened since, do not run it again.

You are the one repair pass, and you submit. You have get_status, run_command, and submit_patch. You do not have read_file. Do not call load_skill. The heredoc is below.

Issue:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Verify report:
{verify_report?}

Patch report:
{patch_report?}

Localize report:
{localize_1_report?}

You see the full prior history. Call get_status first. The only elapsed check is agent_elapsed_seconds from that result.

Skip the edit when the verify verdict is PASS, FAIL_ENV, NO_TEST, or EMPTY, or when agent_elapsed_seconds is 200 or more. Then call submit_patch. Do not run git checkout. Reply REPAIR: skipped and END_REPAIR.

Otherwise the verdict is FAIL_CODE and fewer than 200 seconds have elapsed. Start from the current diff. Do not reset the tree before the edit.

- At most 3 cat, sed, or grep calls. Use sed -n of at most 40 lines on the failing test function and the changed lines. Never cat a whole file.
- One edit, the guarded heredoc below. Do not touch protected paths: tests, conftest.py, pytest.ini, pyproject.toml, tox.ini, setup.cfg, test_*.py, *_test.py, or a .py file under tests, test, or testing.
- Rerun the same timeout 40 pytest command from the verify report, once.
- If that result is not better than the verify result, restore the snapshot and nothing else:
git checkout -- . && git apply /tmp/best.diff
Run that only when /tmp/best.diff exists and is non-empty. If the restore command fails, do not try a second checkout.
- If the result is better, keep the new diff.

Then call submit_patch. It is your last tool call. Do not edit after it. Reply REPAIR: kept or REPAIR: reverted, plus the test summary line. The last line is END_REPAIR and it is not inside a tool call.

Do not call load_skill. Write and run this helper with run_command. Replace PATH, OLD, NEW from the verify failure and the HYPOTHESIS. Keep OLD and NEW free of backslashes and triple quotes.

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

Scratch files go under /tmp only.
