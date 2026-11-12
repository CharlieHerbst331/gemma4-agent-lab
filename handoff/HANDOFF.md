# Handoff: Gemma 4 Developer Agent (Kaggle) → Google Antigravity

Written Nov 11, 2026 (PT) by Grok Bot, the coordinator of Charles's earlier bot team, for an
Antigravity agent starting cold. Read this file, `handoff/SETUP.md`, `AGENTS.md`, and
`.agents/rules/*.md` before you change anything. `docs/STATUS.md` has the full per-version
log; this file is the short version plus the current diagnosis.

Owner: Charles A Herbst. Kaggle account `charlesaherbst`. Repo
`github.com/CharlieHerbst331/gemma4-agent-lab`.

---

## 1. Goal

Win Kaggle's **Google – The Gemma 4 Developer Agent** competition (`gemma-4-developer-agent`).
Charles's own words: the goal is to win, and winning takes risk. Every daily submission slot
should test a meaningful bet. Never resubmit an archive that already has a score. No endless
smoke tests.

The model is a local, quantized **Gemma 4 31B** (`gemma-4-31b-it-qat-w4a16-ct`) served by vLLM
on 4× NVIDIA L4 with no internet. It loops, hallucinates, and is flat-out wrong more often than
frontier models. **The harness is a cradle**: it protects the model from noisy outside
information that makes loops and hallucinations more likely.

## 2. Competition rules and limits

| Item | Value |
|---|---|
| Task | Fix a real GitHub issue in a Python repo snapshot. Graded by hidden tests. Public LB uses 58 tasks (score = resolved / 58); the hosted run covers 129 tasks. |
| What you submit | `submission.zip` with `agent.yaml` at the root (declarative Google ADK agent: prompt, tools, sampling, eval budget). The file **must** be named `submission.zip`. |
| Allowed agent surface | YAML only. Official tools (`run_command`, `read_file`, `edit_file`, `write_file`, graph tools, `get_status`, `submit_patch`), sandboxed skills, sub-agents/LoopAgent. **No Python callbacks**, so no host-side loop detector, output truncation, or state store. |
| Submissions | **One per UTC day.** The slot resets at 00:00 UTC = 4:00 PM PST (5:00 PM PDT). |
| Runtime | **12 h hard limit = 43,200 s** for all 129 tasks plus model load (413–1170 s measured). That means a mean of **about 300 s per task or less**. The per-task cap (`max_time_minutes`) is a worst case, not the mean: 129 × 480 s = 61,920 s, so an 8-minute cap only works if most tasks finish early. |
| Harness-fixed | Tool output caps (5000 chars stdout; read_file 150 lines / 10k chars). The scorer's ADK context compaction: `EventsCompactionConfig(token_threshold=14336, event_retention_size=5, compaction_interval=15, overlap_size=2)`. You cannot change these. |
| Code sharing | Public code-sharing rules apply. Credit the public notebooks we built on (see `agents/structured-v22/NOTICE.md`). |

Noise: one public score has a 95% range of about ±0.08–0.11. Identical archives have scored
7–13 of 58 across draws, and our own structured-v8 archive scored 0.10 and then 0.13. Treat
gaps under ~0.05 as noise.

## 3. Repo and harness architecture

```
agents/<name>/          one candidate per directory. Never edit a directory after it was
                        submitted or evaluated; copy it to a new version instead.
  agent.yaml            model, tools, !include prompt and sampling, evaluation budget
  prompts/system.md     the system prompt (no { or } characters: ADK templating)
  configs/sampling.yaml temperature, top_p, max_output_tokens, thinking_config
  eval_config.yaml      timeout_seconds / max_tool_calls / max_time_minutes / max_turns
  NOTICE.md LICENSE.txt README.md   attribution (ships in the zip, not in the prompt)
src/gemma_lab/          the `gemma-lab` toolkit (uv run gemma-lab --help)
  bundle.py             validate + deterministic pack (same dir → same sha256)
  notebook.py           generates a private offline Kaggle GPU evaluation notebook that
                        embeds the archive, runs the official starter harness on chosen
                        task IDs, and emits task_results.jsonl, traces, patches, manifest
  operations.py         submit (one/day, ledger runs/submissions.jsonl, evaluation checks,
                        129-task runtime projection), wait-run, status, logs
  paired.py multi_arm.py  older multi-arm notebooks (not used for the latest runs)
configs/cohorts/dev-13-environment-screened.json   the 13 dev tasks used for every comparison
configs/splits/public-v1.json                      95 train / 14 dev / 20 holdout (frozen)
docs/STATUS.md          per-version log (newest first). docs/RUNBOOK.md: operations.
scripts/handoff/        the core loops (section 8), written for this handoff
handoff/scored-archives.json  every submitted archive's sha256. Never resubmit one.
.agents/rules/ .agents/skills/  Antigravity rules and slash-command skills
```

