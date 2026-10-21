# structured-v16.2

Unevaluated copy of structured-v16.1. The directory is `agents/structured-v16-2`
and the agent name is `structured_v16_2`. Existing agent directories were
not modified. No score is claimed. No GPU run and no submission of this
candidate. The dev-13 notebook was not executed.

## Hypothesis

structured-v16.1 dev-13 (archive `2bcee926…`, commit `a722a0f`) resolved 3
of 13. Mean wall was 237.05 seconds, minimum 199.5, maximum 246.76. That
is a dev-13 result, not a leaderboard score. repair_1 made 13 to 39 calls
(median 19). The `[elapsed]` clock is real time since `/tmp/t0`, and t0
is created on the first command, so the prefix ran 19.3 to 34.1 seconds
behind the agent clock (median 24.0). A displayed 100 therefore first
appeared at agent time 123.4 to 159.5 seconds, already past the 120 second
target, on all 13 tasks. Five tasks never reached 6 reads because they
spent the calls on grep or exec. On 10 of 13 tasks the model made at least
4 more calls after the trigger. A text-only reply did end the role: the
next role started 3.8 to 20.9 seconds later. On 3 tasks the model wrote
`HYPOTHESIS` in the same turn as a tool call, which kept the role going.

The change is prompt text and repair_1's generate config. Caps stay 240
seconds, 220 calls, and 320 turns. The shell prefix, which ships in the
zip, adds 25 seconds before it prints `[elapsed]`. At a displayed 100 it
also prints `HAND-OFF DUE: reply now with HYPOTHESIS and END_ROUND_1, no
tool call`. The prompt stops on that banner or on 10 tool calls of any
kind, including `get_status`. repair_1's `generate_content_config` sets
`stop_sequences` to `END_ROUND_1`, `max_output_tokens` to 1024, and
thinking off (`thinking_budget` 0, `include_thoughts` false). Graph tools
are removed from repair_1. The missed-hand-off heredoc is removed from
repair_1 because it told the model to make another tool call after the
trigger. repair_2 still reads one 40-line window and then edits.

This is a hypothesis. A hand-off near 100 to 125 seconds would leave
repair_2 about 60 to 100 seconds more than the v16.1 hand-offs. That
might turn some of the 8 no-edit runs into edits. The effect on resolves
is unknown until a run of this candidate. None of these levers hard-forces
the hand-off. The hosted schema has no per-role call cap. If the model
emits a tool call before `END_ROUND_1`, the role continues.

## What changed

repair_1 is still one `LlmAgent`. There is no loop and no callback. Tools
are `get_status` and `run_command`. The read template is the clock prefix
plus `nl -ba PATH | sed -n 'A,Bp' | head -c 4000`.

The prefix is:

```
test -f /tmp/t0 || date +%s > /tmp/t0; e=$(( $(date +%s) - $(cat /tmp/t0) + 25 )); printf '[elapsed %ss]\n' "$e"; [ "$e" -ge 100 ] && echo 'HAND-OFF DUE: reply now with HYPOTHESIS and END_ROUND_1, no tool call';
```

Displayed 100 is raw elapsed plus 25. With the measured lag of 19.3 to
34.1 seconds, that is about 95 to 109 seconds of agent time.

`END_ROUND_1` is the last line of the reply and is not part of the
`HYPOTHESIS` line. OpenAI-compatible `stop` drops the stop string and
keeps the text before it. The `HYPOTHESIS` line stays in the history, and
repair_2 still looks for the latest `HYPOTHESIS` line. Putting the marker
inside the `HYPOTHESIS` line would cut that line. The prompt forbids that.

