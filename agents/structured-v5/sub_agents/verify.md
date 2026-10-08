Verify this issue from the repair report and the skill output, not from the repairer's confidence.
{problem_description}

Hints, if the harness supplied any:
{hints?}

Triage brief:
{triage_brief}

Repair report:
{repair_report}

The loop allows 3 iterations and has no exit tool. Using all 3 without a submission
restarts triage. Read loop_iteration from the repair report. If it is missing, use 1.
This is the last iteration when loop_iteration is 3 or greater, or when get_status
shows time_seconds_remaining under 40.

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

Start with get_status, then audit, then phase verify with no code argument so the
pinned script is reused. Use the child JSON passed and exit_code, not the outer
skill envelope. passed true with imports_installed_copy true is not a pass.
default_import_origin INSTALLED-COPY means a raw python command would import the
host copy; the skill result is the one that counts only when import_origin says
WORKSPACE.

Scratch files go only in top-level /workspace/build/ or /tmp. Untracked build/ and
dist/ directories at any depth, and .adk_exec_*.py, are excluded from the patch.
Never create a real source file under a nested build/ or dist/ directory. Do not
create files. The repro already lives outside the workspace.

If audit lists a protected path (conftest.py, test_*.py, tests/, test/, pytest.ini,
pyproject.toml, setup.cfg), revert that edit with edit_file when you still have the
original text, then continue. Do not edit tests to make a check pass.

Submission rules: edits after the last submit_patch are dropped, so any edit_file
must be followed by another submit_patch. A text reply after a submission ends the
task. submit_patch must be your last tool call.

- If this is not the last iteration and the verify check passed, import_origin is
  WORKSPACE or the repro imports nothing outside the stdlib, and a fresh audit
  matches that check's patch_sha256: call submit_patch and stop. Do not keep looking.
- If this is not the last iteration and the check failed, do not call submit_patch.
  Reply with a concrete failure and stop: loop_iteration, file, assertion, exit code,
  and the one change repair should make. No other tool after that reply.
- If this is the last iteration, call submit_patch as your last tool even when the
  check failed or the diff is empty. Do not wait for another repair pass.

An empty clean patch is correct when the issue gave no behavior clue. Do not claim
the issue is fixed unless the workspace check passed. No network, no reference
patches, no grading files.
