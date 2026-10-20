# structured-v14

Unevaluated copy of structured-v13-1. The directory is `agents/structured-v14`
and the agent name is `structured_v14`. Existing agent directories were not
modified. No score is claimed. No GPU run and no submission.

## Hypothesis

A zero-arg map before any read, plus numbered 100-line windows, should cut
no-edit runs below 59/118 and calls to the first edit below the median of 21.
That trace comparison was not run. The offline file-hit numbers below are a
proxy for localization only.

## What changed

The cap stays 300 seconds, with 220 calls and 320 turns. The guarded heredoc,
the empty-diff net, the 180/240 second handoffs, and the repeat-ban wording
stay at v13-1. `get_status` never counts as a repeat.

Triage's only call is the map skill. It names at most three files and the
class or function copied from the map, before repair reads. Repair and verify
reads are `nl -ba PATH | sed -n 'A,Bp' | head -c 4000` with a 100-line window.
Noisy commands go through `tail -n 40 | head -c 4000`. Those commands are
plain `bash -c` tools. The map script is Python and does not read shell rc
files.

The map walks the task repo at run time. It skips dotfiles, vendored
directories, and test, docs, and example directories, including `docs_src`.
It prints every kept path it can, then class and function signatures until
12000 characters. Truncation is deterministic: files stay in sorted order,
and signature names stop when the next name would pass the budget. Nothing
is precomputed for a public repo.

## Offline file-hit

Method. Train IDs are the 95 IDs in `configs/splits/public-v1.json`. The
competition `tasks.jsonl` is not in this checkout, so each ID was read as a
public GitHub pull request (`fastapi_11355` is `fastapi/fastapi` pull 11355,
and the same for Rich, Requests, and HTTPX). The gold set is the pull
request's `.py` files outside the directories the map skips. Three pulls
changed only those skipped paths, so they are not in the denominator.
Dev and holdout IDs were not used. Gold paths were not written into the
agent.

This is not a model. Both arms rank three paths by identifier overlap with
the pull-request title and body. The baseline uses the full map-eligible
path listing and no signatures. The map arm uses the skill output, so a
file that the budget dropped cannot be chosen, and a signature token can
raise a file's score. Ties break by path. A hit means one gold source file
is in the three paths.

| Arm | Hits | n | Rate |
|---|---:|---:|---:|
| Baseline listing | 31 | 92 | 33.7% |
| Map output | 33 | 92 | 35.9% |

Both hit on 20. The map alone hit on 13. The listing alone hit on 11.
Neither hit on 48.

Map wall time is the second render, after the tree was already checked out.
Across 91 unique base commits the median was 0.071 seconds, the mean was
0.083 seconds, and the max was 0.147 seconds. The longest output was 12000
characters.

Limits. The proxy misses a paraphrase that does not reuse an identifier.
Pull-request files are not the competition gold patch. The base commit is
the pull request's base SHA. Checkout time is not in the map timing. n=92
is not a resolve rate, and it does not measure the 59/118 no-edit claim.

## Record

- Base git revision: `06c0344323f6ee561451379ee216506af717e61e`
- Archive SHA256:
  `1fd3227d23da56900cdfca23fc5ff5a73cf9da6a5ffa7d613fbb3b83fc3e9336`
- Frozen split: `configs/splits/public-v1.json`, train IDs only. No cohort
  was executed.
- Hardware: none. No GPU run.
