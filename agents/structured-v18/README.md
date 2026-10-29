# structured-v18

Unevaluated full localize/patch split. The directory is `agents/structured-v18`
and the agent name is `structured_v18`. The tree started as a copy of
`agents/structured-v13-1`. `skills/check` is the `agents/structured-v17` copy.
Existing agent directories, archives, and evidence were not modified. No score
is claimed. No GPU run and no submission yet.

## Hypothesis

v17 (hypothesis-then-edit) scored 0.12, tying v13-1, below v8 at 0.13. The
main recoverable loss is never-edit (about 50 of 118 tasks with a zero diff),
caused by exploration tools in repair roles and soft empty-diff escapes.
Structurally removing read and graph tools from the patch phase and deleting
those escapes should raise edit-rate and score.

## What this candidate does

Sequential roles: triage, then localize_1 (read-only tools, no `run_command`),
then `patch_1_loop` (`LoopAgent`, `max_iterations: 2`, `get_status` and
`run_command` only, plus the force-heredoc skill), verify_1, `patch_2_loop`
(same tool limit), verify_2, patch_3 (one pass, same tool limit), verify_3.
Empty-diff time escapes are deleted from the patch roles. Verify handoffs use
`{patch_N_report?}` slots, and patch_1 reads `{localize_1_report?}`. YAML,
prompts, and skills only. No Python callbacks. The budget stays 300 seconds,
220 calls, and 320 turns. There is no hard per-task cap and no new prompt clock.

## Archive

The submission SHA256 is recorded in `docs/STRUCTURED_V18.md` and the pull
request. This README is inside the packed archive, so repeating the digest
here would change it.

```bash
uv run gemma-lab pack agents/structured-v18 --output /tmp/structured-v18.zip
```
