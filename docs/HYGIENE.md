# Patch hygiene

`gemma-lab hygiene candidate|run|patch` is controller tooling. It is not packed
into an agent archive, and `lint_candidate` is not called from `submit` or
`pack`. The CLI writes `hygiene.json` (a run directory gets `DIR/hygiene.json`;
candidate and patch checks write `./hygiene.json`). Root `/hygiene.json` and
`/projection.json` are gitignored so a later pack is not marked dirty.

The default policy file is `configs/hygiene/default.yaml`, resolved from the
working directory or, if that file is absent, from the repository root. Rate
warnings (`R.*`) are never a gate and cannot be promoted to block.

Trace source is the harness file `trace_<id>.json`, with `/` in the task id
written as `__`. Search order is the task group's `traces/` and
`results/traces/`, then the directory you passed, then
`results/<arm>/r<k>/traces/`. `results/<id>.json` is the evaluator record, not
the trace. Official ATIF v1.7 tool output is read from `observation.results[]`
and from `observation.content` (string or list of parts), including a later
observation-only step for one result of a parallel call. These fixtures were
produced by the official ATIF writer. They are not a Kaggle GPU result.

`verifier_reached` is true when a step author is `verify` or `verifier`. It is
false when a `triage` or `repair` author shows a structured pipeline that never
reached verify. It is null only when the trace has neither, which is the
single-agent case. `R.verifier_reach_rate` is skipped only when every task is
null.

## Runtime projection

`projection.json` records `basis: measured_mean`. Both blocks run on the
measured per-task mean of `duration_seconds` at `submit --execute` (promotion).
They are not a precondition for dev GPU runs. The per-task cap
(`max_time_minutes` × 60) never produces a block; `blocks_use_cap_wall` is
false.

`L` is `model_load_seconds` from `run_manifest.json` when that value is
present (`L_source: measured`), otherwise 900 (`L_source: default`).
`--scorer-overhead-seconds` defaults to 70. Overhead is added only to the
120-task block and the worst-case warning.

| Check | Formula | Result |
| --- | --- | --- |
| 120-task block | `120 × (mean + overhead) ≤ 39600` | refuse upload |
| 129-task block | `L + 129 × mean ≤ 38880` | refuse upload |
| Worst case | `L + 129 × (cap_wall + overhead) > 43200` | warn only |

Equality passes the blocks. A 250s mean with the default 70s overhead passes
both blocks. The simple-v3 dev13 mean of 297.98s fails the 120-task block.

## H2 and the 0.2.7 checkout

H2 stays a block for edits to tracked test files. In swegemma 0.2.7, grading's
reset is one `git checkout` that names files a normal workspace lacks
(`verification.py` reset list). That checkout aborts, so tracked test-file
edits survive into grading. This is inferred from the package source. The
hosted scorer has not been re-run to confirm it. Do not weaken H2.

## Rule index

| Rule | Severity | Meaning |
| --- | --- | --- |
| H1.scratch | block | Known scratch or artifact path, including root `requirements*.txt` |
| H1.symlink | block | New symlink |
| H1.binary | block | Binary file added |
| H1.explained | info | New module imported by the patch and written by an edit tool |
| H1.unexplained | warn | Other new file, including a plain root `*.txt` that is not requirements |
| H2.protected | block | Grading protected set: `conftest.py`, `test_*.py`, `*_test.py`, `pytest.ini`, `.pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, every file under `tests/` or `test/`, and `.py` under `testing/`. Directory names are case-insensitive |
| H3.unknown | warn | Trace missing or unrecognized. Finalization is not inferred from the patch. An empty patch with no submit is not a block |
| H3.fallback | warn | Recognized trace, nonempty patch, no `submit_patch` |
| H3.submit_count | info | `submit_patch` called more than once |
| H3.edit_after_submit | warn | `edit_file`, `write_file`, or `run_command` after the last `submit_patch` (harness discards those edits, `agent_runner.py:758`). `get_status` and `read_file` do not warn |
| H4.debug | block | `breakpoint`, `pdb`/`ipdb`/`pudb`, `code.interact`, `__import__` / `importlib.import_module` of those debuggers, and `getattr(builtins, "breakpoint")`. Import aliases are tracked. `def breakpoint` is not a debugger |
| H4.print | warn | Bare `print` call |
| H5a.import_hook | block | `*.pth`, `sitecustomize.py`, `usercustomize.py`, `_swegemma_stubs.py`, before H1 |
| H5a.path | block | Path under `site-packages`, `.venv`, or `build/lib` |
| H5a.sys_path | block | `sys.path` insert/append/extend/assignment, `site.addsitedir`, and the same mutations through `import sys as s` or `from sys import path as P` |
| H5b.host_import | warn | Tool output references `/site-packages/`. Sets `evidence_blocked` |
| H5c.host_metadata | warn | `pip show`/`list`/`freeze`, `importlib.metadata`, or `pkg_resources` |
| H5d.python_flags | warn | `python -I` or `python -E` |
| H8.packaging | warn | `noxfile.py` or `setup.py` |
| R.explicit_submit_rate | warn | Explicit `submit_patch` rate below the policy floor. Not a gate |
| R.verifier_reach_rate | warn | Verifier reach rate below the policy floor. Skipped when every task is null. Not a gate |
| G0.write_file | block | Repair role exposes `write_file` |
| G0.missing_submit | block | No role declares `submit_patch` |
| G0.early_submit | block | A role other than verify declares `submit_patch` |
| G0.missing_skill | block | Repair or verify has no `skills/` entry |
| G0.scratch_clause | warn | Prompt does not keep scratch off the workspace |
| G0.submit_clause | warn | Verify prompt does not say to submit |
| G0.handoff_ratio | warn | Handoff deadline is a large fraction of `max_time_minutes` |
| G2.divergence | block | In-agent check disagrees with this checker on a shared case |
| G2.superset | block | This checker blocks a case the in-agent check allows |
| G2.grading_gap | warn | In-agent check misses a grading-reset name |
| G2.error | block | In-agent check could not be loaded |

Frozen `agents/structured-v4` and `agents/structured-v4-10m` are expected to
block candidate lint on `G2.superset` only. `G2.grading_gap` stays a warning.
Those trees are not edited by the checker.

Aliases that stay open, on purpose: `exec('import pdb')`, `PYTHONBREAKPOINT`,
`sys.meta_path`, `p = sys.path` then `p.insert`, `sys.path.__setitem__`, and
string-concatenated `__import__`.
