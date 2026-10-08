# Project status

Last updated: October 8, 2026 (Pacific).

## Current development budget variant

User requested10–15minutes after the five-minute pilot. New active development
source `agents/structured-v4-10m`:10min per task,80 counted tool calls,60 model turns,
300s command cap. Repair's soft handoff target scales180→360s. No other agent/skill
changes. Candidate commit `b005268`, archive SHA256
`0730b5f0a373fc23bdb4362779a4757ded14cfa6a77896c7d54ce3efb7ad8cab`.
Archive `artifacts/structured-v4-10m/submission.zip`; same-cohort official notebook
executed from `notebooks/generated/structured-v4-10m-diagnostic`.
Private official run: https://www.kaggle.com/code/charlesaherbst/gemma4-structured-v4-10m-diagnostic
(v1 COMPLETE); output `runs/kaggle/structured-v4-10m-diagnostic-v1`.
Same frozen diagnostic IDs: fastapi_11194,fastapi_14786,rich_3454. Portable validation
passed and archive hash matched. Official diagnostic3/3 versus five-minute v4's1/3:
two paired wins,no regressions,1468.5taskseconds/104calls,zero recordedinfra/budgeterrors.
Two tasks use fallback with scratch files; only fastapi14786 explicitly submits a clean
patch and invokes verify-patch. No new competition submission. Full report:
`docs/STRUCTURED_V4_10M_DIAGNOSTIC.md`. Outputs/stages/audit/paired comparison are saved;
collector completed, no active run or recurring job. Do not generalize three-task success
or promote without broader same-cohort measurement and patch-hygiene remediation. Original
five-minute candidate, archive and results remain unchanged. The two diagnostic
failures explicitly report session timeout, not single-command timeout. The12hour
competition-wide generation limit still applies; longer caps require runtime evidence.

## Evaluated five-minute development candidate

- `agents/structured-v4` implements bounded tool-free triage, isolated repair/verifier
  histories with explicit state handoffs, and three scoped sandboxed skills.
- Skills: task-memory (bounded/locked task evidence), source-lookup (bounded literal
  search/windows), verify-patch (same-repro contract, real exit status, freshness and
  read-only patch audit). No global Codex skill installation or new custom tool.
- Candidate commit: `62f8bab`; archive SHA256:
  `01568061ee105be99a51af1bca592dd59756db9184dfada735c0e3074ae7e77e`.
- Archive: `artifacts/structured-v4/submission.zip`;14 files, pure declarative agent
  plus sandboxed skill resources. Diagnostic official notebook executed at
  https://www.kaggle.com/code/charlesaherbst/gemma4-structured-v4-diagnostic (v1 COMPLETE), frozen
  dev IDs `fastapi_11194`, `fastapi_14786`, `rich_3454`. Holdout untouched.
- Design/use/limits: `docs/STRUCTURED_V4.md`. All64 tests plus lint/format pass; skill
  manifests validated. Official diagnostic:1/3, two timeouts, zero skill-tool invocations; see below.
- Submitted v3 and its archive are unchanged. No new competition submission.
  Its last checked server history reported PENDING.
- Official SDK CPU preflight confirms compiled skill tools are exposed and all three
  helper scripts execute successfully; it is synthetic validation, not model performance.
- Diagnostic report: `docs/STRUCTURED_V4_DIAGNOSTIC.md`. V4 regressed on rich_3454;
  do not promote. Next experiment: restrict raw-tool bypasses and explicitly activate
  scoped operations, with a triage-only control. Do not add further skills as a remedy.
- Outputs: `runs/kaggle/structured-v4-diagnostic-v1`, `structured-v4-sdk-preflight-v3`.
  No active collector, GPU job or recurring automation remains.

## Active work

User requested review, implementation, official evaluation, and Kaggle submission of
a simple three-role Gemma agent. Implementation/evaluation are authorized; actual
submission must use the checked uploader and respect one per UTC day. Submission **56905832** was accepted at 01:41 AM Pacific on October 7, 2026
(08:41 UTC). Account history confirms `SubmissionStatus.PENDING`; no score yet.
Kaggle reports zero submissions remaining for this UTC day. Do not retry/upload again today.

- Active source: `agents/simple-v3`.
- Archive: `artifacts/simple-v3/submission.zip`.
- SHA-256: `50d7b69dd4d0f6a5b4925bda919f69e57196b72337190bd6073be95591ff2646`.
- Architecture: declarative SequentialAgent wrapper with exactly three Gemma LlmAgent
  roles: locator → investigator → verifier. No adapters or custom tools.
- Locator now has only read_file, get_status, and the three graph tools: shell access
  caused all observed v2 workspace repro leakage and is removed. Investigator owns
  rg/grep fallback when graph data is missing/stale. No write_file in any role.
