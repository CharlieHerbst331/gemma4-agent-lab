---
name: verify-patch
description: Create and rerun assertion-based scratch repros with real exit statuses and import origins, then audit patch syntax, protected files, test edits, whitespace, and untracked artifacts before finalization.
---
Run scripts/check.py with run_skill_script. skill_name, file_path, and args are
top-level. Never put skill_name or file_path inside args. One full call:
{"skill_name":"verify-patch","file_path":"scripts/check.py","args":{"mode":"repro","phase":"before","code":"assert True","timeout":"20"}}
args is one JSON object of scalar strings. If a tool returns the same error twice, do not repeat that call. Switch to run_command or edit_file. Use edit_file when
the role has no run_command. The outer ADK envelope
can say warning even when the child check fails. Use the JSON passed and exit_code
fields. If --mode is omitted, check.py defaults to repro. The harness error
INVALID_ARGUMENTS ('Argument file_path is required') is raised before this script
runs when file_path is missing at the top level. That text is not produced here.

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

The repro child sets PYTHONPATH to /workspace/src first, then the workspace root
(/workspace/src:/workspace), and does not use python -I or python -E. That is the
same order the repair prompt uses after an INSTALLED-COPY probe. JSON import_origin
is that environment. default_import_origin repeats the same imports with PYTHONPATH
set to the workspace root only, which is the sandbox default (no editable install),
not a second ordering. The origin probe uses python -P so the workspace cwd does
not jump ahead of that PYTHONPATH. -P is not python -I or python -E. WORKSPACE means
module.__file__ is under the workspace. INSTALLED-COPY means the host copy was
imported. imports_installed_copy is true when the repro environment itself imported
a host copy. A passing exit code against INSTALLED-COPY is not evidence about the
edit. Do not trust pip show, pip list, or importlib.metadata.version.

Nonzero exit, timeout, or blocked import is not a pass. The helper keeps the real
exit status, kills the process group, limits output to 1 MiB, rejects a check that
mutates the patch, and returns repro/patch SHA256 fingerprints. Expected before-fix
failure has passed=false. Missing imports are flagged blocked. No installs.

Scratch files go only in TEST_TMPDIR, top-level /workspace/build/, or /tmp.
Never write repro.py or any repro*.py inside the repo.
Untracked build/ and dist/ directories at any depth, and .adk_exec_*.py, are
excluded from the patch. Never create a real source file under a nested build/ or
dist/ directory.

Audit args: {"mode":"audit"}. It parses changed Python without importing it, checks
whitespace, flags untracked files (except the live official executor wrapper), and
flags grading's protected set: conftest.py, pytest.ini, pyproject.toml, tox.ini,
setup.cfg, .pytest.ini, sitecustomize.py, usercustomize.py, _swegemma_stubs.py,
any .pth file, test_*.py, *_test.py, and any .py file under a tests, test, or
testing directory (those directory names are case-insensitive). A non-Python file
under those directories is not protected. It never
deletes, edits, stages, or submits. Audit passing means hygiene only
(behavior_verified=false). Before submission, a passing verify check's patch_sha256
must match the latest audit. Any edit invalidates prior check evidence.

Run check scripts sequentially. Finish other skill scripts before auditing so a live
executor file does not look like contamination. This script does not submit.
