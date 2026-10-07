# Project status

Last updated: October 6, 2026 (Pacific).

## Established

- Private GitHub repository: https://github.com/CharlieHerbst331/gemma4-agent-lab
- Python 3.12 local environment, locked dependencies, installed `gemma-lab` CLI.
- Kaggle account `charlesaherbst`; authenticated competition file access verified.
- Official notebook, HARNESS_README, and tasks downloaded into ignored directories.
- Public task inventory: 129 tasks; frozen split is 95 train / 14 dev / 20 holdout.
- Baseline config, validated deterministic archive, private GPU notebook generator.
- Research snapshot saved locally: `runs/research/2026-10-06.json`.
- 30 toolkit tests, formatter/linter, and package build pass locally.
- GitHub Actions passed for the initial development-kit commit.
- Submission command exercised in plan mode; no leaderboard submissions sent.

## GPU smoke experiment B0

- URL: https://www.kaggle.com/code/charlesaherbst/gemma-4-agent-lab-evaluation
- Version: 1.
- Candidate SHA-256: `2df8bc24ea9a2ee298da6487e95a0c891879349325692ab0a0821d453c9117fe`.
- Two public tasks selected by the official starter's order.
- Completed: 0/2; one context-window error and one agent timeout. These are infrastructure/debugging evidence, not a generalization measurement.
- Outputs: `runs/kaggle/smoke-v1`. Original summary omitted returned runner errors; source diagnostics contain them.

## Simple v1 implementation and dev evaluation

- Source: `agents/simple-v1`; review and limits: `docs/SIMPLE_V1.md`.
- Implementation commit: `22cd4ab` (initial candidate); revised prompt source hashes are recorded in manifests.
- Initial candidate SHA-256: `510b45f2a24e61aa1b17b6341366c4425223efb092541ea5ab09f3403675b8ce`.
- Initial dev3: 1/3 versus baseline 0/3; FastAPI win, no regressions. Two candidate timeouts, three baseline timeouts. No runner infrastructure errors. Requests grading timed out at 60 seconds and the candidate patch contained scratch/debug output; initial archive NOT submitted.
- Actual hardware: 4 × NVIDIA L4; swegemma 0.2.7, adk-submission 0.2.12, adk-eval-core 0.1.0, vLLM 0.19.1, google-adk 1.36.1.
- Comparison/audit: `runs/experiments/simple-v1/comparison.json`, `trace-audit.json`.
- Revised SHA-256: `fb9ebb8f452dc78fba7fb5bdcf80b74190496b1e31a72cd206be803bd855db7d`.
- Revised prompts target observed ignored limits, skipped investigator, malformed arguments, swallowed assertions, and scratch/debug pollution. Verification timeout restored to official 300 seconds.
- Portable validation/packaging passed; toolkit 33 tests plus formatting/linting passed.
- Revised dev3: https://www.kaggle.com/code/charlesaherbst/gemma4-simple-v1-r1-dev3 (v1, running).
- Full frozen dev14: https://www.kaggle.com/code/charlesaherbst/gemma4-simple-v1-r1-dev14 (v1, dispatched).
- Output paths: `runs/kaggle/simple-v1-r1-dev3`, `runs/kaggle/simple-v1-r1-dev14`.
- Identical pilot IDs: `fastapi_11194`, `requests_7502`, `rich_3105`. Full dev IDs: `configs/splits/public-v1.json` dev partition.
- No leaderboard submission yet. User authorized submission after exact-hash evaluation through the checked uploader. Holdout untouched.

## Next actions

1. Collect revised dev3/dev14 runs, audit patches/traces, compare revised dev3 against the identical baseline and initial candidate.
2. Record full-dev results and use the checked uploader for the evaluated archive if infrastructure and patch hygiene permit.
3. Reserve holdout for milestone comparison; do not claim competitiveness from the pilot.

## Practical limits

This Mac has roughly 6 GiB free disk, no NVIDIA GPU, and no Docker. It is the control machine;
Kaggle provides the offline GPU evaluation worker. The optional training recipe needs a
separate sufficiently large NVIDIA worker and has not been GPU-validated. No paid compute
or recurring automations have been configured.
