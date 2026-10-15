---
name: locate
description: Literal search with one string. Prints each hit and a few surrounding lines, then stops. Output is truncated.
---
Call run_skill_script once: {"skill_name":"locate","file_path":"scripts/run.py","args":["literal text"]}. args is a list of one string. Never put skill_name or file_path inside args. The script finds the git repo from GEMMA_CHECK_ROOT, then /workspace, then a PYTHONPATH entry that contains .git. Do not set those yourself. It does not write files. Filenames that start with a dot, including `.adk_exec_*.py`, are skipped.
