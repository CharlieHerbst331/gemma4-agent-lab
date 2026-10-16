# structured-v10

Unevaluated candidate forked from structured-v8. structured-v8 scored 0.10 on
the leaderboard. structured-v9 scored lower; the exact leaderboard value is not
in this repository, so it is not recorded here. No new score is claimed. No
Kaggle push and no GPU run. Existing agent directories, notebooks, and archive
hashes were not edited.

The hypothesis is coverage. Losses come from a single trajectory that never
edits, or from one lucky sample, rather than from context overflow. The design
note for this candidate (16 October 2026, base `6bce7ae`) is the evidence:

- Leaderboard: structured-v8 0.10, single-v6 0.08, v3 0.03. structured-v9 is
  recorded only as lower. At p ≈ 0.10 over about 129 tasks, binomial SE is
  about `sqrt(0.09/129) ≈ 0.026` (about 3.4 tasks). A drop of 0.03 or less is
  within about one standard error. One submission slot per UTC day means a v8
  re-submit is not the comparison, so v9 is weak evidence.
- Dev-13 plateau: every thinking-off structure scored 2–3/13. The core three
  tasks are solved on nearly every run. `fastapi_11194` flips (1/7) and was
  solved only by one sampled insight at temperature 1.0. Three of the 13 tasks
  are environment-unreachable.
- Combined smoke: the dominant failure is a cap hit with no source edit (8 of
  15 runs). Prompt deadlines (165 second forced edit, 180 second handoff) were
  never obeyed. The second mode is a wrong or destructive patch, including
  SyntaxError, captured by the fallback diff.
- Heredoc edit path: 48 runs, 0 argument corruption. `edit_file` failed on
  45–53 percent of calls. The check skill was called 0 times when it was
  optional. A skill runs only when the model emits the call.
- v8 `verify_3` was about 17.5k characters, roughly 4–5k tokens, far from a
  32k window. v9's `include_contents: none` dropped tool results across roles
  to fix a context problem the 300 second runs did not have.

That is the regime where parallel samples plus an execution filter help small
models (CodeMonkeys 2501.14723, Satori-SWE EvoScale 2505.23604, Co-PatcheR
2505.18955, Agentless): pass@k rises faster than pass@1, and cheap execution
filtering recovers part of the gap. Full history stays inside each branch.
Only a diff file and a repro script cross the candidate boundary.

## Why architecture A

The compiler and google-adk 1.36.1 accept a nested
`SequentialAgent` of triage, a `ParallelAgent`, and select. Seeds, temperature
1.3, `include_contents: none`, the check skill, and explicit thinking budgets
of 0 and 256 all round-trip. An explicit budget of 0 stays 0 when the
competition default would otherwise supply 4096. Architecture B (parallel
localization, then serial repair) was not built.

What the YAML enforces:

- Triage has `tools: []` and `max_output_tokens: 1024`. It cannot search or
  edit.
- The root is `SequentialAgent` `structured_v10`: triage, then `ParallelAgent`
  `repairs`, then select. There is no `LoopAgent`.
- `repairs` has three children. google-adk 1.36.1 runs them under
  `asyncio.TaskGroup` with isolated events, so each branch sees its own tool
  history.
- `submit_patch` is only on select. A text reply after `submit_patch` ends the
  task, so only the last role may submit. `G0.early_submit` would block a
  submit on any earlier role.
- `edit_file` and `write_file` are not granted. The edit path is the
  `run_command` heredoc.
- Each repair branch has `include_contents: default`. Select has
  `include_contents: none` and reads optional `{repair_a_status?}`,
  `{repair_b_status?}`, `{repair_c_status?}`, and `{triage_brief?}`. A missing
  key becomes empty text. A required missing key raises `KeyError` and can
  skip the fallback diff, which v5 recorded, so every handoff key is optional.
  `{problem_description}` stays required, as on v8.

Diversity is the tool list, the prompt recipe, and the seed:

| Branch | Tools | Recipe | Seed | Temperature |
| --- | --- | --- | --- | --- |
| repair_a | status, read, command, graph | repro-first, then the real-repo fallback | 101 | 1.0 |
| repair_b | status, read, command | edit-first; repro only after a source edit | 202 | 1.0 |
| repair_c | status, command, graph | graph tools and sed windows | 303 | 1.3 |

