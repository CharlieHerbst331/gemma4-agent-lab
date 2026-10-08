# Run catalog and findings

Machine-readable observations: [evidence/run-results.json](../evidence/run-results.json).
These are our measured outcomes, not redistributed task data or leaderboard scores.
Private raw evidence and generated notebooks are intentionally not in a fresh clone.
Each task result is graded by the official fresh-sandbox evaluator. Different cohorts
must not be compared as paired rates. Recorded error labels have known omissions.

| Run folder ID | Cohort/purpose | Raw result | Interpretation |
| --- | --- | --- | --- |
| smoke-v1 | Official starter two train tasks | 0/2 | Baseline infrastructure smoke:context overflow and timeout; old summary omitted returned runner errors |
| baseline-dev3 | First frozen dev ID per represented repo | 0/3 | Three timeouts; Requests grading had recursive httpbin fixture errors |
| simple-v1-dev3 | Same dev3 | 1/3 | FastAPI win; two timeouts; workspace scratch/debug leakage |
| simple-v1-r1-dev3 | Same dev3 | 0/3 | Shortened prompts did not invoke investigator |
| simple-v1-r1-clean | Unaffected dev2 preflight; archive hash not recorded | No task results | Worker failed before model setup:wheelhouse not at hard-coded mount |
| simple-v1-r1-dev14 | Full frozen dev14 | 3/14 | FastAPI3/6,Rich0/7,Requests0/1; 9 recorded budget failures and 2 recorded infrastructure failures (rich_3472, rich_3454); test-patch application issue after agent test edits |
| simple-v2-clean | FastAPI/Rich diagnostic dev2 | 1/2 | Three-role sequence executes; smoke only |
| simple-v2-dev13 | All dev except Requests, prospectively environment-screened | 3/13 | Two FastAPI/one Rich; nine timeouts; locator created workspace repro files |
| simple-v3-dev13 | Same dev13 | 3/13 | Same resolved IDs; locator shell removal eliminates observed scratch leakage; ten budget failures |
| structured-v4-diagnostic-v1 | Frozen diagnostic dev3 | 1/3 | Tool-free triage completes; zero skill calls; one regression versus v3 same IDs; two timeouts/scratch leakage |
| structured-v4-sdk-preflight-v1 | CPU synthetic fixture, no model/task evaluation | Setup error | Compilation completed; asyncio.run incorrectly used inside IPython |
| structured-v4-sdk-preflight-v2 | CPU synthetic fixture | Partial preflight | Tool exposure/scripts worked; TMPDIR placed resource files inside fixture, causing false audit failure |
| structured-v4-sdk-preflight-v3 | CPU synthetic fixture | All checks pass | Correct external TMPDIR; skill exposure, memory, lookup, before/after and audit fingerprint validated |
| structured-v4-10m-diagnostic-v1 | Same structured diagnostic dev3 | 3/3 | Two paired wins, no regression vs5min; two fallback patches still contain scratch; only one clean explicit finalization |

## Fixed cohorts

- Splits:`configs/splits/public-v1.json`,95train/14dev/20holdout grouped by repo+base_commit.
- Diagnostic3:`configs/cohorts/diagnostic-3.json` (fastapi11194/14786,rich3454 with underscores).
- Environment-screened dev13:`configs/cohorts/dev-13-environment-screened.json`.
  Only Requests7502 excluded prospectively for known official fixture failure.
- Source task checksum:e4b3fd60f69dbc2b9213e54eeb9636db78aefe92c1d06269d73d9f5f8f3c8ad6.
- Holdout never evaluated. No model training performed.

## Principal conclusions

Capability restrictions worked more reliably than prompt prohibitions: v3's locator
cannot write through its attached tools, while per-role call/time targets were ignored.
V3 locator generated261/367 total tool events and repeated44 exact navigation calls.
Verifier reached only2/13 cases. Sequential order is not independent time allocation.

Structured-v4 removes the tool-based triage loop and isolates repair/verifier history.
The5min pilot resolved1/3; skills were present/executable in SDK but unused by the model.
The10min pilot resolved all3, with first edits404.4s/581.1s in the formerly failing cases.
One verifier used verify-patch to surface argument/contract errors, remove repository
 test edits and rerun a matching-fingerprint check before explicit submission. The other
 two cases relied on fallback and contain scratch. task-memory was loaded but not run;
source-lookup was not invoked. More time helped this pilot but did not enforce adoption.

The ten-minute cohort's total task duration1468.5s includes setup/grading. Its counted
calls104 are distributed50/19/35 per task, not a violation of80per-task allowance.
These selected three cases, one stochastic run and bundled changes do not establish
hidden-repository generalization or isolate all causal effects. Keep a matched control.

## Measurement blind spots

Historical collector labels do not capture every grading setup error. Requests has
recursive httpbin fixture failures. fastapi14356 has a missing dirty_equals import
while also timing out. Some Rich test-patch errors follow agent edits to target tests.
Do not silently relabel all of these as bad reasoning or healthy infrastructure.
Preserve raw official scores and annotate concurrent execution/verification failures.

## Competition submission

Only ref56905832 (simple-v3) was uploaded. Upload receipt was successful, but current
account status checked for this handoff is ERROR with no score. Cause not available
from the CLI summary. It is not a scored3/13 leaderboard success;3/13 is the separate
public-dev evaluator result. No automatic final selection or recurring monitor exists.
