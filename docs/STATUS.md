# Project status

Last updated: October 10, 2026.

## Unevaluated structured-v5 candidate

`agents/structured-v5` is a new candidate forked from `agents/structured-v4-10m`.
No evaluated candidate was modified. v5 is not evaluated and not submitted.
Design, harness evidence, and the repair-submit decision: `docs/STRUCTURED_V5.md`.

Shape: Sequential[triage, Loop(max_iterations 3)[repair, verify]]. Thinking is off
via the single knob `sub_agents/thinking.yaml` (`include_thoughts: false`, no
budget). Budgets are 270s (`max_time_minutes: 4.5`), 48 counted calls, and 64
turns. Skill script runs count as calls, so turns and calls are roughly
co-binding, and the 270s clock usually binds first. Repair hands off at about
90 seconds remaining. Verify submits when fewer than 60 seconds remain, re-reads
the clock before its check, and replies with one sentence. Verify's tools are
get_status, read_file, edit_file, submit_patch, and the verify-patch skill. Repair
does not have submit_patch: a text handoff after a submission ends the task before
verify. src-layout requests tasks are unreliable in the notebook subprocess eval
and are excluded from promotion decisions.

Archive SHA256 `6202ab26252df59061547e0fd7dbcc1e8ef62b5cb12c61c14c2b2e953865bbb5`
(`artifacts/structured-v5/submission.zip`, 16 files). Repacking the evaluated
candidates still matches their recorded hashes, including v4-10m
`0730b5f0a373fc23bdb4362779a4757ded14cfa6a77896c7d54ce3efb7ad8cab`.

## Matched single-agent control

`agents/single-v1` is a new unevaluated control forked from `agents/structured-v4-10m`
and aligned to structured-v5 (`cursor/structured-v5-3d40` at `38a51c8`) except the
multi-agent structure. One LlmAgent, thinking off (`include_thoughts: false`, no
budget), 270s / 48 calls / 64 turns. Archive
SHA256 `84b4b0f720493041704209dd175061c003be387fc49a826ebca0a13c0b5cf0f8`.
Remaining differences: `docs/SINGLE_V1.md`. Src-layout (requests) tasks are excluded
from promotion decisions. No GPU run and no submission. Re-packed structured-v4,
structured-v4-10m, and simple-v3 archives match their documented hashes.

## Thinking-off copies for the paired run

`agents/structured-v5t0` and `agents/single-v1t0` are unevaluated copies of the
frozen parents. The only change is `thinking_budget: 0` with `include_thoughts`
still false, because on adk-submission 0.2.13 a missing budget is overridden by
swegemma's default of 4096. The two thinking files are byte-identical, and so
are the two `eval_config.yaml` files. `configs/protocols/v5-vs-single-v1.yaml`
now points at these copies. Archives: structured-v5t0
`b2cce93de41ad7a487178de67fe10ef82d3aa69f48820639dc3ee720839ae7a9`, single-v1t0
`90ba7ee8918daf959831cf2845d771c3f09cf46295546d0509f98e6641da845f`.
Notes: `docs/THINKING_OFF_T0.md`. No GPU run.

## Protocol pair structured-v6 vs single-v2

`agents/structured-v6` (from structured-v5t0) and `agents/single-v2` (from
single-v1t0) are unevaluated copies for the r1b tool-protocol failures. Thinking
stays off (`thinking_budget: 0`, `include_thoughts: false`). The 270s / 48-call
caps are unchanged. The two thinking files and the two `eval_config.yaml` files
stay byte-identical. `configs/protocols/v6-vs-single-v2.yaml` points at this
pair. `configs/protocols/v5-vs-single-v1.yaml` is unchanged. Archives:
structured-v6 `6d324b008ea5c3a389d34277087433200e2521fd17edfd7b3ddc616c965e6e56`,
single-v2 `28d5b6e46ad8a95d1ed48086f5c63b003a3d78a11e281c210dd98a3b0d40325c`.
Notes: `docs/V6_SINGLE_V2.md`. No GPU run.

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
five-minute candidate, archive and results remain unchanged. The two failures in
that five-minute diagnostic explicitly report session timeout, not single-command
timeout. The10-minute diagnostic had no failures. The12hour
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
  Its publication-time server history reports ERROR, without a score.
- Official SDK CPU preflight confirms compiled skill tools are exposed and all three
  helper scripts execute successfully; it is synthetic validation, not model performance.
