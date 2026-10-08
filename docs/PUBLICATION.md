# Public release record and boundaries

October8,2026 Pacific. Owner explicitly requested publishing the repository and all
current findings for handoff to their Grok bot. This authorizes this visibility change;
AGENTS.md still requires explicit owner intent for future visibility/team actions.

## Scope

Publish own agent/toolkit/training-recipe code, tests, supporting design/runbook/handoff
documents, grouped cohort identifiers and checksums, and allowlisted own result
observations. Original task text, snapshots, reference/test patches, grading conditions,
generated patches, raw traces/logs, credentials, weights, archives and downloaded
third-party packages remain ignored/excluded. Existing operational notes refer to
private paths for the owner; a public reader cannot assume those artifacts exist.

`export_public_findings.py` emits a strict field allowlist and binds retained private
raw results by SHA256 without disclosing their contents. It does not anonymize raw
traces or copy generic result objects wholesale. Redaction tests check that private
patch/error/credential sentinels do not enter the public export.

A Git object audit scanned all historical blobs for high-confidence credential
patterns and checked historical paths against excluded artifact/data categories.
No matching credential or forbidden tracked artifact was found. This is a bounded
source/history audit, not a guarantee against every possible secret encoding.

## Code-sharing obligation

The [official rules](https://www.kaggle.com/competitions/gemma-4-developer-agent/rules)
permit public code sharing and require shared competition code to be made available
through associated Kaggle forums/notebooks, under an OSI-approved commercial-use
license. This repository uses Apache2.0.

The owner explicitly requested delaying the Kaggle notebook and will add it later.
That sharing step remains pending. No public Kaggle notebook, forum post, teammate
invitation or new legal acceptance was performed for this release. This record does
not assert that the outstanding Kaggle sharing step is completed.

## Current score truthfulness

The only uploaded submission56905832 was accepted for upload but now reports ERROR,
without a leaderboard score. Dev/diagnostic counts are separate official local-style
harness evaluations on public tasks. The selected3/3 pilot is not a leaderboard or
holdout/generalization claim. Raw/diagnosed infrastructure failures must stay visible.

## Published state

GitHub repository is PUBLIC; authenticated metadata and an unauthenticated GitHub
API request both confirmed it. README, HANDOFF, HARNESS_SPEC, RUN_CATALOG and redacted
evidence were fetched without credentials and matched committed local bytes.
Release checks:66tests plus lint/format passed;160historical blobs scanned with no
matched credential pattern or forbidden artifact path. All own findings/source are
at https://github.com/CharlieHerbst331/gemma4-agent-lab . Kaggle mirror remains pending
owner action, exactly as requested. No collaborator invitation or new submission.
