# Resume here — handoff to another coding agent

This document is written for a new agent with no chat history. Read AGENTS.md,
README.md, this file, STATUS.md, and HARNESS_SPEC.md before changing anything.

## Objective and current state

Build a technically credible, competitive offline Gemma4 coding agent for Kaggle's
Google – The Gemma4 Developer Agent competition. Preserve honest experiment evidence.
The code is a prototype; a3/3 selected diagnostic does not establish generalization.

Latest evaluated candidate: `agents/structured-v4-10m`.
Unevaluated fork: `agents/structured-v5` (see `docs/STRUCTURED_V5.md`). It is not
a measured improvement and has not been submitted. v4-10m and its archive stay
the comparison baseline.
Latest evaluated archive SHA256:
`0730b5f0a373fc23bdb4362779a4757ded14cfa6a77896c7d54ce3efb7ad8cab`.
Candidate code commit: `b00526833928c5ce9f1e181b77ad982e5bf12e84`.

It resolved3/3 on the diagnostic IDs in `configs/cohorts/diagnostic-3.json` versus
five-minute structured-v4's1/3. Two wins, no regression on those three IDs. Two
successful patches still contain workspace scratch and use fallback capture. Only
one case explicitly finalized a clean source-only patch and used verification skills.
The broader dev cohort has NOT been evaluated with the10minute candidate. Holdout
has never been evaluated or used for tuning/training. No adapter has been trained.

Actual competition submission: simple-v3, ref56905832, SHA256
`50d7b69dd4d0f6a5b4925bda919f69e57196b72337190bd6073be95591ff2646`.
It was accepted for upload, but fresh account history at publication reports ERROR,
with no public/private score. The CLI did not provide the failure cause. Do not
confuse successful upload or local3/13 with a successful leaderboard evaluation.
Resolve the server error before repeating uploads; preserve the submission ledger.

No model/GPU run, collector, paid hardware, training, or recurring job is active.

## What is implemented

A declarative SequentialAgent routes exactly three Gemma LlmAgent roles:
1. Tool-free triage: one response containing issue/hint/layout clues.
2. Repair: source evidence, reproduction, minimal implementation edit.
3. Verify: explicit compact state, isolated conversation history, verification/audit,
   then submit_patch. It is frequently not reached before the task deadline.

All use gemma-4-31b-it-qat-w4a16-ct. Current task budget is10min total across roles,
80 counted tools,60 turns,300s command cap. Repair's360s handoff is a SOFT prompt target.
Official get_status/submit_patch are free of counted calls, not free of wall time.

The three bundled skills are scoped:
- task-memory: atomic/locked bounded factual ledger in task scratch, tied to workspace
  and baseline identity; no whole transcripts or cross-task repair answers.
- source-lookup: bounded literal lookup/windows; no writes; optional graph fallback.
- verify-patch: assertion-based scratch repro, same-source before/after contract,
  real exit status, timeout/process cleanup, freshness fingerprints, read-only audit.

All64 original tests pass; publication adds export-redaction tests. The CPU official
SDK preflight exposed skill tools and executed the scripts successfully. However,
Gemma generally bypasses them through raw shell/file tools. More skills alone will
not fix adoption or enforcement. See STRUCTURED_V4*.md for measured behavior.

## First useful work

1. Inspect capability bypasses, scratch leakage, missed finalization and installed-
   package versus workspace imports. Preserve current candidates/results.
2. Test a narrowly scoped variant that makes needed structured operations the default:
   fewer raw-shell bypasses and explicit first skill activation. Do not invent an
   unsupported per-role quota/callback or alter official grading to inflate scores.
3. Compare with a matched triage-only/native-tool or single-agent control. Global
   time/model/sampling/cohort differences must be recorded. Repeat key tasks to measure
   variability before attributing a gain to one component.
4. Evaluate the same diagnostic cohort, then the broader dev cohort if warranted.
   Keep holdout for a predeclared milestone. Do not train from any dev/holdout trace.
5. Promote only after patch hygiene, independent verification, runtime and paired
   regressions are understood. A10min cap may exceed the competition-wide12hour
   generation limit if too many tasks consume it; measure actual aggregate timing.

## Reproduce on a new machine

```bash
uv sync --locked
make check
uv run gemma-lab validate agents/structured-v4-10m
uv run gemma-lab pack agents/structured-v4-10m \
  --output artifacts/structured-v4-10m/submission.zip
```

Competition inputs, raw evidence, generated notebooks and credentials are not bundled.
Use your own authorized Kaggle login and accept rules yourself through Kaggle if needed.
Do not obtain a token from this repository or ask anyone to commit credentials.

```bash
uv run kaggle auth login
uv run gemma-lab fetch-starter
uv run gemma-lab fetch HARNESS_README.md tasks.jsonl
uv run gemma-lab notebook agents/structured-v4-10m --owner YOUR_KAGGLE_USER \
  --slug gemma4-structured-v4-10m-diagnostic \
  --task-ids configs/cohorts/diagnostic-3.json \
  --output notebooks/generated/structured-v4-10m-diagnostic
uv run gemma-lab push-notebook notebooks/generated/structured-v4-10m-diagnostic --execute
uv run gemma-lab wait-run YOUR_KAGGLE_USER/gemma4-structured-v4-10m-diagnostic \
  --output runs/kaggle/structured-v4-10m-new-run --timeout-minutes 120
```

These commands create a private evaluation, not a leaderboard submission. Never run
competition repositories directly on a personal Mac. Use the disposable official
Kaggle worker or an appropriately isolated Linux GPU host. Never provision paid
hardware without an explicit budget; never download the full dataset/base model to
a low-disk control machine. Use a fresh output directory for each run/version.

## Evidence access and publication boundary

`evidence/run-results.json` contains allowlisted own result metadata from14 completed
runs/preflights. `RUN_CATALOG.md` explains cohorts, caveats and versions. Raw task
statements/snapshots/reference patches/test patches, generated patches, traces/logs,
weights, credentials and binary archives remain excluded. Original grading diagnostic
contents must not be copied into submitted agent context. A Grok bot using only this
public repo can inspect code and findings, but cannot open private Kaggle outputs
without the owner's authorization/account access. Re-run authorized inputs when needed.

Private local artifacts lived under runs/,artifacts/,vendor/,data/,notebooks/generated/.
Their paths are documented for the owner, but do not exist in a fresh clone. Own raw
results are hash-bound in public metadata without disclosing raw material.

## Copyable starting prompt

> Read AGENTS.md, README.md, docs/HANDOFF.md, docs/STATUS.md, docs/HARNESS_SPEC.md,
> docs/RUN_CATALOG.md and docs/STRUCTURED_V4_10M_DIAGNOSTIC.md. Continue development
> from agents/structured-v4-10m while preserving evaluated candidates and evidence.
> Prioritize intentional skill use, workspace imports, clean finalization, and
> same-cohort controls. Do not claim benchmark gains from unit tests or the selected
> 3/3 pilot. Use only the permitted model/declarative tools/sandboxed skills. Keep
> grading answers out of agent context, train only on train IDs, reserve holdout,
> respect checked submission limits, and do not provision paid hardware without a
> budget. Update STATUS.md from actual state and report remaining blockers honestly.
