# Competition mount wait

The smoke4 kernel (single-v3 vs single-v4) failed twice in generated-notebook cell 3 with `FileNotFoundError` for `/kaggle/input/competitions/gemma-4-developer-agent/tasks.jsonl`. A CPU probe with the same competition, wheelhouse v30, and model sources found that path present, including `tasks.jsonl`. Earlier GPU runs worked. The likely cause is a late or empty competition mount on some workers, not a new layout.

Cell 3 is our payload cell (`_pair_payload_cell` in `src/gemma_lab/notebook.py`), not leftover official-starter text. It still uses that same path and `load_tasks`. Before the read it polls `DATA_DIR / 'tasks.jsonl'` every `DATA_WAIT_INTERVAL_SECONDS` (5) for up to `DATA_WAIT_TIMEOUT_SECONDS` (300). An empty or unreadable file is not ready. The first miss is logged, then about every `DATA_WAIT_LOG_EVERY_SECONDS` (30), and one line is printed when the file is ready, with the wait time. A file that is already there returns without sleeping.

On timeout the cell runs `ls -la /kaggle/input /kaggle/input/competitions` and `find /kaggle/input -maxdepth 4 -name tasks.jsonl`, each with a subprocess timeout, and writes that text to `/kaggle/working/data_mount_probe.txt` before raising `FileNotFoundError`. The wait is merged into `/kaggle/working/run_manifest.json` as `data_wait_seconds` and copied onto the in-kernel pair manifest.

The wheelhouse cell (notebook cell 1, official starter plus the empty-wheelhouse fallback) globs `WHEELHOUSE_DIR` immediately. The server cell (notebook cell 5) passes `MODEL_PATH` (`/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`) straight into model setup. Those are directory mounts, not this file check, so they do not use this wait. A real Kaggle mount delay was not reproduced here.
