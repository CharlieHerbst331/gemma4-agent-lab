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
2. Loop bounds. `repair_1_loop` has `max_iterations: 15`, `repair_2_loop`
   6, and `repair_3_loop` 3. The timing model in `docs/SINGLE_V5.md` is
   about 2.05 seconds plus 26 ms per completion token. Repair thinking is
   256 tokens, at most about 6.7 seconds. One obedient step, a short tool
   call plus that thinking, is about 10 seconds. `15 * 10 = 150` and
   `(15 + 6 + 3) * 10 = 240`. v8 smoke5 walls, recorded in
   `docs/STRUCTURED_V13.md`, were 248.3, 302.5, 303.5, 304.7, and 307.6
   seconds (mean 293.3). This checkout has no per-call trace, so 10 seconds
   is that model, not a counted smoke call. `max_output_tokens` is 2048 on
   `repair_1` (the heredoc has to fit), 1024 on `repair_2`, `repair_3`,
   and `verify_3`, and 512 on `verify_1` and `verify_2`. A full 2048-token
   generation is about 55 seconds before thinking, so the iteration count
   is not a wall clock if a step fills its budget.
3. Gate skill. `verify_3` lists `skills/gate`. The prompt requires
   `{"skill_name":"gate","file_path":"scripts/run.py"}` before
   `submit_patch` when 45 seconds or more remain. The script compiles
   touched `.py` files, imports them, runs `tests/test_<stem>.py` or
   `test/test_<stem>.py` or `test_<stem>.py` when that file exists, and
   prints PASS or FAIL. A `py_compile` failure restores `/tmp/pre_` plus
   the path with slashes replaced, and only when that backup exists. An
   import failure or a test failure does not restore. The repo comes from
   `git rev-parse --show-toplevel` on the process cwd, its parents, or a
   `PYTHONPATH` entry. It does not fall back to `/workspace`. A path under
   `/tmp` is not an edit. The check budget is 20 seconds per command.
4. Clock. Roles with tools are told to call `get_status` and to prefix
   `run_command` with the v12 `/tmp/t0` elapsed line. `get_status` is the
   harness clock (`agent_elapsed_seconds`). The `/tmp/t0` line starts at
   the first command. Both are prompt text. `get_status` does not stop a
   role.

`eval_config.yaml` stays at 300 seconds, 220 calls, and 320 turns. That is
not a uniform per-task cut. Map and check are the structured-v14 scripts,
including their `/workspace` lookup. The gate does not use that lookup.

## What cannot be enforced from the zip

- A hard end of `repair_1` at 150 seconds, or of the repair phase at 240
  seconds, when the model keeps calling tools. `LoopAgent` in google-adk
  1.36.1 (`loop_agent.py`) increments `times_looped` only after the
  sub-agent returns. `max_iterations` does not interrupt that call.
  structured-v7 recorded the same hole: `max_iterations: 3` never started
  verify because repair never returned. The 15/6/3 counts bound restarts
  of a step that does return. They do not guarantee the clock.
- There is no escalate tool in the host list, and a skill script's return
  value is stdout. The repair loops run every iteration even after a good
  edit. The prompt says later steps should be text only.
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

SHA256 `9b9e3bb1f3b500811358d00c608def24573ed12f8090ebb59a0900168636e072`.
27 files. Portable validation passed. structured-v14's archive is unchanged
at `8eeae0c1859766bc08afafe2b6139e4ea4ebd82ab52b42c04bd01836e4e361bf`.
