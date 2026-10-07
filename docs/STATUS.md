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

## Simple v1 implementation and dev pilot

- Source: `agents/simple-v1`; design review: `docs/SIMPLE_V1.md`.
- Exactly three roles; bounded locator and investigator AgentTools; root verifies and submits.
- Archive SHA-256: `510b45f2a24e61aa1b17b6341366c4425223efb092541ea5ab09f3403675b8ce`.
- Portable validation and packaging passed. Toolkit: 33 tests plus formatter/linter passed.
- Candidate: https://www.kaggle.com/code/charlesaherbst/gemma4-simple-v1-dev3 (v2, running; v1 stopped before model setup due to notebook hardware-recording order, repaired).
- Baseline: https://www.kaggle.com/code/charlesaherbst/gemma4-baseline-dev3 (v2, running; v1 stopped before model setup due to notebook hardware-recording order, repaired).
- Identical frozen dev cohort: `fastapi_11194`, `requests_7502`, `rich_3105`.
- Run record: `runs/experiments/simple-v1/EXPERIMENT.md`; outputs to `runs/kaggle/simple-v1-dev3` and `runs/kaggle/baseline-dev3`.
- New notebook outputs preserve returned runner errors and actual GPU metadata. Infrastructure errors block submission; timeouts are tracked as agent-budget failures.
- No leaderboard submission yet. User authorized submission after evaluation through the checked uploader. Holdout untouched in this experiment.

## Next actions

1. Collect both existing dev runs; inspect runner and verification diagnostics.
2. Compare identical cohorts, fix concrete failures if needed, and submit a valid evaluated candidate via the daily-slot-checked uploader.
3. Expand evaluation to the full 14-task dev cohort before claiming strength; keep the holdout for milestone comparisons.

## Practical limits

This Mac has roughly 6 GiB free disk, no NVIDIA GPU, and no Docker. It is the control machine;
Kaggle provides the offline GPU evaluation worker. The optional training recipe needs a
separate sufficiently large NVIDIA worker and has not been GPU-validated. No paid compute
or recurring automations have been configured.
