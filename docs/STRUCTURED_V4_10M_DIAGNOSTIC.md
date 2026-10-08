# Ten-minute structured-v4 official diagnostic

October8,2026 Pacific. Same frozen diagnostic cohort as five-minute v4.
Private official run https://www.kaggle.com/code/charlesaherbst/gemma4-structured-v4-10m-diagnostic
version1 COMPLETE, four NVIDIA L4s, official starter and swegemma.
Candidate commitb005268; SHA256
`0730b5f0a373fc23bdb4362779a4757ded14cfa6a77896c7d54ce3efb7ad8cab`.
Full hashes, task checksum, hardware and package versions: run_manifest.json.

## Result

| Task | Five-minute v4 | Ten-minute v4 | Task duration | Counted calls |
| --- | --- | --- | --- | --- |
| fastapi_11194 | Unresolved | Resolved | 611.0s | 50 |
| fastapi_14786 | Resolved | Resolved | 251.3s | 19 |
| rich_3454 | Unresolved | Resolved | 606.1s | 35 |

Raw official3/3 vs1/3: two paired wins, no regressions. No recorded infrastructure
or agent-budget errors, no empty patches. Total1468.5 task seconds/104 counted calls
vs839.9seconds/81calls previously. Task durations include setup/grading; they are not
pure inference time. Three selected diagnostic tasks are not a generalization estimate.
Sampling variability means one run does not isolate every causal effect of more time.

Only session allowance5→10minutes and scaled soft handoff180→360seconds changed;
80 counted calls/60turns/300second command cap and agent/skills/model/sampling otherwise
match. Neither agent's original source/archive nor current competition submission changed.

## Stage and skill evidence

- Triage ends16.6–24.0seconds; zero triage tools.
- fastapi11194: first implementation edit404.4s, verifier starts503.4s. Model still
  confuses installed-package versions/workspace imports. No skill calls or explicit
  submit_patch; fallback contains implementation plus repro.py/comprehensive_repro.py.
- rich3454: first implementation edit581.1s. Verifier not reached; fallback patch
  passes fresh official grading but includes multiple scratch scripts. No skill calls.
- fastapi14786: first edit43.9s, verifier starts126.0s. Verifier discovers/loads skills
  and makes seven verify-patch script calls. Initial call omits skill_name/file_path,
  next violates the before-check contract; errors are surfaced. It then establishes
  a before contract after the implementation is already fixed (that check passes,
  so this is not evidence of an original failing repro), reruns verification, and audits.
  Audit detects repository test edits; the verifier removes them, audits again, reruns
  check at the new fingerprint, and explicitly submits a clean single-source patch.
- task-memory is loaded but its script is not used. source-lookup is not invoked.
- No root pytest.ini/conftest.py changes. Two patches contain workspace scratch and
  print-based self-checks; genuine resolution comes from independent fresh grading,
  not those prints. No claim of complete skill compliance or reliable finalization.
- Two tasks finish at the time ceiling/fallback boundary even though official error
  fields are empty. Do not interpret zero recorded timeout errors as ample headroom.

## Decision

More time materially enabled later implementation in this diagnostic. Retain the
10minute development variant for further diagnosis, but do not automatically promote
or submit from3/3. Next: improve mandatory clean finalization and scoped tool adoption,
then compare the identical broader dev cohort. The12hour competition-wide generation
limit still applies; this run cannot establish an acceptable full-task average.
Holdout untouched; no training, recurring job, paid hardware or new submission.

Evidence: runs/kaggle/structured-v4-10m-diagnostic-v1; paired/stage/audit reports in
runs/experiments/structured-v4-10m. Raw official results preserved unchanged.