Evaluation stack on Kaggle (from run manifests): swegemma 0.2.11, adk-submission 0.2.13,
google-adk 1.36.1, vllm 0.19.1, 4× L4, tensor parallel 4, machine shape `NvidiaL4`, wheelhouse
dataset `metric/gemma-4-developer-agent-wheelhouse`, model source
`google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2`, internet off.

### The current harness family (v21-1 / v22)

One `LlmAgent`, no sub-agents, no skills. Tools: `run_command`, `read_file`, `edit_file`,
`get_status`, `submit_patch` (no `write_file`, no graph tools). Temperature 0.2, top_p 0.95,
thinking on with `thinking_budget: 4096` and `include_thoughts: true`. Budget: 28 counted tool
calls, 8 minutes, 240 s per command, 80 turns. `get_status`/`submit_patch` are not counted.
The harness attaches a `budget_warning` to tool results when ≤10 calls remain. When time or
calls run out, the working tree is graded as it is.

## 4. Version history

Public scores from `kaggle competitions submissions gemma-4-developer-agent` (dates UTC).
Dev-13 = resolved of the 13 dev tasks in one private GPU run (s1, s2… are repeat draws).

| Version | Kaggle ref (UTC date) | Public | Dev-13 | What it was / lesson |
|---|---|---|---|---|
| simple-v3 | 56905832 (Oct 7) | 0.03 | 3 | Read-only locator, then sequential repair/verify. Multi-role hand-offs waste the budget. |
| single-v6 | 57081417 (Oct 11) | 0.08 | 3 | Single agent, **thinking off**, 270 s / 48 calls. Thinking off was a mistake (see lessons). |
| structured-v8 | 57176412 (Oct 14) | 0.10 | — | Triage/repair/verify roles, time slices, forced hand-off, 300 s cap. |
| structured-v9 | 57224300 (Oct 15) | 0.08 | — | Compact hand-offs and small reads on v8. |
| structured-v10 | 57262340 (Oct 16) | 0.01 | — | Parallel repair branches + select. Branching starves each branch. |
| structured-v11 | 57300592 (Oct 17) | 0.13 | — | Byte-identical v8 resubmission to measure noise: 0.10 vs 0.13. |
| structured-v12 | 57363951 (Oct 18) | 0.06 | — | Elapsed-time stamps, edit by 120 s, 250 s cap. Shorter caps hurt. |
| structured-v13 | 57412943 (Oct 19) | 0.10 | — | v8 full time, late soft deadline, empty-diff net. |
| structured-v13-1 | 57454574 (Oct 20), 57575301 (Oct 24) | 0.12, 0.10 | 4 | Repeat-ban exemptions. Same archive twice: noise again. |
| structured-v14 / v14-1 | 57483600, 57512188 | none | — | Map skill; hosted crash, no score. Skills are fragile on the hosted runner. |
| structured-v15-4min / v15 | 57614074, 57647354 | 0.06, 0.08 | — | YAML harness at 240 s vs 300 s. Hard caps scored worse. |
| structured-v16.x | not submitted | — | 3 | Prompt clocks and hand-off banners. Clocks are ignored: the model rarely calls get_status. |
| structured-v17 | 57718020 (Oct 28) | 0.12 | — | Call-bounded hypothesis-then-edit. |
| structured-v18-1 | 57780163 (Oct 29) | 0.12 | 4 | Localize/patch split, 512-token localize, heredoc, empty-diff gate. |
| structured-v19-1 | 57822100 (Oct 31) | 0.10 | — | Verify-then-repair, best-diff restore. Extra roles cost more than they return. |
| structured-v20-1 | 57927493 (Nov 3) | 0.08 | — | 5-role LoopAgent chain. Low point of the multi-role line. |
| **structured-v21-1** | 57996686 (Nov 4) ERROR, **58037165 (Nov 5)** | **0.17 (best)** | **5, 4** | Public LB-0.24 single-agent bundle plus our kept fixes: no write_file, no graph tools, docs_src hint removed, early edit-format switch, passing-repro rule. Packing commit cbcb4b1a, sha `1a49094d…`. The first upload errored with no reason; the identical retry scored. |
| public LB-0.24 bundle | (author's) | 0.24 | 4, 4, 3 | `gemma-4-baseline-lb-0-24` by verracodeguacas (config from `flexonafft/gemma-4-budget-aware-coding-agent-v2`). Unmodified, it does **not** beat v21-1 on dev-13. |
| structured-v22 | not submitted | — | 4, 4, 3 | "Cradle" (PR #51, sha `c45c6c4c…`). Section 5. |

Lessons that carry forward (evidence in `docs/STATUS.md` and the box notes):

1. **Never starve reasoning.** Thinking off or a 256-token budget, and 1–2k output caps, roughly
   halved resolves (v6, v16–v20 sat at 0.06–0.12). Keep thinking 4096 and an output cap that
   covers thinking plus answer (6144–8192).
2. **One agent beats role chains** at this budget. Every hop re-sends a 5–15k prompt with no
   cache hits; later roles often never ran.
3. **Prompt-only clocks, gates and caps are ignored** (get_status called 0–1 times per task).
   The only hard levers are tools, budgets, output tokens, stop sequences, and prompt *content*.
4. **Shorter hard caps hurt** (v12 at 250 s and v15 at 240 s scored 0.06). Cutting calls from
   50 to 25 cost 14/129 in a public ablation.
5. **Skills / run_skill_script failed 68% of the time** on argument shape and add ~870 tokens
   per request. Graph tools returned nothing useful 21/21 times. write_file calls in the bundle
   were 5/5 failed `/tmp` writes ("Path traversal detected").
6. **Single public scores are noise-level.** Use dev-13 with 2–3 seeds for decisions; use LB
   slots for bets that dev-13 already supports.

## 5. Current diagnosis (Nov 11, 2026)

Full write-up: box tarball `gemma4-team/v22/diagnosis.md`; Agent Engineering's self-audit:
`gemma4-team/v22/agent-eng-input.md`.

**Why v21-1 (0.17) trails the 0.24 bundle:** mostly draw noise. The two send byte-identical
sampling and budgets to vLLM (stub capture). The bundle shows no local advantage on dev-13.

**What actually limits every version:**
1. **Context compaction at 14,336 tokens.** The first request is already 4.1–5.5k tokens, so the
   agent has ~10k tokens of working memory. 12 of 13 v21-1 tasks compacted (19 events), usually
   around calls 13–18. Afterward the model re-reads, re-runs, and once forgot its own edit.
2. **Late commitment.** 4 of 5 empty diffs first tried to edit at call 29–30, after the budget
   was gone, even though `budget_warning` appeared at call ~18.
3. **Noisy tool output.** 40 outputs over 4k chars per run (whole-repo greps hitting JSON,
   docs translations, whole-file reads).
4. **Edit-parse loops** (see below) and issue-number / git-history searches on title-only
   issues (the repo history is one commit named `baseline`).
5. Three dev tasks are environment-dead (fastapi_14246, fastapi_14262, fastapi_14356) and two more
   were judged unreachable (rich_3105, rich_3938). The dev-13 ceiling is about 6–8 of 13, so dev-13
   shows mechanism changes (first-edit call, empty diffs, compactions) better than score.

**v22 = bundle + cradle.** Narrow `git grep … | head -20`, read windows ≤60 lines, no history
or issue-number searches, `git diff --stat` when unsure, a one-line `STATE:` note at the start of
each reply (survives compaction because the latest events are retained), a COMMIT RULE tied to
the literal `budget_warning`, edit_file old_string ≤6 lines with a sentinel-heredoc fallback plus
`py_compile`, max_output_tokens 6144, thinking 4096, 5 tools, 28 calls, 8 minutes. Prompt 7941
chars, no attribution header.

**v22 dev-13 results, 3 seeds each** (reproduce with `scripts/handoff/analyze_dev13.py` on the
tarball's `v22/out/*` and `testing/v21-1-walltime/out`):

| Run | Resolved | Empty | Mean / p90 / max wall | Compactions | Failed edits (param) | Identical repeats | Loop tasks | Outputs >4k |
|---|---|---|---|---|---|---|---|---|
| bundle s1/s2/s3 | 4, 4, 3 | 4, 2, 6 | 326/483/483, 300/375/385, 331/483/483 | 19, 21, 17 | 25 (22), 29 (24), 23 (17) | 33, 42, 32 | 7, 8, 5 | 42, 57, 43 |
| v21-1 s1/s3 | 5, 4 | 5, 5 | 283/460/482, 256/352/484 | 19, 15 | 12 (8), 9 (4) | 22, 17 | 3, 1 | 40, 31 |
| v22 s1/s2/s3 | 4, 4, 3 | 3, 5, 6 | 329/484/490, 326/485/489, 307/476/482 | 18, 14, 12 | 10 (8), 45 (42), 28 (20) | 18, 51, 21 | 2, 3, 3 | 28, 29, 12 |

(v21-1 s2 errored on the data mount, section 7.)

Verdict: v22 does **not** beat v21-1 (3.67 vs 4.5 of 13, sd ~0.6) and its mean wall (~321 s)
fails the 300 s gate, so it was not submitted. The cradle did what it was built for — fewer
compactions, big outputs and loop tasks than the bundle — but resolves did not move. Three
tasks resolve in every run of every arm (fastapi_14786, fastapi_14794, rich_3454) and
fastapi_11194 in 6 of 8; the only other resolve was rich_3944 once (v21-1 s1).

**The edit path is now the main bottleneck.** Almost every failed edit is the same failure:
`Invoking edit_file() failed as the following mandatory input parameters are not present:
old_string`. The tool-call parser splits a multi-line `old_string` containing quotes,
parentheses and commas into bogus argument *keys* (in v22 s2 rich_4070 the argument keys were
`filepath`, `new_string`, and a key literally named `if (\n self.rich_tracebacks\n and
record.exc_info …`). The model then resent that identical broken call **37 times**. These
rejected calls do not count against the 28-call budget, so they burn turns and wall time
instead. The prompt's "switch to the heredoc after a missing-parameter error" rule was ignored.
`run_command` (one string argument) had 0 corrupted calls in 395 in earlier lab runs.

## 6. Open next step: v22-1 (not built yet)

Propose the plan to Charles before writing code. Spec as agreed so far:

1. **Keep the v22 cradle protections** (narrow output, ≤60-line windows, STATE note, commit rule,
   no history searches, 5 tools, thinking 4096, max_output 6144).
2. **Fix the edit path** so a parse failure cannot loop. Options to evaluate (pick by evidence):
   make the one-call sentinel-heredoc Python edit through `run_command` the *primary* path for
   any multi-line or quote/paren-containing change and keep `edit_file` for single-line edits;
   or unregister `edit_file` entirely; plus a hard rule that an identical failed call is never
   repeated. Measure failed edits, identical repeats and first-edit call index.
3. **Get the mean wall under 300 s**, probably with `max_time_minutes: 6`. Truncating the existing
   traces at 360 s gives a mean of 271–284 s for v22 and would have lost 1 resolve in 3 seeds
   (v22 s1 resolved a task at 490 s; v21-1 s1 one at 460 s). The agent behaves differently with
   less time, so measure it; do not assume it.
4. **Remove the FastAPI `docs_src` hint.** v21-1 dropped it, but v22 was rebuilt from the bundle and
   has it again (`agents/structured-v22/prompts/system.md` line 64).
5. **Make the data-mount fix permanent** in `src/gemma_lab/notebook.py` (two `DATA_DIR = …`
   lines, ~285 and ~997): poll both `/kaggle/input/competitions/gemma-4-developer-agent` and
   `/kaggle/input/gemma-4-developer-agent`. Until then `push_dev13.sh` applies
   `scripts/handoff/patch_datapath.py`.
6. Gate to spend a slot: on dev-13 with ≥2 seeds (3 preferred), mean resolved ≥ v21-1's 4.5 or a
   clear empty-diff/failed-edit reduction with no resolve loss, **and** mean wall ≤300 s. Then
   submit with `scripts/handoff/submit_guarded.py`.

Longer-term (Charles): once enough tasks are solved inside the 300 s mean, relax the per-task
limit (spend the slack from fast solves on hard tasks), always re-checking the 12 h projection.

## 7. Known pitfalls

- **Kaggle auth quirk.** Kaggle API tokens start with `KGAT_`. The CLI refuses a `KGAT_` token in
  `KAGGLE_KEY` or in `~/.kaggle/kaggle.json`'s `key` field. It must be in `KAGGLE_API_TOKEN` or
  `~/.kaggle/access_token`. `. scripts/handoff/kaggle_env.sh` fixes this automatically; the
  Python scripts do the same. Never print or commit the token.
- **Data mount.** Kaggle sometimes mounts the competition at `/kaggle/input/gemma-4-developer-agent/`
  instead of `/kaggle/input/competitions/gemma-4-developer-agent/`. v21-1 s2 died waiting for
  `tasks.jsonl`. Always patch notebooks (push_dev13.sh does) until notebook.py is fixed.
- **Compaction at 14,336 tokens** (scorer-owned). Every prompt character and every large tool
  output spends that budget. Keep the system prompt ≤8k chars.
- **Wall time.** Report mean, p90 and max over the 13 tasks. The 8-minute cap makes p90 ≈ 480 s.
  `gemma-lab submit --execute` re-checks the 129-task projection.
- **Unexplained hosted ERROR.** v21-1's first upload errored and the identical retry scored 0.17.
  If an upload errors, read Kaggle's status first; a retry of the same archive is the one allowed
  exception to "never resubmit" (it never scored).
- **Determinism.** `gemma-lab pack` is deterministic, so any tiny change produces a new sha.
  The guard compares exact sha; it cannot tell that a one-byte change is "the same bet". Do not
  game it.
- **Prompt braces.** ADK treats `{…}` as template variables. Keep prompts brace-free.
- **GPU concurrency.** At most 2 Kaggle GPU sessions run at once. A dev-13 run takes ~1.5–2 h.
  The weekly GPU quota is finite; check `kaggle kernels list --mine` and quota before queuing.
- **Dates.** Kaggle timestamps are UTC. Charles is in America/Los_Angeles.

## 8. Core loops (scripts/handoff, also slash-command skills)

| Loop | Command | Skill |
|---|---|---|
| Pack | `scripts/handoff/pack.sh structured-v22-1` → `artifacts/<name>/submission.zip`, prints sha, warns if already scored | `/pack-agent` |
| Push a dev-13 run | `scripts/handoff/push_dev13.sh structured-v22-1 s1 --execute` (omit `--execute` for a dry run) | `/push-dev13` |
| Fetch results | `scripts/handoff/fetch_dev13.sh structured-v22-1-dev13-paired-s1 --wait` → `runs/dev13/<slug>/` | `/analyze-dev13` |
| Analyze | `uv run python scripts/handoff/analyze_dev13.py v21-1-s1=DIR v22-1-s1=DIR …` | `/analyze-dev13` |
| Submit | `uv run python scripts/handoff/submit_guarded.py ARCHIVE --evaluation DIR … --message "…" --execute` | `/submit-candidate` |

## 9. Where the rest of the context lives

`gemma4-handoff-artifacts.tar.gz` (Charles has it; see its README): the former team's notes
(`gemma4-team/`: research, ideation, implementation, verification, rebuild, v22 diagnosis, the
dev-13 run outputs with traces for v21-1, bundle and v22) and `audit/` (source of the public
LB-0.24 notebook and three other public notebooks we studied). Extract it **outside** the repo,
e.g. `~/gemma4-context/`, and read from there. Do not commit it.

Former team workflow (for reference; you replace it): Research, Ideation, Implementation,
Testing, Verification and Agent Engineering bots. Implementation opened a PR per candidate,
Verification reviewed it, and PRs merged once Verification approved. A daily routine at 5:15 PM
PT submitted only Verification-approved new candidates. That routine stays off until Charles
asks for it again.
