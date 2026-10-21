# structured-v16.1

Unevaluated copy of structured-v16. The directory is `agents/structured-v16-1`
and the agent name is `structured_v16_1`. Existing agent directories were
not modified. No score is claimed. No GPU run and no submission. The dev-13
notebook was not executed.

## Hypothesis

structured-v16 smoke7 (archive `6b8920c3…`, swegemma 0.2.11, adk-submission
0.2.13) resolved 1 of 7. The wall was 240.5 to 334.8 seconds, and 6 of 7
tasks ran past the 300 second cap. Mean duration was 302.7 seconds (n=7).
`HYPOTHESIS` appeared only after a clock check, and only after 8 to 21
reads on four of the five editing runs. Two tasks never edited. `read_file`
range arguments were corrupted four times. A repro that printed the buggy
output was treated as a pass because it raised no exception.

The change is prompt text and `eval_config` only. The task cap is 240
seconds (`max_time_minutes: 4.0`, `timeout_seconds: 240`). Call and turn
caps stay 220 and 320. repair_1 loses `read_file`, so every read is a
`run_command` that prints `[elapsed]`. At a prefix of 100 seconds, at 6
reads, or at 120 seconds of agent time, repair_1 writes `HYPOTHESIS` and
ends the round with a text report. repair_2's first counted call edits
that target. verify_3 submits at 200 seconds and skips the check. A repro
is still optional and still costs at most 2 calls. Two non-failing repros
means stop reproducing. The steering paragraph tells the model to compare
`repr()` of captured output with the issue title and to read a cleanup
method before a render path. It names no library and no task.

This is a hypothesis. The smoke7 analysis judged an expected 1.5 to 2 of 7
against 1 of 7, within noise at n=7 and temperature 1.0. That judgment is
not a v16.1 measurement. A 240 second cap cuts late solves. No cohort was
run.

## What changed

repair_1 is still one `LlmAgent`. There is no loop. It has `get_status`,
`run_command`, and the three graph tools. It does not have `read_file`.
repair_2 still has `read_file`. The map skill stays out, for the same
reason as v16: the smallest change adds no tools, and 3 of 13 against 4 of
13 is noise, not evidence for dropping the map.

The read template is:

```
test -f /tmp/t0 || date +%s > /tmp/t0; printf '[elapsed %ss]\n' "$(( $(date +%s) - $(cat /tmp/t0) ))"; nl -ba PATH | sed -n 'A,Bp' | head -c 4000
```

`/tmp/t0` is written on the first command, about 15 seconds after the
agent clock starts. A prefix of 100 is about 115 seconds of agent time,
next to the 120 second hand-off.

The guarded heredoc is unchanged: `cat > /tmp/line_fix.py <<'EOF'`,
`assert s.count(old) == 1`, `ast.parse` before the write, a `/tmp/pre_`
backup, and `py_compile` restores only that file. `get_status` never
counts as a repeat. `submit_patch` stays on verify_3 only.

## Threshold table

Scale from the 300 second cap is 240/300. Word caps ("under 120 words",
"under 160 words", "under 100 words", "under 80 words") are words and are
unchanged. The old "next call is the heredoc" happy path inside repair_1
is gone. Six reads or a prefix of 100 ends the round so repair_2 edits.
The empty-diff heredoc remains only as the missed-hand-off net, for the
run that never returns, and on repair_2, repair_3, and verify_3.

| Clock | Who | What |
| --- | --- | --- |
| prefix `[elapsed]` >= 100, or 6 reads, or `agent_elapsed_seconds` >= 120, before the round 1 report | repair_1 | `HYPOTHESIS` and the text report. No tool call. repair_2 edits. Prefix 100 is about 115 seconds of agent time |
| still in repair_1, diff empty, remaining under 96 and at least 36, no round 1 report yet | repair_1 | write `HYPOTHESIS` and the next call is the guarded heredoc. Scaled missed-hand-off (45–120 on a 300 second cap). About 144 to 204 seconds elapsed. repair_2 has not started |
| remaining under 36 while repair_1 is still running | repair_1 | text only. Do not run that heredoc. verify_3 owns the empty diff. Under 36 is not overridden by the 36 to 96 window |
| re-entry: a round 1 report already exists, or a source edit exists | repair_1 | text only. Do not edit. Never revert |
| about 192, and a source edit exists | repair_1, repair_2, repair_3, verify_1, verify_2 | stop exploring and write the text report. Scaled from 240. Does not extend repair_1 |
| repair_2, diff empty, remaining >= 36 | repair_2 | first counted call is the heredoc on the `HYPOTHESIS` target. If that line is missing, the first file and function in the triage brief or the round 1 report. Do not read first. Do not wait for remaining under 96. `get_status` does not count. One 40-line window only if the assert fails, then one retry |
| repair_2, diff non-empty, or elapsed about 192, or remaining <= 48 and the diff is non-empty | repair_2 | text only. Do not revert |
| repair_2, remaining under 36 | repair_2 | text only. verify_3 owns the empty diff |
| verify_1 and verify_2, remaining under 72 | verify | text only. No check. Scaled from 90 |
| verify_1 and verify_2, remaining above 72, source edit | verify | the check once, then the report |
| verify_3, elapsed >= 144, source edit, remaining above 72 | verify_3 | the check, then submit. Scaled from 180 / 90 |
| verify_3, about 192, source edit, remaining not above 72 | verify_3 | stop investigating, then submit |
| verify_3, elapsed >= 200, source edit | verify_3 | `submit_patch` now. Skip the check. About 40 seconds remain, which is still at least 36, so this overrides "the check is required whenever 36 seconds or more remain" |
| verify_3, elapsed >= 200, diff empty | verify_3 | one heredoc, then `submit_patch`, no check |
| remaining under 96, diff empty, before 200, remaining >= 36 | repair_3 and verify_3 | the heredoc still applies. repair_2 does not wait for this line |
| remaining under 36 | repair_3 and verify_3 | repair_3 is text only. verify_3 heredocs if the diff is empty, then submits, and does not run the check |

