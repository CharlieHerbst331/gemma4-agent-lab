---
name: map
description: Print the repo file tree and class or function signatures. No arguments. Output is capped.
---
Call run_skill_script with no args. The only call is {"skill_name":"map","file_path":"scripts/run.py"}. Both keys stay top-level. Do not pass args. The script finds the git repo from GEMMA_CHECK_ROOT, then /workspace, then a PYTHONPATH entry that contains .git. Do not set those yourself. It does not write files. Dotfiles, vendored directories, and test, docs, or example directories are skipped. The output stops at a fixed character budget.
