# Structured v4 official diagnostic result

October7,2026 Pacific. Submitted v3/archive unchanged; no new competition submission.

## GPU run

Official starter/swegemma, private offline Kaggle worker, four NVIDIA L4s.
https://www.kaggle.com/code/charlesaherbst/gemma4-structured-v4-diagnostic version1.
Source commit62f8bab, archive SHA256
`01568061ee105be99a51af1bca592dd59756db9184dfada735c0e3074ae7e77e`.
Frozen dev cohort: fastapi11194,fastapi14786,rich3454 (original IDs contain underscores).
Task checksum/split, exact files and package versions are in run_manifest.json.
No holdout examined and no reference/grading metadata included in agent inputs.

| Task | Structured v4 | Prior v3 same ID | Observed execution |
| --- | --- | --- | --- |
| fastapi_11194 | Unresolved | Unresolved | Repair timed out; no implementation edit; workspace repro included in fallback patch |
| fastapi_14786 | Resolved | Resolved | Repair and verifier ran; explicit submission; implementation plus repository test edits |
| rich_3454 | Unresolved | Resolved | Repair timed out; wrong patch and scratch/test files; verifier never reached |

Raw official1/3 vs prior2/3: no paired wins, one regression rich3454. Two timeouts,
zero recorded infrastructure failures, no empty patches,81 counted calls,839.9 task
seconds (including setup/verification). Three tasks are a diagnostic pilot, not a
performance/generalization estimate. Sampling/bundled changes preclude causal attribution.

Triage completed without tools on all tasks in18.4–25.2 seconds. First implementation
edit was near50–51 seconds in two cases; none in fastapi11194. Verifier reached only
fastapi14786, near102.7 seconds. Skill-tool calls were ZERO: no load_skill,
load_skill_resource, or run_skill_script. Repair ignored the structured routes and
used raw shell/file tools. Timed-out cases introduced workspace scratch and print-based
repros. Successful task also edited repository tests despite the prompt restriction.
Do not promote this candidate on the strength of its64 synthetic-fixture tests.

## Official SDK/executor preflight

To distinguish missing tools from model non-use, a separate CPU-only private notebook
compiled the exact same archive and ran helpers on a synthetic Git repository. No
model inference, weights, competition tasks, or scored measurements were involved.
https://www.kaggle.com/code/charlesaherbst/gemma4-structured-v4-sdk-preflight version3.
Official compiler resolves load_skill/load_skill_resource/run_skill_script for repair
and verifier (plus list_skills). All three scripts execute through the official ADK
sandbox code executor: memory roundtrip, literal lookup, actual baseline assertion
failure, same-script after-fix pass, matching patch audit fingerprint. All checks pass.

Preflightv1 failed because asyncio.run was used inside IPython's event loop; corrected
to top-level await. Preflightv2 used generic SubprocessSandbox with its default TMPDIR
inside the synthetic repository, causing materialized skill resources to appear as
untracked files during audit. V3 explicitly sets external TMPDIR to match the actual
SWE worker's environment. These were preflight setup defects, not hidden agent-score
changes. Reports/logs retained separately. No submitted source was changed for them.

The preflight establishes compiler/tool exposure and deterministic execution, not that
Gemma will choose the skills or that every submitted-runtime environment is identical.

## Decision and next experiment

Keep v3 as the submitted archive. V4's one-response triage mechanism worked, but the
exploration bottleneck moved into repair and skill adoption failed. The best-supported
next control is to make the structured operations the default path: narrower repair
capabilities, explicit initial skill activation, and fewer raw-shell bypasses. Compare
that with a triage-only/native-tools control at the same global budget. Do not fix
this by adding more skills or increasing all task budgets. Audit/repro selection and
mandatory verification remain soft until the allowed runtime provides enforcement.

Raw outputs: runs/kaggle/structured-v4-diagnostic-v1.
Stage/audit/paired reports: runs/experiments/structured-v4/diagnostic-v1-*.json.
CPU SDK report: runs/kaggle/structured-v4-sdk-preflight-v3/sdk_preflight.json.
No recurring job or active collector remains.
