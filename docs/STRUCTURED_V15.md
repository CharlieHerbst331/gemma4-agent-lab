# structured-v15

Unevaluated copy of structured-v14. The directory is `agents/structured-v15`
and the agent name is `structured_v15`. Existing agent directories were not
modified. No score is claimed. No GPU run and no submission. The dev-13
notebook was not executed.

## Hypothesis

Code deadlines, a forced edit, and a pre-submit check should make verify and
the final submit run on every task, and should revert a rich_4070-style
import deletion before capture. v13-1 left 6 of 13 tasks empty or wrong on
reachable work: 4 empty timeouts, 1 wrong file, and 1 regression. The
taxonomy's own estimate for the edit gate is 0-1 flips. That comparison was
not run.

## Mechanisms

The prompts are the v14 prompts. The gates live in `callbacks.py` and are
named on every LlmAgent as `before_tool_callbacks`, `after_tool_callbacks`,
and `before_model_callbacks`. Each callback catches its own errors.

1. Clock and deadlines. `after_tool` appends `[elapsed Xs / remaining Ys]`
   to every tool result. The clock starts at the first callback in the
   invocation. The cap in the stamp is 300 seconds. `repair_1` ends at 150
   seconds. `repair_1`, `repair_2`, and `repair_3` end at 240 seconds. Ending
   sets `end_invocation` on that role's invocation copy and returns a final
   model response, so the SequentialAgent continues. Verify roles are not
   ended by these deadlines. At 240 seconds the ending repair role also runs
   the capture check below.
2. Edit forcing. On a repair role, once 120 seconds have passed or 30 counted
   tool calls have run and no edit has been seen, a non-edit call is rejected
   with `next call must be an edit`. `get_status` and `submit_patch` are not
   rejected. An edit call is `edit_file`, `write_file`, or a `run_command`
   whose text contains `line_fix`, `cat >`, `tee `, or `>>`. After that call,
   `py_compile` runs on touched `.py` files when the repo is visible, and a
   failure is appended to the tool result. An identical read or command with
   no edit since returns `already seen: <short summary>` and is not run
   again. `get_status` never counts as a repeat. The first `git diff` and the
   first `git status` in a role stay allowed. A new read range stays allowed.
   An edit clears the seen set, so a post-edit rerun is allowed.
3. Capture gate. Before `submit_patch`, and when a repair role ends at 240
   seconds, the gate compiles touched modules, imports them, and runs
   `tests/test_<module>.py` when that file exists. The shell budget is 20
   seconds. A passing check snapshots the file bytes. A failing check
   restores that snapshot, or the `HEAD` bytes when there is no snapshot.
   An empty diff is left alone. If the restored tree is the first failure
   and there is no snapshot, `submit_patch` is not run, so the empty-diff
   net in the v14 prompts still applies. A later failure that has a snapshot
   restores it and lets `submit_patch` capture that tree.

Shell checks use `bash --noprofile --norc -c`. When
`GEMMA_SANDBOX_CONTAINER` or `DOCKER_CONTAINER` is set, the same script is
`docker exec -i <id>` with no `-t`, and the process waits. The repo is
`V15_REPO`, else `GEMMA_CHECK_ROOT`, else `/workspace` inside that container.
Without one of those, the git and pytest checks do nothing. The clock,
deadlines, repeat ban, and edit force still run.

## Compiler

`adk-submission` resolves callback names only from the host
`CallbackRegistry`. The current public `agent_runner` calls
`compile_submission` without one, and a missing registry drops the names.
The candidate still lists the names. `register_callbacks` fills a registry.
`notebooks/structured-v15-dev13.ipynb` installs that wrapper before the
evaluation loop. A zip submitted without that wrapper compiles and does not
run these gates. Compile was checked against the public compiler source with
`thinking_budget` `ge` set to 0, labeled 0.2.12 and 0.2.13, and
`google-adk` 1.36.1. Real 0.2.12 and 0.2.13 wheels are not on PyPI.

## Runtime gate

The cap stays 300 seconds, 220 calls, and 320 turns. It was not shrunk.

The internal 120-task block is `120 * (mean + 70) <= 39600`, so the mean
must be at most 260 seconds. `120 * ((300 + 8) + 70) = 45360`, which fails
that block. v13-1's dev-13 mean was 279.6 seconds, and
`120 * (279.6 + 70) = 41952`, which also fails. The capture check adds at
most 20 seconds on a task that has a diff. The host limit is 12 hours total.
An upload whose mean is above 260 seconds still needs the uploader override.
None of these figures is a v15 measurement.

## Dev-13 notebook

`notebooks/structured-v15-dev13.ipynb` lists the 13 dev ids. The reachable
ceiling is 10 because `fastapi_14246`, `fastapi_14262`, and `fastapi_14356`
fail in collection. The report cell reads `task_results.jsonl` and trace
JSON, and prints resolved count, per-task wall time, no-edit runs, and
calls to the first edit. It was not run.

## Archive

SHA256 `c70b05eaeb6cfcaf05e5fec107e2f32bf789abdf6a6559eb6d9dac692dc6ae7d`.
23 files. Portable validation passed. structured-v14's archive is unchanged.
