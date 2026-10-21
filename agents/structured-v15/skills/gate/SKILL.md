---
name: gate
description: Compile touched Python, import it, and run the matching test. Print PASS or FAIL. Restore a file only when py_compile fails and a /tmp backup exists.
---
Call run_skill_script with skill_name gate and file_path scripts/run.py. Do not pass args. Run this before submit_patch when 45 seconds or more remain. The script finds the repo with git rev-parse from the sandbox cwd or PYTHONPATH. It does not look up /workspace. A path under /tmp is not an edit. py_compile failure restores only /tmp/pre_ plus the path with slashes replaced, and only when that backup exists. Import failure and test failure print FAIL and leave the file. The script cannot wrap submit_patch and cannot end the role.
