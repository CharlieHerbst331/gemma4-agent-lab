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
- Toolkit tests, formatter/linter, and package build pass locally.
- Submission command exercised in plan mode; no leaderboard submissions sent.

## GPU smoke experiment B0

- URL: https://www.kaggle.com/code/charlesaherbst/gemma-4-agent-lab-evaluation
- Version: 1.
- Candidate SHA-256: `2df8bc24ea9a2ee298da6487e95a0c891879349325692ab0a0821d453c9117fe`.
- Two public tasks selected by the official starter's order.
- Last observed state: running. No verified resolution rate yet.
- Generate/push provenance is locally under `notebooks/generated/baseline` (ignored).
- Output destination: `runs/kaggle/smoke-v1` (ignored).

## Next actions

1. Check B0 status, pull outputs and logs; repair any real harness failure.
2. Record B0 results and infrastructure limits. Do not treat two tasks as performance evidence.
3. Generate a fixed dev cohort and run B0 versus a text-only localization control (E1).
4. Preserve run artifacts and update the experiment template with exact hashes and results.

## Practical limits

This Mac has roughly 6 GiB free disk, no NVIDIA GPU, and no Docker. It is the control machine;
Kaggle provides the offline GPU evaluation worker. The optional training recipe needs a
separate sufficiently large NVIDIA worker and has not been GPU-validated. No paid compute
or recurring automations have been configured.
