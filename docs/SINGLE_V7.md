# single-v7

Unevaluated prompt-only copy of `agents/single-v6`. No score is claimed.
No Kaggle push and no GPU run. `docs/STATUS.md` is unchanged.
Thinking stays off: `thinking.yaml` is a byte copy (`include_thoughts: false`,
`thinking_budget: 0`). `eval_config.yaml` is a byte copy (270 seconds, 48
counted calls). `agent.yaml` and the tool list are byte copies. There are no
skills.

## Prompt

Only `prompts/system.md` changes. single-v6 is 7459 characters. single-v7 is
8024. That is well under the prompt ceiling the other candidates use: 2048
reserved completion tokens leave 30720 of the 32768 context for the prompt.

The rich_4070 loop was not an `old_string` miss. In the dev-13 pair, arm A
made 18 identical `edit_file` calls and arm B made 15. Every one of those
calls was `{filepath, new_string}` with no `old_string`. The harness text is
`mandatory input parameters are not present`. A rule that waits for
`Failed to replace: old_string not found` would not have fired on that loop.
single-v6 already said to change a tool call after two failures, and that
counting rule did not stop the repeats.

`src/gemma_lab/tool_failures.py` still names a failed edit only when the
output contains `mandatory input parameters` or `missing-parameter`. It does
not name `old_string not found` or `Target string occurs N times`. The prompt
uses the harness phrases itself. The counter is unchanged.

- After one missing-parameter error, retry one smaller `edit_file`.
- The same failing `edit_file` call is not repeated. The second identical
  failing call is the trigger, not a third.
- After the second `edit_file` error of any kind on the same file, stop using
  `edit_file` on that file. Count `mandatory input parameters are not present`,
  `Failed to replace: old_string not found`, and `Target string occurs N times`.
- Rewrite with a short `run_command` snippet in a quoted heredoc under `/tmp`.
  Read and write bytes, or open with `newline=''`. `read_text` and
  `write_text` turn a CRLF file into LF. Assert `s.count(old) == 1` before
  `str.replace`, because replace changes every match. Assert the new string
  is present after, then `git diff`.
- The public-wrapper sentence is its own paragraph, before that fallback, so
  it is not part of the submit-current-diff rule.

Archive SHA256
`f62c8c0b92bc5bd1fb1015f20e7cbd7a5599d5518d2d59097bf2b40d9f3412b0`.
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
