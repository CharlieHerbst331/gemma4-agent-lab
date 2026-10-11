# single-v6

Unevaluated prompt-only copy of `agents/single-v5`. No score is claimed.
No Kaggle push and no GPU run. `docs/STATUS.md` is unchanged.
Thinking stays off: `thinking.yaml` is a byte copy (`include_thoughts: false`,
`thinking_budget: 0`). `eval_config.yaml` is a byte copy (270 seconds, 48
counted calls). `agent.yaml` and the tool list are byte copies. There are no
skills.

## Prompt

Only `prompts/system.md` changes. single-v5 is 6984 characters. single-v6 is
7459. That is well under the prompt ceiling the other candidates use: 2048
reserved completion tokens leave 30720 of the 32768 context for the prompt.

Two rules were added. The second replaces single-v5's "after a second failure,
rewrite the line" sentence instead of repeating it.

- Nothing rendered is not the same as None. For stray or extra output, the
  repro tries empty-but-non-None inputs, such as `Group()`, an empty list or
  string, or a zero-width render, as well as None, before the fix is accepted.
- After two failed `edit_file` calls on the same file, stop and rewrite the
  line with a short `run_command` Python snippet: read the file, `str.replace`,
  write it back, then `git diff`. A new parameter on an internal class is also
  passed through the public wrapper. Check where the public API constructs the
  class.

Archive SHA256
`f90204f21e2bbee4638f8c13a6af14d5dc933d82449bf2f78a2aad3d2879c488`.
Hygiene gate pass, findings empty, output under `/tmp`.

## Protocol

`configs/protocols/single-v5-vs-single-v6-dev13.yaml` is the dev-13 cohort in
file order, one repeat, arm A single-v5 and arm B single-v6. It is a promotion
pair, not a smoke. `matched_pair` is true. `prompts/*` is an allowed
difference. Sampling and budgets match because `thinking.yaml` and
`eval_config.yaml` are byte-identical.

The schedule hash is
`629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed`, the same as
`configs/protocols/v6-vs-single-v3.yaml`, because both use the cohort order,
one repeat, and `per_task_parity_v1`. Nothing in the repo requires schedule
hashes to be unique, and there is no salt field. `notebook.py` and `paired.py`
were not edited. The sixteen previous archive hashes are unchanged, including
single-v5 `618766eaab2f191f6f6a9960ce0b79641512a3647a3af6d6adab0f98f8c84d59`
and single-v5-think256
`2c2e7b3ba4a900e62c563fb28748e2687cd6c82ec6265e12a033daef73e69b89`.
