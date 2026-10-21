# structured-v16

Unevaluated copy of structured-v13-1. The directory is `agents/structured-v16`
and the agent name is `structured_v16`. It is not a copy of structured-v14 or
structured-v15. Existing agent directories were not modified. No score is
claimed. No GPU run and no submission. The smoke notebook was not executed.

## Hypothesis

The never-edit deep dive (9 runs of rich_3105, rich_3934, and rich_3938 on
v13-1, v14, and v15) found every run still empty at about 302 seconds, all
of it inside triage plus repair_1. The repro-first rule treated a passing
repro as "wrong place." The clock was checked 0 or 1 times, so the 180
second text stop never fired. Later roles, which already heredoc an empty
diff, never got a turn.

The change is prompt text only. A repro is optional and costs at most 2
calls. A passing repro is not evidence of the wrong place. After at most 4
file reads the model writes `HYPOTHESIS: <path>:<function> - <change>` and
the next call is the guarded heredoc. repair_1 hands off at 150 seconds
even when the diff is empty. repair_2's first counted call edits that
target when the diff is still empty. verify_3 submits at 250 seconds and
skips the check. The 4-read rule does not need the clock. The clock rules
are the fragile half: those 9 runs barely called `get_status`, and v15's
`[elapsed]` prefix was on 62 of 256 `run_command`s.

This is a hypothesis. The deep dive's expected effect is judgment on one
run per version, not a measurement: rich_3934 is the task that might
resolve, rich_3105 and rich_3938 can become non-empty and still fail the
hidden tests. fastapi_11194's first edit was at 232 seconds in v13-1 and
209 seconds in v15, so a 150 second hand-off cuts that exploration inside
repair_1. The HYPOTHESIS line is what repair_2 is told to edit. No cohort
was run.

## What changed

Repair round 1 is already one pass. `agent.yaml` lists
`sub_agents/repair_1.yaml` directly. That file is an `LlmAgent`. There is
no `LoopAgent` and no `max_iterations`. A loop of 1 would still run the
child to completion, and `max_iterations` does not interrupt a child that
keeps calling tools. The hand-off is the text report. After the heredoc,
the prompt says the next response is that report.

The map skill was not ported. That is the smallest change: Testing's plan
adds no tools, and triage stays the v13-1 tool-free brief. v14 at 3 of 13
and v13-1 at 4 of 13 is one task on n=13. That is noise, the same way
structured-v8 is 0.10 and 0.13 on one archive. It is not evidence for
dropping the map.

Caps stay 300 seconds, 220 calls, and 320 turns. The heredoc still asserts
`s.count(old) == 1` and parses before it writes. `get_status` never counts
as a repeat. The empty-diff net stays on verify_3.

## Clock reconciliation

On a 300 second cap, `time_seconds_remaining` under 120 is about 180
seconds elapsed. The 150 second hand-off is still the stop when repair_1
notices the clock. If it is still running, the diff is empty, and between
45 and 120 seconds remain, it writes the HYPOTHESIS line and the next call
is the heredoc. That is the missed-hand-off net. repair_1 never returning
is the common case in the deep dive, so later roles' nets do not cover it.
Repair round 2 still edits an empty diff first and does not wait for the
under-120 line. If no HYPOTHESIS line exists, that edit uses the first file
and function named in the triage brief or the round 1 report.

