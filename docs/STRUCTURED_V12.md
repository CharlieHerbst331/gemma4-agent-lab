# structured-v12

Unevaluated copy of structured-v8 with a visible task clock. structured-v8
scored 0.10. This candidate has no score. No Kaggle push and no GPU run.
Existing agent directories were not modified. The scored v8 archive stays
`9b1b01ca6881268867b06b5610fa03fc5fcb7b9f0ae3f98df5df565fb1ab586e`. The v12
archive is
`3d3f320ec7b9efbb92f0a732db1750fb63c6dbbde34624aa171d1dbe22e94d7b`.

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
call `read_file` once the latest elapsed line is 120 or more and `git diff`
is empty. `include_contents` stays `default`, so a printed line remains in
the history for the next role. `get_status` stays in the tool list and does
not count as a call. It is not the handoff clock. v12 does not call it
before every command. That pattern is what starved structured-v10.

## Handoffs and the cap

The elapsed line is the handoff key.

- repair_1 stops when the line is 150 or more. From 120 up to 150, an empty
  diff means the next call is the v8 heredoc, then the text report. No
  further reads.
- repair_2 stops when the line is 210 or more. An empty diff at 120 or more,
  and still under 210, is the same heredoc.
- verify_3 submits when the line is 215 or more, or
  `time_seconds_remaining` is under 45. 215 is the cap minus 45 seconds.
  An empty diff at that point is one heredoc, then `submit_patch`. The
  prompt still says to call `submit_patch` anyway if the diff stays empty.

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

`max_time_minutes: 4.5` is allowed. structured-v5 uses it, and the notebook
reads the field as a float. 4.5 minutes is 270 seconds. A cap-hit mean of
270 fails the block that uses the measured mean:

- `120 × (270 + 70) = 40800`, over 39600.
- `120 × (260 + 70) = 39600`, which passes.
- `900 + 129 × 260 = 34440`, under the 38880 block.
- `900 + 129 × (260 + 70) = 43470`, over the 43200 warning. The warning
  still fires at a 260 second cap. The cap itself never blocks.

260/60 is `4.333333333333333`, and that float times 60 is 260.0, so
`max_time_minutes` is that value. `timeout_seconds` is 260 so one command
cannot outlive the task. The aimed submit at elapsed 215 passes with
margin: `120 × (215 + 70) = 34200`.

The smoke mean of 293.3 would still fail. v12's claim is that a run which
hits the new cap produces a mean the block accepts. That is unmeasured.

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
  stops at 150. That can drop the only explicit solve in the smoke.
- A forced heredoc on rich_4070 and rich_3938 is likely the wrong edit. The
  smoke analysis already said those tasks are a multi-file refactor and a
  missing API. The 120 second rule exists so the run edits instead of
  reading until the cap.
- repair_2 stops at 210 and verify_3 submits at 215. Five seconds is a
  tight gap for repair_3. The submit line is what the cap-minus-45 rule
  requires at a 260 second cap.
- n=5 cannot say whether the clock helps. The protocol is the comparison,
  and it has not been run.
