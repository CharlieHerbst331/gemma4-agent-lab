# Nits backlog

Not in the current archives. `agents/` stays unchanged until a later
single-v8-check revision. These notes are from the PR #23 recheck.

## check skill (`agents/single-v8-check/skills/check/scripts/run.py`)

- `_harness_only` strips with `lstrip("./")`. That treats every leading `.`
  and `/` as trim characters, so a staged `.pytest.ini` alone becomes
  `pytest.ini` and loses its `[protected]` marker. Use `removeprefix("./")`.
  `setup.cfg` alone is still flagged.
- The prompt calls the skill once, after the edit. That call creates the pin,
  so the script prints `before: PASS exit=0`. The result can be a real pass,
  but the label says before, and the weakening detector cannot fire on a
  single call.
- `conftest.py` and `pytest.ini` are unmarked only when they are the only
  changes. Once any real edit exists they are marked `[protected]` again
  (`diff conftest.py [protected]`).
- The prompt recipe uses `old = b'''OLD'''` and `new = b'''NEW'''`. An OLD or
  NEW that ends in a single quote, or that contains `'''`, is a SyntaxError.
  The file is left untouched. The prompt warns about triple quotes and
  backslashes, not about a trailing quote.
- Repo discovery tries `GEMMA_CHECK_ROOT`, then `/workspace`, then
  `PYTHONPATH`. On the subprocess sandbox `/workspace` is the host path. If
  that host directory is a git checkout, the skill inspects the wrong repo.
  Prefer `PYTHONPATH` (the sandbox workspace) before `/workspace`. In Docker
  both point at the task workspace, so either order works there.

## `hit_cap.wall` on unmatched pairs

The notebook session uses one cap, the max of the two arms (`cap_seconds=330.0`
on single-v7 vs single-v8 dev-13). `hit_cap.marker` ("exceeded session
timeout") is per run and is the accurate cap signal for arm A (270 s).

`hit_cap.wall` in the regenerated pair report is now per arm when
`matched_pair` is false: wall is compared with that arm's
`max_time_minutes`. Arm A at about 275 s counts. Arm B still uses 330 s.
The marker is left as the session stored it. Matched reports keep the stored
wall flag. The notebook runtime is unchanged, so existing generated notebooks
stay the same. The live `pair_results.jsonl` row is still written against the
shared session cap.
