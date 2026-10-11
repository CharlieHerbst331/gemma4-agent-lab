# Patch hygiene

`gemma-lab hygiene candidate|run|patch` is controller tooling. It is not packed
into an agent archive, and `lint_candidate` is not called from `submit` or
`pack`. The CLI writes `hygiene.json` (a run directory gets `DIR/hygiene.json`;
candidate and patch checks write `./hygiene.json`). `hygiene.json` and
`projection.json` are gitignored at any depth and omitted from the pack, so a
report left inside a candidate does not change the archive or mark it dirty.

The default policy file is `configs/hygiene/default.yaml`, resolved from the
working directory or, if that file is absent, from the repository root. Rate
warnings (`R.*`) are never a gate and cannot be promoted to block.

Trace source is the harness file `trace_<id>.json`, with `/` in the task id
written as `__`. Search order is the task group's `traces/` and
`results/traces/`, then the directory you passed, then
`results/<arm>/r<k>/traces/`. `results/<id>.json` is the evaluator record, not
the trace. The single-arm notebook writes the evaluator record to
`results/<id>.json` and does not replace `results/traces/trace_<id>.json`.
Official ATIF v1.7 tool output is read from `observation.results[]` and from
`observation.content` (string or list of parts). Parallel calls to the same
tool match by `tool_call_id`, then by order, including a later
observation-only step. These fixtures were produced by the official ATIF
writer. They are not a Kaggle GPU result.

`verifier_reached` is true when a step author is `verify` or `verifier`. It is
false when a `triage` or `repair` author shows a structured pipeline that never
reached verify. It is null only when the trace has neither, which is the
single-agent case. `R.verifier_reach_rate` is skipped only when every task is
null. A paired run tags each task with `arm` and `replicate` from
`results/<arm>/<replicate>/` and keys rows by `(arm, replicate, instance_id)`.
Rates and summaries are per arm, with a per-replicate breakdown. Arms are not
pooled, so a single-agent arm does not create a false verifier-reach warning
for a structured arm.

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

## H3 and read-only shell commands

`H3.edit_after_submit` warns when a call after the last `submit_patch` can change files. `edit_file` and `write_file` always count. A `run_command` counts only when the command can modify files. `get_status` and `read_file` do not.

A compound command is read-only only when every part is. Separators are `&&`, `||`, `;`, `|`, a bare `&`, and newlines. The executable must be a bare name with no `/`, so `./git`, `./cat`, and `/tmp/x/git` count. A leading `NAME=value` prefix counts, including `GIT_EXTERNAL_DIFF=` and `GIT_PAGER=`. An empty command counts. `python` and `python3` count in every form, including `python -c` and `python -m`.

The allow-list is:

- `git status`, `git diff`, `git log`, and `git show` only. No option may appear before the subcommand, so `-c`, `-C`, `--git-dir`, `--work-tree`, `--namespace`, and `--exec-path` count. After the subcommand, a flag is read-only only when it is one of `--stat`, `--shortstat`, `--numstat`, `--name-only`, `--name-status`, `--cached`, `--staged`, `--exit-code`, `-p`, `--patch`, `--color`, `--no-color`, `--word-diff`, `--ignore-space-change`, `--ignore-all-space`, `--ignore-blank-lines`, `-w`, `-b`, `--minimal`, `--raw`, `--summary`, `--short`, `-s`, `--porcelain`, `--branch`, `-z`, `--null`, `--oneline`, `--graph`, `--decorate`, `--all`, `--follow`, `--abbrev-commit`, `--reverse`, `--check`, `--no-prefix`, `--full-index`, `--no-ext-diff`, `--renames`, `--no-renames`, `--ahead-behind`, `--no-ahead-behind`, `-v`, `--verbose`, `--long`, `--column`, `--no-column`, `--show-stash`, `--first-parent`, `--compact-summary`, or a valued flag `-U` / `--unified`, `-n` / `--max-count`, `--pretty`, `--format`, `--abbrev`, `-u` / `--untracked-files`, `--diff-filter`, `--ignore-submodules` (the value is the next word, or the text after `=`). A single token `-<digits>` such as `-5`, or `-U<digits>` such as `-U3`, is allowed. `--output` (any `--output*`), `--ext-diff`, `--textconv` (any `--textconv*`), `-c`, and `-C` count even after the subcommand. Anything after `--` is a path. Any other subcommand counts, including `apply`, `checkout`, `reset`, `stash`, `commit`, `add`, and `blame`.
- `grep` and `rg`, except `--pre`, `--pre-glob`, and `--hostname-bin` (with or without `=`).
- `sed` only as `sed -n '<script>' [file...]`, or the same with `--quiet` or `--silent`. The script must be a print command: a line address or range, or a `/re/` address, ending in `p`, such as `1,40p`, `151,300p`, or `/re/p`. `sed` without that quiet flag counts. So do `-i`, `--in-place`, `-f`, `-e`, `w`, `e`, `r`, `W`, and `s///w`.
- `find` except `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fprint`, `-fprint0`, `-fprintf`, and `-fls`.
- `ls`, `cat`, `head`, `tail`, `wc`, `pwd`, `echo`, `printf`, `stat`, `diff`, `sort`, `uniq`, `cut`, and `tr`.
- `cd` with a directory, `--`, `-`, `-L`, or `-P`.

`>`, `>>`, and `&>` onto a file count. The same operators onto `/dev/null` do not, and neither does an fd copy such as `2>&1` or `>&2`. `tee`, `mv`, `cp`, `rm`, `touch`, `mkdir`, and `patch` count because they are not on the list.

These count wherever they appear: `$(...)`, `${...}`, backticks, `<(...)`, `>(...)`, a here-doc (`<<`), and a backslash. An unterminated quote counts. The classifier does not interpret backslash escapes.

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
| H3.edit_after_submit | warn | `edit_file` or `write_file` after the last `submit_patch`, or a `run_command` that can modify files (harness discards those edits, `agent_runner.py:758`). `get_status`, `read_file`, and a read-only `run_command` do not warn |
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
| G0.write_file | block | Any role that declares `write_file` |
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

Expected candidate-lint blocks, without editing those trees:

- `baseline`, `simple-v1`, and `simple-v2` block on `G0.write_file`
  (`gemma_coder`, `root`, and both `investigator` and `verifier`).
- `simple-v3` passes.
- `structured-v4` and `structured-v4-10m` block only on `G2.superset`.
  `G2.grading_gap` stays a warning.

Aliases that stay open, on purpose: `exec('import pdb')`, `PYTHONBREAKPOINT`,
`sys.meta_path`, `p = sys.path` then `p.insert`, `sys.path.__setitem__`, and
string-concatenated `__import__`.
