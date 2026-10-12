# Combined candidate smoke

One Kaggle notebook runs single-v8, single-v8-check, structured-v7, and
single-v7 on the same five tasks. It is a smoke. It is not promotion eligible.
One repeat cannot name a winner.

The notebook is generated and not pushed. No GPU run is started from this
change.

## Design

The paired tooling is still two-arm. `execute_session`, `build_schedule`, and
`build_report` live inside the notebook runtime marker in `src/gemma_lab/paired.py`.
Editing that marker would change every existing protocol notebook. A separate
generator, `gemma-lab notebook-multi`, embeds that same runtime unchanged and
feeds it a schedule whose `order` lists every arm. `execute_session` already
walks `order`, so all four arms run in one session and the model loads once.

`build_report` inside that runtime only totals arms A and B. After the session
the notebook overwrites `pair_report.json` and `pair_report.md` with the
multi-arm smoke report, and writes the same bytes to `multi_report.json` and
`multi_report.md`. `gemma-lab pair-report` still refuses this protocol, because
`load_protocol` still requires arms A and B. Regenerate with `gemma-lab multi-report`.

`early_stop` must be null. The embedded early-stop only knows A and B.

`src/gemma_lab/paired.py` and `src/gemma_lab/notebook.py` are not modified.
`generate_pair` is still the two-arm path. New code is `src/gemma_lab/multi_arm.py`.
The CLI additions are `notebook-multi` and `multi-report` in `main()`.

Option 2, three pair notebooks on one task list, was not built. Its cost is
below.

## Arms

| Label | Agent | Time cap | Calls | Turns | Archive |
| --- | --- | --- | --- | --- | --- |
| A | single-v8 | 330 s | 150 | 200 | `6f44de6401910907b6c65f89549727d2c4492a54c3ed13743033623d81dfdc22` |
| B | single-v8-check | 330 s | 150 | 200 | `64dc727d78c4189c1db1184e74129290574c7b97816dd91f91d2baa7defe0fb0` |
| C | structured-v7 | 360 s | 150 | 200 | `a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df` |
| D | single-v7 | 270 s | 48 | 64 | `f62c8c0b92bc5bd1fb1015f20e7cbd7a5599d5518d2d59097bf2b40d9f3412b0` |

These are the archives on main `85cb52bcf4385cf920311451a0bc181764dfa386`.
No existing agent directory is edited. There are still 21 agent directories.
`agents/single-v7-lenient` was not added.

single-v7 stays at 270 s / 48 calls / 64 turns. Editing `agents/single-v7`
would change archive `f62c8c0b…`. A new directory with only `eval_config.yaml`
copied forward to single-v8's 330 s / 150 / 200 would answer a different
question and add a 22nd archive. The evaluator still enforces single-v7's own
limits. The 48-call cap can end that arm before 270 s. Charles's comparison
is wall time. The smoke records that wall. The call cap is the known
difference, and it is left in place.

The session cap is the max of the arm time caps: **360 s**. Each evaluator
uses its own `max_time_minutes`, `max_tool_calls`, and `max_turns`. The value
passed to `execute_session` as `cap_seconds` is 360, which is the same
unmatched-pair rule as PR #23. This smoke report does not recompute
`hit_cap.wall`.

## Tasks and schedule

Tasks, in order, from `single-v8-vs-single-v8-check-smoke.yaml`:

1. rich_4070
2. rich_3934
3. fastapi_11194
4. rich_3938
5. fastapi_14262

Repeats: 1. Order rule: `per_task_parity_v1`. No shuffle.

The two-arm schedule hash of that list is

`5672ef15323e1d59847cc7cde3f1b6cb1912346d7456b13cb716902437b3e9fd`

The combined schedule hash is

`4d2904f77afbafbdc2bc5f52266b60f09bf45c51fc072fb24808e0b3dd2961cd`

The hashes differ because `order` is part of the hash. Task ids, positions,
and `p0` match the two-arm schedule. Arm order rotates with `(p0 + repeat0) mod 4`:

| Task | Order |
| --- | --- |
| rich_4070 | A, B, C, D |
| rich_3934 | B, C, D, A |
| fastapi_11194 | C, D, A, B |
| rich_3938 | D, A, B, C |
| fastapi_14262 | A, B, C, D |