- Model: `gemma-4-31b-it-qat-w4a16-ct`; output ceiling 4096; thinking 512/1024/1024.
- Budgets: five minutes, 80 counted calls, 60 turns, official 300-second command/test timeout.
- Portable validation and packaging passed. Toolkit: 39 tests plus lint/format passed.
- GPU evaluation: https://www.kaggle.com/code/charlesaherbst/gemma4-simple-v3-dev13 (v1, COMPLETE).
- Collector/output: `runs/kaggle/simple-v3-dev13`; collection complete; no active collector or recurring job.
- Cohort: all frozen dev IDs except `requests_7502`, excluded prospectively because
  the official verification worker has a recursive httpbin fixture dependency.
  IDs: `runs/experiments/simple-v1/dev-13-clean.json`. Holdout unexamined.
- Run record: `runs/experiments/simple-v1/EXPERIMENT.md`. Candidate file hashes and
  generation git revision/working snapshot are pinned in manifests.

## Completed evidence

- Baseline smoke: 0/2, context exhaustion and timeout; infrastructure check only.
- Baseline dev3: 0/3, three timeouts; Requests fixture failure makes its grading inconclusive.
- Initial AgentTool v1 dev3: 1/3, two timeouts, scratch/debug pollution; not submitted.
- Shorter AgentTool R1 dev3: 0/3; investigator never invoked.
- AgentTool R1 full dev14: 3/14 (FastAPI3/6, Rich0/7, Requests0/1), ten budget failures.
  Rich grading patch failed after candidate test edits; Requests also has fixture errors.
- Sequential v2 smoke: 1/2, all three roles execute, clean patches; successful FastAPI
  patch captured by fallback before explicit submit_patch. Smoke is not generalization evidence.
- Sequential v2 dev13: 3/13 (FastAPI2/6, Rich1/7), nine timeouts, zero reported infrastructure
  failures, 3577.1 task seconds/364 calls. Same-cohort R1 comparison: one win (rich_3454),
  one regression (fastapi_11194), net zero. Locator wrote workspace repro scripts in
  three failed cases; v2 was not submitted.
- Audits/comparisons: `runs/experiments/simple-v1/*audit.json`, `*comparison.json`.
- All measured GPU runs used four NVIDIA L4s; swegemma0.2.7, adk-submission0.2.12,
  adk-eval-core0.1.0, vLLM0.19.1, google-adk1.36.1 (confirm v3 manifest after collection).

## Toolkit repairs

Returned runner errors are preserved even when the evaluator reports status SUCCESS.
The uploader inspects official diagnostics, distinguishes timeout/turn-budget failures
from infrastructure, and blocks known grading fixture failures. It never rewrites raw
results to conceal failures. Alternate official wheelhouse mount discovery handles a
worker that previously failed with zero wheels; missing mounts fail explicitly.

## Submission evidence and next actions

- V3 dev13: 3/13 (23.1%; Wilson95% 8.2–50.3%), FastAPI2/6, Rich1/7.
- Resolved IDs: `fastapi_14786`, `fastapi_14794`, `rich_3454`.
- Same-cohort v2 comparison: no wins or regressions; same three resolutions.
- 3873.7 task seconds, 343 counted calls, zero infrastructure failures, ten budget
  failures, eight empty patches. Task duration includes setup/verification overhead.
- Audit: no workspace repro files, added debug output, or root protected-file changes.
  `rich_3454` also edits repository tests; grading succeeded, but source-only editing
  remains a soft policy. Locator is strictly read-only; its four-call prompt cap is
  not enforced and it consumed entire budgets on some tasks. All three roles are
  reached only when earlier roles finish. Explicit submit_patch is not reliable on
  timed-out/fallback cases. Do not describe this as a proven competitive agent.
- Actual hardware/packages match prior four-L4 official runs; see run_manifest.json.
- Evaluation/patches/traces: `runs/kaggle/simple-v3-dev13`.
- Audit/comparison: `runs/experiments/simple-v1/v3-dev13-audit.json`, `v3-dev13-comparison.json`.
- Receipt/reservation: `runs/submissions.jsonl`; exactly one accepted upload, server ref56905832.

Next: query `gemma-lab status` for the leaderboard result. No scheduled monitor was
created. Preserve v3/its immutable archive; make any future tuning in a new candidate.
Prioritize localization loops and verifier time headroom on the same dev IDs; holdout
remains reserved. No leaderboard strength claim until actual results are available.

## Environment and limits

Private repo: https://github.com/CharlieHerbst331/gemma4-agent-lab; Kaggle account
`charlesaherbst`. Locked Python3.12 Mac environment, no GPU/Docker, roughly6GiB free.
Weights and task repositories run only on disposable offline Kaggle workers. No paid
hardware, training, holdout evaluation, public release, or recurring automation.
See `docs/SIMPLE_V1.md` and `docs/EXPERIMENT_RESULTS.md` for review/evidence.

## October 7 design review

Review/roadmap: `docs/HARNESS_REVIEW.md`. No candidate, GPU run, or submission changed.
Trace reanalysis: locator261/367 total tool events; verifier reached2/13; locator44
repeated exact navigation calls. Primary proposed controls are one-shot/tool-free
triage and a matched single-agent baseline, followed by navigation/handoff ablations.
A newly inspected grading output for fastapi14356 cannot import dirty_equals; the old
summary recorded only its simultaneous timeout. Therefore zero recorded infrastructure
failures was incomplete. Preserve raw3/13 and diagnose this as concurrent execution
and verification-environment failures before future promotion/submission decisions.
