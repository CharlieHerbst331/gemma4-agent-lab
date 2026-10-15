# structured-v9

Unevaluated copy of structured-v8 with a smaller context. structured-v8 scored
0.10 on the leaderboard (single-v6 0.08, v3 0.03) with no ERROR, so the 12 hour
total held at the realized mean. No new score is claimed. No Kaggle push and no
GPU run. Existing agent directories, notebooks, and archive hashes were not
edited.

The hypothesis is context management. Each role should not redo work, and it
should not put the same file or tool log back into the next request. The
harness structure and two flat skills do that. Sampling, thinking, the seven
roles, and the 300 second / 220 call / 320 turn budget stay equal to v8 so a
later score difference is about this context change.

## What the harness ADK supports

Measured runs used google-adk 1.36.1. The notebook allow-list is swegemma
0.2.10 or 0.2.11 with adk-submission 0.2.13. adk-submission older than 0.2.11
refuses to run. Real wheels are not installed in this checkout. The findings
below are from the google-adk 1.36.1 sources that those runs used
(`instructions_utils.py`, `instructions.py`, `contents.py`, `llm_agent.py`).

`output_key` is a legal LlmAgent field. `__maybe_save_output_to_state` writes
it only on a final response that has non-thought text. A tool-only ending does
not store a handoff. v8 already compiled with `output_key` and
`include_contents`.

`include_contents` is `default` or `none`. `none` does not mean an empty
request. `_get_current_turn_contents` starts at the latest user event or the
latest other-agent reply, then keeps that event and everything after it. In
this sequential tree that is the previous role's final text, rewritten as
`[role] said: ...`, plus this role's own tool calls and tool results. Earlier
roles' tool logs are not in the request. Thoughts are dropped from the other
agent's message. A function call from an earlier role is not in that window
once a later final text exists.

State is separate from that window. `inject_session_state` fills `{name}` from
session state. `{name?}` is the optional form: a missing key becomes an empty
string. A required `{name}` raises `KeyError: Context variable not found`.
v5 records that this KeyError skips the fallback diff. Every handoff in v9
uses the optional form. `{problem_description}` stays required, as in v5 and
v8, because the harness puts the issue in state. `{hints?}` stays optional
because empty hints are omitted.

A role still sees what it needs without the old log. The instruction contains
the short summaries. The turn window contains the previous role's final text
once, which is the same short summary, and this role's own `git diff` or
`sed` output. Verify runs `git diff` itself instead of re-reading a file.

adk-submission 0.2.12 and 0.2.13 accept `thinking_budget: 0` and turn thinking
off. 0.2.13 replaces a missing budget with 4096, so the zero is explicit. A
budget of 0 does not compile on 0.2.11 (`ge=1`). v9 keeps v8's thinking files
byte for byte, so it validates on 0.2.12 and 0.2.13 and has the same 0.2.11
rejection. Repair still thinks at 256, which compiles on both.

## Compact handoffs

v8 already put `{triage_brief?}` in the instruction and set `output_key`, but
every role used `include_contents: default`, so the full tool history was
still sent. v9 sets `include_contents: none` on all seven LlmAgents. The root
SequentialAgent does not set the field. The field is legal only on LlmAgent.

Each of triage, repair, and the first two verifies must end with a short text
report. That text is the `output_key`. The shape is `files`, `hypothesis`,
`edit`, and `test`. Later instructions inject every summary with `{name?}`.
The current-turn window only starts at the previous role, so verify would not
see triage without the template. The template is how a nudge, which is a new
user message, still has the issue and the handoffs. The duplicate is one
short block (the `[role] said:` line plus the same text in the instruction),
not the tool log.

What it saves: every later request drops the earlier roles' tool transcripts.
What it does not save: this role's own tool results stay until the role
returns. That is why locate and the check print a short result, and why a
role must not `cat` a file.

## Locate skill

`skills/locate` replaces a chain of grep and whole-file reads. The only call
is `{"skill_name":"locate","file_path":"scripts/run.py","args":["literal text"]}`.
`args` is one string. `skill_name` and `file_path` stay top-level. The script
finds the repo from `GEMMA_CHECK_ROOT`, then `/workspace`, then a PYTHONPATH
entry that contains `.git`. It searches `.py` files for that literal, prints
at most five hits with two lines on either side, and caps the text at 1500
characters. A missing or extra argument prints the call shape and does not
search.

What it saves: one truncated window instead of several `read_file` or graph
payloads that would stay in this role's turn.

## Check skill

`skills/check` is the v8 flat check plus three lines. The call is still
`{"skill_name":"check","file_path":"scripts/run.py"}` with no args. It still
pins `/tmp/repro_check.py` through `tempfile.gettempdir()` and finds the repo
through `GEMMA_CHECK_ROOT`. It now `py_compile`s up to three changed Python
files (bytecode goes under the process temp dir, not the repo), prints
`diff: non-empty` or `diff: empty` (harness-staged `conftest.py` and
`pytest.ini` do not count), runs one targeted pytest when a mapped test
exists, and truncates the whole print at 1500 characters.

What it saves: the verify role does not re-read the diff and the test log
into the next request. The handoff stores the one-line result.

