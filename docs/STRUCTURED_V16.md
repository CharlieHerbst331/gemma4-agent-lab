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

The map skill was not ported. Testing's smallest change adds no tools.
v14, which did add the map, resolved 3 of 13 on the same dev cohort where
v13-1 resolved 4 of 13, and the three never-edit tasks still made no edit.
Triage stays the v13-1 tool-free brief.

Caps stay 300 seconds, 220 calls, and 320 turns. The heredoc still asserts
`s.count(old) == 1` and parses before it writes. `get_status` never counts
as a repeat. The empty-diff net stays on verify_3.

## Clock reconciliation

On a 300 second cap, `time_seconds_remaining` under 120 is about 180
seconds elapsed. That was repair_1's empty-diff heredoc, and it sat after
the 150 second hand-off. It is removed from repair_1. Repair round 2 owns
that edit and does not wait for the under-120 line.

| Clock | Who | What |
| --- | --- | --- |
| 4 file reads, elapsed under 150 | repair_1 | `HYPOTHESIS` with no tool call, then the heredoc, then the text report |
| about 90 seconds, or about 38 calls, still under 150, no edit yet | repair_1 | same hypothesis and heredoc, even with fewer than 4 reads |
| elapsed >= 150 | repair_1 | text report, including `HYPOTHESIS`, even if the diff is empty. No heredoc. Replaces the 180 second stop |
| about 240, and a source edit exists, and repair_1 is still running | repair_1 | text report. Does not extend the round |
| remaining under 45 while repair_1 is still running | repair_1 | text only. Only if the 150 second hand-off was missed |
| repair_2, diff empty, remaining >= 45 | repair_2 | first counted call is the heredoc on the HYPOTHESIS target. `get_status` does not count. One 40-line window only if the assert fails, then one retry |
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
verify_1, repair_2, verify_2, repair_3, verify_3. If each is one short
turn, that floor is `5 * 3.9 = 19.5` seconds at the median, `5 * 5 = 25`
seconds at the text-only median, `5 * 6.6 = 33` seconds at the mean, and
`5 * 13.8 = 69` seconds at the p90. An empty diff adds repair_2's heredoc
and at most one retry, about two more turns: `7 * 3.9 = 27.3`,
`7 * 6.6 = 46.2`, `7 * 13.8 = 96.6` seconds. A repair_1 hand-off at 150
seconds of wall time would put verify_3 near 177 to 247 seconds on that
arithmetic. A role that keeps calling tools is still not interrupted, so
the 250 second submit is the backstop, not a guarantee.

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
the first edit, and whether `HYPOTHESIS:` appeared. It does not delete
traces. It was not run.

## Archive

SHA256 `5670e1f83ebdec52abf7fec85895619cba7fe46922e298d129461039928f233d`.
20 files. Portable validation passed. structured-v13-1's archive is
unchanged at
`74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe`.
Base git revision: `2811f433524128a15a9e9cd304bafb396c992714`.