| Clock | Who | What |
| --- | --- | --- |
| 4 file reads, elapsed under 150 | repair_1 | `HYPOTHESIS` with no tool call, then the heredoc, then the text report |
| about 90 seconds, or about 38 calls, still under 150, no edit yet | repair_1 | same hypothesis and heredoc, even with fewer than 4 reads |
| elapsed >= 150, and remaining still above 120 | repair_1 | text report, including `HYPOTHESIS`, even if the diff is empty. No heredoc. Replaces the 180 second stop |
| still in repair_1, diff empty, remaining under 120 and at least 45 | repair_1 | write `HYPOTHESIS`, then the heredoc. The missed-hand-off net. About 180 to 255 seconds elapsed |
| about 240, and a source edit exists, and repair_1 is still running | repair_1 | text report. Does not extend the round |
| remaining under 45 while repair_1 is still running | repair_1 | text only. The missed-hand-off heredoc does not run |
| repair_2, diff empty, remaining >= 45 | repair_2 | first counted call is the heredoc on the HYPOTHESIS target, or the first file and function in triage or the round 1 report if that line is missing. `get_status` does not count. One 40-line window only if the assert fails, then one retry |
| repair_2, diff non-empty, or elapsed about 240 with a source edit | repair_2 | text only. Do not revert. 240 does not delay the empty-diff edit |
| repair_2, remaining under 45 | repair_2 | text only. verify_3 owns the empty diff |
| verify_3, elapsed >= 180, diff non-empty, remaining above 90 | verify_3 | the check, then submit. Unchanged |
| verify_3, about 240, diff non-empty, remaining not above 90 | verify_3 | stop investigating, then submit. Unchanged |
| verify_3, elapsed >= 250, diff non-empty | verify_3 | `submit_patch` now. Skip the check. About 50 seconds remain, so this overrides "the check is required whenever 45 seconds or more remain" |
| verify_3, elapsed >= 250, diff empty | verify_3 | one heredoc, then `submit_patch`, no check. The empty-diff net still runs |
| remaining under 120, diff empty, before 250 | repair_3 and verify_3 | the heredoc still applies. repair_2 does not wait for this line |

verify_1 no longer tells repair_2 to wait for remaining under 120.

## Runtime math

v8 smoke5 model turns, cited from `docs/STRUCTURED_V15.md` and not
remeasured here: median 3.9 seconds, mean 6.6 seconds, p90 13.8 seconds.
Text-only gaps are median about 5 seconds.

There is no leftover loop. After repair_1 returns, five roles remain:
verify_1, repair_2, verify_2, repair_3, verify_3. Each of those roles
starts with `get_status`, then still has to answer, so the floor is two
turns per role, 10 turns, not one. An empty diff adds repair_2's heredoc
and at most one retry, about two more turns, 12 in all.

- Median: `10 * 3.9 = 39` seconds, `12 * 3.9 = 46.8` seconds.
- Text-only median: `10 * 5 = 50` seconds, `12 * 5 = 60` seconds.
- Mean: `10 * 6.6 = 66` seconds, `12 * 6.6 = 79.2` seconds.
- p90: `10 * 13.8 = 138` seconds, `12 * 13.8 = 165.6` seconds.

If repair_1 hands off at 150 seconds, verify_3 starts near 189 to 197
seconds at the median and 216 to 229 seconds at the mean. The check is
another 1 to 3 turns, about 10 to 20 seconds, so a submit around 215 to
260 seconds is inside the 300 second cap at the median and the mean. At
the p90 the same floor is 138 to 166 seconds, so verify_3 starts near 288
to 316 seconds and is often already past the cap. A role that keeps
calling tools is still not interrupted. The 250 second submit is the
backstop when verify_3 does run, not a guarantee that it runs. If repair_1
never returns, verify_3 is not reached. That is the v8 smoke5 pattern and
the deep dive's 9 runs.

The internal 120-task block is `120 * (mean + 70) <= 39600`, so the mean
must be at most 260 seconds. `120 * ((300 + 8) + 70) = 45360`, which
fails. v13-1's dev-13 mean of 279.6 seconds fails it
(`120 * (279.6 + 70) = 41952`). The deep dive's judgment, not a v16 run:
if capped tasks submit by about 240 to 270 seconds, the mean is about 255
to 265 seconds, which is borderline. The 250 second submit is there so the
check does not fill that last minute. None of this is a v16 measurement.
The host limit is 12 hours total. An upload whose mean is above 260
seconds still needs the uploader override.

## Smoke notebook

`notebooks/structured-v16-smoke7.ipynb` lists rich_3934, rich_3105,
rich_3938, rich_3472, rich_3944, fastapi_11194, and rich_3454. Those ids
are not under `agents/`. `compile_plain` calls `compile_submission` with
no callback registry. The report cell reads `task_results.jsonl` and trace
JSON and prints resolved count, per-task wall time, no-edit runs, calls to
the first edit, whether `HYPOTHESIS:` appeared, whether repair_1 returned
before the 300 second cap, and the elapsed time of that hand-off. It does
not delete traces. It was not run.

## Archive

SHA256 `6b8920c396f4e84fe14e7b7a907c1771436a55b840fae7464b3ce6f7cac13491`.
20 files. Portable validation passed. structured-v13-1's archive is
unchanged at
`74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe`.
Base git revision: `2811f433524128a15a9e9cd304bafb396c992714`.