## Sed windows, no whole-file reads

`read_file` is not granted on any role. v8 granted it on repair_1, repair_2,
verify_1, and verify_2, and told repair_1 to call it with `filepath` only,
which returns the whole file. v9 reads with `sed -n 'A,Bp'` and a window of
at most 40 lines, then `head -c 2000`. `cat` and `sed -n '1,$p'` are refused
in the prompt. repair_3 still cannot read. Verify uses `git diff --stat` and
`git diff -U3 | head -n 40`.

The three graph tools are not on repair_1. A graph payload would stay in
repair_1's own turn even with `include_contents: none`. Locate is the one
search. This is a tool-list change, listed below.

What it saves: a 40-line window instead of a whole module, and no second copy
of that module in the next role.

## Deadlines kept from v8

Cap stays 300 seconds. v8 ran at that cap, scored 0.10, and did not ERROR.
The 45 second submit rule still aims at elapsed 255 seconds. Calls stay 220.
Turns stay 320. `timeout_seconds` stays 300.

- repair_1 hands off at `agent_elapsed_seconds` 180, or when 120 seconds or
  less remain and a diff exists. Under 120 seconds with an empty diff, the
  next call is the heredoc.
- verify_1 and verify_2: under 90 seconds, text only.
- repair_2 hands off at 240 seconds, or at 60 seconds remaining with a diff.
- Under 45 seconds, earlier roles stop so verify_3 can submit. verify_3
  submits even if the diff is still empty after one heredoc. A text-only
  ending restarts all seven roles from triage.
- The heredoc still parses with `ast.parse` before the write, copies that
  PATH to `/tmp/pre_` plus the path with `/` replaced by `_`, and on
  `py_compile` failure copies that backup back onto that path only. A failed
  assert does not restore. The prompt says never run git checkout.
- repair_2, repair_3, and repair_1 on a later pass do not revert a non-empty
  source diff.

## Limits and the runtime gate

Same formulas as v8. Overhead 70 seconds. L = 900. Blocks use a measured
mean. The warning uses the cap.

Cap 300 seconds, as if the mean equaled the cap:

- `120 * (300 + 70) = 44400` seconds. Above 39600. The 11 hour block would fail.
- `900 + 129 * (300 + 70) = 48630` seconds. Above 43200. **WARN**.
- `900 + 129 * 300 = 39600` seconds. Above 38880. The 129-task block would fail.

Aimed mean 255 seconds:

- `120 * (255 + 70) = 39000` seconds. At or under 39600. The 11 hour block passes.
- `900 + 129 * 255 = 33795` seconds. At or under 38880. The 129-task block passes.
- `900 + 129 * (255 + 70) = 42825` seconds. At or under 43200. This is the warn
  formula applied to the mean. The live warn still uses the 300 second cap.

v8's realized run held the 12 hour total. That is not a measured mean of 255.
No new mean is claimed.

## Diff against structured-v8

Equal, byte for byte: `eval_config.yaml`, `sub_agents/thinking.yaml`,
`sub_agents/repair_thinking.yaml`. Same role order, model, temperature 1.0,
top_p 0.95, top_k 64, repair thinking 256, other roles thinking 0, output
token caps, and the heredoc rollback.

Changed:

- Root name `structured_v9`.
- `include_contents: none` on all seven LlmAgents. v8 used `default`.
- `output_key` names are `triage_summary`, `repair_1_summary`,
  `verify_1_summary`, `repair_2_summary`, `verify_2_summary`,
  `repair_3_summary`. v8 used `triage_brief` and `*_report`. verify_3 still
  has no `output_key`.
- Every instruction templates `{problem_description}`, `{hints?}`, and all
  six `{name?}` summaries. v8 templated only the previous role or two.
- Prompts no longer say the role sees the full prior history.
- `read_file` removed from repair_1, repair_2, verify_1, and verify_2.
  repair_3 and verify_3 already lacked it.
- `search_similar_code`, `get_code_neighbors`, and `get_code_subgraph`
  removed from repair_1.
- New `skills/locate` on repair_1 and repair_2. One string argument.
- `skills/check` still on the three verify roles. The script adds
  `py_compile`, `diff: non-empty` / `diff: empty`, and a 1500 character cap.
  v8's check script is unchanged in `agents/structured-v8`.
- Prompts require `sed` windows of at most 40 lines and forbid `cat`.
- Handoff text is the four-line summary. Deadlines and the S1 rollback
  sentences stay.

## Archive

```bash
uv run gemma-lab pack agents/structured-v9 --output /tmp/structured-v9-submission.zip
```

sha256 `7fdc1a7db97a5acfb9bd2e532ec99146b22e872e641977ca6aba330d6282f45a`.

Portable `gemma-lab validate` is what this checkout can run. Official
adk-submission compilation still happens on the GPU notebook. Existing
archives stay at structured-v8
`9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e`,
single-v9 `42665a7febbfc63a1811df5fd1f46ade4afd78977cbf6576dd285d9543fdd7f3`,
and structured-v7
`a3a08b179fee800ee0575af2a55ad14f47c42c369bf32fd4d52227a9da1109df`.
