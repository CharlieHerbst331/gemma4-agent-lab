#!/usr/bin/env bash
# Build a private dev-13 GPU evaluation notebook for one agent and (with --execute) push it.
# Usage: scripts/handoff/push_dev13.sh <agent-name> <seed-label> [--execute]
#   e.g. scripts/handoff/push_dev13.sh structured-v22-1 s1 --execute
# Kernel slug: <agent-name>-dev13-paired-<seed-label> under the charlesaherbst account.
# Notes:
#   - Each run is a fresh sampling draw of the same archive on the same 13 tasks.
#     Run at least 2 seeds per arm (3 is better); one seed is noise (sd ~0.6 task).
#   - Kaggle runs at most 2 GPU sessions at once on this account. Queue the rest.
#   - The notebook is patched to accept either data mount (see patch_datapath.py).
#   - One run takes about 1.5 to 2 h (model load about 7 min plus 13 tasks).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
name="${1:?usage: push_dev13.sh <agent-name> <seed-label> [--execute]}"
seed="${2:?seed label such as s1}"
execute="${3:-}"
owner="${KAGGLE_OWNER:-charlesaherbst}"
slug="$name-dev13-paired-$seed"
dir="artifacts/dev13/$slug"
rm -rf "$dir"
mkdir -p "$(dirname "$dir")"
uv run gemma-lab notebook "agents/$name" --owner "$owner" --slug "$slug" \
  --task-ids configs/cohorts/dev-13-environment-screened.json --output "$dir"
python3 scripts/handoff/patch_datapath.py "$dir"
echo "notebook folder: $dir  (kernel $owner/$slug)"
if [ "$execute" != "--execute" ]; then
  echo "Dry run. Re-run with --execute to push it to Kaggle (uses GPU quota)."
  exit 0
fi
# shellcheck source=/dev/null
. scripts/handoff/kaggle_env.sh
$KAGGLE_BIN kernels push -p "$dir"
echo "Pushed. Check with: scripts/handoff/fetch_dev13.sh $slug"
