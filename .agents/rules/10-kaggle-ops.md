---
trigger: always_on
description: Safety rules for Kaggle submissions, GPU kernels and secrets in this repo.
---

# Kaggle operations

- **Submit only via** `uv run python scripts/handoff/submit_guarded.py ARCHIVE --evaluation
  DIR … --message "…" --execute`. Never call `kaggle competitions submit` directly. The guard
  refuses an archive already in `handoff/scored-archives.json` or in Kaggle history, and an
  archive without a complete dev-13 run of the same sha with mean wall ≤300 s. Then
  `gemma-lab submit` enforces one per UTC day and the 129-task projection.
- After a successful upload, add its row to `handoff/scored-archives.json` and a
  `docs/STATUS.md` entry in the same day's PR. Record the Kaggle ref and, once scored, the score.
- **Push GPU kernels only via** `scripts/handoff/push_dev13.sh` (it pins the archive hash and
  patches the data-mount path). At most 2 GPU sessions run at once. Check `kaggle kernels list
  --mine` before pushing, and never push duplicates of a running slug.
- Kernel names: `<agent-name>-dev13-paired-s<N>`. Download results with
  `scripts/handoff/fetch_dev13.sh` into `runs/dev13/` (git-ignored).
- **Secrets.** Kaggle tokens live only in `~/.kaggle/access_token` or `~/.kaggle/kaggle.json`
  (chmod 600) or the `KAGGLE_API_TOKEN` env var. Never print, log, commit, or paste them. Source
  `scripts/handoff/kaggle_env.sh` before CLI calls (it fixes the KGAT_/KAGGLE_KEY quirk).
- Never commit data, model weights, traces, archives, or `runs/` contents. `.gitignore` covers
  `*.zip`, `artifacts/`, `runs/`, `data/`, `kaggle.json`, `access_token`.
- Agent directories are immutable once evaluated or submitted. New idea → new directory
  (`agents/structured-v22-1`), copied from its base, with a `docs/STATUS.md` entry.
- Kaggle times are UTC; report times to Charles in Pacific time.
