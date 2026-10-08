---
name: task-memory
description: Persist a compact task-scoped evidence ledger after hypothesis changes, failed checks, or role handoffs; recover decisions after a context gap without rereading source.
---
Use this for decisions and evidence, not transcripts or general conversation memory.
Run scripts/ledger.py through run_skill_script. Default workspace comes from sandbox
PWD, scratch from TEST_TMPDIR. Updates are locked and atomic. Memory is outside the repository, bounded to 4200
characters, and reset when workspace/baseline identity changes.

Use args as an object for simple calls: {"action":"read"}, or
{"action":"update","hypothesis":"A discards B","evidence":"src/module.py:42 branches on A"}.
For several evidence/list items use a native args list, e.g. ["--action","update",
"--evidence","src/module.py:42 branch","--evidence","src/caller.py:8 caller"].
These flat options avoid nested JSON escaping. Alternatively packet is a
JSON-encoded string containing only these optional fields:
- hypothesis, next_action: factual strings, at most 400 characters each;
- evidence (8), rejected (4), changed (12), checks (4), navigation (10): lists of
  factual strings, each at most 240 characters; numbers are maximum item counts.
Updates replace the supplied lists; keep the few useful existing entries. Duplicates
are removed. Omitted fields survive. Example packet: {"hypothesis":"A discards B",
"evidence":["src/module.py:42 branches on A"],"next_action":"Check B boundary"}.

Record path:line evidence, rejected causes and why, actual check exit statuses and
fingerprints, and lookup query_keys. Do not store source dumps, hidden/reference
patches, grading metadata, credentials, or reasoning essays. A check report is an
observation; writing "passed" into memory does not verify anything.
Read after context loss or at a handoff. Update when evidence changes a decision,
not after every tool call. If the ledger rejects oversize input, compress it once.
This is durable task memory; model context reduction comes from explicit isolated
agent handoffs, not automatic transcript compaction by this script.