`top_p` is 0.95 and `top_k` is 64 on every role. Repair includes
`repair_thinking.yaml` (`thinking_budget: 256`, `include_thoughts: true`).
Triage and select include `thinking.yaml` (`thinking_budget: 0`,
`include_thoughts: false`). Both thinking files and `skills/check` are byte
copies of structured-v8.

## Worktrees and the empty-diff fallback

Grading uses `submit_patch` when it was called, otherwise `git diff` of the
real repo against `_swegemma_baseline`. Paths under `/tmp`, including a git
worktree, are invisible unless they are applied back onto the real repo.

Each branch's first command is `git worktree add -q /tmp/cand_<letter> HEAD`.
Reads, edits, and tests run with `cd /tmp/cand_<letter>`. The branch writes
`/tmp/cand_<letter>.diff` from `git diff` in that worktree, plus
`/tmp/cand_<letter>_repro.py`. Untracked files and `/tmp` paths are not in
that diff.

Branch a, after its first edit that `py_compile`s, also runs
`cd /workspace && git apply /tmp/cand_a.diff` once. That is the empty-diff
fallback: if the selector never runs, the real repo already holds a compiling
source edit. Branches b and c are told never to edit `/workspace` and never to
`git apply` onto it.

Select votes in `/tmp/select_vote`, a separate worktree, so the fallback on
`/workspace` stays until a winner is chosen. For each non-empty
`/tmp/cand_X.diff` it runs `git apply --check`, applies, `py_compile`s changed
Python files, and cross-runs `python /tmp/cand_a_repro.py`,
`/tmp/cand_b_repro.py`, and `/tmp/cand_c_repro.py`. The winner is the compiling
diff with the most zero exits. Ties go to a, then b, then c. The install line
is `cd /workspace && git checkout -- . && git apply /tmp/cand_X.diff`. If that
compile fails, select restores `/tmp/cand_a.diff`. If nothing compiles, select
leaves `/workspace` and calls `submit_patch`.

When 45 seconds or more remain, select copies the winner repro to
`/tmp/repro_check.py` and calls
`{"skill_name":"check","file_path":"scripts/run.py"}` before `submit_patch`.
Under 45 seconds it submits the diff already on the real repo.

## Heredoc

The helper is v8's algorithm with a per-branch script and backup prefix, so
three concurrent branches do not share `/tmp/line_fix.py` or one `/tmp/pre_`
file. `ast.parse` runs before the write. After that parse succeeds, the helper
copies this PATH to `/tmp/pre_<letter>_` plus the path with `/` replaced by
`_`, then writes PATH. If `py_compile.compile` fails, the helper copies that
backup back onto PATH and onto no other file. A failed assert or `ast.parse`
never writes PATH. Repair prompts say never run git checkout. The selector is
the role that may `git checkout -- .`, and only inside the vote worktree or on
`/workspace` after `git apply --check`.

## Limits and the runtime gate

`eval_config.yaml`: `max_time_minutes: 5` (300 seconds), `max_tool_calls: 300`,
`max_turns: 480`, `timeout_seconds: 300`. v8 was 220 calls and 320 turns. Calls
and turns are shared across parallel branches. Three branches at about 60
calls each is 180, plus select, so 300 calls fits (`3 * 60 = 180 <= 300`).
The runner fallback when `max_turns` is omitted is 500
(`harness/agent_runner.py`); 480 stays under that fallback. `get_status` and
`submit_patch` do not count as tool calls. Skill script runs do count. The
clock is still the intended binding limit.

300 seconds is the largest cap whose 45 second submit deadline lands on the
255 second mean ceiling (`300 - 45 = 255`). Branches are told to stop when
`agent_elapsed_seconds` is 220 or more. That stop is prompt text.
`get_status` reports the clock and does not stop a role. If repair_a runs to
the cap, the mean can still be 300.

Overhead 70 seconds and L = 900 are the toolkit constants. The blocks use a
measured mean. The warning uses the cap.

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

## Prompts

Character counts are this revision. `chars/4` is not a Gemma tokenizer count.
No first-request token total is claimed.

| Role | Characters | chars/4 |
| --- | --- | --- |
| triage | 2119 | 529.75 |
| repair_a | 6574 | 1643.5 |
| repair_b | 5897 | 1474.25 |
| repair_c | 5923 | 1480.75 |
| select | 4781 | 1195.25 |

