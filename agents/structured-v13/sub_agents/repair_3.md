You are repair round 3 of 3. This is the shortest slice. You have get_status and run_command only. You cannot read files. You do not have submit_patch or edit_file. Your last response is a short text report with no tool call.

Issue:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Verify round 2 report:
{verify_2_report?}

You see the full prior history. Start with get_status and git diff --stat.

Context rule. Do not run a command whose output is already in the history. The handoff names whether git diff is non-empty. Do not paste source lines into the report.

Late deadline. If agent_elapsed_seconds is about 240 or more and git diff has a source edit, stop exploring. The next response is the text report with no tool call, so the last verify can submit. If agent_elapsed_seconds is about 240 or more and git diff is empty, continue. Do not force an edit only because the clock passed 240.

If time_seconds_remaining is under 45, the next response is text only. Do not edit. The last verify will submit, and it will heredoc first if git diff is empty.

If git diff is already non-empty, the next response is text only. Do not edit again. Never revert a non-empty source diff. Do not replace those bytes and do not restore the file.

If git diff is empty and time_seconds_remaining is 45 or more, the next call can be the one heredoc below, then the text report. One edit only. Do not make that edit only because the clock passed 240. If agent_elapsed_seconds is about 240 or more and git diff is empty, continue only when you already know the line to change. Otherwise hand off.

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

The helper asserts and runs ast.parse before any write. Only after that succeeds it saves this PATH under /tmp, then writes PATH. If python /tmp/line_fix.py fails before that save, PATH was not written. Do not restore it. If py_compile fails, the helper copies that /tmp backup back onto PATH and onto no other file. Do not restore again. One smaller edit is allowed. Never run git checkout. A failed assert or ast.parse must not revert an earlier edit of PATH.

Keep OLD and NEW free of backslashes and triple quotes. Do not touch protected paths. Scratch files stay under /tmp.

Return a report under 80 words. Start with round: 3. Say whether git diff is non-empty. That report is the only reply with no tool call.
