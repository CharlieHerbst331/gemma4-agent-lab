# structured-v20

Unevaluated three-role candidate. The directory is `agents/structured-v20`
and the agent name is `structured_v20`. Evaluated candidates were not
modified. No score is claimed.

## Hypothesis

v13-1 and v18-1 each scored 0.12 public. On a private six-task run of
v18-1, 4 of 6 patches were non-empty and 0 of 6 resolved. A 0 of 6 count
has a 95% interval of 0–46%, so it is not a resolve-rate claim. Time went
into patch reads, and a repro that passed on unfixed code was treated as
no bug. Searching existing tests first, handing off file, function,
hypothesis, and evidence, and forcing one edit by about 12 patch calls or
150 seconds should leave a source diff and one real test run inside the
same 300 second cap. That effect is not measured.

## What this candidate does

Three sequential roles: triage_localize, one patch pass, one verify that
submits. The task cap stays 300 seconds, 220 calls, and 320 turns. The
12-call and 150-second edit trigger is prompt-only. It is not a second
wall clock.

Hard: tool lists, `LoopAgent` `max_iterations` 1 on patch, `max_output_tokens`,
and stop sequences. Prompt-only: the test-first search, the ban on an
already-fixed claim, the 12-call and 150-second trigger, duplicate
commands answered with `already ran, see above`, and unknown tool-arg keys.
Hosted compile drops callbacks, so those checks are not tool wrappers.
The submission has no field for extra test packages, so `dirty_equals` and
`inline_snapshot` are not added to the grader.

## Archive

SHA256: `see docs/STATUS.md and the pull request`

```bash
uv run gemma-lab pack agents/structured-v20 --output /tmp/structured-v20.zip
```
