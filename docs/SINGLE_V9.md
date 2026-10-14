# single-v9

Unevaluated copy of single-v8. The only change is `prompts/system.md`.
`agent.yaml`, `eval_config.yaml`, `sampling.yaml`, and `thinking.yaml` are
byte-identical to single-v8, including the historical agent name `single_v1`.
No score is claimed. No Kaggle push and no GPU run.

The prompt changes are the two single-agent fixes:

1. With `time_seconds_remaining` under 120 and an empty diff, the next call is
   the heredoc edit. With under 45 seconds left, submit the current diff. If
   the diff is still empty, one heredoc runs first, then `submit_patch`. A cap
   hit with no diff is the failure the prompt forbids. The single-v8 lines
   "fewer than 60 seconds" and "fewer than 20 seconds" are gone. The first-edit
   rule (about 90 seconds, or about 38 calls) and the stop-reading rule (about
   165 seconds, or about 75 calls) stay.
2. The heredoc parses Python with `ast.parse` before it writes. After that
   parse succeeds it copies the file to `/tmp/line_fix.bak`, then writes.
   The next command is `python -m py_compile` when the path ends in `.py`.
   If the helper fails, the file was not written, so nothing is restored.
   If `py_compile` fails, `cp /tmp/line_fix.bak PATH` restores only that
   backup. The prompt does not tell the model to restore with git.

`edit_file` stays on the tool list. Dropping it was not part of this copy.
There is no check skill. The flat check is the structured-v8 verify step.

These deadlines are prompt-only. single-v9 is one `LlmAgent`. The harness
cannot interrupt it at 120 or 45 seconds. `max_llm_calls` does not compile,
and callbacks are dropped.

## Limits

Unchanged from single-v8: `max_time_minutes: 5.5` (330 seconds),
`max_tool_calls: 150`, `max_turns: 200`, `timeout_seconds: 300`. Thinking is
off (`thinking_budget: 0`). Sampling is temperature 1.0, top_p 0.95, top_k 64.

The 45 second submit rule on a 330 second clock aims at elapsed 285 seconds.
That point is above the 255 second mean ceiling:

- `120 * (285 + 70) = 42600` seconds. Above 39600. The 11 hour block would fail.
- `900 + 129 * 285 = 37665` seconds. At or under 38880. The 129-task block
  (no overhead) would pass.
- `900 + 129 * (285 + 70) = 46695` seconds. Above 43200. **WARN** if that
  formula is applied to 285.

The live warning uses the 330 second cap, not 285:

- `900 + 129 * (330 + 70) = 52500` seconds. **WARN**.
- `120 * (330 + 70) = 48000` and `900 + 129 * 330 = 43470` would both block if
  the measured mean equaled the cap.

single-v9 is not submission-safe on the 285 second aimed submit point. No
measured mean exists. Do not treat 285 as an observation.

The prompt is 9156 characters. `9156 / 4 = 2289` is not a Gemma tokenizer
count. No first-request token total is claimed.

## Archive

- single-v9 sha256 `0b9efe69189799bde760529e9b75e35d15dbcc63d4214ca459e57dcd3b21dd7e`
- single-v8 sha256 `6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22`
  (unchanged)

```bash
uv run gemma-lab pack agents/single-v9 --output /tmp/single-v9-submission.zip
```

single-v9 is arm C of `configs/protocols/structured-v8-candidate-smoke.yaml`.
See `docs/STRUCTURED_V8.md` for the notebook command.
