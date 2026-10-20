# structured-v13-1

Unevaluated copy of structured-v13. The directory is `agents/structured-v13-1`
and the agent name is `structured_v13_1`. `agents/structured-v13` and every
other existing candidate are unchanged. No score is claimed. No GPU run and
no submission.

## Hypothesis

v13's identical-call ban treats a new role's opening `git diff` and
`git status` as repeats of an earlier role's call when no source edit has
happened since. Those opening commands are how the role sees whether a diff
exists. `get_status` never counts as a repeat and is always allowed, because
repair_1 calls it before each edit and the 240 second and under-120 second
checks need a fresh reading. The first `git diff` and the first `git status`
when a role starts stay allowed even if an earlier role made that same call.
A later identical `git diff` or `git status` in that role, with no source
edit since, stays banned. Triage has no tools, so it has no exemption
sentence. This is a hypothesis, not a measurement.

Submitted v13 (Kaggle ref 57412943, score pending) has the same literal
conflict in a weaker form. Its context rule bans an identical call when no
source edit has happened since, and that sentence can be read as covering
`get_status`, while repair_1 also says to call `get_status` before each edit.
v13 does not name `get_status` inside a later-repeat ban.

## What changed

Every file is byte-identical to structured-v13 except the agent name and one
paragraph on repair_1, repair_2, repair_3, verify_1, verify_2, and verify_3:

Opening calls. get_status never counts as a repeat and is always allowed.
The first git diff and the first git status when this role starts are allowed
even if an earlier role made that same call and no source edit has happened
since. A later identical git diff or git status in this role, with no source
edit since, is still banned.

Cap, calls, turns, heredoc, empty-diff net, late deadline, and the rest of
the repeat rule stay at v13. v13's realistic timing projection remains about
267 seconds and still fails the internal 120-task block. 247.66 stays a
hypothesis about the no-edit loops.

## Record

- Base git revision: `eef720bcc161d42e7c0ddcea4d743e09c65087df` (main, after
  structured-v13 merged).
- Archive SHA256:
  `74a6e27904e88d4d73d3ca1846f5ad228eb9e27ec431c347517b60f79b1e52fe`
- Frozen split and task IDs: none. No cohort was run.
- Hardware: none. No GPU run.
