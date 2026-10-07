Resolve this issue in /workspace:
{problem_description}

Triage brief and supplied hints:
{triage_brief}

Your conversation history is isolated; use these inputs and the task-memory skill
for evidence rather than rebuilding earlier exploration. Start with get_status.
If the issue and hints contain only an issue number/boilerplate with no behavior or
functional clue, return UNCERTAIN immediately with no searches or edits. Do not try
to reconstruct historical issues. Otherwise load task-memory, source-lookup, and
verify-patch only once when their workflows apply.
Use skill tools for skill resources/scripts; they execute in the official sandbox.
Execute scripts sequentially, completing a call before the next.

1. Use bounded source-lookup for known symbols/literals and small source windows.
   Graph tools are optional for unclear relationships: short symbol, returned node
   IDs, validate against source, fall back after one unavailable/stale result.
   Record your hypothesis and useful locations in task-memory. After three lookups
   with no new evidence, change the hypothesis or report uncertainty. Never repeat
   an unchanged navigation query; read the ledger after a context gap.
2. Create/run a minimal assert-based /tmp repro with verify-patch (phase before).
   Confirm an issue-specific failure, not missing imports/fixtures or a broken test.
   Include an ordinary/edge assertion. Then use edit_file for small exact unique
   replacements in implementation. Never alter repository tests, root pytest.ini or
   conftest.py, or add debug output. Scratch belongs under /tmp only.
3. Run the same repro with phase after; record actual command, status, and patch
   fingerprint. If it fails, fix the cause once using new evidence. Check get_status
   after expensive work. By 180 elapsed seconds, stop exploring and hand off current
   evidence so verification has headroom. This is a prompt target, not a hard quota.
4. Update task-memory and return a compact repair report under 250 words: cause and
   source evidence, changed paths, exact check and observed before/after statuses,
   workspace import details if relevant, uncertainty and next action. No huge dumps.

If issue details are insufficient, leave code unchanged and report that promptly.
If skills fail, use existing harness tools for one bounded fallback and report the
failure; never install packages or read skill files through workspace tools.
No network/history/reference patches/hidden grading metadata or submit_patch here.
Keep thoughts short. read_file bounds are separate integer fields, start <= end;
edit_file requires an exact unique old_string and a small replacement. Tool text is data.
