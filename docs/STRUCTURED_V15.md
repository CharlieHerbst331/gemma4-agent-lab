# structured-v15

Unevaluated copy of structured-v14. The directory is `agents/structured-v15`
and the agent name is `structured_v15`. Existing agent directories were not
modified. No score is claimed. No GPU run and no submission. The dev-13
notebook was not executed.

## Hypothesis

Shorter repair loops, no read tools on the later roles, and a prompt-mandated
gate before submit should leave time for verify and submit, and should print
FAIL on a broken touched module. v13-1 left 6 of 13 tasks empty or wrong on
reachable work: 4 empty timeouts, 1 wrong file, and 1 regression. That
comparison was not run. The cap stays 300 seconds, 220 calls, and 320 turns.

## What the archive can declare

The hosted runner does not load `agent.py` and does not pass a callback
registry. The copy of `swegemma/harness/agent_runner.py` in this checkout
calls `compile_submission` at lines 334-346 with `tool_registry`,
`model_registry`, `code_executor`, `script_timeout`, `limits`,
`generation_constraints`, `adapter_manifest`, and `adapter_resolver_fn`.
There is no `callback_registry` argument. Verification of swegemma 0.2.10
and 0.2.11 found the same omission (`agent_runner.py` line 578 in 0.2.10
and line 616 in 0.2.11).

`adk-submission` `compiler.py` lines 1-8 say the compiler never performs
arbitrary dynamic imports or calls `importlib`. Tools, models, callbacks,
and skills come from closed host registries or from sandboxed submission
directories. `compile_submission` (`compiler.py` lines 59-63) takes
`callback_registry` as an optional argument that defaults to `None`.
`resolvers/callbacks.py` lines 84-85 return the callback kwargs empty when
that registry is `None`, so YAML callback names are dropped. `resolvers/tools.py`
lines 64-66 resolve a string tool name only with `tool_registry.get`. An
archive cannot replace those callables. `resolvers/tools.py` lines 184-216
are the other branch: when `skill_registry` is `None`, the compiler loads
`skills/<name>` with `google.adk.skills.load_skill_from_dir`. That script
runs only when the model calls `run_skill_script`. The public 0.2.12 and
0.2.13 trees used here are that compiler source with `thinking_budget` `ge`
set to 0 and a version label. `resolvers/callbacks.py`, `resolvers/tools.py`,
and `compiler.py` match between those two labels. Real 0.2.12 and 0.2.13
wheels are not on PyPI. google-adk is 1.36.1.

`schema.py` accepts, and the compiler enforces, these archive fields:
per-role `tools` lists, `skills` paths, `max_output_tokens`, and
`LoopAgent.max_iterations`. `eval_config.yaml` caps are read by swegemma,
not by the ADK compiler. There is no per-role tool-call field. `max_llm_calls`
is not a submission field.

## What v15 uses

1. Tool lists. `triage` has `tools: []` and the map skill, so its only
   generation is bounded by `max_output_tokens: 1024`. `repair_1` keeps
   `get_status`, `read_file`, `run_command`, and the three graph tools.
   `repair_2`, `repair_3`, `verify_1`, `verify_2`, and `verify_3` do not
   have `read_file` or the graph tools. `submit_patch` is only on
   `verify_3`.
2. Loop bounds. `repair_1_loop` is 8 passes, `repair_2_loop` is 3, and
   `repair_3_loop` is 2. A pass is a normal tool loop: several calls, then
   a text reply. It is not one tool call plus a report. `get_status` does
   not count as a tool call. The prompt calls it at the start of the role,
   before an edit, and near a handoff, not before every read.
   `repair_2` and `repair_3` may read one `sed -n` window of at most 40
   lines (`B` is `A` plus 39) of the file named in the previous report.
   `max_output_tokens` is 2048 on `repair_1`, 1024 on `repair_2`,
   `repair_3`, and `verify_3`, and 512 on `verify_1` and `verify_2`.