- Diagnostic report: `docs/STRUCTURED_V4_DIAGNOSTIC.md`. V4 regressed on rich_3454;
  do not promote. Next experiment: restrict raw-tool bypasses and explicitly activate
  scoped operations, with a triage-only control. Do not add further skills as a remedy.
- Outputs: `runs/kaggle/structured-v4-diagnostic-v1`, `structured-v4-sdk-preflight-v3`.
  No active collector, GPU job or recurring automation remains.

## Submitted simple-v3

User requested review, implementation, official evaluation, and Kaggle submission of
a simple three-role Gemma agent. Implementation/evaluation are authorized; actual
submission must use the checked uploader and respect one per UTC day. Submission **56905832** was accepted at 01:41 AM Pacific on October 7, 2026
(08:41 UTC). Publication-time account history now reports `SubmissionStatus.ERROR`, with no
leaderboard score. The CLI summary does not expose the cause. The earlier zero-slot
message applied to the upload's UTC day; use the checked uploader for current history
and quota, never assume a cached slot count.

- Submitted source: `agents/simple-v3`. The active development source is `agents/structured-v4-10m`, above.
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
  Public IDs: `configs/cohorts/dev-13-environment-screened.json`. Holdout unexamined.
- Run record: `runs/experiments/simple-v1/EXPERIMENT.md`. Candidate file hashes and
  generation git revision/working snapshot are pinned in manifests.

## Completed evidence

- Baseline smoke: 0/2, context exhaustion and timeout; infrastructure check only.
- Baseline dev3: 0/3, three timeouts; Requests fixture failure makes its grading inconclusive.
- Initial AgentTool v1 dev3: 1/3, two timeouts, scratch/debug pollution; not submitted.
- Shorter AgentTool R1 dev3: 0/3; investigator never invoked.
- AgentTool R1 full dev14: 3/14 (FastAPI3/6, Rich0/7, Requests0/1), 9 recorded budget
  failures and 2 recorded infrastructure failures (`rich_3472`, `rich_3454`).
  Rich grading patch failed after candidate test edits; Requests also has fixture errors.
  An older "ten budget failures" label does not match `evidence/run-results.json`.
  Reclassifying `rich_3472` as turn-budget exhaustion is unverified and is not applied here.
- Sequential v2 smoke: 1/2, all three roles execute, clean patches; successful FastAPI
  patch captured by fallback before explicit submit_patch. Smoke is not generalization evidence.
- Sequential v2 dev13: 3/13 (FastAPI2/6, Rich1/7), nine timeouts, zero reported infrastructure
  failures, 3577.1 task seconds/364 calls. Same-cohort R1 comparison: one win (rich_3454),
  one regression (fastapi_11194), net zero. Locator wrote workspace repro scripts in
  three failed cases; v2 was not submitted.
- Audits/comparisons: `runs/experiments/simple-v1/*audit.json`, `*comparison.json`.
- All measured GPU runs used four NVIDIA L4s; swegemma0.2.7, adk-submission0.2.12,
  adk-eval-core0.1.0, vLLM0.19.1, google-adk1.36.1. The v3 manifest matches these
  packages; see the submission evidence below.

## Toolkit repairs

Returned runner errors are preserved even when the evaluator reports status SUCCESS.
The uploader inspects official diagnostics, distinguishes timeout/turn-budget failures
from infrastructure, and blocks known grading fixture failures. It never rewrites raw
results to conceal failures. Alternate official wheelhouse mount discovery handles a
worker that previously failed with zero wheels; missing mounts fail explicitly.

The checked uploader refuses an archive when either projected block fails. Gates
run on the measured per-task mean at `submit --execute` only (`projection.json`
`basis` is `measured_mean`). They are not a precondition for dev GPU runs, and
the per-task cap never blocks. `--scorer-overhead-seconds` (default 70) is added
only to the 120-task block and the worst-case warning: 120 × (mean + overhead)
must be at most 11 hours, and model-load seconds (from `run_manifest.json`, else
900) + 129 × mean, with no overhead, must be at most 10.8 hours. A worst case of
load + 129 × (cap + overhead) above 12 hours warns and does not block.
`git_revision()` appends `-dirty` when the worktree is dirty, and the public
findings export keeps that marker plus the pack provenance fields. `gemma-lab
hygiene candidate|run|patch` audits patches offline. Rule IDs, the 0.2.7
checkout-abort reason H2 stays a block, and the trace paths are in
`docs/HYGIENE.md`. It does not edit agents or raw run files. `hygiene run DIR`
writes `DIR/hygiene.json`, and `hygiene candidate` and `hygiene patch` write
`./hygiene.json` unless `--output` is given. `hygiene.json` and
`projection.json` are gitignored at any depth and omitted from packs, so a
report left inside a candidate does not change the archive. Candidate lint is
not wired into submit
or pack. Frozen structured-v4 and structured-v4-10m block that lint on
`G2.superset`. baseline, simple-v1, and simple-v2 block it on `G0.write_file`.

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

