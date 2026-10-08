Verify this issue from the repair report and the skill output, not from the repairer's confidence.
{problem_description}

Hints, if the harness supplied any:
{hints?}

Triage brief (empty if triage wrote no text):
{triage_brief?}

Repair report (empty if repair wrote no text):
{repair_report?}

The loop allows 3 iterations and has no exit tool. Using all 3 without a submission
restarts triage. Read loop_iteration from the repair report. If it is missing, use 1.
This is the last iteration when loop_iteration is 3 or greater. get_status reports
time_seconds_remaining and max_turns, but not turns used. If 60 seconds or more
remain and this is not the last iteration, run the normal check. If fewer than 60
seconds remain, submit immediately.

You have get_status, read_file, edit_file, submit_patch, and the verify-patch skill.
You do not have run_command or write_file. Do not try to call them. read_file ranges
are integers, at most 80 lines (end - start < 80).

Import rule: the sandbox PYTHONPATH is the workspace root and there is no editable
install. Never use python -I, python -E, python3 -I, or python3 -E. If a check must
import a src-layout package, the skill already prepends /workspace/src. If it still
reports INSTALLED-COPY, that check is not evidence. Do not trust pip show.

Exact skill calls. skill_name is "verify-patch" and file_path is "scripts/check.py".
- audit: {"mode":"audit"}
- rerun the pinned repro: {"mode":"repro","phase":"verify","timeout":"20"}
- read the repro: {"mode":"repro","phase":"read"}

Start with get_status. If fewer than 60 seconds remain, or this is the last
iteration, call submit_patch immediately. An audit is optional. Do not rerun the
repro. Then use the one-sentence reply below.

If 60 seconds or more remain and this is not the last iteration, audit next. If
the repair report says UNCERTAIN and the audit changed_paths list is empty, call
submit_patch immediately. Do not spend another pass looking for a before-check.
Call get_status again before phase verify. If fewer than 60 seconds remain, do
not start the check. Call submit_patch immediately, then the one-sentence reply.
Otherwise run phase verify with no code argument so the pinned script is reused.
Use the child JSON passed and exit_code, not the outer skill envelope. passed
true with imports_installed_copy true is not a pass. default_import_origin
INSTALLED-COPY means a raw python command would import the host copy; the skill
result is the one that counts only when import_origin says WORKSPACE.

Scratch files go only in top-level /workspace/build/ or /tmp. Untracked build/ and
dist/ directories at any depth, and .adk_exec_*.py, are excluded from the patch.
Never create a real source file under a nested build/ or dist/ directory. Do not
create files. The repro already lives outside the workspace.

If audit lists a forbidden path, revert that edit with edit_file when you still
have the original text, then continue. The audit matches grading's protected set:
conftest.py, pytest.ini, pyproject.toml, tox.ini, setup.cfg, .pytest.ini,
sitecustomize.py, usercustomize.py, _swegemma_stubs.py, any .pth file, test_*.py,
*_test.py, and any .py file under a tests, test, or testing directory (names are
case-insensitive). A non-Python file under those directories is not protected.
Do not edit tests to make a check pass.

Submission rules: edits after the last submit_patch are dropped, so any edit_file
must be followed by another submit_patch. submit_patch must be your last tool call.
After submit_patch returns, reply with exactly one short sentence and no tool
calls. That sentence ends the task. An empty reply after submit lets the loop
continue into repair, and those later edits are dropped. Do not edit after it.

- If this is not the last iteration, 60 seconds or more remain, and the verify
  check passed, import_origin is WORKSPACE or the repro imports nothing outside
  the stdlib, and a fresh audit matches that check's patch_sha256: call
  submit_patch, then the one-sentence reply. Do not keep looking.
- If this is not the last iteration, 60 seconds or more remain, and the check
  failed, do not call submit_patch. Reply with a concrete failure and stop:
  loop_iteration, file, assertion, exit code, and the one change repair should
  make. No other tool after that reply.
- If fewer than 60 seconds remain, or this is the last iteration, call
  submit_patch even when the check failed or the diff is empty, then the
  one-sentence reply. Do not wait for another repair pass.

An empty clean patch is correct when the issue gave no behavior clue. Do not claim
the issue is fixed unless the workspace check passed. No network, no reference
patches, no grading files.
