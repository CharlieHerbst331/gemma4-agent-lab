# Portfolio evidence

The portfolio should let an experienced engineering or research reviewer verify the work quickly.

Deliver these assets as evidence accumulates:

1. A short architecture walkthrough with exact reproduction commands and runtime requirements.
2. A results table with baseline, ablations, paired wins/regressions, per-repository scores, uncertainty, and compute use.
3. Two or three annotated issue-repair case studies with task inputs, localization decisions, minimal patches, real tests, and failures that changed the design.
4. A useful reusable contribution: safe experiment/submission operations, a trace-analysis tool, a localization technique, or a documented failure taxonomy.
5. A concise technical report explaining the research question, method, controls, results, limitations, and negative findings. Consider the optional paper track if the evidence supports an original result.

Do not claim leaderboard rank, resolution rate, speedup, or generalization until measured. Distinguish harness smoke tests, public dev estimates, held-out estimates, and Kaggle public/private scores. Keep data/trace redistribution within competition and upstream licensing requirements.

Before public release, remove credentials and restricted data, retain third-party attribution, verify a clean clone can reproduce the toolkit checks, and satisfy the competition's public sharing requirement. Add screenshots/demos only when they show a real capability.
