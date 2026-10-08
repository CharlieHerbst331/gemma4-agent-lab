# single-v1: matched single-agent control

Unevaluated control for `agents/structured-v5` on branch
`cursor/structured-v5-3d40` (commit `cc080df`). Forked from
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
| Thinking | `thinking_budget: 0`, `include_thoughts: true` | `thinking.yaml` is a byte copy of `sub_agents/thinking.yaml`. `agent.yaml` includes it once and does not repeat the integer. On adk-submission 0.2.12, budget 0 forces thinking off even with `include_thoughts: true`. Changing that one integer to 256 is the ablation. |
| Task cap | `max_time_minutes: 4.5` (270s) | `eval_config.yaml`, copied |
| Calls / turns | 48 / 48 | same file. Inside the 40-60 band. `timeout_seconds` stays 300 and is still clipped by remaining task time. |
| Output ceiling | `max_output_tokens: 2048` | repair's cap. Prompt ceiling 32768 − 2048 = 30720, which is the largest reservation v5 documents. |
| Tool output | `read_file` with `end - start < 80`; shell through `head -n 40` and `head -c 4000`; no whole-file `cat` | repair.md wording |
| Exploration | at most 3 candidate files; provisional edit by about 12 counted calls or 95 seconds, whichever comes first. 95 seconds is 35 percent of the 270 second cap. No repeated identical call. | triage.md and repair.md |
| Imports | the `module.__file__` probe with `PKG`, then `PYTHONPATH=/workspace/src:/workspace` when it prints `INSTALLED-COPY` and `/workspace/src` exists. Never `python -I`, `python -E`, `python3 -I`, or `python3 -E`. | repair.md, copied |
| Scratch | top-level `/workspace/build/` or `/tmp`. Untracked `build/` and `dist/` at any depth, and `.adk_exec_*.py`, are excluded. Never a real source file under a nested `build/` or `dist/`, such as `pkg/build/module.py`. | repair.md, copied. The same sentences are in the copied verify-patch skill. |
| Submit | `submit_patch` is the last tool call. Any `edit_file` is followed by another `submit_patch`. A text reply after a submit ends the task. When `time_seconds_remaining` is under 40, submit even if the check failed or the diff is empty. | verify.md |
| verify-patch | byte copy of v5's `SKILL.md` and `scripts/check.py` | reports `import_origin`, `default_import_origin`, and `imports_installed_copy`. Audit flags nested `conftest.py`, `test_*.py`, `tests/` and `test/` dirs, `pytest.ini`, `pyproject.toml`, and `setup.cfg`. The child uses `PYTHONPATH=<workspace>:<workspace>/src` and does not pass `-I` or `-E`. |
| Other skills | task-memory and source-lookup | byte-identical to v4-10m and to v5 |
| Tools | union of v5's role lists | `get_status`, `read_file`, `edit_file`, `run_command`, the three graph tools, `submit_patch`. No `write_file`. |
| Hints | `{hints?}` | same optional placeholder v5 uses |

## Remaining differences other than the multi-agent structure

1. **`include_contents` is `default`, not `none`.** v5 sets `none` on triage, repair, and verify so each role sees the previous role's final text instead of that role's tool transcript. On this one agent, `none` would drop the tool transcript when a harness nudge arrives as a new user message. The control keeps `default`. Overflow is limited by the 2048 ceiling and the same bounded tool output, not by dropping history.

2. **One output cap, not three.** v5 uses 1024 for triage (prompt ceiling 31744), 2048 for repair (30720), and 1536 for verify (31232). One `LlmAgent` has one `max_output_tokens`. This control uses 2048, repair's cap and v5's largest reservation, so an edit is not truncated below what v5's repair role can emit. Triage's 1024 and verify's 1536 are not applied.

3. **The tool and skill lists are the union.** v5's verify role has only `get_status`, `read_file`, `edit_file`, `submit_patch`, and verify-patch. It has no `run_command` and no `write_file`. This agent has repair's tools as well, including `run_command` and the graph tools, because the import probe is a shell command and the original control is the union. task-memory and source-lookup are attached here; v5 loads them on repair only. The no-shell verify boundary is a prompt, not a missing tool.

4. **No iteration counter for the forced submit.** v5 submits on the last loop pass when `loop_iteration` is 3 or greater, and also when under 40 seconds remain. This agent has no pass index. The under-40s rule is in the prompt, in v5's words: call `submit_patch` as the last tool even when the check failed or the diff is empty. A failed check with 40 or more seconds left is not submitted yet; the same agent makes one more edit and then submits. v5 would hand that failure to repair instead of editing inside verify.

5. **`{problem_description}` and `{hints?}` are in the one instruction**, as in v5, but there is no `{triage_brief}` or `{repair_report}` handoff.

No other budget, sampling, thinking, import, scratch, or verify-patch difference is intended. The protected-path audit matches v5, including the paths it does not flag (`tox.ini`, `*_test.py`, `testing/`).

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

Archive SHA256: `2f92b83be8e90e75df4cccf565965c91e33129c06d109346a8b6c90aba1adf56`.

Portable validation returned `{"files": 10, "portable_checks": "passed"}`.
`make check`: ruff passed, 74 files already formatted, 88 tests passed.

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
verify-patch bytes against the v5 copies. It does not run competition repositories.
Portable `gemma-lab validate` is the local checker. Full `compile_submission` is
not run here; v5's notes say the same, and adk-submission is not on PyPI.
