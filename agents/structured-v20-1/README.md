# structured-v20-1

Unevaluated copy of structured-v20. The directory is `agents/structured-v20-1`
and the agent name is `structured_v20_1`. structured-v20 and other evaluated
candidates were not modified. No score is claimed.

## Hypothesis

v13-1 and v18-1 each scored 0.12 public. On a private six-task run of
v18-1, 4 of 6 patches were non-empty and 0 of 6 resolved. A 0 of 6 count
has a 95% interval of 0–46%, so it is not a resolve-rate claim. v20 keeps
the tests-first handoff and the forced edit. This copy adds three checks
so a repro or a new test file cannot enter the graded diff: every repro
stays under /tmp, verify deletes untracked files before submit, and
line_fix rejects test directories and test modules. pyproject.toml and
setup.cfg remain editable. No score is claimed. That effect is not measured.

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
uv run gemma-lab pack agents/structured-v20-1 --output /tmp/structured-v20-1.zip
```
