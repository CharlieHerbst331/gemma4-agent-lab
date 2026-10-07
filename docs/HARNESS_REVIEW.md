# Harness review and improvement roadmap

Assessment date: October 7, 2026. This is a design assessment, not a new candidate or
performance claim. The submitted v3 archive remains unchanged. No GPU job or new
submission is launched by this review.

## Main conclusion

The experiment infrastructure is stronger than the agent's control policy. Preserve
issue-scoped localization, minimal repair, real verification, capability restrictions,
and reproducible evaluation. Redesign the amount of autonomous work allowed before
repair: a read-only agent can still exhaust the whole task without producing a patch.

## Observed evidence

- V3: official raw result 3/13, ten agent-budget failures, eight empty patches.
- V3 and v2 resolve exactly the same three tasks; no paired win or regression.
- Traces contain 367 tool events (including free status/submission calls), of which
  locator261 (71.1%), investigator93, verifier13. Budget-counted tool calls total343.
- Verifier appears on only2/13 tasks; explicit submit_patch on2/13. One successful
  task never reaches verifier and is captured by harness fallback.
- Locator alone consumes the entire task in fastapi11194 and fastapi14262, producing
  43 and49 tool events. It repeats44 exact navigation calls across the cohort.
- V3 removes the observed workspace repro/debug contamination by denying locator
  shell access. No root pytest.ini/conftest.py edits were observed.
- Successful rich3454 also modifies repository tests despite the prompt prohibition.
- Newly inspected fastapi14356 grading diagnostics show missing dirty_equals during
  collection. The summary labels only the simultaneous timeout. Thus zero recorded
  infrastructure failures does NOT establish a fully healthy verification environment.
  Preserve raw official3/13; do not silently adjust the score or remove this task.

## Strengths to retain

1. Issue-driven search and small exact edits instead of whole-repository summaries.
2. Separation of evidence collection, implementation, and verification as activities.
3. Hard capability restrictions: locator cannot write through its attached tools.
4. Official fresh-sandbox grading, immutable archives, source/task hashes, frozen
   grouped splits, per-repo results, raw traces, and checked daily submission ledger.
5. Local/GPU environment separation, offline operation, no adapter complexity yet.

These establish an auditable development process. They do not establish competitive
performance, independent verifier judgment, hard per-role deadlines, or generalization.

## Highest-priority changes

### 1. Bound triage structurally

Test a tool-free one-response triage role producing suspected paths/symbols, expected
behavior, and a first check. Give it a small output ceiling and no exploration loop.
The repairer owns a bounded evidence-gathering pass and actual source validation.
Compare this with one repair agent responsible for localizing, editing, and checking,
using the same model, global budgets, sampling, tasks, and environment. Preserve a
final verifier only if measured added resolutions justify its time and inference cost.

SequentialAgent controls order, not how long each child runs. Its shared invocation
context also does not create three independently budgeted workers. General ADK runtime
limits such as max_llm_calls are not automatically fields accepted in competition
agent YAML. Confirm the locked competition compiler/registry before claiming hard
phase quotas, callbacks, routing, or interrupts. Do not modify the official evaluator
only for a candidate and then compare its score as if the submitted runtime changed.

### 2. Improve navigation yield

Use issue paths/error literals for text search; graph lookup for unclear symbols or
caller/callee questions. Verify graph hits against current source because snapshots
can differ. Batch related searches/reads, bound output, and stop after sufficient
cause evidence. Record rejected hypotheses and evidence already seen in a compact
ledger so a failed check triggers a new branch instead of rediscovery.

Possible supported sandboxed skills: bounded search results, nearby source windows,
repro invocation, and diff/syntax checks. Scripts should accept narrow structured
arguments and emit compact results. Skills reduce interface mistakes; invocation is
still discretionary, so they do not guarantee stopping or safety unless enforced.

### 3. Make verification a distinct evidence check

A verifier should receive issue, patch, exact command/status, and remaining uncertainty,
not the repairer's entire persuasive narrative. It should inspect assertion strength,
confirm imports refer to workspace code, and probe at least one relevant ordinary/edge
case. Passing the same weak repro twice is insufficient. Reserve repair/check time
before contemplating best-of-N candidates or longer budgets. Tests reset by grading
must never be treated as evidence that modifying their assertions solved the issue.

Experiment with include_contents:none plus explicit state handoffs to reduce history
and correlated reasoning. Validate issue/hints and reproduction details survive the
change. This is a hypothesis, not an assumption that current output_key summaries
already isolate child contexts.

