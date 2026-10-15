---
name: check
description: Pin the repro, py_compile changed Python files, print whether the diff is non-empty, and one short pytest line. No arguments. Output is truncated.
---
Call run_skill_script with skill_name check and file_path scripts/run.py. Do not pass args. Before the first call, write the repro with run_command to /tmp/repro_check.py. The script opens that file from tempfile.gettempdir() and finds the git repo from GEMMA_CHECK_ROOT, then /workspace, then a PYTHONPATH entry that contains .git. Do not set those yourself. conftest.py and pytest.ini are not marked protected when they are the only changes.
