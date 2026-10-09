# structured-v6 and single-v2

Unevaluated pair forked from `agents/structured-v5t0` and `agents/single-v1t0`.
No GPU run and no submission. The ten earlier archive hashes stay the recorded
values. `configs/protocols/v5-vs-single-v1.yaml` is not this pair.

Protocol: `configs/protocols/v6-vs-single-v2.yaml` (arm A `agents/structured-v6`,
arm B `agents/single-v2`). Shape, model, sampling, and budgets are the t0 pair:
thinking off (`include_thoughts: false`, `thinking_budget: 0`), 270 seconds
(`max_time_minutes: 4.5`), 48 counted calls, 64 turns, 300 second command cap.
`thinking.yaml` and `eval_config.yaml` are byte-identical across the two new
trees and match the t0 parents. The triage / repair / verify loop is unchanged.
Repair still has no `submit_patch`. Verify still has no `run_command`.

## What changed

r1b (v5t0 vs single-v1t0, dev-13) lost most empty patches to tool-protocol
failures and exploration with no edit. These trees change the verify-patch skill
and the role prompts.

- One literal `run_skill_script` call, with top-level `skill_name`, `file_path`,
  and `args`, is in both `SKILL.md` files and in repair, verify, and the single
  prompt, plus the sentence "Never put skill_name or file_path inside args".
- `check.py` defaults `--mode` to `repro` when a phase is present. A missing
  mode on a call that already has phase and code is a behavior check. Audit
  stays explicit. If both mode and phase are omitted, the script prints the
  corrected example instead of running a default verify phase (that path used
  to answer "Baseline repro changed"). A bad argument prints the same example
  instead of stock argparse usage. The example code is
  `assert 1 == 2  # put the real failing assert here`, a failing placeholder.
- The harness error `INVALID_ARGUMENTS` (`Argument file_path is required`) is
  raised before `check.py` runs, when `file_path` is nested inside `args`. That
  string is not produced by this repo and cannot be changed from the agent.
  Only the prompt and the skill can steer the next call. If a tool returns the
  same error twice, the prompt says not to repeat it and to switch to
  `run_command` or `edit_file` (verify has no `run_command`, so it switches to
  `edit_file` only).
- `edit_file` strings stay a few plain lines, without backticks, `\n` escapes,
  or quote-heavy text. After one missing-parameter error, retry a smaller edit.
  After a second failure, repair and the single agent rewrite the line with
  `run_command` and a short Python snippet that must not touch tests,
  `conftest.py`, `pyproject.toml`, or `setup.cfg`. If that rewrite fails too,
  repair hands off in its final report and the single agent calls
  `submit_patch` with the current diff. Verify has no `run_command`: after a
  second `edit_file` failure it stops editing and calls `submit_patch` with
  the current diff.
- The primary edit point stays about 12 counted calls or about 95 seconds.
  About 30 counted calls, or about 18 calls remaining, is only the hard
  backstop. Verify hands back only when more than 90 seconds remain. A
  hand-back reply starts with `loop_iteration: N` (the iteration it received)
  and the next line is `next loop_iteration: N+1`, which repair reads as its
  counter. At 90 seconds or less with no edit, verify makes its best-guess
  edit and submits. Fewer than 60 seconds means do not start a new repro.
  Under 20 seconds, submit as is. The empty UNCERTAIN submit remains only when
  the issue text is just an issue number, such as `Fix #3104`, and that case
  still says no search. A copied placeholder assertion is refused before it
  can pin a baseline.
- Scratch stays in `/tmp` or top-level `/workspace/build/`. Do not write
  `repro.py` or `repro*.py` inside the repo.

## Prompt size

No Gemma tokenizer is installed here. Counts are characters, and the token
estimate is characters divided by 4. Output caps are unchanged (triage 1024,
repair 2048, verify 1536, single 2048). The 2048 cap leaves a 30720-token
prompt ceiling inside 32768. These instruction files stay far under that.

| File | Chars before | Chars after | Est. tokens before | Est. tokens after |
| --- | ---: | ---: | ---: | ---: |
| structured-v5t0 `sub_agents/triage.md` | 2174 | 2174 | 543 | 543 |
| structured-v5t0 `sub_agents/repair.md` | 4691 | 6332 | 1172 | 1583 |
| structured-v5t0 `sub_agents/verify.md` | 4715 | 7919 | 1178 | 1979 |
| verify-patch `SKILL.md` (both trees) | 3702 | 4399 | 925 | 1099 |
| single-v1t0 `prompts/system.md` | 6221 | 7980 | 1555 | 1995 |

## Archives

Packed with `gemma-lab pack` to `/tmp` (archives are not committed). The ten
parent hashes matched their recorded values on the same pack.

- structured-v6: `6d324b008ea5c3a389d34277087433200e2521fd17edfd7b3ddc616c965e6e56`
- single-v2: `28d5b6e46ad8a95d1ed48086f5c63b003a3d78a11e281c210dd98a3b0d40325c`

swegemma 0.2.10 and adk-submission 0.2.13 are not installable from PyPI in this
environment, and this VM has no Kaggle credentials. Stub capture of the thinking
config stays with Verification.