repair_1 thinking uses `thinking.yaml` (budget 0). repair_2 and repair_3
still use `repair_thinking.yaml` (budget 256). `max_output_tokens` is
1024 only on repair_1. The other roles stay at 2048. On adk-submission
0.2.12 and 0.2.13 the no-registry compile attaches `stop_sequences`
`["END_ROUND_1"]`, `max_output_tokens` 1024, and `thinking_budget` 0 on
repair_1. The hosted model is a `LiteLlm`, and that compile also sets
`enable_thinking` false on repair_1's model. Nothing was dropped.

The steering paragraph at `repair_1.md` is the same paragraph as
v16.1's `repair_1.md:96`. It was tuned on rich_3934. The wording names no
library and no task, but a dev-13 gain on rich_3934 is in-sample.

v16.1 did resolve rich_3454, along with fastapi_14786 and fastapi_14794.
That result does not transfer to this candidate by assumption. repair_1
still does not edit on the normal path, and it no longer has the
missed-hand-off heredoc.

Graph tools had 0 calls on the v16.1 run. Removing them is not a measured
gain.

## Runtime math

Caps are unchanged, so the v16.1 dev-13 walls are the bound until this
candidate is run. L on that notebook was 498.3 seconds. The same formulas
with the earlier L of 1170 seconds are in the rightmost column.

| Gate | v16.1 measured | Pass | With L=1170 |
| --- | --- | --- | --- |
| `120 * (mean + 70) <= 39600` | `120 * (237.05 + 70) = 36846` | yes | 36846 |
| `L + 129 * mean <= 38880` | `498.3 + 129 * 237.05 = 31077.75` | yes | `1170 + 30579.45 = 31749.45` |
| `L + 129 * max <= 43200` | `498.3 + 129 * 246.76 = 32330.34` | yes | `1170 + 129 * 246.76 = 33002.04` |

If every task hits the measured maximum wall of 246.76 seconds,
`120 * (246.76 + 70) = 38011.2`, which passes 39600. A 240 second agent
cap plus the measured overhead of at most about 6.8 seconds is that
246.76 second wall. v12 used a 250 second cap and scored 0.06. This cap
is shorter. That is a known risk, not a predicted score. structured-v8
remains the scored best, at 0.10 and 0.13 on the same archive.

## Dev-13 notebook

`notebooks/structured-v16-2-dev13/evaluation.ipynb` was built with
`gemma-lab notebook`. The archive is embedded and hash-pinned. The
notebook unpacks it and compiles that plain zip. It does not register a
callback registry and it does not need a checkout of this repo. Task ids
are the dev-13 cohort and are not under `agents/`. Traces stay at
`results/traces/trace_<id>.json`. The report cell prints the v16.1 fields
(resolved, wall, no-edit runs, calls to the first edit, whether
`HYPOTHESIS:` appeared, the first `[elapsed]` at that line, whether
repair_1 returned before 240 seconds, and the hand-off elapsed) and also
whether `HAND-OFF DUE` was printed and whether `END_ROUND_1` was observed.
The stop string is consumed by the API, so a hand-off can be real while
`END_ROUND_1` is absent from the trace. Kernel metadata mounts only
`google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2`, sets `machine_shape`
to `NvidiaL4`, uses the official starter `docker_image`, and pins the
wheelhouse at `metric/gemma-4-developer-agent-wheelhouse/30`. Provenance
was generated from a clean commit of this candidate. The notebook was not
run.

## Archive

SHA256 `0539bdcd5094f1c47af6b2653bc7dff30a8ab8a1c2e4af9042daa56cb8843c27`.
20 files. Portable validation passed. Plain-zip compile with no registry
was checked on adk-submission 0.2.12 and 0.2.13. structured-v16.1's
archive is unchanged at
`2bcee926e39c71c7ca4c8b8443195c7a78fc563f3ab3b4fe0b051c61f2ad7159`.
structured-v16's archive is unchanged at
`6b8920c396f4e84fe14e7b7a907c1771436a55b840fae7464b3ce6f7cac13491`.
Base git revision: `103cbc5c064eac9feafd96086e38dc509e8b6441`.