Public repo: https://github.com/CharlieHerbst331/gemma4-agent-lab; Kaggle account
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

## Public handoff release

Owner requested public GitHub release for their Grok bot and asked to add the Kaggle
sharing notebook later. HANDOFF.md/HARNESS_SPEC.md/RUN_CATALOG.md/README describe the
current implementation, all14 runs/preflights, evidence caveats and next priorities.
evidence/run-results.json contains allowlisted own observations only; raw competition
material, logs/traces/patches, credentials and weights remain excluded. Kaggle public
code-sharing step is pending owner action. No new submission/run or collaborator invite.

Public GitHub visibility and unauthenticated source/document access are verified.
Publication checks:66tests/lint/format;160historical source blobs, no matching secret
patterns or forbidden tracked data/artifacts. Release handoff documents and evidence
are committed. Kaggle notebook/post deferred to owner; no public Kaggle action.

## Paired notebook toolkit

`gemma-lab notebook-pair`, `pair-schedule`, and `pair-report` live in the toolkit.
No paired GPU session has been run. `pins_mode` stays `record` until the six grading
file hashes are confirmed against the official Kaggle wheelhouse; they currently match
the public happyc0der copy only. max_tool_calls and max_time_minutes are now set
explicitly from eval_config; previously inherited from the fetched starter. The paired
notebook sets each arm's caps from that arm's resolved eval_config. adk-submission
older than 0.2.11 refuses to run, and a version below 0.2.12 warns that a
thinking_budget ablation would not be honored. The exact version is recorded on the
pair manifest. Each arm writes `results/<arm>/r<k>/task_results.jsonl` and `model_load_seconds`
in that arm's `run_manifest.json`. A harness ATIF file already at
`results/<arm>/r<k>/traces/trace_<id>.json` is left in place; a missing trace is
saved with `trace.save()` when that writer exists, and a raw dump otherwise goes
to `trace_<id>.raw.json`. Task ids with `/` use `__` in that filename. Restart
starts vLLM in its own session. The process-group id equals the parent pid and
is recorded before stop(); after stop() that group gets SIGTERM and then
SIGKILL, and the same id is used for a wait of up to 60 s for the port and any
leftover GPU memory. Agent trees and the recorded archive
hashes are unchanged.

## Health probe

t0-r1 aborted on the first task because the notebook probed `base_url + '/health'`
while harness `base_url` is `http://host:port/v1` and vLLM serves `/health` at the
root. Probes use `health_url` or strip a trailing `/v1`. Three failures at 2 s
spacing, or a dead server process, restart once and rerun that task.
`events.jsonl` adds `health_check_failed` (`url`, `status`, `error`, `kind`,
`attempt`), `health_poll` (`url`, `status`, `latency_seconds`), `task_retry`,
and `gpu_memory` (`phase` `before_task` or `after_task`; `gpus` of `index`,
`memory_used_mib`, `memory_total_mib`). `server.log` is a best-effort copy of
the vLLM log after the server starts, again before a restart, and on abort.
It is not copied at normal session end.

## Hygiene in the pair report

Pair-report and local paired sessions write `results/<arm>/<repeat>/hygiene.json`
when that file is absent, and leave an existing sidecar untouched. The decision
rule reads those gates. `not_computed` remains only when no sidecar exists, and
a hygiene block on an arm means that arm cannot win. The report prints one
compact line per arm (gate, H1/H2/H3/H5 counts, explicit submit rate) instead
of the sidecar dict. Gate `reasons` name blocking findings, such as
`H1 scratch file repro.py in fastapi_11194`, and do not list warn-level rate
shortfalls as the cause of a block. The pair-report worst-case check is the
upload warning `L + 129 * (cap + 70)` and is warn-only. The 120-task and
129-task block formulas are unchanged. Generated notebook cells are unchanged.

