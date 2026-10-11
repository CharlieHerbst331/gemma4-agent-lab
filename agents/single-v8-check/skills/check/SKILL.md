---
name: check
description: Pin /tmp/repro_check.py, rerun it, and print git status, git diff --stat, and one short pytest line. No arguments.
---
Call run_skill_script with skill_name check and file_path scripts/run.py. Do not pass args. Write the repro to /tmp/repro_check.py with run_command before the first call.
