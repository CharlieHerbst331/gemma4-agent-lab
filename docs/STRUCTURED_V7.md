# structured-v7

Unevaluated copy of the structured-v6 loop. No score is claimed. No Kaggle
push and no GPU run. `docs/STATUS.md` is unchanged. `notebook.py`,
`paired.py`, and the hygiene code were not edited.

## What the spec asked, and what the YAML can express

Per-role thinking is supported. Each `LlmAgent` has its own
`generate_content_config.thinking_config`. The old "single knob" was one
shared include, not a schema limit. Repair includes
`sub_agents/repair_thinking.yaml` (`include_thoughts: true`,
`thinking_budget: 256`). Triage and verify include `sub_agents/thinking.yaml`
(`include_thoughts: false`, `thinking_budget: 0`). 256 is the small budget
from single-v5-think256. The harness default of 4096 is not used. A budget of
0 turns thinking off on adk-submission 0.2.12 and 0.2.13. It does not compile
on 0.2.11.

Full history between roles is `include_contents: default` on triage, repair,
and verify. structured-v6 set `none`, which drops the other role's tool
transcript and leaves only its final text. `include_contents` is legal on
`LlmAgent` only. The SequentialAgent and the LoopAgent do not set it.
ADK event compaction is not an `agent.yaml` field. The starter notebook still
sets `EventsCompactionConfig` (`token_threshold=14336`,
`event_retention_size=5`). That can still replace tool calls with a summary
once the prompt is large. This candidate does not change that notebook
setting.

## Skill

The three structured-v6 skills are not copied. Their `run_skill_script` calls
took a free-form `args` object, and 107 of 279 calls in the r1b run were
rejected for nesting. The research rank for a skill that is actually robust
is one flat, zero-argument `check` (`{"skill_name":"check","file_path":"scripts/run.py"}`).
Verify has that skill. The script is a byte copy of the single-v8-check
script that reads the repro from `tempfile.gettempdir()` and finds the repo
from `GEMMA_CHECK_ROOT`, then `/workspace`, then `PYTHONPATH`. Repair does
not get a skill. Its edit path is `run_command`, which had 0 corrupted calls
in 395. Whether the model emits the constant check call is untested.

## Edit path and empty diffs

Repair's primary edit is the single-v8 quoted heredoc to `/tmp/line_fix.py`
(`b'''OLD'''` / `b'''NEW'''`, `assert s.count(old) == 1`). `edit_file` stays
secondary, including the second-error stop. Repair has no `submit_patch`.

Verify has `run_command`. If `git diff` is empty and time remains, it does
not submit. It hands back to repair with `loop_iteration` and the line
"make the most plausible minimal edit; do not submit an empty diff." On the
last iteration, or under 20 seconds, verify makes one minimal edit itself
and then submits. It does not submit an empty diff. A passing check is
followed by `git diff` and `submit_patch`.

## Limits and the runtime gate

`eval_config.yaml`: `max_time_minutes: 6` (360 seconds), `max_tool_calls: 150`,
`max_turns: 200`, `timeout_seconds: 300`. Sampling on every role is
temperature 1.0, top_p 0.95, top_k 64.

The cap is not an input to either block check. Overhead 70 seconds, L = 900.

- `120 * (360 + 70) = 51600` seconds = 14.333 hours
- `900 + 129 * (360 + 70) = 56370` seconds = 15.658 hours

Verdict: **WARN**, not BLOCK. The 12 hour warn fires. The blocks read a
measured mean, not the cap, so 360 seconds is kept. The largest cap that is
OK on the warn formula is `(43200 - 900) / 129 - 70 = 257.907` seconds.
If a later measured mean equals 360 seconds, the 11 hour block fails. The
largest mean that still passes that block is 260 seconds. Dev-13 agent time
if every run hits its own cap is `13 * 330 + 13 * 360 = 8970` seconds, inside
the 40200 second session budget.

## Prompts

Characters, then a four-characters-per-token estimate. The ceiling is 30720
tokens inside 32768 after the 2048 completion reservation.

| Role | Characters | About tokens |
| --- | --- | --- |
| triage | 1771 | 443 |
| repair | 5152 | 1288 |
| verify | 3375 | 844 |

Against structured-v6, by role:

- Triage stays tool-free. It no longer treats a bare issue number as a stop.
  It tells repair the history is the full transcript.
- Repair drops source-lookup and verify-patch. The first edit is the
  `run_command` heredoc, at about 90 seconds or 38 calls, instead of
  `edit_file` at 12 calls or 95 seconds. There is no UNCERTAIN empty handoff.
- Verify gains `run_command` and the flat check, and loses the dict-args
  verify-patch calls. An empty diff is handed back instead of submitted.
  "Submit as is" is gone.

## Archive and protocol

- structured-v7 sha256 `bdd1ed74fd8249647c6e5c88ed3619564f51569b86bab2762db5eb53f9f6d2e8`
- The twenty previous archive hashes are unchanged, including single-v8
  `6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22` and
  single-v8-check `64dc727d78c4189c1db1184e74129290574c7b97816dd91f91d2baa7defe0fb0`.
- `configs/protocols/single-v8-vs-structured-v7-dev13.yaml` is dev-13, one
  repeat, A single-v8, B structured-v7, `matched_pair: false`. Markers:
  `eval_config.yaml`, `sampling.yaml`, and `thinking.yaml`. The schedule hash
  is `629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed`, the
  same as the other one-repeat dev-13 protocols.

Whether the model follows the heredoc, the empty-diff handoff, or the 256
token thinking budget needs a GPU run. The 70 second overhead is still an
estimate. Compaction on the hosted scorer is unconfirmed.
