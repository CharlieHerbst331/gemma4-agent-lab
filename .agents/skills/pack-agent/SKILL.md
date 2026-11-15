---
name: pack-agent
description: Validate and pack one agents/<name> candidate into artifacts/<name>/submission.zip and report its sha256. Use before any dev-13 run or submission, or when asked for an archive hash.
---

# Pack an agent

1. Confirm the directory exists: `ls agents/<name>/agent.yaml`.
2. Run:
   ```bash
   scripts/handoff/pack.sh <name>
   ```
3. Report the archive path, sha256, and git commit, and whether the tree was dirty. A dirty
   tree means the archive does not match any commit; commit first if it will be evaluated.
4. If the script prints "already submitted", stop: this archive cannot be submitted again.
   Packing is deterministic, so the same directory always gives the same sha.
5. Check the prompt size: `wc -c agents/<name>/prompts/system.md` (keep ≤8k chars) and that it
   has no `{` or `}`: `grep -c '[{}]' agents/<name>/prompts/system.md` should print 0.
