# structured-v18-1

Unevaluated copy of structured-v18 with two localize and patch-prompt changes.
The directory is `agents/structured-v18-1` and the agent name is
`structured_v18_1`. Existing candidates, including structured-v18, were not
modified. No score is claimed. No GPU run and no submission yet.

## Hypothesis

v17 scored 0.12 public, v13-1 scored 0.12, and v8 scored 0.13. Those three
are within noise. v18 removed read and graph tools from the patch phase so
an empty diff is harder to finish without an edit. This copy keeps that
split. It also stops localize_1 from holding the 300 second cap with an
empty diff, and it puts the line_fix heredoc in the patch prompts so the
edit does not depend on load_skill.

## What changed

localize_1 stays one sequential `LlmAgent`. It is not a `LoopAgent`.

Hard levers the harness enforces:

- `max_output_tokens: 512` on localize_1. Each completion is cut there.
- `stop_sequences: [END_LOCALIZE]`. Generation stops when that marker is emitted.
- Tools are `get_status` and `read_file` only. Graph tools are not granted.

Prompt-only, which the harness does not enforce:

- At most 6 tool calls, then the `HYPOTHESIS` line and `END_LOCALIZE`.
  There is no per-role call cap in the schema.

patch_1, patch_2, and patch_3 prompts include the line_fix heredoc. They say
not to call load_skill. The force-heredoc skill stays attached. No Python
callbacks. The budget stays 300 seconds, 220 calls, and 320 turns.

## Archive

SHA256: `see docs/STATUS.md and the pull request`

```bash
uv run gemma-lab pack agents/structured-v18-1 --output /tmp/structured-v18-1.zip
```
