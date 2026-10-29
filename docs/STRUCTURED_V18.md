# structured-v18

Unevaluated full localize/patch split. The directory is `agents/structured-v18`
and the agent name is `structured_v18`. The tree started as a copy of
`agents/structured-v13-1`. `skills/check` is the `agents/structured-v17` copy.
Existing agent directories, archives, and evidence were not modified. No score
is claimed. No GPU run and no submission yet.

## Hypothesis

v17 (hypothesis-then-edit) scored 0.12 public, Kaggle ref 57718020, tying
v13-1, below v8 at 0.13. The main recoverable loss is never-edit (about 50 of
118 tasks with a zero diff), caused by exploration tools in repair roles and
soft empty-diff escapes. Structurally removing read and graph tools from the
patch phase and deleting those escapes should raise edit-rate and score.

That comparison has not been run. Do not read the v17 or v13-1 scores as a
v18 score.

## What changed

Sequential roles:

1. triage, copied from v17, with no tools
2. localize_1, read-only tools, no `run_command`, ends on one `HYPOTHESIS` line
3. `patch_1_loop`, a `LoopAgent` with `max_iterations: 2`, wrapping patch_1
4. verify_1
5. `patch_2_loop`, the same loop limit, wrapping patch_2
6. verify_2
7. patch_3, one `LlmAgent` pass, no loop
8. verify_3, the only role with `submit_patch`

Patch roles have `get_status` and `run_command` only, plus the force-heredoc
skill. They do not have `read_file` or graph tools. Verify handoffs use
`{patch_N_report?}` slots. patch_1 reads `{localize_1_report?}`. The
empty-diff line that allowed a text-only ending under 45 seconds while
`git diff` was empty is not in the patch prompts. verify_3 still attempts one
emergency heredoc when the diff is empty, then calls `submit_patch`.

YAML, prompts, and skills only. No Python callbacks. The hosted compiler drops
callbacks, so this candidate does not declare any. The budget stays 300
seconds, 220 calls, and 320 turns. There is no hard per-task cap and no new
prompt clock. The minimal A/B fallback was not used. The full split compiled.

## Disclosures

`LoopAgent` `max_iterations: 2` retries an idle patch pass. It does not stop a
pass that keeps calling `get_status`. A text-only ending is still possible.
The heredoc still requires exact bytes, so a failed assert can leave the diff
empty. verify_3 is the last attempt, and it is also prompt compliance.

verify_1 and verify_2 still say that under 90 seconds the next response is
text only and the check is not called. That line is in the paste. It skips
the check. It is not the deleted repair escape that allowed an empty diff to
finish while time remained.

No v18 cohort has been run.

## Deviations from the paste

- `eval_config.yaml` is the v17 file. One comment names structured-v18. The
  numbers match the paste and v17: `timeout_seconds` 300, `max_tool_calls`
  220, `max_time_minutes` 5, `max_turns` 320.
- `thinking.yaml`, `repair_thinking.yaml`, `triage.yaml`, and `triage.md` are
  byte copies of v17. The paste printed shorter comments on the thinking
  files. The fields match: triage and verify use `thinking_budget: 0`, and
  patch roles use `thinking_budget: 256`.
- `skills/check` is a byte copy of v17. That tree matches v13-1.
- The candidate `README.md` is packed with the archive, so it states the
  hypothesis and points here for the digest. Embedding the digest in that
  README would change the digest.

## Archive

SHA256 `b6137580f3870e312491f68f97cfdd36cb88d89387dbd782d8007ba3056b42d5`.
26 files. Portable validation passed. Plain-zip compile with no registry was
checked on adk-submission 0.2.12 and 0.2.13, using the public compiler
sources with `thinking_budget` `ge` set to 0, plus google-adk 1.36.1. Real
0.2.12 and 0.2.13 wheels are not on PyPI. Both labeled trees compiled this
candidate. structured-v17 is unchanged at
`27b47d34554d9b64f3786b430856dd950d678d5ea6dbd4a0ae6fb7dd687e79e6`.
structured-v13-1 is unchanged at
`74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe`.

Pack command:

```bash
uv run gemma-lab pack agents/structured-v18 --output /tmp/structured-v18.zip
```
