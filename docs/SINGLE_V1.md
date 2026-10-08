# single-v1: matched single-agent control

Unevaluated control for `agents/structured-v5` on branch
`cursor/structured-v5-3d40` (commit `38a51c8`). Forked from
`agents/structured-v4-10m` and then aligned to the files on that branch. No
existing candidate directory was edited. This page does not claim a score.
Src-layout (requests) tasks are excluded from promotion decisions.

The intentional structure difference is one `LlmAgent` named `single_v1`. v5 is
`Sequential[triage, Loop(max_iterations 3)[repair, verify]]`. There is no
`max_iterations`, no `loop_iteration`, and no separate role history. Everything
below is what still differs after that structure, or what was copied so the
control matches.

## Copied from structured-v5

| Knob | Value | Source on the v5 branch |
| --- | --- | --- |
| Model | `gemma-4-31b-it-qat-w4a16-ct` | every role |
| Sampling | temperature 0.5, top_p 0.95 | every role. Temperature 0.2 is not set. |
| Thinking | `include_thoughts: false`, no `thinking_budget` | `agents/single-v1/thinking.yaml` is a byte copy of v5@`38a51c8` `sub_agents/thinking.yaml`. The path differs because this candidate has no `sub_agents/` directory. On adk-submission 0.2.11 and 0.2.12 that turns thinking off and sends no `thinking_token_budget`. A budget of 0 compiles only on 0.2.12. Ablation needs 0.2.12: set `include_thoughts` true and add `thinking_budget` 256. On 0.2.12 that forwards the numeric budget. On 0.2.11 the same file compiles, but the budget is dropped and only `enable_thinking` is sent. |
| Task cap | `max_time_minutes: 4.5` (270s) | `eval_config.yaml` is a byte copy of v5@`38a51c8` |
| Calls / turns | 48 calls, 64 turns | Same file: `timeout_seconds` 300, `max_tool_calls` 48, `max_turns` 64. Skill script runs count as tool calls, so turns and counted calls are roughly co-binding. The 270s clock usually binds before either. |
| Output ceiling | `max_output_tokens: 2048` | repair's cap. That reserves 2048 completion tokens, so the prompt must stay under 30720. It does not bound history. |
| Tool output | `read_file` with `end - start < 80`; shell through `head -n 40` and `head -c 4000`; no whole-file `cat` | repair.md wording. These are soft bounds. Harness caps are larger. |
| Exploration | at most 3 candidate files, in the same response as the first tool call; provisional edit by about 12 counted calls or 95 seconds, whichever comes first. 95 seconds is 35 percent of the 270 second cap. No repeated identical call. | triage.md and repair.md, plus the same-response constraint used for checkpoints |
| Imports | the shell probe is v5's `python3 -c` `module.__file__` probe with `PKG`, then `PYTHONPATH=/workspace/src:/workspace` when it prints `INSTALLED-COPY` and `/workspace/src` exists. Never `python -I`, `python -E`, `python3 -I`, or `python3 -E`. | repair.md, copied. The skill probe is separate and uses `python -P`. |
| verify-patch child | `PYTHONPATH` is `/workspace/src` then the workspace root. The origin probe is `sys.executable -P -c`. | byte copy of `scripts/check.py`. `-P` is not `-I` or `-E`. `default_import_origin` repeats imports with only the workspace root on `PYTHONPATH`. |
| Scratch | top-level `/workspace/build/` or `/tmp`. Untracked `build/` and `dist/` at any depth, and `.adk_exec_*.py`, are excluded. Never a real source file under a nested `build/` or `dist/`, such as `pkg/build/module.py`. | repair.md, copied. The same sentences are in the copied verify-patch skill. |
| Protected paths | grading's predicate: `conftest.py`, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`, `.pytest.ini`, `sitecustomize.py`, `usercustomize.py`, `_swegemma_stubs.py`, any `*.pth`, `test_*.py`, `*_test.py`, and any `.py` under a directory whose name lowercases to `tests`, `test`, or `testing`. Non-Python files under those directories are not protected. | byte copy of v5's audit |
| Checkpoint | every few calls, in the same response as the next tool call: target files, edits made, and the last check result | Same constraint as v5@`38a51c8` repair step 6. A response with no function call is the final response and ends the turn. |
| Submit | After each edit, rerun the check. `submit_patch` after each passing check and after a final check. `submit_patch` is the last tool call. Never edit after the last submit. If fewer than 60 seconds remain, submit immediately and do not rerun the repro. If the result is UNCERTAIN and audit `changed_paths` is empty, submit the empty patch at once. After `submit_patch`, exactly one short sentence and no further tools. | one rule for this agent. v5's verify prompt still also has the last-iteration path. |
| Other skills | task-memory and source-lookup | byte-identical to v4-10m and to v5 |
| Tools | union of v5's role lists | `get_status`, `read_file`, `edit_file`, `run_command`, the three graph tools, `submit_patch`. No `write_file`. |
| Hints | `{hints?}` | same optional placeholder v5 uses |

## Context overflow

The real history bound is ADK event compaction, not the 2048 output reservation.
`max_output_tokens` only reserves completion tokens (prompt ceiling 32768 − 2048
= 30720). vLLM rejects a request when the prompt is at least 32768 tokens, or
when prompt plus `max_output_tokens` exceeds 32768, and that exception drops even
a patch that was already submitted.

