# single-v1: matched single-agent control

Unevaluated control for `agents/structured-v5`. Forked from
`agents/structured-v4-10m` because structured-v5 is built on another branch and is
not present here. No existing candidate directory was edited. This page does not
claim a score. Src-layout (requests) tasks are excluded from promotion decisions.

## Structure

One `LlmAgent` named `single_v1`. No `SequentialAgent`, no `LoopAgent`, no triage /
repair / verify split, and no `max_iterations`. The prompt carries the exploration,
import, scratch, and submission rules that v5 splits across roles.

## What matches the v5 spec

| Knob | single-v1 | Why |
| --- | --- | --- |
| Model | `gemma-4-31b-it-qat-w4a16-ct` | Same base model. No adapter. |
| Sampling | temperature 0.5, top_p 0.95 | v4-10m sampling, unchanged. Temperature 0.2 is not set. |
| Thinking | `thinking_budget: 0` once, `include_thoughts: true` | Single knob. On adk-submission 0.2.12, budget 0 compiles to thinking off. `include_thoughts` stays true so changing this one integer to 256 is the ablation; `include_thoughts: false` would keep thinking off even at 256. |
| Task cap | `max_time_minutes: 4.5` (270s) | Spec cap. |
| Calls | `max_tool_calls: 50` | Midpoint of the spec's 40-60 range. v5's branch was not available to copy an integer. |
| Turns | `max_turns: 50` | Spec says to pick a turn limit. 50 is inside 40-60 and equal to the call cap, so turns do not cut a tool trajectory off early. |
| Command cap | `timeout_seconds: 300` | Unchanged official per-command cap. Remaining task time still bounds each command, so a 270s task cannot run a 300s command. |
| Output ceiling | `max_output_tokens: 2048` | Modest versus the organizer default 16384. See token arithmetic. |
| Tool output | Prompt requires head, limits, and line ranges of at most 80 | Same overflow rule as v5. |
| Tools | Union of the v5 role lists | `get_status`, `read_file`, `edit_file`, `run_command`, `search_similar_code`, `get_code_neighbors`, `get_code_subgraph`, `submit_patch`. `write_file` is absent: repair in v4-10m does not have it, and v5's verify spec forbids it. |
| Skills | Own copies of task-memory, source-lookup, and verify-patch | task-memory and source-lookup are byte-identical to v4-10m. verify-patch is extended in this tree only. No new skill directory. |
| Submission | Resubmit after every edit; `submit_patch` is the final action | Round 2: edits after the last submit are not diffed. A text-only reply after a submit, or the agent finishing, ends the task. |
| Scratch | Top-level `/workspace/build/` or `/tmp` only | Nested `build/` and `dist/` are git-excluded at any depth, so real source must not be created there. The rule is in the agent prompt and in verify-patch, the prompts that create files. |
| Imports | Section 3 probe from import-origin.md, then `PYTHONPATH=/workspace/src:/workspace` when the probe says `INSTALLED-COPY` and `/workspace/src` exists | Never `python -I` or `python -E`. `pip show` / metadata are not evidence. |
| Exploration | At most the top 3 files; a provisional edit by about 12 counted calls and no later than 18 (35% of 50); no repeated identical calls | 35% of 50 is 17.5, so 18 is the first integer past that share. |
| verify-patch | Reports `import_origin`; audit flags the spec's protected set | Nested `conftest.py`, `test_*.py`, `tests/` and `test/` directories, `pytest.ini`, `pyproject.toml`, `setup.cfg`. An `INSTALLED-COPY` verdict forces `passed` false. The repro child uses `PYTHONPATH=<workspace>/src:<workspace>`. |
| Data boundary | No reference patches, test patches, or grading output in the prompt or skills | Train-only and holdout rules are unchanged. |

## Token arithmetic

vLLM 0.19.1 rejects a request when the prompt is at least 32768 tokens, or when
`prompt + max_tokens > 32768`. Round 2: that exception skips both the submitted
patch and the fallback diff, so an earlier `submit_patch` does not survive overflow.

- `max_output_tokens` is 2048, so the prompt-plus-history ceiling is 32768 − 2048 = 30720.
- `thinking_budget` 0 turns thinking off, so those 2048 tokens are for the visible answer and tool-call JSON. A small empty thought channel can still appear.
- The organizer default of 16384 would leave only 16384 tokens of prompt, which overflows sooner.
- `include_contents: none` is not used here (see below), so tool history accumulates. The prompt therefore bounds every tool result.

2048 tokens is enough for one small `edit_file` or `submit_patch`. A replacement that does not fit is truncated. The prompt tells the model to keep edits small. That truncation risk is accepted so the ceiling stays modest.

## What this control could not match

