---
trigger: always_on
description: Charles's standing principles for the Gemma 4 Kaggle project. Always apply.
---

# Charles's principles (owner: Charles A Herbst)

1. **The goal is to win.** Winning takes risk. Prefer a bold, evidence-backed bet over a safe
   tweak. A version that only re-tests an idea we already measured is not a bet.
2. **Every daily slot tests a meaningful bet.** One submission per UTC day. Before spending it,
   write down the hypothesis, what dev-13 showed, and what score would confirm or refute it.
3. **Never resubmit an already-scored archive.** Check `handoff/scored-archives.json` and the
   Kaggle history. The only exception: an identical retry of an upload that ERRORED without a
   score, and only after reading why it errored.
4. **No endless smoke tests.** One infrastructure check per new mechanism is enough. Then run
   real dev-13 seeds (2–3) or submit. Do not spend GPU hours re-confirming things that work.
5. **The harness is a cradle.** The local Gemma 4 31B W4A16 loops, hallucinates and is often
   wrong. Protect it from noisy outside information: narrow searches, small read windows, short
   prompts, no stale instructions, no tools it misuses, one reliable edit path, an early commit
   to an edit. Do not starve its reasoning (keep thinking on, budget 4096, output cap ≥6144).
6. **Respect the 12 h limit.** Mean wall ≤ ~300 s per task over 129 tasks. Long-term, once
   enough tasks solve inside that mean, relax the per-task limit to give hard tasks more time,
   but always re-check the 129-task projection.
7. **Evidence over vibes.** Every claim cites a trace, a run, or a source. Report mean, p90 and
   max wall, resolved per seed, empty diffs, compactions, failed edits. Never invent scores.
   One public score is ±0.08–0.11 noise.
8. **Merging.** Docs, scripts and toolkit PRs may merge once CI passes. A PR that adds or
   changes a submission candidate (`agents/…`) needs a verification pass first: a separate
   review of the diff against the spec plus the dev-13 numbers. Charles does not need to be
   asked to merge a verified PR.
9. **Ask Charles before** spending a submission slot on anything that fails the gates in
   `10-kaggle-ops.md`, provisioning paid hardware, accepting new terms, making anything public,
   or starting a recurring job.