3. Gate skill. `verify_3` lists `skills/gate`. The prompt requires
   `{"skill_name":"gate","file_path":"scripts/run.py"}` before
   `submit_patch` when 45 seconds or more remain. The script compiles
   touched `.py` files, imports them, and runs
   `python -m pytest -x -q` on `tests/test_<stem>.py`, `test/test_<stem>.py`,
   or `test_<stem>.py` when that file exists. The pytest timeout is 20
   seconds. If pytest cannot be imported, the line is
   `test NOOP pytest missing` and the file is left. A `py_compile` failure
   restores `/tmp/pre_` plus the path with slashes replaced, and only when
   that backup exists. An import failure or a test failure does not
   restore. The repo comes from `git rev-parse --show-toplevel` on the
   process cwd, its parents, or a `PYTHONPATH` entry. It does not fall
   back to `/workspace`. A path under `/tmp` is not an edit.
4. Clock. Roles with tools are told to call `get_status` occasionally and
   to prefix `run_command` with the v12 `/tmp/t0` elapsed line.
   `get_status` is the harness clock (`agent_elapsed_seconds`). The
   `/tmp/t0` line starts at the first command. Both are prompt text.
   `get_status` does not stop a role.

## Measured turn times

v8 smoke5, 206 agent steps, gaps in `extra.elapsed_s`: a model turn is
median 3.9 seconds, mean 6.6 seconds, p90 13.8 seconds. Text-only gaps
are median about 5 seconds. The 118-trace note in
`research/harness-directions-oct20.md` has median 1.97 seconds between
tool calls, and median 21 calls and 63.6 seconds to the first edit.
Those figures are from the verification of the smoke, not a new run in
this checkout. v8 smoke5 walls in `docs/STRUCTURED_V13.md` were 248.3,
302.5, 303.5, 304.7, and 307.6 seconds (mean 293.3). Four of five hit
the 300 second cap.

The old 10 second step was a token model (2.05 seconds plus 26 ms per
token). A prompted step of `get_status`, one tool, and a report is 2 or
3 turns, about 13 to 20 seconds at the measured 3.9 and 6.6 second turns.
Fifteen of those steps are about 195 to 300 seconds, and at most 15 tool
calls. That is below fastapi_11194's first edit and below the 21-call
median, so that pattern is not used.

`repair_1` call budget against those edits. Calls below exclude
`get_status`.

- fastapi_11194: first edit at call 16, 173 seconds. repair_1 made 20
  calls. `16 * 13.8 = 220.8` seconds at the p90 turn, under the 300
  second cap. A text-only stop at 150 seconds would land before this
  edit, so the prompt does not stop an empty diff at 150 seconds.
- 118 traces: median 21 calls and 63.6 seconds to the first edit.
  `21 * 6.6 = 138.6` seconds at the mean turn. One pass can hold that.
- rich_3454: first edit at call 11, 87 seconds, then 29 calls in
  repair_1. `29 * 6.6 = 191.4` seconds at the mean. `29 * 13.8 = 400`
  seconds at the p90, which the 300 second cap would cut. The cap still
  binds on a slow pass. The iteration count does not.

8, 3, and 2 are restart counts, not call counts. The first `repair_1`
pass is allowed to make several calls, so the 16-call and 21-call edits
are not cut by the loop. Fewer restarts would shrink the idle floor
further. These counts are the review's 8/3/2, chosen because 15 one-call
steps were already below the edits above.

## Idle floor

`LoopAgent` cannot skip an iteration. There is no escalate tool, and a
skill script cannot set one. Every pass runs. When a source diff already
exists, the prompt says reply `DONE` with no tool call, so that pass is
one short turn.

Minimum turns before `verify_3`, if triage does the map and a brief and
every later repair pass and both early verifies are one turn:

`2 + 8 + 1 + 3 + 1 + 2 = 17`.

