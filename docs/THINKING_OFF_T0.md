# Thinking-off copies: structured-v5t0 and single-v1t0

Unevaluated copies of the frozen parents `agents/structured-v5` and
`agents/single-v1`. Neither parent directory is edited. No score is claimed.

Verified on swegemma 0.2.10 and 0.2.11 with adk-submission 0.2.13. swegemma
0.2.11 removed the `swegemma.models` discovery and registry helpers. On
adk-submission 0.2.13 with swegemma 0.2.10, `include_thoughts: false` with
no `thinking_budget` no longer turns thinking off. swegemma's default budget
of 4096 overrides the missing budget (`generation.py` around lines 403-417),
so both parents send `enable_thinking` true and `thinking_token_budget` 4096.
That budget is above every role's `max_output_tokens`. `thinking_budget: 0`
turns thinking off on both 0.2.12 and 0.2.13.

## What changed

Each t0 tree is a copy of its parent. The only file that differs is the shared
thinking knob:

- `agents/structured-v5t0/sub_agents/thinking.yaml`
- `agents/single-v1t0/thinking.yaml`

Those two files are byte-identical. They keep `include_thoughts: false` and
set `thinking_budget: 0`. `eval_config.yaml` is a byte copy of the parent and
is byte-identical between the two t0 candidates. Internal agent names are
unchanged. The path of `thinking.yaml` still differs because single-v1 has no
`sub_agents/` directory.

The paired protocol `configs/protocols/v5-vs-single-v1.yaml` points arm A at
`agents/structured-v5t0` and arm B at `agents/single-v1t0`. `notebook-pair`
has no other default; it reads that file from `--protocol`. `expected_sha256`
stays null until Verification pins the archives. `src/gemma_lab/paired.py` is
not edited here.

Src-layout (requests) tasks stay excluded from promotion, as on the parents.

## Archives

Portable validation: structured-v5t0 16 files, single-v1t0 10 files, both passed.
`hygiene candidate` on each directory returned gate `pass` with no findings.
`make check` on this branch: ruff passed, 120 files formatted, 504 passed,
2 skipped, 1 deselected.

Archive SHA256:

- structured-v5t0 `b2cce93de41ad7a487178de67fe10ef82d3aa69f48820639dc3ee720839ae7a9`
- single-v1t0 `90ba7ee8918daf959831cf2845d771c3f09cf46295546d0509f98e6641da845f`

The eight existing archives repacked to their recorded hashes, including
structured-v5 `6202ab26252df59061547e0fd7dbcc1e8ef62b5cb12c61c14c2b2e953865bbb5`
and single-v1 `84b4b0f720493041704209dd175061c003be387fc49a826ebca0a13c0b5cf0f8`.

Verified on swegemma 0.2.10 and 0.2.11 with adk-submission 0.2.13. Those wheels
are not on PyPI, and this VM has no Kaggle credentials for the competition
wheelhouse. The stub-server capture against that harness was not run. swegemma
0.2.11 removed the `swegemma.models` discovery and registry helpers.
