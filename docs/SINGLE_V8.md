# single-v8 and single-v8-check

Unevaluated copies of `agents/single-v7`. No score is claimed. No Kaggle push
and no GPU run. `docs/STATUS.md` is unchanged. `structured-v7` is not started.

`agents/single-v8` has no skills. `agents/single-v8-check` is the same agent
plus one flat `check` skill. Thinking stays off: `thinking.yaml` is a byte
copy of single-v7 (`include_thoughts: false`, `thinking_budget: 0`).

## Edit path

`run_command` is the primary edit. The harness tools are the nine built-ins.
There is no custom editor, so the agent writes `/tmp/line_fix.py` itself with
a quoted heredoc, runs it, and prints `git diff`. The snippet reads and writes
bytes, asserts `s.count(old) == 1` before `str.replace`, and asserts the new
bytes are present after. `OLD` and `NEW` are triple-quoted byte strings
(`b'''...'''`). They must not contain a backslash or `'''`. A line break can
be `\n` inside `b"..."`. Non-ASCII bytes need `\xNN`. `read_text` and
`write_text` are forbidden because they turn a CRLF file into LF. `edit_file`
stays secondary, for a short one-line change, and that path still forbids
`\n` escapes. The single-v7 second-error rule still applies to that
secondary path: one missing-parameter retry, never the same failing call more
than once, and after the second `edit_file` error of any kind on that file
(`mandatory input parameters are not present`, `Failed to replace: old_string
not found`, or `Target string occurs N times`) stop using `edit_file` and use
the recipe. The public-wrapper sentence is its own paragraph. Protected paths
are unchanged.

The rich_4070 loop was a repeated missing-parameter `edit_file` call, not an
`old_string` miss. `run_command` takes one string and was not corrupted in the
smoke traces (0 of 395 calls). Whether the model follows the new recipe is
untested. It needs a GPU run.

## Limits

`eval_config.yaml` sets `max_time_minutes: 5.5` (330 seconds),
`max_tool_calls: 150`, `max_turns: 200`, and `timeout_seconds: 300`. The
harness reads `max_time_minutes`. The per-command ceiling stays 300 seconds.
The prompt's first edit is by about 90 seconds or about 38 counted calls. The
hard edit point is about 165 seconds or about 75 counted calls. Call
`get_status` about every 5 calls, and again before `submit_patch`, so those
clocks stay current. Keep editing only while the check has not passed and
more than 60 seconds remain. After a passing check, run `git diff` and call
`submit_patch`. The last 60 seconds submit the current diff. Under 20
seconds, if the diff is still empty, make one minimal edit and then submit.
Do not submit an empty diff, including for a bare issue number. `not
reproducible`, `already fixed`, and `not a bug` do not end the task. Call
counts are not a reason to stop.

## Runtime gate

Constants in `src/gemma_lab/operations.py`: overhead 70 seconds, default load
L = 900 seconds, block limit 11 hours (39600 seconds) on
`120 * (measured mean + 70)`, block limit 10.8 hours (38880 seconds) on
`L + 129 * measured mean`, warn limit 12 hours (43200 seconds) on
`L + 129 * (cap + 70)`. The cap is not an input to either block check.

Per-task cap: **330 seconds**.

| Cohort | Tasks | Repeats | Arms | Task-runs | Agent time if every run hits its cap |
| --- | --- | --- | --- | --- | --- |
| dev-13 (v7 vs v8) | 13 | 1 | 2 | 26 | 13×270 + 13×330 = 7800 s |
| smoke (v8 vs v8-check) | 5 | 1 | 2 | 10 | 10×330 = 3300 s |

Worst case if the cap is treated as the time of every hidden task:

- `120 * (330 + 70) = 48000` seconds = 13.333 hours
- `900 + 129 * (330 + 70) = 52500` seconds = 14.583 hours

Verdict: **WARN**, not BLOCK. The warn check fails. The block checks do not
read the cap. single-v7's 270 second cap also warns:
`900 + 129 * (270 + 70) = 44760` seconds.

The largest cap that is OK on the warn formula is
`(43200 - 900) / 129 - 70 = 257.907` seconds. That is tighter than single-v7,
so this candidate keeps 330 seconds, which is the failsafe in the Oct 11
investigation. If a later measured mean equals 330 seconds, the 11 hour block
fails. The largest mean that still passes that block is 260 seconds
(`39600 / 120 - 70`). Re-measure on dev-13 before any promotion. The 70 second
overhead and whether a 12 hour overrun still errors the whole submission are
still estimates from the host thread, not a live confirmation.

