---
name: analyze-dev13
description: Download finished dev-13 Kaggle runs and compare arms (resolved per seed, empty diffs, wall mean/p90/max, compactions, failed edits, loops). Use after a dev-13 kernel completes or when asked how a version did.
---

# Download and analyze dev-13 results

1. Fetch each finished kernel (add `--wait` to poll every 4 minutes):
   ```bash
   scripts/handoff/fetch_dev13.sh <name>-dev13-paired-s1
   ```
   Output lands in `runs/dev13/<slug>/`. If the kernel ERRORED, read the `.log` there first.
   A "waiting for tasks.jsonl" failure is the data-mount pitfall (HANDOFF.md §7).
2. Compare against the baselines. Box-era runs are in the artifacts tarball
   (`~/gemma4-context/gemma4-team/...`, see handoff/SETUP.md §7):
   ```bash
   uv run python scripts/handoff/analyze_dev13.py \
     v21-1-s1=$C/testing/v21-1-walltime/out v21-1-s3=$C/v22/out/paired-nb-v21-1-s3 \
     <name>-s1=runs/dev13/<name>-dev13-paired-s1 [more seeds] --json runs/dev13/summary.json
   ```
   Labels ending in `-s<N>` are grouped into one arm.
3. Read traces for the tasks that changed state (R/F/E matrix). Traces are
   `results/traces/trace_<task>.json`; look at the first edit call, compaction points, and any
   repeated identical calls.
4. Report to Charles: the per-arm table, the 300 s gate verdict, what moved and why (with
   trace evidence), and a clear recommendation: submit, iterate, or drop. Verdicts must account
   for noise (sd ≈ 0.6 task per seed on dev-13).
