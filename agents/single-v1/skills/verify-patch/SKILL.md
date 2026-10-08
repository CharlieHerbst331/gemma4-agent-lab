---
name: verify-patch
description: Create and rerun assertion-based scratch repros, report whether imports resolve inside the workspace, and audit patch syntax, grading-protected paths, whitespace, and untracked artifacts before finalization.
---
Run scripts/check.py with run_skill_script. skill_name="verify-patch" and
file_path="scripts/check.py" are required. Use the JSON result's passed/exit_code
fields; the outer ADK skill envelope can say warning even when the child check fails.

Audit args: {"mode":"audit"}. It parses changed Python without importing it, checks
whitespace, flags any untracked file (except the exact live official executor wrapper),
and flags grading's protected set: nested conftest.py, test_*.py, any path under
tests/ or test/, and pytest.ini, pyproject.toml, or setup.cfg at any depth. It also
flags escaping symlinks. It never deletes, edits, stages, or submits files.

Repro args: {"mode":"repro","phase":"before","timeout":20,"code":"<python with assert>"}.
phase is before, after, verify, read, or probe. timeout is an integer 1-30 (default 20).
Supplying code writes ONLY the fixed scratch gemma-agent-repro.py under sandbox
TEST_TMPDIR; omit code to reuse the SAME script. phase="read" returns its bounded
source for assertion review. The helper pins the before script's hash to this task
and rejects changed assertions in after/verify. Do not replace the baseline check.
Use phase="probe" with code for an additional edge-case check; it uses a separate
scratch file and never replaces the baseline repro. Code requires assertions and
rejects caught AssertionError, broad Exception/BaseException, or bare except handlers.

Executed phases add import_origin: up to four local top-level modules, each with
module, file, and verdict WORKSPACE, INSTALLED-COPY, UNKNOWN, or ERROR. The child
uses PYTHONPATH=<workspace>/src:<workspace> and does not use python -I or python -E.
imports_outside_workspace true means at least one module resolved outside the
workspace, and passed is false even when the exit code is 0. Empty import_origin
means the repro did not import a package that lives in the tree. Do not treat
pip show or installed versions as the origin; trust module.__file__.

Nonzero exit, timeout, blocked import, or INSTALLED-COPY is not a pass. The helper
preserves actual exit status, kills its process group on timeout/completion, limits
log/file output to 1 MiB, rejects a check that mutates the patch, stores a bounded
log and last four results outside the workspace, and returns repro/patch SHA256
fingerprints. Expected before-fix failure still has passed=false: confirm it matches
the issue, not a setup error. Missing imports are separately flagged blocked. No installs.

Scratch for this script stays in TEST_TMPDIR, outside the repo. Any other scratch
file goes only in top-level /workspace/build/ or /tmp. Never create real source
files under a nested build/ or dist/ directory; untracked build/ and dist/ paths
are omitted from the patch. Clean up only agent-created scratch or unsupported
changes using existing tools, then audit again. Intentional new implementation
files require manual review; this conservative audit blocks them by listing them
as untracked.

Audit passing means hygiene/syntax ONLY (behavior_verified=false). Before submission,
a passing after/verify check's patch_sha256 must match the latest audit. Any edit
invalidates prior check evidence. Resubmit after every edit. submit_patch is the
final action. Review for debug additions/API regressions too: the script cannot
determine semantic correctness. Record compact facts in task-memory, then call
submit_patch immediately as the last tool action. Skill invocation remains
model-controlled; this script is not a hard scheduler or automatic submission hook.

Run check/audit scripts sequentially; they share scratch/check state. Finish other
skill scripts before auditing so live executor files do not cause false contamination flags.
