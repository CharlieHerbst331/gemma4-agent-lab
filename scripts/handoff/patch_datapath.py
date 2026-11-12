"""Make a generated gemma-lab evaluation notebook accept either Kaggle data mount.

Kaggle normally mounts the competition at /kaggle/input/competitions/gemma-4-developer-agent.
On Nov 11, 2026 one kernel (structured-v21-1-dev13-paired-s2) got it at
/kaggle/input/gemma-4-developer-agent instead, and the run failed waiting for tasks.jsonl.
This patch polls both paths. It is idempotent.

The permanent fix belongs in src/gemma_lab/notebook.py (the two DATA_DIR lines). Until that
lands, scripts/handoff/push_dev13.sh applies this patch to every notebook it builds.

Usage: python3 scripts/handoff/patch_datapath.py <notebook-dir> [...]
"""

import json
import sys

MARK = "# DATA_PATH_FALLBACK v1\n"
OLD = [
    "TASKS_PATH = DATA_DIR / 'tasks.jsonl'\n",
    "_data_wait_seconds = wait_for_tasks_jsonl(TASKS_PATH)\n",
]
NEW = [
    MARK,
    "import time as _t\n",
    "_DATA_CANDIDATES = [Path('/kaggle/input/competitions/gemma-4-developer-agent'),"
    " Path('/kaggle/input/gemma-4-developer-agent')]\n",
    "_t0 = _t.monotonic()\n",
    "while _t.monotonic() - _t0 < DATA_WAIT_TIMEOUT_SECONDS:\n",
    "    _found = [d for d in _DATA_CANDIDATES if (d / 'tasks.jsonl').is_file()]\n",
    "    if _found:\n",
    "        DATA_DIR = _found[0]\n",
    "        break\n",
    "    _t.sleep(DATA_WAIT_INTERVAL_SECONDS)\n",
    "print(f'DATA_DIR resolved to {DATA_DIR}', flush=True)\n",
    *OLD,
]


def patch(folder: str) -> str:
    path = f"{folder}/evaluation.ipynb"
    with open(path) as handle:
        notebook = json.load(handle)
    hits = 0
    for cell in notebook["cells"]:
        source = cell["source"]
        lines = source if isinstance(source, list) else source.splitlines(True)
        if MARK in lines:
            return "already patched"
        for i in range(len(lines) - 1):
            if lines[i] == OLD[0] and lines[i + 1] == OLD[1]:
                cell["source"] = lines[:i] + NEW + lines[i + 2 :]
                hits += 1
                break
    if hits != 1:
        raise SystemExit(f"{folder}: expected the data-wait lines exactly once, found {hits}")
    with open(path, "w") as handle:
        json.dump(notebook, handle, indent=1)
    return "patched"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for arg in sys.argv[1:]:
        print(arg, patch(arg))
