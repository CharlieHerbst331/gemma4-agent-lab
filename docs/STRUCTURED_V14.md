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

Triage calls the map once, then names at most three files. Repair and verify
reads are `nl -ba PATH | sed -n 'A,Bp' | head -c 4000` with a 100-line window.
Noisy commands go through `tail -n 40 | head -c 4000; echo "exit=${PIPESTATUS[0]}"`.
That echo runs in `bash -c` and keeps the first command's status. The map
script is Python and does not read shell rc files.

The map prints a per-directory summary for the whole visited tree, then class
and function signatures until 12000 characters. Rendering keeps a running
length. It does not rebuild the text once per file. An internal 3 second
budget stops the walk and still prints the partial summary. Truncation is a
`truncated=1` header plus a `truncated:` line.

Signature order uses issue keywords only when `GEMMA_MAP_KEYWORDS` is set or
the caller passes them. The shipped call is zero-arg and does not set that
variable, so the order is top-level package files (shallower paths first).
Nothing is precomputed for a public repo.

Skipped directories are dotfiles, vendored trees, `site-packages`,
`node_modules`, and virtualenv or bytecode caches. `docs_src`, `test`,
`testing`, `tests`, `build`, and `example` are kept. Binary and large files
are counted and not parsed.

If the map errors, times out, prints `files=0` or `signatures=0`, or the repo
is non-Python, triage writes the brief from the issue text and the workspace
layout. A path in the directory summary or the workspace layout may be named
even when it has no signature line. Triage still finishes well under 20
seconds, does not invent paths, and still gives a best-guess file list for a
bare issue number such as Fix #3104.

## Offline file-hit

Method. Train IDs are the 95 IDs in `configs/splits/public-v1.json`. The
competition `tasks.jsonl` is not in this checkout, so each ID was read as a
public GitHub pull request. The gold set is every `.py` file in that pull
request. No pull was dropped for its directory. Dev and holdout IDs were not
used. Gold paths were not written into the agent. The zero-arg map was called
with no keywords.

This is not a model. Both arms rank three paths by identifier overlap with
the pull-request title and body, over the full Python listing. The map arm
adds overlap with signature tokens the map printed. Ties break by path. A
hit means one gold `.py` file is in the three paths. A separate directory
check asks whether any gold file's directory, or an ancestor printed after
roll-up, appears in the summary.

| Arm | Hits | n | Rate |
|---|---:|---:|---:|
| Baseline listing | 26 | 95 | 27.4% |
| Map output | 26 | 95 | 27.4% |

Both hit on 19. The map alone hit on 7. The listing alone hit on 7.
Neither hit on 62. Discordant counts are 7 vs 7. The exact two-sided
McNemar p is 1.0. The directory summary covered a gold file's directory
on 95 of 95.

The earlier proxy, before this fix, was 33/92 vs 31/92. That gap is two
tasks: discordant 13 vs 11, exact McNemar p ≈ 0.84. Noise. Those 92 also
dropped fastapi_14487, fastapi_14492, and fastapi_15023, the three train
pulls whose only `.py` changes sit in `docs_src` and tests. The old map
skipped those directories, so dropping the pulls hid cases the map could
not name. This run scores all 95. On those three, neither arm's top 3
hit, and the new summary does include their directories.

Map wall time is a warm render, after checkout. Across 94 train trees the
median was 0.118 seconds and the max was 0.135 seconds. A synthetic
20,000-file tree, measured three times, took 0.592, 0.592, and 0.597
seconds. Putting those three next to the 94 train renders gives n=97,
median 0.119 seconds, max 0.597 seconds. The longest train output was
11999 characters. The 20,000-file output was 11991 characters, with all
20 directories listed and `truncated=1`.

Limits. The proxy misses a paraphrase that does not reuse an identifier.
Pull-request files are not the competition gold patch. The base commit is
the pull request's base SHA. Checkout time is not in the map timing. The
skill does not see the issue text, so keyword priority was not used here.
n=95 is not a resolve rate, and it does not measure the 59/118 no-edit claim.

## Record

- Base git revision: `06c0344323f6ee561451379ee216506af717e61e`
- Archive SHA256:
  `8eeae0c1859766bc08afafe2b6139e4ea4ebd82ab52b42c04bd01836e4e361bf`
- Frozen split: `configs/splits/public-v1.json`, train IDs only. No cohort
  was executed.
- Hardware: none. No GPU run.
