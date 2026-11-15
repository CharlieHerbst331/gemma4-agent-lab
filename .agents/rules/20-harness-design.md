---
trigger: glob
globs: "agents/**"
description: Design constraints for submission agents (agent.yaml, prompts, sampling, eval budget).
---

# Harness design constraints (apply when editing anything under agents/)

Hard facts:
- YAML only. No Python callbacks: no host-side loop detector, output truncation, or state
  store. Hard levers are the tool list, eval budget, `max_output_tokens`, stop sequences,
  thinking config, and prompt content. Prompt-only clocks and caps get ignored.
- The scorer compacts context at 14,336 tokens (retains the last 5 events). The first request
  is already 4–5.5k tokens. Keep `prompts/system.md` ≤8k chars and free of `{` `}`.
- Tool output is capped by the harness (5000 chars stdout; read_file 150 lines / 10k chars).
- Rejected tool calls (missing parameters) do not count against `max_tool_calls` but burn
  turns and wall time.

Keep (measured to help or be neutral):
- One LlmAgent; tools run_command, read_file, edit_file, get_status, submit_patch.
- Thinking on, `thinking_budget: 4096`, `include_thoughts: true`; max_output 6144–8192.
- Temperature 0.2, top_p 0.95 (temperature 1.0 is untested here; ablate on dev only).
- 28 calls, 240 s per command, 80 turns; per-task minutes tuned so the dev-13 mean is ≤300 s.
- Narrow greps (`-- '*.py' | head -20`), read windows ≤60 lines, `git diff --stat`, a one-line
  STATE note per reply, a commit rule tied to the literal `budget_warning`, the passing-repro
  rule, py_compile before finishing, protected test paths.

Do not reintroduce (measured to hurt):
- Thinking off, thinking budget 256, output caps of 1–2k.
- Multi-role chains, LoopAgent safety nets, critics, parallel branches.
- Skills / run_skill_script, graph tools, write_file.
- Hard caps of 4–4.2 minutes, or call budgets around 22–25.
- Stale lines about tools that are not registered; attribution text inside the prompt.
- Issue-number or git-history searches (the repo history is a single `baseline` commit).

Every new agent directory needs: README.md (hypothesis, deltas vs base, expected effect),
NOTICE.md and LICENSE.txt carried from its base, `uv run gemma-lab validate agents/<name>`
passing, and a `docs/STATUS.md` entry with its sha256 and pack command.
