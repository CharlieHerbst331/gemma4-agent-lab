---
name: verify-patch
description: Create and rerun assertion-based scratch repros with real exit statuses, then audit patch syntax, protected files, test edits, whitespace, and untracked artifacts before finalization.
---
Run scripts/check.py with run_skill_script. Use the JSON result's passed/exit_code
fields; the outer ADK skill envelope can say warning even when the child check fails.

Repro args: mode="repro", phase="before"/"after"/"verify"/"read"/"probe", optional code as
a Python string, timeout integer 1-30 (default 20). Supplying code writes ONLY the
fixed scratch gemma-agent-repro.py under sandbox TEST_TMPDIR; omit code to reuse the
SAME script. phase="read" returns its bounded source for assertion review. The helper pins the before script's hash to this task and rejects changed assertions
in after/verify (even if edited through another tool). Do not replace the baseline
check. Use phase="probe" with code for an additional edge-case check; it uses a
separate scratch file and never replaces the baseline repro. Code requires
assertions and rejects caught AssertionError, broad Exception/BaseException, or bare
except handlers. This catches common false passes; it does not prove assertions
are meaningful or executed on the right behavior. Check the code and workspace
imports (module.__file__) when uncertain. Include an ordinary/boundary assertion.

Nonzero exit, timeout, or blocked import is not a pass. The helper preserves actual
exit status, kills its process group on timeout/completion, limits log/file output to 1 MiB, rejects a check that mutates the patch, stores a bounded log and
last four results outside the workspace, and returns repro/patch SHA256 fingerprints.
Expected before-fix failure still has passed=false: confirm it matches the issue,
not a setup error. Missing imports are separately flagged blocked. No installs.

Audit args: mode="audit". It parses changed Python without importing it, checks
whitespace, flags any untracked file (except the exact live official executor wrapper),
root pytest.ini/conftest.py changes, repository test edits, and escaping symlinks.
It never deletes, edits, stages, or submits files. Clean up only agent-created scratch
or unsupported changes using existing tools, then audit again. Intentional new
implementation files require manual review; this conservative audit blocks them.

Audit passing means hygiene/syntax ONLY (behavior_verified=false). Before submission,
a passing after/verify check's patch_sha256 must match the latest audit. Any edit
invalidates prior check evidence. Review for debug additions/API regressions too:
the script cannot determine semantic correctness. Record compact facts in task-memory,
then call submit_patch immediately as the last tool action. Skill invocation remains
model-controlled; this script is not a hard scheduler or automatic submission hook.

Run check/audit scripts sequentially; they share scratch/check state. Finish other
skill scripts before auditing so live executor files do not cause false contamination flags.
