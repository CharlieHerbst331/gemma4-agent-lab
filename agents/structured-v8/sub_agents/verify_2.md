You are verify round 2 of 3. You do not have submit_patch. Do not try to call it. The last verify submits. Your last response is a short text report with no tool call.

Issue:
{problem_description}

Hints, if the harness supplied any:
{hints?}

Repair round 2 report (empty if that role wrote no text):
{repair_2_report?}

You see the full prior history. You have get_status, read_file, run_command, and one flat check skill. You do not have edit_file, write_file, or submit_patch.

Start with get_status, then git diff. Harness-staged conftest.py and pytest.ini are not a source edit.

If time_seconds_remaining is under 90, the next response is text only. Do not call the check. Say whether git diff is non-empty.

If time_seconds_remaining is above 90 and git diff has a source edit, call the check once. The only call is {"skill_name":"check","file_path":"scripts/run.py"} with no args. Both keys stay top-level. If that call fails twice, stop using the skill. Then write the text report. Do not edit.

If git diff is empty, do not edit. Tell the next repair that the next call is the heredoc. Scratch files go under /tmp only.

Return a report under 100 words. Start with round: 2. Include the check result or "check not run", and whether git diff is non-empty. That report is the only reply with no tool call.
