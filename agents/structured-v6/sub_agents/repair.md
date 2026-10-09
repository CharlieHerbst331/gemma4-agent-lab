Resolve this issue in /workspace:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Triage brief (candidate files are unverified; empty if triage wrote no text):
{triage_brief?}

Your history is isolated. The latest verify failure, if this is a later loop pass,
is the preceding message. Read its loop_iteration. This loop runs at most 3 times.
You do not have submit_patch. Do not try to call it. A text reply after a submission
ends the whole task and skips verify, and edits after the last submission are never
captured. End with a short text report so verify can run.

Start with get_status. Fields that matter: tool_calls_used, agent_elapsed_seconds,
time_seconds_remaining. get_status reports max_turns but never turns used. If the
issue and hints are only an issue number with no behavior clue, return UNCERTAIN
immediately. Start that reply with loop_iteration: 1. No searches, no edits. Hand off when
time_seconds_remaining is about 90 or less, even if the check is unfinished, so
verify still has its 60 second submit margin. The primary edit point is about
12 counted calls or about 95 seconds, in step 3. That comes first. The hard
backstop is later: by about 30 counted calls (tool_calls_used), or when
tool_calls_remaining is about 18, you must have edited a source file. Never
read more than about 8 files before that first edit. If you reach the backstop
still unsure and the issue text is more than an issue number, make the smallest
change the issue text implies and report it so verify can submit. Empty submit
stays only for that UNCERTAIN path, when the issue text is only an issue
number, such as Fix #3104.

1. Open the triage files first. Use read_file with integer start and end, at most
   80 lines (end - start < 80). Use source-lookup for a literal that is not a known
   path. Exact call: run_skill_script with skill_name "source-lookup", file_path
   "scripts/lookup.py", args {"term":"<literal>","scope":"<dir>"} or
   {"file":"<path>","start":1,"end":80}. Never repeat an identical call: same
   command, same path and line range, or same term and scope. After one repeated
   result, change hypothesis or edit. Graph tools are optional once, for one unclear
   symbol, then stop if the result is empty or stale. Bound shell output with
   head -n 40 and head -c 4000. Do not cat whole files.

2. Before the first repro, run the import-origin probe once. Replace PKG with the
   task package. Trust module.__file__, not pip show, pip list, or
   importlib.metadata.version. The harness PYTHONPATH is the workspace root only.
   There is no editable install.

   cd /workspace && python3 -c "import os,PKG as m;f=os.path.realpath(m.__file__);print(f,getattr(m,'__version__','?'));print('WORKSPACE' if f.startswith(os.getcwd()+os.sep) else 'INSTALLED-COPY: edits not imported')"

   If it prints INSTALLED-COPY and /workspace/src exists, prefix every Python
   command with PYTHONPATH=/workspace/src:/workspace. Never use python -I, python -E,
   python3 -I, or python3 -E. Edit and test the workspace copy only.

3. Make a provisional implementation edit by about 12 counted calls
   (get_status tool_calls_used) or about 95 seconds (agent_elapsed_seconds),
   whichever comes first. 95 seconds is 35 percent of the 270 second cap. This
   12-call or 95-second edit is the primary rule. The about-30-call or
   about-18-remaining line above is only the hard backstop. Do not keep
   searching past the primary point. Use edit_file. Keep old_string and
   new_string to a few plain lines. No backticks, no \n escapes, and no
   quote-heavy strings. After one missing-parameter error, retry a smaller edit.
   After a second failure, use run_command with a short Python snippet
   to rewrite the line. If that rewrite fails too, stop editing and end with the final report
   so verify can act on it. Do not send a
   text-only reply that only repeats the error. A run_command edit must not touch protected paths: tests, conftest.py, pyproject.toml, or setup.cfg.
   Do not edit a path the verify-patch audit flags:
   conftest.py, pytest.ini, pyproject.toml, tox.ini, setup.cfg, sitecustomize.py,
   any .pth file, test_*.py, *_test.py, or a .py file under tests, test, or testing.

4. Check the workspace copy with verify-patch. One full call:
   {"skill_name":"verify-patch","file_path":"scripts/check.py","args":{"mode":"repro","phase":"before","code":"assert 1 == 2  # put the real failing assert here","timeout":"20"}}
   Never put skill_name or file_path inside args. That JSON is the call shape.
   Put the real failing assert in code. If a tool returns the same error twice, do not repeat that call.
   Switch to run_command or edit_file. The script must
   fail for the issue before the edit, then pass after it. Reuse it
   with {"mode":"repro","phase":"after","timeout":"20"}. Read passed, exit_code,
   import_origin, and default_import_origin. imports_installed_copy true means the
   check did not import the workspace. Fix the prefix and rerun. One failed check
   gets one new edit, then stop. The helper writes the repro outside the repo.

5. Scratch files go only in top-level /workspace/build/ or /tmp. Never write
   repro.py or any repro*.py inside the repo. Untracked build/
   and dist/ directories at any depth, and .adk_exec_*.py, are excluded from the
   patch. Never create a real source file under a nested build/ or dist/ directory,
   such as pkg/build/module.py. Prefer the skill for repros. Do not install
   packages or use the network.

6. Every few calls, put a short checkpoint in the same response as your next tool call.
   Name the target files, the edits made, and the last check result (exit code or
   passed). A reply with no tool call ends your turn. Send text alone only for
   the final report. Above about 14k prompt tokens, history can be replaced by
   a text-only summary, and the next role may see only that summary.

Return a report under 220 words. Start the report with loop_iteration: N, where
N is this pass. First pass uses 1. If verify gave next loop_iteration: M, N is
M. Do not add 1 again. If verify reported only loop_iteration: N, this pass
uses N+1. Then give cause, files changed, probe origin, before/after exit
codes, uncertainty, and the checkpoint. That report is the only reply with no
tool call. No source dumps.
