---
name: submit-candidate
description: Spend today's Kaggle submission slot on a candidate archive, through the guarded script. Use only when a new archive has dev-13 evidence and Charles's gates are met.
---

# Submit a candidate

1. Preconditions (stop and tell Charles if any fails):
   - The archive sha is not in `handoff/scored-archives.json`.
   - At least one complete dev-13 run of this exact sha has mean wall ≤300 s; ideally the mean
     across all its seeds is too.
   - It is a meaningful bet: write the one-sentence hypothesis.
   - Today's UTC slot is unused (`$KAGGLE_BIN competitions submissions gemma-4-developer-agent`).
2. Plan (no upload):
   ```bash
   uv run python scripts/handoff/submit_guarded.py artifacts/<name>/submission.zip \
     --evaluation runs/dev13/<name>-dev13-paired-s1 --evaluation runs/dev13/<name>-dev13-paired-s2 \
     --message "<name> main <short commit>: <hypothesis>"
   ```
3. If every guard passes, rerun the same command with `--execute`.
4. Afterward: add the row (ref, UTC date, agent, sha256, score null) to
   `handoff/scored-archives.json`, add a `docs/STATUS.md` entry, open a PR, and merge it once CI
   passes. Check the score a few hours later and fill it in.
5. If the upload ERRORS on Kaggle, do not retry blindly. Read the status and logs first.
