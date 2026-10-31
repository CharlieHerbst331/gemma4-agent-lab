# structured-v19-1

Unevaluated copy of structured-v19 with three prompt fixes. The directory is
`agents/structured-v19-1` and the agent name is `structured_v19_1`. Other
candidates, including structured-v19, were not modified. No score is claimed.

## What run1 implies

On the six-task private run of structured-v18-1, the first patch phase
lasted about 133 to 251 seconds and usually held the clock until the cap.
Verify was reached on 2 of 6 tasks. None of the 4 non-empty patches was
tested. A model call costs about 6 to 8 seconds, so 300 seconds is about
40 calls. The whole-task cap stays 300 seconds. A 240 or 250 second cap
scored 0.06.

## Phase budget

Targets sum to 250 seconds, with about 50 seconds of slack inside 300.
They are not a second wall clock.

| Phase | Target | Hard lever | Prompt-only |
| --- | --- | --- | --- |
| triage | 15 s | max_output_tokens 384 | brief text |
| localize | 45 s | max_output_tokens 256, stop END_LOCALIZE, read-only tools | at most 4 tool calls |
| patch | 90 s | LoopAgent max_iterations 1, tools get_status and run_command, stop END_PATCH | at most 3 reads, never repeat a command |
| verify | 40 s | tools get_status and run_command, max_output_tokens 512, stop END_VERIFY | timeout 40 pytest on one file |
| repair | 60 s | LoopAgent max_iterations 1, submit_patch only here, stop END_REPAIR | FAIL_CODE and elapsed under 200 s, or EMPTY and elapsed under 270 s, one heredoc |

There is no exit tool, so a LoopAgent runs every iteration. max_iterations
1 means one pass, not one tool call. A higher cap would repeat the pass.
FAIL_CODE still uses the 200 second get_status check. An EMPTY verdict
gets one heredoc when elapsed is under 270 seconds. Both checks are
prompt-only. Verify writes /tmp/best.diff. Repair restores it with the
guarded checkout only when a later test is not better.

## Archive

SHA256: `see docs/STATUS.md and the pull request`

```bash
uv run gemma-lab pack agents/structured-v19-1 --output /tmp/structured-v19-1.zip
```
