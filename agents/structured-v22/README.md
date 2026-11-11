# structured-v22

Unevaluated single-agent candidate. The directory is `agents/structured-v22`.
The agent name is `structured_v22`. Existing candidates were not modified.
No score is claimed. This candidate has not been run on GPU. No submission.

## Provenance and licence

The files started from the public notebook `gemma-4-baseline-lb-0-24`.
LB-0.24 notebook author not verified; Budget-Fit core by verracodeguacas;
config from `flexonafft/gemma-4-budget-aware-coding-agent-v2`. Rebuilding
that notebook's zip in this workspace produced SHA-256
`205a677fdcbd122f50ac3138b1cda0403aeb625453c93edf4c53b7b691926186`.
That hash is the unmodified bundle, not this candidate.

The public-ideas audit reports that lineage under the Apache License,
Version 2.0. An upstream LICENSE file was not in the rebuilt notebook zip,
so the report is unverified here. This archive includes that licence in
`LICENSE.txt` and the attribution in `NOTICE.md`. This lab's edits are
Apache License 2.0 as well. The prompt itself has no attribution header.

## Hypothesis

v22 keeps the bundle's single agent, thinking budget 4096, temperature 0.2,
top_p 0.95, 28 calls, 8 minutes, 240 second per-command timeout, and 80
turns. It adds output discipline and a commit rule so searches stay narrow,
reads stay at 60 lines or fewer, and an edit happens when `budget_warning`
appears or once the failing function has been read. A STATE line is repeated
on every reply. `edit_file` asks for at most 6 lines, and one sentinel
heredoc is the fallback, with an exactly-once match, `ast.parse`, and a
protected-path check. `max_output_tokens` is 6144.

This is output discipline and a commit rule. It is not a loop guard. The
submission has no callbacks, so the host cannot detect a loop, truncate tool
output, or store state. Compaction belongs to the scorer. Tool output caps
are fixed by the harness. The discipline and commit rules are prompt text,
and prompt text has been ignored before. No score and no runtime are claimed.
The candidate has not been run on GPU.

## What changed, V0–V13

- V0. Start from the bundle. Keep the removals that already helped: no graph
  tools, no `write_file`, an early edit fallback, and "a passing repro still
  means edit".
- V1. Output discipline: `git grep` with `head -20`, `read_file` windows of
  at most 60 lines, and no repeat of a command, search, or region.
- V2. One STATE line at the start of every reply: target, edited, next.
- V3. No history search and no issue-number search. History is one commit
  named baseline.
- V4. On `budget_warning`, if nothing is edited yet, the next call is an
  edit. The COMMIT RULE at the end says the same once the failing function
  has been read.
- V5. After "mandatory input parameters are not present", or a second
  `edit_file` failure, one sentinel heredoc. It checks the path, requires
  one match, and runs `ast.parse` on Python.
- V6. `old_string` is at most 6 lines, one small edit per call.
- V7. `max_output_tokens` 6144.
- V8. No attribution header in the prompt. Credit stays in this file and
  `NOTICE.md`.
- V9. Graph tools stay unregistered, and the prompt does not name them.
- V10. `write_file` stays unregistered. A new source module is one
  `run_command` heredoc.
- V11. A passing repro still means edit. Protected paths include `tests/`,
  `test/`, `testing/`, `test_*.py`, `*_test.py`, `conftest.py`, `pytest.ini`,
  and `tox.ini`.
- V12. The final command is `git status --short && git diff && python -m
  py_compile`. Verify stays at most 2 calls.
- V13. Thinking 4096, temperature 0.2, top_p 0.95, 28 calls, 8 minutes,
  240 seconds, 80 turns, one agent, no skills, no sub-agents.

Not in this candidate: top_k, temperature 1.0, presence penalties, skills,
LoopAgent, prompt clocks, a best-diff restore, or a critic.

The system prompt is 7941 characters and contains no braces. The draft was
9378. The cuts are listed in the pull request.

## Cradle limits

There is no host-side loop detector, no host-side output truncation, and no
host-side state store. Those would need callbacks, and this submission has
none. The scorer owns compaction. The harness owns the tool-output caps.
Every output-discipline and commit rule is only a prompt rule.

## Measurement plan

Not run. Before any leaderboard spend, compare this candidate with
`structured-v21-1` on the same dev-13 notebook path, at least two seeds
each. Record compactions per task, the first-edit call index, empty-diff
count, identical repeats, `edit_file` parse failures, turns at the output
cap, and mean and max wall. The plan promotes the candidate only if empty
diffs drop by at least 2 across the seeds, with no resolved loss, and mean
wall at most 300 seconds, and then uses one leaderboard slot. Those are
thresholds for a future run, not results. Submit readiness also depends on
whether the 8-minute cap fits the 12 hour budget. That question is open.

## Archive

SHA256: `6a6f10cae834f741d852391da5d6587f68cd9150c40f851753250b2ac8c39bba`

The hex above is the `gemma-lab pack` digest of this directory when that
hex is 64 zeros. Restore the zeros and pack again to recompute it. The
digest of the zip that contains the hex, which is the submission archive,
is in `docs/STATUS.md` and the pull request. This file is inside that zip,
so those two digests differ.

```bash
uv run gemma-lab pack agents/structured-v22 --output /tmp/structured-v22.zip
```