The completion reservation is 1024 tokens on triage and 2048 on the other
roles, inside a 32768 context. Those ceilings are harness limits, not measured
prompt tokens.

## Deviations from the design note

- Select's tools are `get_status`, `run_command`, and `submit_patch`, plus the
  check skill. The design listed `run_command`, the check skill, and
  `submit_patch`. `get_status` is how the 45 second submit rule is read. The
  aimed mean of 255 depends on that clock.
- The heredoc backup and helper are per branch: `/tmp/pre_a_` and
  `/tmp/line_fix_a.py`, and the same for b and c. The algorithm is v8's. The
  shared `/tmp/pre_` string was split so concurrent branches do not clobber
  one backup.
- `repair_c` temperature is 1.3. `top_p` and `top_k` match v8. Seeds 101, 202,
  and 303 are only on the three branches.
- Calls went from 220 to 300 and turns from 320 to 480. The cap stays 300
  seconds.
- The selector may `git checkout -- .` in `/tmp/select_vote` and, after
  `git apply --check`, on `/workspace` to replace the fallback. Repair prompts
  still say never run git checkout and do not contain `git checkout --`.
- The compile test uses the public adk-submission 0.2.11 sources
  (happyc0der/gemma-swe-agent) with `thinking_budget` `ge` set to 0, plus
  google-adk 1.36.1 and the competition `GenerationConstraints`. Real 0.2.12
  and 0.2.13 wheels are not on PyPI and were not installed. Both labeled trees
  compile this candidate. The unpatched `ge=1` tree rejects `thinking_budget`
  0. A side fixture with `include_thoughts: false` and no budget compiles to
  4096 under the 0.2.13 defaults. This candidate sets 0 explicitly, so the
  budget stays 0.

## Smoke

`configs/protocols/structured-v8-vs-structured-v10-smoke.yaml` compares
structured-v8 (arm A) and structured-v10 (arm B) on the combined five tasks,
in that order: `rich_4070`, `rich_3934`, `fastapi_11194`, `rich_3938`,
`fastapi_14262`. Purpose is smoke. `matched_pair` is false because the call
and turn budgets differ and because `repair_c` uses temperature 1.3.
`allowed_differences` includes `eval_config.yaml` and `sampling.yaml`.
Repeats is 1. The schedule hash is
`5672ef15323e1d59847cc7cde3f1b6cb1912346d7456b13cb716902437b3e9fd`.
`pair_fits_minimum_budget(5, 2, 300, extra_elapsed=300)` is 4320 seconds.
Session budget is 14400 seconds, under the 43200 second warn cap. No GPU run
is started from this file. One repeat cannot name a winner.

```bash
uv run gemma-lab pack agents/structured-v10 --output /tmp/structured-v10-submission.zip
```

Archive sha256
`e9fd99c7c15233f3e6bf658e4283f0418c66ff3c5bded020d22ac26e6867e932`
(17 files). Repacking structured-v8 and structured-v9 still matches
`9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e` and
`209bd43ed52731813ecc4fc8d40edea186bd1af2a6f00e18acf5aae7809b18a5`.

## Open risks

- Branches may ignore the 220 second prompt stop, so select never runs. The
  mitigation is branch a's real-repo apply after the first compile. If nothing
  compiles, the fallback diff can still be empty.
- Select might `git checkout -- .` on `/workspace` before a winner is chosen
  and clear the fallback. The prompt orders the steps. The harness does not
  enforce that order.
- `docker exec` may serialize `run_command` across branches. That was not
  measured. Three concurrent vLLM streams are expected at about 1.2–1.6×
  per-step latency. That was not measured. No GPU slot was used.
- Worktree imports can miss an installed package. Prompts set
  `PYTHONPATH=/tmp/cand_X/src:/tmp/cand_X` and tell the model to probe import
  origin.
- Prompt deadlines are not harness-enforced. A measured mean of 300 seconds
  fails both block checks. The cap itself warns and does not block.
- A shared `/tmp/pre_*` backup is still possible if the model ignores the
  branch-specific name.
- No concurrency stub (`sleep 5`) was run. The design's pre-submit GPU probe
  was not done.
- Small score changes sit inside about one standard error. This document does
  not claim structured-v10 will score above 0.10.
