# single-v7

Unevaluated prompt-only copy of `agents/single-v6`. No score is claimed.
No Kaggle push and no GPU run. `docs/STATUS.md` is unchanged.
Thinking stays off: `thinking.yaml` is a byte copy (`include_thoughts: false`,
`thinking_budget: 0`). `eval_config.yaml` is a byte copy (270 seconds, 48
counted calls). `agent.yaml` and the tool list are byte copies. There are no
skills.

## Prompt

Only `prompts/system.md` changes. single-v6 is 7459 characters. single-v7 is
7619.

`src/gemma_lab/tool_failures.py` names a failed `edit_file` when the output
contains `mandatory input parameters` or `missing-parameter`. It does not name
the harness miss `could not find old_string`. That miss is what rich_4070
repeated 15 to 18 times, so the prompt uses the harness phrase.

- A missing-parameter error still retries one smaller `edit_file`.
- The same failing `edit_file` call is not repeated.
- If `edit_file` could not find `old_string`, stop using `edit_file` on that
  file. Rewrite with a short `run_command` snippet: read the file,
  `str.replace`, write it back, assert the old string was present before and
  the new string is present after (`assert old in s`), then `git diff`.
- The public-wrapper sentence is its own paragraph, before that fallback, so
  it is not part of the submit-current-diff rule.

Archive SHA256
`7c7e5ed8142171969fdde3600f5349dc8a8aa606736c8d0b24becebe11b3a65f`.
Hygiene gate pass, findings empty, output under `/tmp`.

## Protocol

`configs/protocols/single-v6-vs-single-v7-dev13.yaml` is the dev-13 cohort in
file order, one repeat, arm A single-v6 and arm B single-v7. It is a promotion
pair, not a smoke. `matched_pair` is true. `prompts/*` is an allowed
difference. Sampling and budgets match because `thinking.yaml` and
`eval_config.yaml` are byte-identical.

The schedule hash is
`629000fccc9d9da5bfeab9823fb0e216d8c044b3a8753f320f0561223d5d24ed`, the same as
`single-v5-vs-single-v6-dev13.yaml`, because both use the cohort order, one
repeat, and `per_task_parity_v1`. Nothing requires schedule hashes to be
unique, and there is no salt field. `notebook.py`, `paired.py`, and the
hygiene code were not edited. The seventeen previous archive hashes are
unchanged, including single-v6
`f90204f21e2bbee4638f8c13a6af14d5dc933d82449bf2f78a2aad3d2879c488`.
