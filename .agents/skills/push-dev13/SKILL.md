---
name: push-dev13
description: Build and push a private Kaggle GPU notebook that runs one agent on the 13 dev tasks (one seed). Use to measure a candidate's resolves and wall time before a submission.
---

# Push a dev-13 run

Each push uses ~1.5–2 h of Kaggle GPU time. Plan seeds deliberately (2–3 per arm), no smoke
loops.

1. Make sure the agent is committed and packs cleanly (`/pack-agent`).
2. Check what is already running:
   ```bash
   . scripts/handoff/kaggle_env.sh && $KAGGLE_BIN kernels list --mine --page-size 10
   ```
   At most 2 GPU sessions run at once. If 2 are running, wait.
3. Dry run first, then push:
   ```bash
   scripts/handoff/push_dev13.sh <name> s1
   scripts/handoff/push_dev13.sh <name> s1 --execute
   ```
   The kernel is `charlesaherbst/<name>-dev13-paired-s1`. The script patches the notebook so
   it finds the data at either Kaggle mount path.
4. Tell Charles the kernel slug, the archive sha, and when to expect results (~2 h).
5. Collect with `/analyze-dev13` when it finishes.