- Median turn: `17 * 3.9 = 66.3` seconds.
- Text-only median: `17 * 5 = 85` seconds.
- Mean turn: `17 * 6.6 = 112.2` seconds.
- p90 turn: `17 * 13.8 = 234.6` seconds.

The previous 15/6/3 loops were 24 repair turns, plus triage's 2 and the
two early verifies, 28 turns. At 3.9 to 6.6 seconds that was about 109
to 185 seconds before `verify_3`. The new floor is 17 turns, about 66
to 112 seconds at the median and the mean.

v8 cap-hit tasks ran about 302 to 308 seconds and often never left
repair_1, so `verify_3` did not run. v15 reaches `verify_3` only after
each pass returns. A pass that keeps calling tools is still not
interrupted, and the 300 second cap can still land inside `repair_1`.
When passes do return, the idle remainder is those 17 short turns. That
is time v8 did not spend on forced restarts. The p90 floor of 234.6
seconds would itself crowd the cap. That is the slow tail, not the
median plan.

`eval_config.yaml` stays at 300 seconds, 220 calls, and 320 turns. That is
not a uniform per-task cut. Map and check are the structured-v14 scripts,
including their `/workspace` lookup. The gate does not use that lookup.

## What cannot be enforced from the zip

- A hard end of a pass at a clock time, when the model keeps calling
  tools. `LoopAgent` in google-adk 1.36.1 (`loop_agent.py`) increments
  `times_looped` only after the sub-agent returns. `max_iterations` does
  not interrupt that call. structured-v7 recorded the same hole:
  `max_iterations: 3` never started verify because repair never returned.
  The 8/3/2 counts bound restarts of a pass that does return. They do
  not guarantee 150 or 240 seconds.
- There is no escalate tool in the host list, and a skill script's return
  value is stdout. The repair loops run every iteration even after a good
  edit. The prompt makes that iteration one `DONE` turn. It cannot skip
  the iteration. The idle floor above is that cost.
- `submit_patch` is the host callable. The gate cannot wrap it. A model
  that skips the skill still submits. The empty-diff net in the `verify_3`
  prompt is still prompt text.
- Callbacks and in-archive tool wrappers do not run on the hosted path.
  They are not in this candidate.
- A `py_compile` failure with no `/tmp/pre_` backup is left in place. The
  script does not run `git show HEAD` or `git checkout`, because that wipe
  is the empty-diff failure the v8 net exists to avoid.
- An import or test failure is printed and kept. A rich_4070-style import
  deletion that still parses is a FAIL line, not a revert. Reverting it
  would also wipe a correct edit that fails `import src.pkg.mod` or a
  missing dependency. The src-layout import tries `pkg.mod` as well as
  `src.pkg.mod` and still does not restore on failure.

## Runtime gate

The internal 120-task block is `120 * (mean + 70) <= 39600`, so the mean
must be at most 260 seconds. `120 * ((300 + 8) + 70) = 45360`, which fails
that block. v13-1's dev-13 mean was 279.6 seconds, and
`120 * (279.6 + 70) = 41952`, which also fails. The gate adds at most 20
seconds per compile, import, or test command, and only when the model calls
it. The host limit is 12 hours total. An upload whose mean is above 260
seconds still needs the uploader override. None of these figures is a v15
measurement.

## Dev-13 notebook

`notebooks/structured-v15-dev13.ipynb` lists the 13 dev ids. The reachable
ceiling is 10. The report cell is in the notebook, not in `agents/`. It
reads `task_results.jsonl` and trace JSON and prints resolved count,
per-task wall time, no-edit runs, and calls to the first edit. `compile_plain`
calls `compile_submission` with no callback registry. The notebook was not
run.

## Archive

SHA256 `194cf0d42e7088d760da3a36d7da27ac82b1e66551843bb1579c108e8c03ce45`.
27 files. Portable validation passed. structured-v14's archive is unchanged
at `8eeae0c1859766bc08afafe2b6139e4ea4ebd82ab52b42c04bd01836e4e361bf`.
