#!/usr/bin/env bash
# Check a dev-13 kernel and download its outputs once it finishes.
# Usage: scripts/handoff/fetch_dev13.sh <kernel-slug> [--wait]
#   Output goes to runs/dev13/<kernel-slug>/ (runs/ is git-ignored).
#   --wait polls every 4 minutes until the kernel is COMPLETE, ERROR, or CANCELLED.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
slug="${1:?usage: fetch_dev13.sh <kernel-slug> [--wait]}"
owner="${KAGGLE_OWNER:-charlesaherbst}"
# shellcheck source=/dev/null
. scripts/handoff/kaggle_env.sh
out="runs/dev13/$slug"
while true; do
  st="$($KAGGLE_BIN kernels status "$owner/$slug" 2>&1 | tail -1)"
  echo "$(date '+%Y-%m-%d %H:%M %Z') $owner/$slug: $st"
  if echo "$st" | grep -qE 'COMPLETE|ERROR|CANCEL'; then break; fi
  [ "${2:-}" = "--wait" ] || exit 0
  sleep 240
done
mkdir -p "$out"
$KAGGLE_BIN kernels output "$owner/$slug" -p "$out" >/dev/null
echo "Downloaded to $out"
if echo "$st" | grep -q ERROR; then
  echo "Kernel ERRORED. Read $out/*.log before changing anything." >&2
  exit 1
fi
echo "Analyze: uv run python scripts/handoff/analyze_dev13.py $out [more run dirs...]"
