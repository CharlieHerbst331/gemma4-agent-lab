---
name: verify-patch
description: Create and rerun assertion-based scratch repros with real exit statuses and import origins, then audit patch syntax, protected files, test edits, whitespace, and untracked artifacts before finalization.
---
Run scripts/check.py with run_skill_script. Always pass skill_name and file_path.
Exact call: skill_name "verify-patch", file_path "scripts/check.py", args as one
JSON object of scalar strings. The outer ADK envelope can say warning even when
the child check fails. Use the JSON passed and exit_code fields.

Examples:
- audit: {"mode":"audit"}
- before: {"mode":"repro","phase":"before","code":"<python with assert>","timeout":"20"}
- same script again: {"mode":"repro","phase":"verify","timeout":"20"}
- read the pinned script: {"mode":"repro","phase":"read"}
- extra edge case: {"mode":"repro","phase":"probe","code":"<python with assert>","timeout":"20"}

Supplying code writes ONLY gemma-agent-repro.py under sandbox TEST_TMPDIR (outside
the repo). Omit code on after/verify to reuse that script. The helper pins the
before script hash and rejects changed assertions. phase probe uses a separate
scratch file and never replaces the baseline. Code must contain assert and must
not catch AssertionError, Exception, BaseException, or use a bare except.

The repro child sets PYTHONPATH to the workspace root plus workspace/src and does
not use python -I or python -E. JSON import_origin is that environment.
default_import_origin repeats the same imports with PYTHONPATH set to the workspace
root only, which is the sandbox default (no editable install). WORKSPACE means
module.__file__ is under the workspace. INSTALLED-COPY means the host copy was
imported. imports_installed_copy is true when the repro environment itself imported
a host copy. A passing exit code against INSTALLED-COPY is not evidence about the
edit. Do not trust pip show, pip list, or importlib.metadata.version.

Nonzero exit, timeout, or blocked import is not a pass. The helper keeps the real
exit status, kills the process group, limits output to 1 MiB, rejects a check that
mutates the patch, and returns repro/patch SHA256 fingerprints. Expected before-fix
failure has passed=false. Missing imports are flagged blocked. No installs.

Scratch files go only in TEST_TMPDIR, top-level /workspace/build/, or /tmp.
Untracked build/ and dist/ directories at any depth, and .adk_exec_*.py, are
excluded from the patch. Never create a real source file under a nested build/ or
dist/ directory.

Audit args: {"mode":"audit"}. It parses changed Python without importing it, checks
whitespace, flags untracked files (except the live official executor wrapper), and
flags grading's protected set: any conftest.py, any test_*.py, anything under tests/
or test/, and pytest.ini, pyproject.toml, or setup.cfg at any depth. It never
deletes, edits, stages, or submits. Audit passing means hygiene only
(behavior_verified=false). Before submission, a passing verify check's patch_sha256
must match the latest audit. Any edit invalidates prior check evidence.

Run check scripts sequentially. Finish other skill scripts before auditing so a live
executor file does not look like contamination. This script does not submit.
