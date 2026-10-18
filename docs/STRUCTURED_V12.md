# structured-v12

Unevaluated copy of structured-v8 with a visible task clock. structured-v8
scored 0.10. This candidate has no score. No Kaggle push and no GPU run.
Existing agent directories were not modified. The scored v8 archive stays
`9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e`. The v12
archive is
`1db40320137309e3a496b1590156ca98579e02ae385cc2cd7d44d43879515f39`.

## Smoke that motivated the clock

The real structured-v8 GPU smoke5 (n=5, archive
`9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e`, Gemma
Testing Bot, 18 October 2026) resolved 2 of 5: fastapi_11194 and rich_3454.
Four of five runs hit the 300 second cap (302–308 seconds). fastapi_11194
finished at 248.3 seconds. Mean wall was 293.3 seconds. That fails the
120-task block: `120 × (293.3 + 70)` is about 43598, and the limit is 39600,
which needs a mean of 260 seconds or less. The same hash later moved
0.10 → 0.13 on the public leaderboard. With n=5 and one repeat, a change of
one task or 0.03 on the leaderboard is noise. This smoke replaced
fastapi_14262 with rich_3454, so 2/5 is not a rate to compare with earlier
smokes.

repair_1 is supposed to hand off at 180 seconds by calling `get_status`. It
did that on time in 1 of 5 runs (fastapi_11194, 185 seconds), which is also
the only explicit `submit_patch` (verify_3 at 244 seconds). rich_3454
resolved only through the harness fallback: first edit at 86 seconds,
repair_1 handed off at 249 seconds, verify_3 never ran. rich_4070 made 45
calls and rich_3938 made 52 calls, all reads, zero `get_status`, no edit,
empty diff, repair_1 to about 297 seconds. rich_3934 edited the wrong file,
called `get_status` at 237 and 272, and left repair_1 at 286 seconds. The
check skill was called 0 of 5 times. Four heredoc writes all compiled. The
compile guard never had to fire. Model load from the kernel log was about
388 seconds (tasks.jsonl ready at 105, vLLM up at 493), so
`L + 129 × mean` still passed.

## What actually injects the clock

Nothing in the harness adds a line to every `run_command` result. The
mechanism in this candidate is a mandatory prefix on every shell command.
The model has to copy it. A missed prefix does not print `[elapsed Ns]`.

The swegemma sandbox copy inspected for this change (the same tree
previously cited as 0.2.7) starts a container with environment
`TEST_TMPDIR=/tmp` only (`sandbox/docker.py` line 93). `exec` does not pass
an environment override. It runs:

```
timeout -k 5s {timeout} /bin/bash -c {shlex.quote(command)}
```

inside `container.exec_run(cmd=['/bin/bash', '-c', timeout_command])`
(`sandbox/docker.py` lines 705–708). That is non-interactive, non-login
`bash -c`. It does not source `~/.bashrc` and it does not run
`PROMPT_COMMAND`. A command cannot persist `BASH_ENV` into the next exec,
because the next exec is a new process with the container's start
environment.

The subprocess sandbox does the same shape. `build_sanitized_env` keeps
`PATH`, `LANG`, `LC_ALL`, `TERM`, `USER`, `LOGNAME`, `SYSTEMROOT`,
`LD_LIBRARY_PATH`, `TMPDIR`, and `TEST_TMPDIR` (`sandbox/subprocess_sandbox.py`
lines 24–35). `BASH_ENV` is not in that list. `HOME` is the sandbox tmp
directory (line 48). The command is `['/bin/bash', '-c', translated_cmd]`
(`sandbox/subprocess.py` lines 495–500).

`BASH_ENV=/path bash -c` does source that file, which a local check
confirmed. The harness never sets `BASH_ENV`, so that hook does not apply.
A skill wrapper would print the line only when the model calls the skill.
The check skill was called 0 of 5 times in the smoke when the prompt left it
optional. Replacing `/bin/bash` inside the image is out of scope.

Triage's only command writes the origin and prints the line:

```
date +%s > /tmp/t0; printf '[elapsed %ss]\n' "$(( $(date +%s) - $(cat /tmp/t0) ))"
```

Every later `run_command` starts with this prefix, then the real command,
in the same shell call:

```
test -f /tmp/t0 || date +%s > /tmp/t0; printf '[elapsed %ss]\n' "$(( $(date +%s) - $(cat /tmp/t0) ))";
```

`read_file` still does not carry the line. The repair prompts say not to
call `read_file` once the latest elapsed line is 110 or more and `git diff`
is empty. The heredoc recipe itself starts with the same prefix, then
`cat > /tmp/line_fix.py`, so the copied command prints `[elapsed Ns]` too.
`include_contents` stays `default`, so a printed line remains in
the history for the next role. `get_status` stays in the tool list and does
not count as a call. It is not the handoff clock. v12 does not call it
before every command. That pattern is what starved structured-v10.

