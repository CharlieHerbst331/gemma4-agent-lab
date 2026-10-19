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

Two additions:

- Context. Do not `read_file` a path already in the history, and do not
  rerun a command whose output is already there. The handoff names files
  and whether `git diff` is non-empty. It does not paste source. The next
  role uses the report.
- Late deadline. If `agent_elapsed_seconds` is about 240 or more and
  `git diff` has a source edit, stop exploring and let the last verify
  submit. If the diff is empty, continue. Do not force an edit only
  because the clock passed 240.

v8's repair_1 text still hands off at about 180 seconds when a source
diff is already present. An empty diff no longer ends that round, and the
"remaining under 120, so heredoc now" trigger is gone.

## Why the cap stays 300

Both submit blocks have to pass at a measured mean:

- `120 × (mean + 70) <= 39600` means mean <= 260.
- `900 + 129 × mean <= 38880` means mean <= 294.4.

The 120-task block binds. A realistic cap-hit adds 2–8 seconds. The
largest integer cap whose +8 second overrun still passes is 252:
`120 × (252 + 8 + 70) = 39600`. A mean of 255 passes both blocks
(`120 × 325 = 39000`, `900 + 129 × 255 = 33795`). v12 set the cap to 250
so a cap-hit mean would pass, and scored 0.06. Four of five v8 tasks are
already on the cap, so a shorter cap cuts those runs instead of removing
the repeated reads that fill them.

## Projected timing

This is a projection, not a measurement.

The soft deadline alone, applied to the two smoke tasks that already had
a diff (rich_3934 and rich_3454 land near 240; rich_4070 and rich_3938
stay on the cap; fastapi_11194 stays 248.3), gives
`(303.5 + 240 + 302.5 + 248.3 + 240) / 5 = 266.86`.
`120 × (266.86 + 70)` is about 40423, still over 39600.

The pass needs the two no-edit read loops to shrink as well. If those two
finish near 255 and the two diff tasks hand off near 240, the mean is
`(255 + 240 + 255 + 248.3 + 240) / 5 = 247.66`.
`120 × (247.66 + 70)` is about 38119, and
`900 + 129 × 247.66` is about 32848. Both blocks pass. A measured mean of
261 or more still fails the 120-task block. The 300 second cap still
warns: `900 + 129 × (300 + 70) = 48630`, over 43200.

## Smoke

No GPU run is started from this change. A later comparison is v8 against
v13 on the same five tasks (rich_4070, rich_3934, fastapi_11194,
rich_3938, rich_3454), one repeat. n=5 cannot name a winner. v8 at 0.10
and 0.13 on the same archive is the noise band.