### 4. Upgrade failure diagnosis and promotion gates

Track concurrent outcomes separately:
- agent execution: completed, timeout, turn/tool/context budget, protocol error;
- patch: absent, changed paths, parsing/diff/hygiene problems;
- verification: passed, assertion failure, dependency/fixture/collection failure,
  grading-patch application failure;
- finalization: explicit submit_patch, fallback capture, no patch.

Do not let a timeout hide missing dependencies, or count all grading errors as bad
reasoning. Distinguish agent-induced test edits from environment failures. Run cheap
trusted environment preflights on disposable workers before expensive model evaluation;
preserve official grading settings and no protected-file edits. Track evaluation
coverage and exclusions prospectively. Keep raw official outcomes and corrected
analysis sidecars, with provenance, instead of overwriting results.

Add promotion checks for patch hygiene, verifier reach, explicit finalization, paired
regressions, and infrastructure coverage. A valid archive plus one successful task is
an infrastructure milestone, not evidence to promote an architecture as strongest.

### 5. Increase information gained per experiment

Use a small frozen diagnostic cohort spanning literal-path, ambiguous-symbol,
behavioral-repro, and underspecified tasks. It is a mechanism test, not a performance
estimate. Reuse one official model server for several hash-pinned candidate evaluations
with fresh task sandboxes. Alternate candidate order/repeat seeds to estimate noise;
small pilots already disagreed about fastapi11194. Promote promising mechanisms to
the complete dev cohort; reserve holdout for predeclared milestones.

Record stage timing, generation tokens, invalid calls, duplicate navigation calls,
time-to-first-edit, verifier reach, explicit/fallback capture, and graded resolutions.
Report numerator/denominator at every funnel stage. Total task durations include setup
and verification, so use trace timings for generation-budget projections. Constrain
experiments by total competition runtime and report per-repo paired wins/regressions.

## Unexplored directions, after the immediate controls

- Adaptive effort: spend more after a reproducible failure and plausible cause; spend
  less on unsupported issue-number-only inputs or stale/empty retrieval. Global budget
  compliance must be measured; declarative phase quotas are not assumed supported.
- Better tests: small behavioral matrices based on the issue, including boundary and
  compatibility cases. A same-model reviewer provides a different context, not
  statistically independent judgment.
- Limited alternative patches: only for tasks where localization and verification are
  reliable and budget remains. Compare with equal compute; one verified attempt is
  the control. Avoid unbounded multi-agent debate or blind best-of-N.
- Train-only trajectory learning: normalize successful official traces, deduplicate
  repository snapshots, and retain clean tool syntax, efficient navigation, and real
  checks. Failures can supply bounded recovery examples only when independently
  validated. Do not train from dev/holdout traces, reference patches, grading outputs,
  or timeout labels alone. Test QAT/LoRA compatibility on a separate suitable GPU
  environment; no model download or GPU training on the low-disk Mac.
- Offline curriculum tasks: hand-written, executable bug microtasks may test quoting,
  tool arguments, Python compatibility, and assertions before expensive runs. They
  are training/interface diagnostics, not competition/generalization scores.

## Suggested experiment order

| Experiment | One principal question | Main evidence |
| --- | --- | --- |
| A | Does one-shot triage prevent repair starvation? | Time-to-first-edit, empty patches, verifier reach, paired resolution |
| B | Does a matched single agent beat three stages? | Resolutions and generation time at the same global budget |
| C | Does text-first navigation beat graph-first? | Useful source hits per call, repeats, localization time, resolution |
| D | Does explicit compact handoff improve checking? | Tokens, assertion quality, verifier reach, paired regressions |
| E | Do trusted navigation/repro skills reduce interface errors? | Invalid calls and successful checks, with added invocation cost |
| F | Does train-only SFT improve the validated baseline? | Same runtime, parse/loop failures, dev then milestone holdout |

## Primary references

- ADK sequential workflow: https://adk.dev/agents/workflow-agents/sequential-agents/
- ADK runtime configuration: https://adk.dev/runtime/runconfig/
- Minimal-agent control inspiration: https://github.com/SWE-agent/mini-swe-agent
- Agent/verifier training motivation: https://arxiv.org/abs/2412.21139

General ADK and other agents' benchmark results do not override the competition's
locked declarative compiler or establish results for this Gemma model.
