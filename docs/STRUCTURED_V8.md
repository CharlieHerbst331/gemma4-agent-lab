# structured-v8

Unevaluated copy of the structured-v7 loop, unrolled into three repair/verify
rounds. No score is claimed. No Kaggle push and no GPU run. Existing agent
directories, `paired.py`, and existing notebooks were not edited.

structured-v7 is still the structured frontier until a measured comparison
exists. Its repair role ran 337–349 seconds and never handed off to verify.
A `LoopAgent` does not interrupt a child that keeps calling tools, so
`max_iterations: 3` never started verify.

## Structural vs prompt

The harness has no per-role clock. `max_llm_calls` is an extra field and fails
compilation. Callbacks are accepted by name and then dropped, so they are not
a deadline. `get_status` reports `agent_elapsed_seconds` and
`time_seconds_remaining`; it does not stop the role. `submit_patch` on a
non-final role is a hygiene block (`G0.early_submit`), and a text reply after
`submit_patch` ends the task, so only the last role may submit.

What the YAML enforces:

- Triage has `tools: []` and `max_output_tokens: 1024`. It cannot search or
  edit. That is the only time bound the schema can put on a role. The "under
  20 seconds" line is still a prompt.
- The root is a `SequentialAgent` of seven `LlmAgent`s, not a `LoopAgent`.
  The round cap is the number of children. Triage does not restart.
- `submit_patch` is only on `verify_3`. Repair and the first two verifies
  cannot submit, so their text handoff does not end the task.
- `edit_file` is not granted. The edit path is the `run_command` heredoc.
- Tools shrink by round. `repair_1` may read and use the three graph tools.
  `repair_2` has `get_status`, `read_file`, and `run_command`. `repair_3` has
  `get_status` and `run_command` only. `verify_3` has `get_status`,
  `run_command`, and `submit_patch`.
- Each verify role mounts `skills/check`, a byte copy of the single-v8-check
  script. The script runs only if the model emits the constant call. The
  skill does not force a stop.

What is prompt-only, via `get_status`:

- `repair_1` hands off at `agent_elapsed_seconds` 180 (60 percent of 300) or
  when `time_seconds_remaining` is 120 or less and a diff already exists.
- `repair_2` hands off at 240 seconds elapsed, or when 60 seconds or less
  remain and a diff exists.
- With under 120 seconds left and an empty diff, the next call is the heredoc.
- With under 45 seconds left, earlier roles stop so `verify_3` can run.
  `verify_3` submits the current diff. If the diff is still empty, its next
  call is one heredoc, then `submit_patch`. A cap hit with no diff is the
  failure the prompt forbids. `verify_3` then calls `submit_patch` even if
  that heredoc left the diff empty. A text-only ending restarts the root.
- `ast.parse` runs before the write. The helper copies `PATH` to
  `/tmp/line_fix.bak` only after that parse succeeds. `python -m py_compile`
  runs after the write. A failed helper does not restore anything. A failed
  `py_compile` restores with `cp /tmp/line_fix.bak PATH`. The recipe does not
  use git to restore a file. This is still prompt text, not a harness hook.
- When 45 seconds or more remain, `verify_3` must call
  `{"skill_name":"check","file_path":"scripts/run.py"}` before `submit_patch`.
  Under 45 seconds the submit deadline wins, so the check is skipped.
  `verify_1` uses the same under-90-second text-only rule as `verify_2`.
- `repair_2`, and `repair_1` on a later pass, leave a non-empty source diff
  alone. They do not edit it and they do not restore it.

`repair_1` can still ignore the 180 second line and run until the task cap.
Nothing in the schema interrupts that role. Narrower tools on later rounds
do not help until `repair_1` returns a final text response. That is the same
hole that kept structured-v7 in repair for 337–349 seconds. The unroll only
helps after the first repair stops.

## Roles

| Role | Tools | Thinking | Handoff |
| --- | --- | --- | --- |
| triage | none | off | one brief, no tools |
| repair_1 | status, read, command, graph | 256 | 180 s elapsed, or 120 s left |
| verify_1 | status, read, command, check | off | under 90 s, text only; otherwise one check |
| repair_2 | status, read, command | 256 | 240 s elapsed, or 60 s left |
| verify_2 | status, read, command, check | off | one check, cannot submit |
| repair_3 | status, command | 256 | one heredoc if the diff is empty |
| verify_3 | status, command, submit, check | off | submit; under 45 s submit now |

`include_contents: default` is set on each `LlmAgent` only. Sampling on every
role is temperature 1.0, top_p 0.95, top_k 64. Repair includes
`repair_thinking.yaml`. The other roles include `thinking.yaml`
(`thinking_budget: 0`).

## Limits and the runtime gate

`eval_config.yaml`: `max_time_minutes: 5` (300 seconds), `max_tool_calls: 220`,
`max_turns: 320`, `timeout_seconds: 300`. Calls and turns are loose so the
clock binds first.

300 seconds is the largest cap whose 45 second submit deadline lands on the
255 second mean ceiling (`300 - 45 = 255`). The cap is above the 255–290
second band. The deadline logic is what keeps the aimed mean at 255: repair
is told to leave at 180 seconds, and the last verify is told to submit once
45 seconds remain. That submit point is prompt-enforced. If `repair_1` runs
to the cap, the mean can still be 300.

Overhead 70 seconds and L = 900 are the toolkit constants. The blocks use a
measured mean. The warning uses the cap. The user's cap formulas are reported
beside the block formulas.

Cap 300 seconds, as if the mean equaled the cap:

- `120 * (300 + 70) = 44400` seconds. Above 39600. The 11 hour block would fail.
- `900 + 129 * (300 + 70) = 48630` seconds. Above 43200. **WARN**.
- `900 + 129 * 300 = 39600` seconds. Above 38880. The real 129-task block
  (no overhead) would also fail.

Verdict at the cap: **WARN**, and both blocks fail if a later measured mean
equals 300. The cap itself does not block.

Aimed mean 255 seconds (submit when 45 seconds remain):

- `120 * (255 + 70) = 39000` seconds. At or under 39600. The 11 hour block passes
  (margin 600 seconds).
- `900 + 129 * 255 = 33795` seconds. At or under 38880. The 129-task block passes.
- `900 + 129 * (255 + 70) = 42825` seconds. At or under 43200. This is the warn
  formula applied to the mean, not the live check.

A submission whose cap is 300 still **warns**, even when the measured mean is
255, because the warning reads the cap. It does not block at mean 255.

## structured-v7 frontier

Archive `a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df`.
Cap 360 seconds (`max_time_minutes: 6`), 150 calls, 200 turns.

- `120 * (360 + 70) = 51600` (would block the 11 hour check if the mean were 360)
- `900 + 129 * (360 + 70) = 56370` (**WARN**)
- `900 + 129 * 360 = 47340` (the 129-task block fails if the mean is 360)

Verdict at the cap: **WARN**, not BLOCK. Blocks read the measured mean.
Pack and submit-archive command, output outside the agent directory:

```bash
uv run gemma-lab pack agents/structured-v7 --output /tmp/structured-v7-submission.zip
```

## Prompts

Character counts are this revision. `chars/4` is not a Gemma tokenizer count.
No first-request token total is claimed.

| Role | Characters | chars/4 |
| --- | --- | --- |
| triage | 1937 | 484.25 |
| repair_1 | 5287 | 1321.75 |
| verify_1 | 1685 | 421.25 |
| repair_2 | 2889 | 722.25 |
| verify_2 | 1316 | 329 |
| repair_3 | 2254 | 563.5 |
| verify_3 | 4183 | 1045.75 |

The completion reservation is 1024 tokens on triage and 2048 on the other
roles, inside a 32768 context. Those ceilings are harness limits, not measured
prompt tokens.

## Archives and protocols

- structured-v8 sha256 `16cee658599fe212c9909868cd0a84c01da6cd8bddab6d9691190b3dbd953e2b`
- single-v9 sha256 `0b9efe69189799bde760529e9b75e35d15dbcc63d4214ca459e57dcd3b21dd7e`
  (see `docs/SINGLE_V9.md`)
- Unchanged: structured-v7 `a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df`,
  single-v8 `6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22`,
  single-v8-check `64dc727d78c4189c1db1184e74129290574c7b97816dd91f91d2baa7defe0fb0`,
  single-v7 `f62c8c0b92bc5bd1fb1015f20e7cbd7a5599d5518d2d59097bf2b40d9f3412b0`

```bash
uv run gemma-lab pack agents/structured-v8 --output /tmp/structured-v8-submission.zip
uv run gemma-lab pack agents/single-v9 --output /tmp/single-v9-submission.zip
```

`configs/protocols/structured-v7-vs-structured-v8-dev13.yaml` is dev-13, one
repeat, A structured-v7, B structured-v8, `matched_pair: false`. The schedule
hash is `629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed`.
Session budget 40200 seconds.

`configs/protocols/structured-v8-candidate-smoke.yaml` is a three-arm smoke
for `notebook-multi`: A structured-v7, B structured-v8, C single-v9. Tasks:
`rich_4070`, `rich_3934`, `fastapi_11194`, `rich_3938`, `fastapi_14262`.
Schedule hash `50ea6e7f7f7e54213ec78a1cec8edd9fd0398deff22450fae42abd781bba7857`.
`pair_fits` worst case is 6780 seconds. Session budget 14400 seconds.

Generate notebooks under `/tmp` (not committed). Owner `charlesaherbst`,
wheelhouse version 30:

```bash
uv run gemma-lab notebook-pair \
  --protocol configs/protocols/structured-v7-vs-structured-v8-dev13.yaml \
  --owner charlesaherbst \
  --slug structured-v7-vs-structured-v8-dev13 \
  --output /tmp/structured-v7-vs-structured-v8-dev13 \
  --wheelhouse-version 30
uv run gemma-lab notebook-multi \
  --protocol configs/protocols/structured-v8-candidate-smoke.yaml \
  --owner charlesaherbst \
  --slug structured-v8-candidate-smoke \
  --output /tmp/structured-v8-candidate-smoke \
  --wheelhouse-version 30
```

## Why verify_3 always submits

`docs/STRUCTURED_V5.md` records the harness behavior: when the root finishes
without a submission, the nudge starts the root again, which reruns triage.
A stub of structured-v8 showed four full passes of all seven roles when
`verify_3` ended in text and never called `submit_patch`. `submit_patch`
stores the diff and a later text response ends the task, which skips that
nudge (`agent_runner.py` in the harness notes above).

`verify_3` is therefore told to end on `submit_patch` after at most one
heredoc and, when 45 seconds or more remain, the flat check. If the diff is
still empty after that heredoc, it still submits once. One submission stops
the restart. If a nudge does happen, triage returns the existing brief, and
`repair_1` on a later pass with a source diff or with 180 seconds already
elapsed hands off in text. `repair_2` and `repair_3` do the same whenever
the source diff is already non-empty.

Hypothesis: unrolling the loop and telling repair to stop at 180 seconds lets
verify run, which structured-v7 did not do. Whether the model obeys the clock
needs a GPU run. The 70 second overhead is still an estimate. No result is
claimed.
