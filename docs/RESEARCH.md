# Research plan

The initial thesis is that small coding models benefit from better localization and disciplined recovery before more elaborate agent orchestration. This is a hypothesis to test, not a performance claim.

## Primary references

- [Official competition starter](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent): inference, tool routing, offline wheels, graph helpers, verification, and packaging.
- [SWE-bench](https://github.com/SWE-bench/SWE-bench): task/verification design and benchmark methodology.
- [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent): a simple sequential agent as a useful control. Its published benchmark numbers do not transfer to this competition/model.
- [SWE-agent](https://github.com/SWE-agent/SWE-agent): agent-computer interfaces, repository tooling, and trajectories.
- [SWE-Gym](https://github.com/SWE-Gym/SWE-Gym): training agents and verifiers with software-engineering environments.
- [Google ADK config](https://adk.dev/agents/config/): general YAML syntax. The competition's sandboxed compiler is the authority for supported features.

`gemma-lab research` saves current repository metadata, public notebook listings, and a leaderboard page. It is discovery, not an automatic endorsement or a full-text literature review. Open the relevant original paper/source, check the license, record the version, and distinguish proposed ideas from measured evidence.

## Ordered experiments

| ID | Hypothesis | Control and measurement |
| --- | --- | --- |
| B0 | The official harness can run our baseline end to end | Two-task smoke; schema, tools, patches, grading, archive |
| E1 | Graph-assisted localization improves correct file selection | Graph tools vs text-only, same prompt/budget/tasks; resolve rate and localization traces |
| E2 | Focused reproduction and regression tests improve patch quality | Remove reproduction instruction only; inspect wins/regressions and time |
| E3 | Budget-aware stopping and smaller edits reduce empty/truncated patches | Matched task set; NO_PATCH rate, timeout rate, tool-call validity |
| E4 | Compact failure summaries improve recovery | One recovery instruction/skill change; repeated-failure rate and resolve rate |
| E5 | Verified trajectory SFT improves tool use and issue repair | Same base/runtime; compare no adapter vs LoRA, parse errors and paired task outcomes |
| E6 | Evidence-based verification merits a specialist agent | Introduce only after single-agent controls; account for added inference cost |

Keep a failure taxonomy: localization, mistaken specification, implementation, API compatibility, inadequate regression test, invalid tool call, context truncation, budget exhaustion, sandbox/dependency failure, patch submission failure. Assign labels from trace evidence, not guesses.

Use the dev set for iteration, with repository breakdowns. At milestones evaluate a locked holdout and a leave-repository-out cohort. Report uncertainty and sample size. The private competition distribution differs from the public repositories; improving the public score alone is insufficient.

For each experiment, save an exact config archive, raw per-task rows, trace/patch links, compute use, comparison, and a retain/reject decision. Promote changes based on evidence. Start SFT after collecting enough valid trajectories; start RL after validating the reward and contamination boundaries.