## Sampling

`adk_submission.schema.GenerateContentConfig` accepts `temperature`, `top_p`,
and `top_k`. `agents/single-v8/sampling.yaml` sets temperature 1.0, top_p
0.95, and top_k 64, the model-card values. `max_output_tokens` stays 2048.
The pair checker compares temperature, top_p, and thinking. It does not
compare `top_k`. A temperature change is refused unless `allowed_differences`
lists the literal `sampling.yaml`. Listing `agent.yaml` does not do it.
Thinking still has to match unless `thinking.yaml` is listed too.

`matched_pair: false` still skips only the shared-file check. A budget change
is refused unless the pair is unmatched and `eval_config.yaml` is listed.
Each half of that rule was already tested on its own, so neither half was
loosened. The pair-checker helpers sit after the notebook runtime marker.

The session-level cap in a generated notebook, and in `report_from_runs`, is
the larger of the two arm caps. That number feeds the abort check
(`wall > cap + 120`), `hit_cap.wall`, and the report. Per-arm evaluator
limits stay on each arm: single-v7 is 270 seconds, 48 calls, and 64 turns;
single-v8 is 330 seconds, 150 calls, and 200 turns. The unmatched dev-13
notebook therefore uses 330 seconds as the session cap. When both arms share
a cap, the embedded literal is unchanged, so notebooks for the older
protocols stay byte-identical.

## Check skill

`agents/single-v8-check/skills/check/` has `SKILL.md` and `scripts/run.py`.
The only call is `{"skill_name":"check","file_path":"scripts/run.py"}` with
no args. The prompt adds that one sentence. The script pins the repro, reruns
it, prints `git status --short` with scratch and protected flags, prints
`git diff --stat`, and runs at most one mapped pytest for 15 seconds. It
does not edit.

The subprocess sandbox used by the dev and smoke notebooks rewrites `/tmp`
and `/workspace` only inside command strings, and ADK runs the script from a
temp directory. Hardcoded `/tmp` and `/workspace` paths in the script itself
pointed at the host, so the report stayed `before: PASS (repro does not fail
yet...)`, `not a git repository`, and an empty diff stat. The script now
reads the repro and the pin from `tempfile.gettempdir()` (the sandbox
`TMPDIR`) and finds the repo from `GEMMA_CHECK_ROOT`, then `/workspace`, then
a `PYTHONPATH` entry that contains `.git`. The agent still writes the repro
with `run_command` to `/tmp/repro_check.py`, because that command string is
what the sandbox rewrites. Harness-staged `conftest.py` and `pytest.ini` are
not marked `[protected]` when they are the only changes. A Docker sandbox
with a real `/workspace` was not tested. Whether the model emits the constant
call is untested.

## Archives and protocols

- single-v8 sha256 `6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22`
- single-v8-check sha256 `64dc727d78c4189c1db1184e74129290574c7b97816dd91f91d2baa7defe0fb0`
- Prompt sizes: single-v7 8024 characters, single-v8 8283, single-v8-check 8524.
  The ceiling is 30720 tokens inside a 32768 context after the 2048 completion
  reservation. 8524 characters is about 2131 tokens at four characters per
  token, not a Gemma tokenizer count.
- `configs/protocols/single-v7-vs-single-v8-dev13.yaml` schedule
  `629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed`
  (same as the other one-repeat dev-13 protocols; the schedule hash does not
  include the arms).
- `configs/protocols/single-v8-vs-single-v8-check-smoke.yaml` schedule
  `5672ef15323e1d59847cc7cde3f1b6cb1912346d7456b13cb716902437b3e9fd`.
  Tasks, in order: rich_4070, rich_3934, fastapi_11194, rich_3938,
  fastapi_14262. The first three are the required bad-call or empty-patch
  tasks. rich_3938 is the other give-up from both arms of the v5/v6 dev-13
  run that was also in the older five-task smoke. fastapi_14262 had stray
  `start_line` reads and merged `edit_file` calls. fastapi_14786 is left out
  because it is the usual solve, not a bad-call task.

The eighteen previous archive hashes are unchanged, including single-v7
`f62c8c0b92bc5bd1fb1015f20e7cbd7a5599d5518d2d59097bf2b40d9f3412b0`.
Hygiene output is under `/tmp`. The hygiene rules were not edited on this
branch. `notebook.py` changes only the session-cap literal for unequal arms.
