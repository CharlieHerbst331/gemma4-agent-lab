#!/usr/bin/env bash
# Validate and pack one agent directory into artifacts/<name>/submission.zip.
# Usage: scripts/handoff/pack.sh <agent-name>      e.g. structured-v22-1
# Prints the archive sha256 and warns when that sha was already submitted or scored.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
name="${1:?usage: pack.sh <agent-name under agents/>}"
src="agents/$name"
[ -f "$src/agent.yaml" ] || { echo "No $src/agent.yaml" >&2; exit 2; }
out="artifacts/$name/submission.zip"
mkdir -p "artifacts/$name"
uv run gemma-lab validate "$src"
uv run gemma-lab pack "$src" --output "$out" >"artifacts/$name/pack.json"
sha="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$out")"
echo "archive: $out"
echo "sha256:  $sha"
echo "commit:  $(git rev-parse HEAD) (dirty: $(git status --porcelain | grep -q . && echo yes || echo no))"
if python3 - "$sha" <<'PY'
import json, sys
rows = json.load(open("handoff/scored-archives.json"))["archives"]
hit = [r for r in rows if r["sha256"] == sys.argv[1]]
if hit:
    print(f"WARNING: this exact archive was already submitted: {hit[0]}", file=sys.stderr)
    sys.exit(0)
sys.exit(1)
PY
then
  echo "Change the agent before spending a slot. Never resubmit a scored archive." >&2
fi