1. **Multi-agent structure.** v5 is `Sequential[triage, Loop(max_iterations 3 or 4)[repair, verify]]`. This control is one agent on purpose. There is no loop counter, no nudge that reruns triage, and no isolated repair/verify history.
2. **`include_contents: none`.** v5 can set it on triage and verify because those roles rebuild from state. On a single agent, `none` keeps only events since the latest user message. The main turn still sees the problem, but a harness nudge is a new user message and would drop the tool transcript. This agent uses `include_contents: default`. Overflow prevention is the 2048 output ceiling plus bounded tool output, not history dropping. `{hints}` is not templated: a missing key can fail instruction formatting, and with `default` the harness message already carries hints. `{problem_description}` is templated so the issue is in the instruction itself.
3. **Per-role tool split.** The union includes `run_command` and `submit_patch` on the same agent. v5's verify role has no `run_command` and no `write_file`. This control cannot enforce that boundary. `run_command` stays because the import-origin probe is a shell command and because repair's tool list is part of the union. Skill use is prompted with exact `skill_name`, `file_path`, and args; it is not capability-forced.
4. **Repair's safety-net submit.** Round 2: any text-only reply after a submit ends the task, and the root finishing after a submit also ends it. In v5 that would skip verify if repair submitted and then replied with text. This control has no later role, so `submit_patch` lives on the only agent. It must be the final action. There is no "submit and continue into verify" path to preserve.
5. **Last-iteration forced submit.** v5's verify submits on the last loop iteration because there is no exit tool. The translation here: if checks are still failing as the deadline approaches, call `submit_patch` anyway and make it the final action. There is no iteration index.
6. **Exact call and turn integers.** The spec's range is 40-60 calls and an author-chosen turn limit. v5 was not on this branch, so 50 and 50 are this control's pick. If v5 chooses another integer in range, the pair is not call-matched until those integers are aligned. Do not treat a later score gap as a structure effect until the integers match.
7. **Protected-set residual.** The audit implements the set named in the v5 spec. READINESS quoted a wider 0.2.11 predicate (`tox.ini`, `*.pth`, `*_test.py`, `testing/`). Round 2 did not restate that predicate, and the binding spec listed the narrower set, so those extra paths are not flagged. `pkg/widget_test.py`, `tox.ini`, and `testing/helper.py` stay unflagged on purpose. A file named `test_*.py` is still flagged wherever it sits.
8. **Official 0.2.12 compile.** `gemma-lab validate` is this repo's portable checker. It accepts `thinking_budget: 0`. The official compiler is not installed here (PyPI has no `adk-submission` wheel). Round 2 says 0.2.12 accepts 0 and 0.2.11 rejects it. Measured runs use 0.2.12. Portable validation is not that compiler.
9. **One output ceiling.** v5 can pick a different modest `max_output_tokens` per role. This agent has one ceiling, 2048.

## verify-patch

Copied into `agents/single-v1/skills/verify-patch/` and extended there. v4 and
v4-10m copies are untouched.

- `import_origin` on executed repro phases (`before`, `after`, `verify`, `probe`). Up to four top-level modules that the repro imports or that changed `.py` paths name, and that exist under the workspace or `src/`. Stdlib names are skipped.
- Verdicts: `WORKSPACE` if `module.__file__` is under the workspace, otherwise `INSTALLED-COPY`. `imports_outside_workspace` forces `passed` false.
- The child interpreter is `sys.executable -c` with `PYTHONPATH=<workspace>/src:<workspace>`. It does not pass `-I` or `-E`. The harness rewrites `/workspace` in shell text, not inside this script, so the script uses the resolved workspace path.
- Audit `forbidden` includes protected edits and protected untracked files. Other untracked files still fail `passed`, including new implementation files. The script still does not delete them.
- No new mode was required. `mode=audit` and `mode=repro` cover the spec.

## Src-layout tasks are excluded from promotion

Import-origin testing on the subprocess sandbox: flat layouts (fastapi, rich) import
the workspace copy; src-layout requests imports the host copy unless `PYTHONPATH`
includes `src`. The official grading command in that sandbox also imported host
requests, so a local pass or fail on those tasks can be wrong in either direction.
The hidden scorer's sandbox (Docker editable install versus subprocess) is not
verified. **Do not use src-layout (requests) outcomes when deciding whether to
promote single-v1 or structured-v5.** dev/diagnostic cohorts that are only fastapi
and rich are not affected by this shadowing. Host dependency versions
(starlette, pydantic) still differ from a repo pin on every task.

## Archive

Packed with `uv run gemma-lab pack agents/single-v1 --output artifacts/single-v1/submission.zip`.
The zip is gitignored. The SHA256 is of the archive contents, not a benchmark result.
Portable validation returned `{"files": 9, "portable_checks": "passed"}`.

Archive SHA256: `6b359d83dc78f90feb0027c40e38a026ad7c1201ee1d0b623fa486fcef8914dd`.

Re-packed existing archives and compared them to the documented hashes. All three
matched, so those candidates are unchanged:

- structured-v4-10m `0730b5f0a373fc23bdb4362779a4757ded14cfa6a77896c7d54ce3efb7ad8cab`
- structured-v4 `01568061ee105be99a51af1bca592dd59756db9184dfada735c0e3074ae7e77e`
- simple-v3 `50d7b69dd4d0f6a5b4925bda919f69e57196b72337190bd6073be95591ff2646`

`make check` on this tree: ruff check passed, ruff format reported 74 files already
formatted, pytest reported 88 passed.

## Reproduce

```bash
uv sync --locked
make check
uv run gemma-lab validate agents/single-v1
uv run gemma-lab pack agents/single-v1 --output artifacts/single-v1/submission.zip
```

Tests in `tests/test_single_v1.py` load `agents/single-v1`'s own skill scripts.
They do not run competition repositories.