## Handoffs and the cap

The elapsed line is the handoff key. Triage writes `/tmp/t0` on its first
command, about 5–15 seconds after the agent starts, and the line is printed
at the start of the command. A threshold read off that line is later on the
wall clock than the same number.

Suggested stops of 135, 170, 195, and a submit at 205 do not leave 15
seconds for every later role. Five roles follow repair_1, and
`135 + 5 × 15 = 210`, which is past the 205 submit line. The stops below
are the adjustment. Each gap is 15 seconds, and verify_3 still submits by
205, which is the 250 second cap minus 45.

- repair_1 stops at 130. verify_1 is 130 to 145.
- repair_2 stops at 160. verify_2 is 160 to 175.
- repair_3 stops at 190. verify_3 is 190 to 205 and must submit by 205.
- An empty diff at 110 or more, and still before that role's stop, is the
  v8 heredoc. PATH is the first file named in the triage brief. If
  `/tmp/repro_check.py` already exists, OLD and NEW are the change that
  repro asserts.

The heredoc is the v8 helper: `ast.parse` before the write, backup
`/tmp/pre_` plus the path with slashes replaced, `py_compile.compile(path,
doraise=True)`, restore onto that path only, never `git checkout`. The
check skill call stays `{"skill_name":"check","file_path":"scripts/run.py"}`.
Sampling stays temperature 1.0, top_p 0.95, top_k 64. Repair thinking stays
256 with `include_thoughts: true`. Triage and verify stay at thinking
budget 0. Calls stay 220. Turns stay 320. The shape stays
Sequential[triage, repair_1, verify_1, repair_2, verify_2, repair_3, verify_3].
Triage's tool list is the one structural change: `run_command` only, so it
can write `/tmp/t0`. v8 triage had `tools: []` and could not run that command.

## Gate math

The v8 smoke5 cap-hit durations were 302–308 seconds on a 300 second cap, an
overrun of 2–8 seconds. A cap of 260 therefore measures about 262–268.
`120 × (262 + 70) = 39840` and `120 × (268 + 70) = 40560`, both over 39600.
The block passes at a mean of 260.0 exactly, and a real cap-hit does not
land on that number.

The cap is 250 seconds. The same overrun is a measured mean of about
252–258.

- `120 × (258 + 70) = 120 × 328 = 39360`, under 39600.
- `120 × (252 + 70) = 38640`, under 39600.
- `900 + 129 × 258 = 34182`, under 38880.
- `900 + 129 × (250 + 70) = 42180`, under the 43200 warning.

250/60 is `4.166666666666667`. That literal times 60 is
250.00000000000003, and `120 × (that product + 70)` is 38400.0, the same
block as an exact 250 second cap. `max_time_minutes` is that literal.
`timeout_seconds` is 250 so one command
cannot outlive the task. Submit at elapsed 205 is `250 - 45`.
`120 × (205 + 70) = 33000`, under 39600.

The smoke mean of 293.3 would still fail. v12's claim is that a run which
hits the new cap, including a 2–8 second overrun, produces a mean the block
accepts. That is unmeasured.

## Smoke protocol

`configs/protocols/structured-v8-vs-structured-v12-smoke.yaml` compares v8
and v12 on rich_4070, rich_3934, fastapi_11194, rich_3938, and rich_3454.
One repeat. `matched_pair` is false because the cap and the handoff text
differ. It is not promotion eligible. No GPU run is started from the file.
The larger arm cap is 300 seconds, so `pair_fits` with a 900 second load
and a 300 second tasks.jsonl wait is 4320 seconds. The session budget is
14400 seconds.

## Open risks

- The prefix is still prompt text. A model that omits it gets no elapsed
  line, which is the failure mode this candidate is trying to leave.
- fastapi_11194's first edit in the smoke was at 173 seconds. repair_1 now
  stops at 130 and repair_2 at 160. That window is earlier than 173 even
  after a 10 second late clock, so that solve can move into repair_3's
  175–190 slice or be missed.
- A forced heredoc on rich_4070 and rich_3938 is likely the wrong edit. The
  smoke analysis already said those tasks are a multi-file refactor and a
  missing API. The 110 second rule targets the first triage file, and a
  repro when one exists, so the run edits instead of reading until the cap.
- Each role after repair_1 has 15 seconds. That is the floor, not spare
  time for a second edit.
- n=5 cannot say whether the clock helps. The protocol is the comparison,
  and it has not been run.
