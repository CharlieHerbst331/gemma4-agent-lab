# Development contract

Work toward a competitive Gemma 4 coding agent and a technically credible portfolio.
Read README.md and docs/RUNBOOK.md before modifying experiments or submission operations.

- Use `uv sync --locked`; keep the Mac environment separate from GPU dependencies.
- Run `make check` for toolkit code changes. Run portable validation and packaging for agent changes.
- Use the official Kaggle starter/harness for performance measurements. Never invent scores.
- Treat smoke results as infrastructure checks, not evidence of generalization.
- Record hypothesis, candidate archive hash, git revision, frozen split, task IDs, hardware, and results.
- Keep reference patches, test patches, and grading metadata out of agent context. Train only on train IDs.
- Tune on dev. Reserve holdout for milestone comparisons; track when it has been examined.
- Compare identical task cohorts and report regressions, infrastructure errors, and per-repo results.
- Keep credentials, data, model weights, traces, and archives in ignored directories.
- Do not download the full competition dataset or base model onto this low-disk Mac.
- Use declarative YAML; only official tools and sandboxed skills execute in submitted agents.
- The user authorized repository setup, development, testing, research, and submission capability.
  Routine local fixes and private development uploads can proceed. Use the checked uploader for
  actual submissions and respect one per UTC day. Do not provision paid hardware without a budget.
- Do not automatically accept new legal terms, publish competition data, invite collaborators,
  or change repository visibility. Observe the competition's public code-sharing requirements.
- Maintain docs/STATUS.md so another session can resume from actual state and known blockers.
- Do not start recurring jobs unless the user requests a schedule.
