# structured-v17

Unevaluated copy of structured-v13-1. The directory is `agents/structured-v17`
and the agent name is `structured_v17`. Existing agent directories were
not modified. No score is claimed for this candidate. No GPU run and no
submission yet.

## Hypothesis

Empty patches come from repair_1 never editing. Across the never-edit
study, 59 of 118 runs never edited. On v13-1 dev-13, 6 tasks were empty
and all 6 made 0 heredoc attempts. The cause is a mandatory failing repro
when a repro passes on buggy code, plus repair_1 keeping the whole 300
seconds because nothing structural hands the turn off. Clock rules do
not fix that. `get_status` is rarely called after the opening, so an
`elapsed >= N` line is never seen. v15 at 4 minutes scored 0.06. Stock
v15 scored 0.08. v13-1 scored 0.12 and 0.10. v8 scored 0.10 and 0.13.
Hard caps have scored worse. v16.x was worse on dev-13.

The bet is a count, not a clock. Repro is optional and costs at most 2
calls. A passing repro is not evidence of the wrong place. After at most
4 file reads, repair_1 writes `HYPOTHESIS: <path>:<function> - <change>`
with no tool call, and the very next tool call is the guarded heredoc.
An imperfect edit is better than an empty diff. After that heredoc
succeeds, or after the hypothesis plus one attempt, repair_1 writes the
text report so later roles run. If the diff is still empty, repair_2's
first tool call is the heredoc on that target. One 40-line window is
allowed only if the assert fails, then one retry.

## Why not clocks

v13-1 already has the empty-diff net and the 180 and 240 second wording.
Those lines stay. This candidate does not add `elapsed >= N` hand-offs,
`HAND-OFF DUE` banners, a +25 display offset, stop sequences aimed at
the clock, or a 240 second cap. The cap stays 300 seconds, 220 calls,
and 320 turns. The 4-read rule and the "next call is the heredoc" rule
are counts of tool calls. They do not require the model to read
`get_status`.

## Why this base

v13-1 is the scored structured candidate at 0.12 and 0.10. v14's map
skill went 3 of 13 against v13-1's 4 of 13. That is one task. The map
skill stays out. v15 wrapped repair in loops and told repair_1 not to
stop while the diff was empty, so later roles rarely ran. v16 shortened
the cap. This copy changes repair_1 and repair_2 prompt text only, plus
the agent name and a comment in `eval_config`. repair_1 is already one
`LlmAgent`, not a `LoopAgent`, so there is no `max_iterations` to set.
A text report with no tool call is what ends that pass. The prompt says
so after the heredoc.

## Disclosures

The 4-read rule and the hand-off after the edit are prompt compliance.
The hosted schema has no per-role call cap. A repair_1 that keeps
calling tools never returns, and the diff from that role stays empty.
That path is still possible. The heredoc still requires exact bytes, so
a failed assert can still leave the diff empty. repair_2 is the second
chance, and it is also prompt compliance.

The steering sentence about a passing repro was written from tasks where
a repro printed the bug and did not raise. The wording names no library
and no task. A gain on the task that prompted it is in-sample.

No v17 cohort has been run. Do not read the v13-1 scores as a v17 score.

## Runtime math at 300 seconds

The internal block is `120 * (mean + 70) <= 39600`, so the mean must
stay at most 260 seconds. A task that uses the full 300 second cap plus
8 seconds of overhead is `120 * (308 + 70) = 45360`, over 39600. That
is the same block v13-1 already fails when the mean is high. The host
limit is 12 hours, 43200 seconds. With a vLLM start of 1170 seconds,
`1170 + 129 * 300 = 39870`, which passes 43200. A worst wall of about
339 seconds (`300 + 34 + 5`) is `1170 + 129 * 339 = 44901`, over 43200.
Keeping 300 seconds does not create a new gate failure. It keeps the
cap that scored 0.12 and 0.10 instead of the shorter caps that scored
0.06 and 0.08.

## Archive

SHA256 `27b47d34554d9b64f3786b430856dd950d678d5ea6dbd4a0ae6fb7dd687e79e6`.
20 files. Portable validation passed. Plain-zip compile with no registry
was checked on adk-submission 0.2.12 and 0.2.13. structured-v13-1 is
unchanged at
`74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe`.

Pack command:

```bash
uv run gemma-lab pack agents/structured-v17 --output /tmp/structured-v17.zip
```