The starter notebook cell 10 sets
`EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)`.
ADK compacts before the next model call when the last reported prompt-token count
is at least 14336, keeping the last 5 events and replacing the rest with a
text-only summary. The lab generator keeps that starter cell. Whether the hosted
scorer enables the same compaction is unconfirmed. Compaction is skipped when
prompt-token usage is unreported, and each compaction is an extra model call
inside the 270 second budget. The prompt restates target files, edits, and the
last check result every few calls, in the same response as the next tool call,
so a summary can still carry them. A checkpoint sent as its own message would
be a final response and would end the turn.

## Remaining differences other than the multi-agent structure

1. **`include_contents` is `default`, not `none`.** v5 sets `none` on triage, repair, and verify so each role sees the previous role's final text instead of that role's tool transcript. On this one agent, `none` would drop the tool transcript when a harness nudge arrives as a new user message. The control keeps `default`. Compaction, above, is what bounds that history. A compaction event is user-authored, so the same starter setting can also erase a `none` role's current-turn tools. That interaction applies to v5 as well.

2. **One output cap, not three.** v5 uses 1024 for triage (prompt ceiling 31744), 2048 for repair (30720), and 1536 for verify (31232). One `LlmAgent` has one `max_output_tokens`. This control uses 2048, repair's cap and v5's largest reservation. Triage's 1024 and verify's 1536 cannot be applied separately.

3. **The tool and skill lists are the union.** v5's verify role has only `get_status`, `read_file`, `edit_file`, `submit_patch`, and verify-patch. It has no `run_command` and no `write_file`. This agent has repair's tools as well, including `run_command` and the graph tools, because the import probe is a shell command and the original control is the union. task-memory and source-lookup stay attached for the whole task; v5 loads them on repair only. A win for this agent can come from the shell, not only from the single-agent structure.

4. **No `loop_iteration` and no 90 second handoff.** v5@`38a51c8` tells repair to hand off when about 90 seconds remain so verify can submit inside a 60 second margin, and verify submits when `loop_iteration` is 3 or greater. This agent has no second role and no pass index. It submits immediately when fewer than 60 seconds remain. A failed check with 60 or more seconds left is not submitted: the same agent edits again and reruns the check, then submits that passing check or the final check. v5 would hand the failure back to repair and would not submit it inside verify.

5. **`{problem_description}` and `{hints?}` are in the one instruction**, as in v5, but there is no `{triage_brief?}` or `{repair_report?}` handoff.

The checkpoint rule matches v5 repair step 6: target files, edits, and the last check result go in the same response as the next tool call. A response with no function call is the final response and ends the turn. The ranked file list uses that same constraint with the first tool call. The only text-only reply here is the one short sentence after `submit_patch`. v5 repair's only text-only reply is the handoff report.

The shell import probe stays `python3 -c`, matching v5's repair prompt. The skill's import-origin probe is `python -P`, matching v5's `check.py`. `thinking.yaml` and `eval_config.yaml` are byte copies of the v5@`38a51c8` files. `thinking.yaml` sits at the candidate root because there is no `sub_agents/` directory. Its first comment still says "every role" because that sentence is part of the byte copy.

## Shared eval path that this control does not change

The starter notebook still hardcodes `max_tool_calls = 100` and `max_time_minutes = 5.0`. `src/gemma_lab/notebook.py` does not substitute `eval_config.yaml`, and structured-v5 at `38a51c8` does not change that generator either. Both arms share it. This branch leaves `notebook.py` alone so the pair stays matched.

## Src-layout tasks are excluded from promotion

v5's note is the rule for this control too. Flat layouts import the workspace when
`PYTHONPATH` is the workspace root. src-layout requests imports the host copy
unless `src` is on `PYTHONPATH`. In the notebook subprocess sandbox, grading also
imports host requests, so a local pass or fail on those tasks is unreliable in
either direction. **Do not use src-layout (requests) outcomes when deciding
whether to promote single-v1 or structured-v5.** FastAPI and Rich diagnostic
cohorts are not excluded by this shadowing result. Host dependency versions still
apply. The hidden scorer's sandbox was not re-checked.

## Archive

Packed with `uv run gemma-lab pack agents/single-v1 --output artifacts/single-v1/submission.zip`.
The zip is gitignored. The SHA256 is of the archive contents, not a benchmark result.

Archive SHA256: `84b4b0f720493041704209dd175061c003be387fc49a826ebca0a13c0b5cf0f8`.

Portable validation returned `{"files": 10, "portable_checks": "passed"}`.
`make check`: ruff passed, 74 files already formatted, 112 tests passed.

Re-packed existing archives matched their documented hashes:

- structured-v4-10m `0730b5f0a373fc23bdb4362779a4757ded14cfa6a77896c7d54ce3efb7ad8cab`
- structured-v4 `01568061ee105be99a51af1bca592dd59756db9184dfada735c0e3074ae7e77e`
- simple-v3 `50d7b69dd4d0f6a5b4925bda919f69e57196b72337190bd6073be95591ff2646`

## Reproduce

```bash
uv sync --locked
make check
uv run gemma-lab validate agents/single-v1
uv run gemma-lab pack agents/single-v1 --output artifacts/single-v1/submission.zip
```

`tests/test_single_v1.py` loads this candidate's own skill scripts and checks the
verify-patch, thinking, and eval bytes against structured-v5 at `38a51c8`. It does
not run competition repositories. Portable `gemma-lab validate` is the local
checker. Full `compile_submission` is not run here: adk-submission is not on PyPI.
A review compile of `include_thoughts: false` with no budget succeeded on both
0.2.11 and 0.2.12.
