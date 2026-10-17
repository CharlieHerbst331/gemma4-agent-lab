# structured-v11

Unevaluated byte copy of structured-v8. structured-v8 scored 0.10.
structured-v9 scored 0.08. single-v6 scored 0.08. structured-v10, archive
`c07fcc5505f509f648a924a09dfa5a0f4c1cfe10d4b0a784f938e69116c66ed0`, merged at
`fcc7c426`, scored 0.01. No new score is claimed. No Kaggle push and no GPU
run. Existing agent directories and evidence were not edited.

## Root cause of the v10 score

structured-v10 scored 0.01 because the three repair branches starved each
other of compute, not because the graded diff was malformed. `run_command`
calls `docker.exec` synchronously (`swegemma/tools/execution.py` line 42 in
the public harness copy). google-adk 1.36.1 runs that callable on the event
loop unless `RunConfig.tool_thread_pool_config` is set
(`flows/llm_flows/functions.py` lines 973–984; `function_tool.py` line 238
calls `target(**args)` for a sync tool). The harness builds
`RunConfig(max_llm_calls=remaining_turns)` and sets nothing else
(`agent_runner.py` line 516), so branch commands run one at a time while
three model streams share vLLM. The v10 prompts also require `get_status`
before every `run_command`, which adds a model round trip per command, and
they stop each branch at 170 seconds. Effective work per branch is about
`170 / (2 × 1.3) = 65` seconds down to `170 / (2 × 1.6) = 53` seconds of
single-stream time. Across 118 earlier single-stream traces the median time
to a first edit was 63.6 seconds (21 calls); only 29 of 118 had edited by
60 seconds, 52 of 118 by 170 seconds, and 59 of 118 never edited. v8 gives
one trajectory the full 300 seconds, which is where its resolves come from.
A second failure mode is real and secondary: `ParallelAgent` merges branches
with `asyncio.TaskGroup` (`parallel_agent.py` line 71), so one branch
exception cancels the others and select never starts. In the 812-line
`agent_runner.py` checked here, that exception leaves the inner run and is
recorded by the outer handler (`agent_runner.py` line 799,
`Sandbox execution error: ...`) before the fallback diff at line 758. The
verification harness, on a longer runner, recorded the same TaskGroup error
and graded whatever was already on `/workspace`. Diff application, worktree
paths, temperature 1.3, and seeds were checked in that verification and did
not explain the score.

## What v11 changes

Nothing in the agent. `agents/structured-v11` is a byte-for-byte copy of
`agents/structured-v8`, including the agent name `structured_v8`, the seven
sequential roles, the heredoc with `py_compile` and the single-file rollback,
the check skill, sampling, and the 300 second / 220 call / 320 turn budget.
The archive hash is therefore v8's scored hash. v8 already reads the clock
with `get_status` before it decides to keep reading. It does not call
`get_status` before every command, and v11 does not add that.

The v9 locate skill is not copied. v9 scored 0.08, below v8, so that skill
is not evidence of a gain. No parallel role is added. Verification will not
accept a parallel or v10-derived candidate without a GPU smoke, and no GPU
slot was available.

## Serial best-of-2, not built

A later candidate could run two repair attempts one after another inside the
same 300 second cap, with no `ParallelAgent`. Wall time would be the sum of
the attempts, so command time would not be multiplied and an error in the
first attempt would not cancel the second. A handoff at 150 seconds would
leave 150 seconds for the second attempt. Each half is longer than the
63.6 second median to a first edit, and longer than v10's 53–65 second
effective branch. The cost is the tail of the single trajectory: two medians
are `2 × 63.6 = 127.2` seconds before either attempt has time to verify, and
the design note's `fastapi_11194` solve edited at 225 seconds, which neither
150 second attempt would reach. That trade is not taken here. If it is built
later, the gate is a 5-task GPU smoke against v8 that reports the fraction
of attempts with a compiling edit, the mean wall time, and any runner
exception.

## Limits

The budget is v8's. Overhead 70 seconds and L = 900 are the toolkit
constants. Blocks use a measured mean. The warning uses the cap.

Aimed mean 255 seconds (submit when 45 seconds remain):

- `120 * (255 + 70) = 39000` seconds. At or under 39600.
- `900 + 129 * 255 = 33795` seconds. At or under 38880.
- `900 + 129 * (255 + 70) = 42825` seconds. At or under 43200.

Cap 300 seconds, as if the mean equaled the cap:

- `120 * (300 + 70) = 44400` seconds. Above 39600.
- `900 + 129 * (300 + 70) = 48630` seconds. Above 43200. **WARN**.
- `900 + 129 * 300 = 39600` seconds. Above 38880.

A 300 second cap still warns when the measured mean is 255. It does not
block at that mean.

## Archive

```bash
uv run gemma-lab pack agents/structured-v11 --output /tmp/structured-v11-submission.zip
```

sha256 `9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e`,
the structured-v8 archive, 20 files. Packing `agents/structured-v8` still
matches it. Packing `agents/structured-v10` still matches
`c07fcc5505f509f648a924a09dfa5a0f4c1cfe10d4b0a784f938e69116c66ed0`.
