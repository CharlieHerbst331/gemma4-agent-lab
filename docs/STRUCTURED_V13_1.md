# structured-v13-1

Unevaluated copy of structured-v13. The directory is `agents/structured-v13-1`
and the agent name is `structured_v13_1`. `agents/structured-v13` and every
other existing candidate are unchanged. No score is claimed. No GPU run and
no submission.

## Hypothesis

v13's identical-call ban treats a new role's opening `get_status`, `git diff`,
and `git status` as repeats of an earlier role's call when no source edit has
happened since. Those opening calls are how the role reads the clock and
whether a diff exists. Allowing the first of each when the role starts, and
still banning a later repeat of that same call inside the role when no source
edit has happened since, should restore the opening check without reopening
the repeated-read loop. Triage has no tools, so it has no exemption sentence.
This is a hypothesis, not a measurement.

## What changed

Every file is byte-identical to structured-v13 except the agent name and one
paragraph on repair_1, repair_2, repair_3, verify_1, verify_2, and verify_3:

Opening calls. The first get_status, the first git diff, and the first git
status when this role starts are allowed even if an earlier role made that
same call and no source edit has happened since. A later repeat of that same
call in this role, with no source edit since, is still banned.

Cap, calls, turns, heredoc, empty-diff net, late deadline, and the rest of
the repeat rule stay at v13. v13's realistic timing projection remains about
267 seconds and still fails the internal 120-task block. 247.66 stays a
hypothesis about the no-edit loops.

## Record

- Base git revision: `eef720bcc161d42e7c0ddcea4d743e09c65087df` (main, after
  structured-v13 merged).
- Archive SHA256:
  `0c8aef814e0b8a3837d5fd489c22c538babc2e51b6bd0384baa8d5dc6ed0f86b`
- Frozen split and task IDs: none. No cohort was run.
- Hardware: none. No GPU run.
