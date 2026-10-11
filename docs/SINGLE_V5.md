# single-v5 and single-v5-think256

Unevaluated copies. No score is claimed. No Kaggle push and no GPU run.
`docs/STATUS.md` is left unchanged because another branch is editing it.
single-v5 is thinking off. single-v5-think256 is thinking on. Nothing in this
file says the think256 candidate has thinking off.

## single-v5

`agents/single-v5` is a copy of `agents/single-v4`. `agent.yaml`,
`thinking.yaml`, and `eval_config.yaml` are byte-identical, so thinking stays
off (`include_thoughts: false`, `thinking_budget: 0`) and the budgets stay
270 seconds and 48 counted calls. Only `prompts/system.md` changes.

The prompt is 6984 characters. single-v4's is 6699. Unrelated sentences were
not trimmed. Three rules were added, and the old call-30 backstop was replaced
so the prompt does not keep two backstops:

- 12 counted calls or about 95 seconds remains the primary edit.
- Call 24 is the hard rule: by call 24 the agent must have edited a source file,
  and if it has not, it stops reading and makes the most plausible minimal edit,
  then verifies it. The old "about 30 counted calls" and "about 18 remaining"
  wording is gone.
- A repro assert is not weakened, deleted, or loosened to make it pass. Output
  that contradicts the issue, such as a stray newline, is the bug.
- UNCERTAIN and an empty diff stay only when the issue text is a bare issue
  number, such as Fix #3104. A short title that names a symptom counts as a
  behavior clue. `rich_3934` ("empty live") and `rich_3938` ("fix background
  style with soft wrap") are behavior clues, not empty submits. If the issue
  describes any behavior, UNCERTAIN, "not a bug", and "already fixed" are not
  allowed.
- The under-20-second submit rule and the pre-submit `git status` step are the
  same sentences as single-v4. Under 60 seconds, a source edit that already
  exists is submitted immediately, also the same sentence as single-v4. If the
  diff is still empty, the prompt says make the minimal edit, then submit.
  That late path does not add a verify step, because a verify does not fit in
  the time left.

Archive SHA256
`618766eaab2f191f6f6a9960ce0b79641512a3647a3af6d6adab0f98f8c84d59`.

## single-v5-think256

`agents/single-v5-think256` is a copy of single-v5. Only `thinking.yaml`
differs. `eval_config.yaml` is byte-identical to single-v4 and single-v5.
`agent.yaml` is byte-identical too, so `max_output_tokens` stays 2048.

`thinking.yaml` is the single thinking knob. It sets `include_thoughts: true`
and `thinking_budget: 256`. Both fields are explicit because adk-submission
0.2.13 ignores `include_thoughts: false` and replaces a missing budget with
4096. 256 is the budget, not 512 and not 4096. Testing's timing model is about
2.05 seconds plus 26 ms per completion token, so 256 adds at most about 6.7
seconds per call. 512 adds about 13 seconds and does not fit the 270 second cap.

With `include_thoughts: true`, the reasoning is re-sent in history each turn,
about 6k tokens by call 25. That pulls compaction earlier than the thinking-off
arm.

Whether thinking tokens count inside `max_output_tokens` is an assumption.
`docs/STRUCTURED_V5.md` says completion tokens are not shared with a thinking
budget while thinking is off, and `docs/THINKING_OFF_T0.md` says a 4096 budget
is above every role's `max_output_tokens`. If that reading is right, 2048 minus
256 leaves 1792 tokens for the visible answer and the prompt ceiling stays
32768 − 2048 = 30720. Confirming it needs a GPU capture. `max_output_tokens`
was not raised.

At full use of 256 thinking tokens per call, the 270 second cap binds around
call 28, and the 95 second primary rule lands at about call 10.

Archive SHA256
`2c2e7b3ba4a900e62c563fb28748e2687cd6c82ec6265e12a033daef73e69b89`.

Hygiene `candidate` on both directories returned gate pass with no findings.
Output was written under `/tmp`, outside the repo. No H-rule or test asserts
that every candidate has thinking off or budget 0. The frozen parents keep
their own assertions. Nothing was loosened for the other candidates.

## Protocol

`configs/protocols/single-v5-vs-single-v5-think256-smoke.yaml` is the five
tool-call tasks in the original order, one repeat, arm A single-v5 and arm B
single-v5-think256. The schedule hash is
`31398c6c61900f3f4813ad59e151df2a15b6549c120fb656c461d438be81a345`, the same as
the first five-task smoke. The report starts with `smoke, not promotion eligible`.
The notes say the arms differ in `thinking.yaml` only, that arm B has thinking
on at budget 256, and that the per-call overhead cannot be gated because the
gates do not apply to smoke.

`matched_pair` stays omitted. `matched_pair: false` skips the whole shared-file
check and still refuses a thinking-budget change, so it is the wrong switch.
`thinking.yaml` is a settings include: the file check ignores its bytes and the
sampling check compares the resolved budget. This protocol lists the literal
entry `thinking.yaml` in `allowed_differences`. That marker, and only that
marker, lets sampling differ in `thinking_budget` and `include_thoughts`.
Temperature, top_p, the model, and the eval budgets still have to match.
`sub_agents/*` does not count as the marker, so existing protocols still refuse
a thinking change. The helper is after the notebook runtime marker in
`src/gemma_lab/paired.py`, so existing notebook cells stay byte-identical.
`notebook.py` is unchanged.

## Archives left unchanged

The fourteen previous archive hashes were repacked and matched, including
single-v4 `470eb8b70f8dfd47d39efa15311aec832bb6a94117274cbc4a8d4e8a14863ffc`
and single-v3 `37abebce49c490d5cdc6abf41b92067aa480929e508084098e883ab9c1938ffc`.
There is no fifteenth frozen archive in `agents/`.