A is first on two tasks. B, C, and D are first on one. Five tasks cannot split
evenly across four arms. That is another reason this repeat cannot name a winner.

For two labels the same rotation matches `build_schedule` exactly, including
the hash. The generator refuses a protocol with fewer than three arms, so that
path is only a check.

## Markers

`matched_pair: false`, with notes. `load_protocol` still rejects the file
(`Protocol arms must be exactly A and B`).

Allowed differences: `agent.yaml`, `sub_agents/*`, `skills/*`, `prompts/*`,
`eval_config.yaml`, `sampling.yaml`, `thinking.yaml`.

The generator checks every pair. single-v8 and single-v8-check have the same
budgets and the same sampling tuple `(1.0, 0.95, 0, false)`, so that pair is
still a matched file check. The other pairs differ:

- structured-v7 budgets are 360 s, and its sampling list is
  `(1.0, 0.95, 0, false)` plus repair `(1.0, 0.95, 256, true)`.
- single-v7 budgets are 270 s / 48 / 64, and its sampling tuple is
  `(0.5, 0.95, 0, false)`.

Those pairs need `eval_config.yaml`, and sampling or thinking differences need
`sampling.yaml` and `thinking.yaml`. `matched_pair: false` skips only the
shared-file identity check. Budget and sampling refusals still use the markers.
`agent.yaml` does not stand in for either marker.

`multi-report` calls the existing protocol-hash refusal. A manifest whose
`protocol_sha256` differs from the raw protocol file is refused. A missing
hash warns and continues, which is the older-run rule. A schedule-hash
mismatch is also refused. The hash is the raw file, so a comment or newline
change is a mismatch.

## Runtime estimate

Constants from `src/gemma_lab/operations.py`: overhead 70 s, default load
L = 900 s, block `120 * (mean + 70) <= 39600` (11 h), block
`L + 129 * mean <= 38880` (10.8 h), warn `L + 129 * (cap + 70) > 43200` (12 h).
The cap never blocks. Blocks use the measured mean. This smoke has no measured
mean, and the gates are not applied.

The in-notebook projection, which this smoke marks not applicable, uses
`mean * 120` without the 70 s overhead, `L + 129 * mean`, and a warning of
`L + n * (cap + p90_delta)` for n in {120, 129}.

If a later measured mean equaled an arm cap, the submit gate would say:

| Cap | `120 * (cap + 70)` | `L + 129 * cap` | `L + 129 * (cap + 70)` |
| --- | --- | --- | --- |
| 270 s | 40800 s, would block | 35730 s, under 38880 | 44760 s, warn |
| 330 s | 48000 s, would block | 43470 s, would block | 52500 s, warn |
| 360 s | 51600 s, would block | 47340 s, would block | 56370 s, warn |

The largest whole-second mean that passes both blocks is 260 s. 261 s fails
`120 * (mean + 70)`.

### This smoke

Task-runs: 5 tasks × 4 arms = **20**.

Worst case if every run hits its own cap:

- Agent time: `5 * (330 + 330 + 360 + 270) = 6450 s`
- Plus one model load: `6450 + 900 = 7350 s` = **2.042 GPU-hours**

`pair_fits` is stricter. It charges every arm the session cap (360 s), plus
60 s of pad. The notebook clock starts before the model load, and the
tasks.jsonl wait (up to 300 s) is on that same clock. Before the last task,
with every wall equal to 360 s:

`900 + 300 + 5 * 4 * 360 + 4 * 60 = 8640 s`

The protocol sets `session_budget_seconds: 14400` (4 h). That clears 8640 s
with 5760 s of slack for wheel install and overshoot. A 120 s overshoot on
every run, which is the abort margin in the runtime, adds about 2400 s and
still lands near 11040 s, under 14400 s.

Kaggle comparison uses the 12 h competition cap in the gate, 43200 s.
14400 s and the 7350 s worst wall are both under that cap. One session can
hold the combined notebook.

No measured per-task durations for these four candidates on these five tasks
are in the repo. Docs mention smoke4 only as a data-mount failure. The
planning number is the cap-based worst case above. A realistic mean would be
lower if arms stop before their caps. single-v7's 48-call cap makes that
especially likely for arm D. That number is not invented here.