120 of 240 is half the budget. The old 60 percent line was 180 of 300,
which scales to 144. That 144 second line is verify_3's "do not edit,
maybe check" line. It is not the repair_1 hand-off.

## Runtime math

v8 smoke5 model turns, cited from `docs/STRUCTURED_V15.md` and not
remeasured here: median 3.9 seconds, mean 6.6 seconds, p90 13.8 seconds.
Text-only gaps are median about 5 seconds.

After repair_1 returns, five roles remain: verify_1, repair_2, verify_2,
repair_3, verify_3. Each starts with `get_status` and then answers, so the
floor is 10 turns. An empty diff adds repair_2's heredoc and one retry,
about 12 turns.

- Median: `10 * 3.9 = 39` seconds, `12 * 3.9 = 46.8` seconds.
- Mean: `10 * 6.6 = 66` seconds, `12 * 6.6 = 79.2` seconds.
- p90: `10 * 13.8 = 138` seconds, `12 * 13.8 = 165.6` seconds.

If repair_1 hands off at 120 seconds, verify_3 starts near 159 to 167
seconds at the median and 186 to 199 seconds at the mean. The 200 second
submit is then the next action. At the p90 the same floor is 138 to 166
seconds, so verify_3 starts near 258 to 286 seconds and is often already
past the 240 second cap. The 200 second submit is the backstop only when
verify_3 is reached. If repair_1 never returns, verify_3 is not reached,
and the missed-hand-off heredoc (remaining under 96 and at least 36) is
the net inside repair_1.

The host limit is 12 hours, 43200 seconds. The harness wraps the agent
loop in `asyncio.timeout(time_minutes * 60)` and also stops when
`context.elapsed_seconds` passes `timeout_seconds`. `duration_seconds`
also includes pre-session setup and post-session capture. On the smoke7
host, pre-session was 14 to 34 seconds (34.3 on one task) and vLLM start
`L` was 1170 seconds. The v13-1 host had `L` of 417 seconds and pre-session
of 2 to 5 seconds. Nothing in the candidate runs before the session.

Smoke7, which is a v16 measurement, not a v16.1 measurement:

- `120 * (302.7 + 70) = 44726`, over the internal block limit of 39600.
- `1170 + 129 * 302.7 = 40218`, and `417 + 129 * 302.7 = 39465`, both over
  the second gate of 38880.
- Worst case `1170 + 129 * 334.8 = 44359`, and `417 + 129 * 334.8 = 43606`.
  Both are over 43200.

With a 240 second agent cap, worst wall is about `240 + 34 + 5 = 279`
seconds. `1170 + 129 * 279 = 37161` and `417 + 129 * 279 = 36408`. Both
pass 43200. A capped task on that host is about `240 + 15 + 4 = 259`
seconds. The analysis estimated a mean of 250 to 258 seconds. That
estimate was not measured. Gate 1 at a mean of 255 is
`120 * (255 + 70) = 39000`, which passes 39600 with a thin margin. The
mean must stay at most 260 seconds (`120 * (260 + 70) = 39600`).
`120 * ((240 + 8) + 70) = 38160`, which passes. Gate 2 at that estimate
is `1170 + 129 * 255 = 34065`, which passes 38880.

v13-1's dev-13 mean of 279.6 seconds fails the internal block
(`120 * (279.6 + 70) = 41952`). v12 used a 250 second cap and scored 0.06.
This candidate's cap is 240 seconds, shorter than the cap that scored
0.06. That is a known risk, not a predicted score. structured-v8 remains
the scored best, at 0.10 and 0.13 on the same archive. No v16.1 cohort
was run.

## Dev-13 notebook

`notebooks/structured-v16-1-dev13/evaluation.ipynb` was built with
`gemma-lab notebook`. The archive is embedded and hash-pinned. The
notebook unpacks it and compiles that plain zip. It does not register a
callback registry and it does not need a checkout of this repo. Task ids
are the dev-13 cohort and are not under `agents/`. The evaluator loop
keeps `results/traces/trace_<id>.json`. A report cell prints resolved
count, wall time, no-edit runs, calls to the first edit, whether
`HYPOTHESIS:` appeared, whether repair_1 returned before the 240 second
cap, and the elapsed time of that hand-off. The notebook was not run.

## Archive

SHA256 `dff316a37290895d377574bbedfd43d0b962f9871e700974b2c1b663be7f6c38`.
20 files. Portable validation passed. Plain-zip compile with no registry
was checked on adk-submission 0.2.12 and 0.2.13. structured-v16's archive
is unchanged at
`6b8920c396f4e84fe14e7b7a907c1771436a55b840fae7464b3ce6f7cac13491`.
structured-v13-1's archive is unchanged at
`74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe`.
Base git revision: `7d5fd87f7677190b688a84647d097c2f35d3a132`.
