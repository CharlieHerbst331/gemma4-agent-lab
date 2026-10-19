# structured-v13

Unevaluated copy of structured-v8 with a late soft deadline and a smaller
read loop. structured-v8 scored 0.10, and the same archive later scored
0.13. structured-v12 scored 0.06. No new score is claimed for v13. No GPU
run and no submission. Existing agent directories were not modified.

## Distribution

`runs/kaggle/structured-v8-smoke5/task_results.jsonl` is not in this
checkout. The per-task walls below are the smoke5 figures recorded from
that file (Gemma Testing Bot, 18 October 2026, archive
`9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e`).
`evidence/run-results.json` has no structured-v8 run. Its durations are
earlier candidates.

| Task | Wall seconds | Cap hit at 300 s |
|---|---:|---|
| rich_4070 | 303.5 | yes |
| rich_3934 | 307.6 | yes |
| rich_3938 | 302.5 | yes |
| fastapi_11194 | 248.3 | no |
| rich_3454 | 304.7 | yes |

Sum 1466.6. Mean 293.32. Median 303.5. Four of five tasks hit the cap.
Their overruns are 3.5, 7.6, 2.5, and 4.7 seconds, inside the 2–8 second
band. Dropping the short task raises the mean to 304.575. The 293 second
mean is the cap, not a few long outliers. The 248.3 second finish pulls
the mean down.

## What v13 changes

The shape, skills, sampling, thinking, heredoc, rollback, 220 calls, and
320 turns stay at v8. v12's elapsed prefix, edit-by-110/120, and the
130/160/190 stops are not copied. The hard cap stays 300 seconds.

"Drop edit-by-120" means v12's elapsed-time rule. v8's remaining-time
empty-diff net stays.

Additions on top of that net:

- Identical calls. Do not repeat `read_file` on the same path and the
  same range, and do not repeat the same command, when no source edit has
  happened since. A new range on the same path is allowed, including
  paging past a truncated read. After an edit, `python /tmp/repro_check.py`,
  pytest, and `git diff` may run again. The handoff names files and
  whether `git diff` is non-empty. It does not paste source.
- Late deadline. If `agent_elapsed_seconds` is about 240 or more and
  `git diff` has a source edit, stop exploring and let the last verify
  submit.
- Empty-diff net, as in v8. If `time_seconds_remaining` is under 120 and
  `git diff` is empty, repair_1, repair_2, and repair_3 take the heredoc
  next. verify_1 and verify_2 tell the next repair to take that heredoc.
  verify_3 takes the heredoc, then the check, then `submit_patch`, when
  45 seconds or more remain. repair_1's text-only handoff at 180 seconds,
  and repair_2's at 240 seconds, apply whether or not a diff exists.
- repair_1 calls `get_status` before each edit. `get_status` does not
  count as a tool call.

## Why the cap stays 300

Both submit blocks have to pass at a measured mean:

- `120 × (mean + 70) <= 39600` means mean <= 260.
- `900 + 129 × mean <= 38880` means mean <= 294.4.

The 120-task block binds inside this lab. A realistic cap-hit adds 2–8
seconds. The largest integer cap whose +8 second overrun still passes is
252: `120 × ((252 + 8) + 70) = 120 × 330 = 39600`, so the block needs a
mean of 260 or less. A mean of 255 passes both blocks
(`120 × 325 = 39000`, `900 + 129 × 255 = 33795`). That block is the lab's
margin model, not a hosted limit. The host enforces 12 hours total only
(`research/runtime-cap.md`). `check_projected_runtime` refuses a mean
above 260 seconds, so a v13 upload with a v8-like mean needs the same
uploader override already used for v8's hosted runs. v12 set the cap to
250 so a cap-hit mean would pass, and scored 0.06. Four of five v8 tasks
are already on the cap, so a shorter cap cuts those runs. v13 keeps 300
seconds and narrows repeated identical calls.

## Projected timing

This is a projection, not a measurement.

The realistic figure is about 267 seconds. Diff tasks hand off near 240
(rich_3934 and rich_3454). The two no-edit tasks stay on the cap
(rich_4070 and rich_3938). fastapi_11194 stays 248.3.
`(303.5 + 240 + 302.5 + 248.3 + 240) / 5 = 266.86`.
`120 × (266.86 + 70)` is about 40423, still over 39600. That failure is
the lab's internal 120-task block. The hosted limit is 12 hours total.

247.66 is a hypothesis. It assumes the two no-edit loops also finish near
255, and no rule makes those loops stop there.
`(255 + 240 + 255 + 248.3 + 240) / 5 = 247.66`.
`120 × (247.66 + 70)` is about 38119, and
`900 + 129 × 247.66` is about 32848. Both internal blocks would pass
under that assumption. A measured mean of 261 or more still fails the
120-task block. The 300 second cap still warns:
`900 + 129 × (300 + 70) = 48630`, over 43200.

## Smoke

No GPU run is started from this change. A later comparison is v8 against
v13 on the same five tasks (rich_4070, rich_3934, fastapi_11194,
rich_3938, rich_3454), one repeat. n=5 cannot name a winner. v8 at 0.10
and 0.13 on the same archive is the noise band.