### If single-v7 were left out

Three arms, session cap still 360 s, 15 task-runs.

- Own-cap agent time: `5 * (330 + 330 + 360) = 5100 s`
- Plus one load: **6000 s** = 1.667 GPU-hours
- `pair_fits` with the 300 s data wait: `900 + 300 + 5 * 3 * 360 + 3 * 60 = 6780 s`

6780 s fits in the older 7200 s smoke budget with 420 s of slack. The
four-arm worst case does not (8640 s). The four-arm protocol therefore uses
14400 s, and single-v7 is included.

### Option 2, not built

Three notebooks, each loading the model once, with single-v8 repeated:

| Notebook | Own-cap agent time | Plus one load |
| --- | --- | --- |
| single-v8 vs single-v8-check | 10 × 330 = 3300 s | 4200 s |
| single-v8 vs structured-v7 | 5 × (330 + 360) = 3450 s | 4350 s |
| single-v8 vs single-v7 | 5 × (330 + 270) = 3000 s | 3900 s |
| Total | 9750 s of agent time | **12450 s** = 3.458 GPU-hours |

That is 30 task-runs, because single-v8 runs three times. The extra cost
against the combined notebook is 5100 s (1.417 h): two extra loads (1800 s)
and two extra single-v8 passes (3300 s). The data-mount wait can also happen
once per notebook.

## Report

The smoke report starts with `smoke, not promotion eligible`. `winner` and
`rule_winner` are null. `promotion` is `not_eligible`. Runtime gates are
`not_applicable`. Pairwise resolved counts are descriptive. They do not name
a winner.

The report lists each arm's own cap, call cap, and turn cap, and the session
cap of 360 s.

Tool-failure rollup stays on the two-arm `pair-report` path. This report does
not import it.

## Existing notebooks

The twelve protocols that already existed on main were regenerated from
`origin/main` at `85cb52bcf4385cf920311451a0bc181764dfa386` and from this
branch, with owner `charlesaherbst` and `--wheelhouse-version 30`.
`evaluation.ipynb`, `kernel-metadata.json`, and `schedule.json` matched for
every protocol. `pair_manifest.json` is not part of that compare: it records
`generated_at` and `git_revision`.

## Generate

From the repo root, not pushed:

```bash
uv run gemma-lab notebook-multi \
  --protocol configs/protocols/combined-candidate-smoke.yaml \
  --owner charlesaherbst \
  --slug combined-candidate-smoke \
  --output /tmp/combined-candidate-smoke-notebook \
  --wheelhouse-version 30
```

Notebook sha256, from that command, not committed:

| File | sha256 |
| --- | --- |
| `evaluation.ipynb` | `2d6c9dae4d24e62eb85d9fc25b7be112cb71813db0d00d4f84c94c2042f019a5` |
| `kernel-metadata.json` | `400b63dcce9ca4cbdf581e242ea71d57fdf9e4d2ab6bc4659338ea57503155bb` |
| `schedule.json` | `654a6cae5c4e3ab58dcc4f6f5c508b5d351e9b63bb16ba5e052643ad75e1eb2c` |

## Caveats

- Smoke only. Not a promotion protocol. Not a dev-13 comparison.
- One repeat, and A is first on two of the five tasks. No winner.
- No measured durations for this cohort are in the repo. Use the cap-based
  worst case until a GPU run exists.
- single-v7 still stops on 48 calls, 64 turns, and 270 s. The session cap of
  360 s does not raise those evaluator limits.
- The 70 s scorer overhead is the submit-gate estimate. It is not added to
  the smoke's wall-time total above. The 900 s load is the default L, not a
  measurement from this notebook.
- Wheel install sits on the session clock before `execute_session`. It is
  covered by the slack in the 14400 s budget, not by a measured install time.
- If the kernel stops after `execute_session` writes `pair_report.json` and
  before the overwrite, that file is the two-arm report and omits arms C and D.
  `multi_report.json` is written in the same cell, after the session returns.
- `gemma-lab pair-report` cannot load this protocol. Use `multi-report`.
