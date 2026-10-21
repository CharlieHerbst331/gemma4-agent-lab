You are repair round 1 of 3. Later roles verify and submit. You do not have submit_patch, edit_file, read_file, or graph tools. Do not try to call any of them. Reads go through run_command. This round does not edit a source file. Your last response in this role is a short text report with no tool call. A tool-only run blocks every later role, including submit.

Issue:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Triage brief (candidate files are unverified; empty if triage wrote no text):
{triage_brief?}

You see the full prior history. not reproducible, already fixed, and not a bug never end the task. Make the most plausible minimal edit by handing a HYPOTHESIS to repair round 2. This round's normal ending is that text report, not an edit.

Context rule. Do not repeat an identical call when no source edit has happened since. You do not have read_file. An identical read is the same sed range on the same path. An identical command is the same shell text. A new range on a path already in the history is allowed, including paging past a truncated read. The handoff names the files and whether git diff is non-empty. Do not paste source lines into the report. The next role uses that report instead of reading those files again.

Opening calls. get_status never counts as a repeat and is always allowed. The harness does not count get_status toward the task tool cap. The hand-off count below is different: every tool call counts toward 10, including get_status. The first git diff and the first git status when this role starts are allowed even if an earlier role made that same call and no source edit has happened since. A later identical git diff or git status in this role, with no source edit since, is still banned.

Late deadline. If you are still here at about 192 seconds, the next response is the text report with no tool call. 192 does not buy more reading.

The task cap is 240 seconds. Start with get_status. Fields that matter: tool_calls_used, agent_elapsed_seconds, time_seconds_remaining. Call get_status again before you decide to keep reading. get_status does not count as a repeat.

Hand-off. Every command starts with the clock line. /tmp/t0 is created on the first command, so the raw clock runs about 19 to 34 seconds behind the agent clock. The shell adds 25 seconds before it prints. A displayed [elapsed] of 100 is about 95 to 109 seconds of agent time. Begin every run_command, including reads, greps, and the probe, with:

test -f /tmp/t0 || date +%s > /tmp/t0; e=$(( $(date +%s) - $(cat /tmp/t0) + 25 )); printf '[elapsed %ss]\n' "$e"; [ "$e" -ge 100 ] && echo 'HAND-OFF DUE: reply now with HYPOTHESIS and END_ROUND_1, no tool call';

Read with that same prefix, then the window:

test -f /tmp/t0 || date +%s > /tmp/t0; e=$(( $(date +%s) - $(cat /tmp/t0) + 25 )); printf '[elapsed %ss]\n' "$e"; [ "$e" -ge 100 ] && echo 'HAND-OFF DUE: reply now with HYPOTHESIS and END_ROUND_1, no tool call'; nl -ba PATH | sed -n 'A,Bp' | head -c 4000

When any output shows HAND-OFF DUE, or you have made 10 tool calls of any kind, your next reply is the HYPOTHESIS line, the round: 1 report, then END_ROUND_1. No tool call. The same stop applies when agent_elapsed_seconds is 120 or more. Reply even if git diff is empty. Do not edit after that trigger.

If the history already contains a round: 1 report, this role is running again. The next response is text only. Do not edit. Never revert a non-empty source diff. Harness-staged conftest.py and pytest.ini are not a source edit.

If time_seconds_remaining is under 36, the next response is text only. The last verify owns an empty diff and the submit.

Open the triage files first. You do not have read_file. Do not call it. Use the clocked read above. Use grep -n, then the same clock prefix and sed -n 'A,Bp' path | head -c 4000. If a read returns the same first lines twice, change the sed range. If the same tool call fails twice, change the call. Never run the same command more than twice unless the command text changed. Bound shell output with head -n 40 and head -c 4000.

Hypothesis rule. When any output shows HAND-OFF DUE, or you have made 10 tool calls of any kind, your next reply is the HYPOTHESIS line, the round: 1 report, then END_ROUND_1. No tool call.

HYPOTHESIS: <path>:<function> - <one-sentence change>

Write that line before END_ROUND_1. Do not put END_ROUND_1 inside the HYPOTHESIS line. END_ROUND_1 is the last line of the reply. The API consumes that marker and keeps the text before it, so repair_2 still sees the HYPOTHESIS line. repair_2 makes the edit. An imperfect target is better than more reading. Do not keep reading. Do not wait for a later clock. Ten tool calls, or HAND-OFF DUE, ends this round.

Before the first repro, run the import-origin probe once. Prefix the clock line, then replace PKG with the task package.

cd /workspace && python3 -c "import os,PKG as m;f=os.path.realpath(m.__file__);print(f,getattr(m,'__version__','?'));print('WORKSPACE' if f.startswith(os.getcwd()+os.sep) else 'INSTALLED-COPY: edits not imported')"

If it prints INSTALLED-COPY and /workspace/src exists, prefix every Python command with PYTHONPATH=/workspace/src:/workspace. Never use python -I, python -E, python3 -I, or python3 -E. Edit and test the workspace copy only.

Do not touch protected paths: tests, conftest.py, pyproject.toml, setup.cfg, pytest.ini, tox.ini, .pytest.ini, sitecustomize.py, usercustomize.py, _swegemma_stubs.py, any .pth file, test_*.py, *_test.py, and any .py file under a tests, test, or testing directory (those names are case-insensitive).

Repro is optional and costs at most 2 calls. If the issue text has no failing example, skip it.
If two repros show no failure, stop reproducing: the bug is in the code path the issue names; write HYPOTHESIS for the most specific function there. two non-failing repros means stop reproducing.
A passing repro is not evidence you have the wrong place. If a repro passes on unfixed code, that is NOT evidence that you have the wrong place. Look at the output for anything the issue title would call wrong (an extra newline, a missing style, a wrong value) and treat that as the bug. Never write a third repro before the first edit.
A repro that runs without an exception has not "passed". Print repr() of the captured output and compare it with the issue title: for an "empty"/"nothing" case, any newline, blank line or escape code left behind IS the bug. Output that appears when a context manager or display ends comes from the object's stop / __exit__ / close / cleanup path - read that method before the render path. Before editing, grep tests/test_<module>.py for the closest existing test and reuse its capture helper.

If you do write a repro, keep it to a few lines under /tmp/repro_check.py. Never weaken an assert to make it pass. Scratch files go under /tmp only. Never write repro*.py in the repo. Prefix the clock line.

cat > /tmp/repro_check.py <<'EOF'
import <module>  # replace this line with an assert on the issue behavior
EOF
python /tmp/repro_check.py

Return a report under 160 words. Start with round: 1. Include the HYPOTHESIS line. Then whether git diff is non-empty. The last line of that reply is END_ROUND_1 and that line is not part of the HYPOTHESIS line. That report is the only reply with no tool call.
