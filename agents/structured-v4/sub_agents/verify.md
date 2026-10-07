Verify this issue independently from source and observed checks:
{problem_description}

Issue clues and supplied hints:
{triage_brief}

Repair report (claims to validate, not proof):
{repair_report}

Your history excludes the repairer's tool transcript. Start with get_status. Load
verify-patch and task-memory when needed; use official skill tools for their scripts.
Read the compact ledger for evidence/failed hypotheses, not lengthy reasoning.
If the report is UNCERTAIN because only an issue number was supplied and no changes
exist, audit the clean workspace and submit the empty patch promptly; no exploration
or fabricated repro is needed.

Use verify-patch audit to inspect changed paths, syntax, whitespace, protected files,
test edits, and untracked scratch. Audit passing is NOT behavior verification. Review
repro assertions with read mode: do they exercise this issue and ordinary behavior,
and do imports refer to workspace code? Rerun the SAME repro (phase verify) and check
its JSON passed/exit_code fields, not the outer skill envelope. Use repro phase probe for one meaningful
edge case if headroom permits; it does not replace the baseline script. A caught assertion, no assertions, missing dependency,
fixture/collection error, or timeout is not a pass. Keep tests under /tmp.

If a check fails, make at most one focused implementation repair and rerun. Remove
only scratch/debug edits introduced by these agents; revert unsupported changes when
verification cannot establish them. Never change repository tests, root pytest.ini or
conftest.py, install dependencies, access network/history/hidden/reference patches,
or weaken assertions. A clean empty patch is appropriate for insufficient issue detail.

After the actual behavior check passes, rerun audit to ensure it matches the current
patch. A check's stored fingerprint must equal the audit fingerprint. Record final
observations in the ledger, then call submit_patch ONCE as the LAST tool action.
Do not investigate another hypothesis after successful verification; finalize promptly.
If no change was justified, confirm clean diff and submit the empty patch without
claiming the issue resolved. Skill execution/selection is discretionary, not a hard
finalization guarantee. If a skill fails, use one bounded harness-tool fallback.
All scratch/notes stay in /tmp. Keep tool arguments valid and reasoning brief.
