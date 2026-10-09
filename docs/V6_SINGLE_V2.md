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
- `check.py` defaults `--mode` to `repro`. A missing mode on a call that already
  has phase and code is a behavior check. Audit stays explicit so a forgotten
  mode is not treated as hygiene-only. A bad argument prints that same example
  call instead of stock argparse usage.
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
  `conftest.py`, `pyproject.toml`, or `setup.cfg`.
- By about 30 counted calls, or when about 18 calls remain, there must be a
  source edit. Do not read more than about 8 files before that edit. If still
  unsure, make the smallest change the issue text implies and submit it. The
  empty UNCERTAIN submit remains only when the issue text is just an issue
  number, such as `Fix #3104`, and that case still says no search.
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
| structured-v5t0 `sub_agents/repair.md` | 4691 | 5733 | 1172 | 1433 |
| structured-v5t0 `sub_agents/verify.md` | 4715 | 6171 | 1178 | 1542 |
| verify-patch `SKILL.md` (both trees) | 3702 | 4277 | 925 | 1069 |
| single-v1t0 `prompts/system.md` | 6221 | 7344 | 1555 | 1836 |

## Archives

Packed with `gemma-lab pack` to `/tmp` (archives are not committed). The ten
parent hashes matched their recorded values on the same pack.

- structured-v6: `f4bb0ed0bfaa7bfa5d7634f18e74a0d9289b950414578c2e804288f0f7fe3bed`
- single-v2: `c764637f85cd63f465d45f2ffdef02f43b59586dabbee033d4f42f0d19152251`

swegemma 0.2.10 and adk-submission 0.2.13 are not installable from PyPI in this
environment, and this VM has no Kaggle credentials. Stub capture of the thinking
config stays with Verification.