## Tool-call smoke protocol

`configs/protocols/v6-vs-single-v2-toolcall-smoke.yaml` is one repeat of
structured-v6 vs single-v2 on five dev-13 ids: fastapi_14786 (A's skill-format
loop, B solved it), rich_3934 (skill failures and B's edit_file streak),
fastapi_11194 (B's skill loop and A's scratch repro.py), rich_3938 (skill streak
and a scratch-only patch), fastapi_14262 (mild edit failures and a no-edit
read). fastapi_14356, the non-format failures, and the two controls stay out.
Schedule `31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345` is
not the 13-task schedule. The pair report is marked smoke and is not promotion
eligible; runtime gates are not applied. The frozen 13-task protocols are unchanged.

## Harness 0.2.11

Verified on swegemma 0.2.10 and 0.2.11 with adk-submission 0.2.13. swegemma
0.2.11 removed the `swegemma.models` discovery and registry helpers, including
`validate_single_declared_model`. Generated notebooks try that import and fall
back to `adk_submission.discovery.discover_declared_models`. Kaggle ignores
the `/N` dataset pin and mounts the latest wheelhouse version. The allow-list
in the first code cell and the recorded installed versions are the real
control. `wheelhouse_version` records intent only.

Which file holds what:

- Generation-time `pair_manifest.json` and `provenance.json` list the
  allow-list as `harness_verified_pairs`. They do not record installed
  versions, because the kernel has not run.
- The kernel writes `/kaggle/working/run_manifest.json` from that allow-list
  cell, merging `installed_harness`, `swegemma`, and `adk-submission` into any
  existing keys.
- Each arm's `results/<arm>/r<k>/run_manifest.json` copies those installed
  versions next to `model_load_seconds` and the task ids.
- After the session, the kernel's `pair_manifest.json` (not the generation-time
  file) gains `installed_harness`. The pair report header and
  `pair_report.json` `harness_versions` read that post-run record.

Real 0.2.10 and 0.2.11 wheels were not installed here.

## single-v3, no skills

`agents/single-v3` is a new unevaluated candidate copied from `agents/single-v2`
with the skills directory removed. Verification is a short `run_command` recipe
under `/tmp`. `thinking.yaml` and `eval_config.yaml` are byte-identical to
single-v2. The prompt is 6656 characters; single-v2's is 7980. The repro example
is an import under `/tmp/repro_check.py`, not a failing placeholder assert.
Archive SHA256
`37abebce49c490d5cdc6abf41b92067aa480929e508084098e883ab9c1938ffc`. Hygiene gate
pass. Not submitted. The twelve previous archive hashes are unchanged.

`configs/protocols/v6-vs-single-v3.yaml` is dev-13, one repeat, arm A
structured-v6 and arm B single-v3. It is not a matched pair. Schedule
`629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed`.
`configs/protocols/single-v2-vs-single-v3-toolcall-smoke.yaml` is the five
tool-call tasks in reverse schedule order, one repeat, arm A single-v2 and arm
B single-v3. Schedule
`0c4e0c31473075ab9cfed9cf305a3ed988e274c9da1d684630136b2b16d18704`. It is smoke
and not promotion eligible. `matched_pair: false` skips only the shared-file
identity check. Existing protocols omit the flag and keep the check. No Kaggle
push and no GPU run.

## single-v4, sed reads

`agents/single-v4` is a prompt-only copy of `agents/single-v3`. `agent.yaml`,
`thinking.yaml`, and `eval_config.yaml` are byte-identical. The prompt is 6619
characters; single-v3's is 6656. `read_file` takes `filepath` only. Line ranges
use `sed -n 'A,Bp' path | head -c 4000`. Archive SHA256
`af39c7eb1f2e58ebb2c7efceeb5c6ac567615019eec06b0d8a6d78e7603200cd`. Hygiene gate
pass. Not submitted. The thirteen previous archive hashes are unchanged.

`configs/protocols/single-v3-vs-single-v4-toolcall-smoke.yaml` is those five
tasks in the original order, one repeat, arm A single-v3 and arm B single-v4.
The schedule hash is `31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345`,
the same as the first five-task smoke, because schedule hashes are not required
to be unique. `prompts/*` is an allowed difference, so `matched_pair` stays on.
The report is smoke and not promotion eligible. No Kaggle push and no GPU run.
