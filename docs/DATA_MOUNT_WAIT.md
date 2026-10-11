# Competition mount wait

The smoke4 kernel (single-v3 vs single-v4) failed twice in generated-notebook cell 3 with `FileNotFoundError` for `/kaggle/input/competitions/gemma-4-developer-agent/tasks.jsonl`. A CPU probe with the same competition, wheelhouse v30, and model sources found that path present, including `tasks.jsonl`. Earlier GPU runs worked. The likely cause is a late or empty competition mount on some workers, not a new layout.

Cell 3 is our payload cell (`_pair_payload_cell` in `src/gemma_lab/notebook.py`), not leftover official-starter text. It still uses that same path and `load_tasks`. Before the read it polls `DATA_DIR / 'tasks.jsonl'` every `DATA_WAIT_INTERVAL_SECONDS` (5) for up to `DATA_WAIT_TIMEOUT_SECONDS` (300).

The ready check follows `load_tasks` on swegemma 0.2.10 and 0.2.11. Blank and whitespace-only lines are skipped. A final newline is not required, so a complete file, a file that ends in two newlines, a blank line in the middle, and a whitespace-only last line can all be ready. A non-blank line must `json.loads` to a JSON object. A number, array, string, or other JSON value is `unparseable`. A last non-blank line that does not parse is `truncated` (the writer may still be appending). An earlier line that does not parse is `unparseable`. A missing file is `missing`. A zero-length file, or one with only blank lines, is `empty`.

That parse is not enough on its own. The size must be unchanged across two consecutive polls, so a half-written file whose last line happens to parse is not accepted at once. There is no instant path and no mtime shortcut. A file that is already valid and stable therefore waits one interval, about 5 seconds, and `data_wait_seconds` records that wait rounded to one decimal (about `5.0`, not `0.0`). Each waiting line names the reason: `missing`, `empty`, `still changing`, `truncated`, or `unparseable`. The first miss is logged, then about every `DATA_WAIT_LOG_EVERY_SECONDS` (30).

On timeout the cell runs `ls -la /kaggle/input /kaggle/input/competitions` and `find /kaggle/input -maxdepth 4 -name tasks.jsonl`, each with a subprocess timeout, and writes that text to `/kaggle/working/data_mount_probe.txt` before raising `FileNotFoundError`. The error names the last check, including `empty`, `truncated`, and `unparseable`. The wait is merged into `/kaggle/working/run_manifest.json` as `data_wait_seconds` and copied onto the in-kernel pair manifest.

`path.stat()` and the following read run on a daemon thread. `DATA_READ_TIMEOUT_SECONDS` is 10. If that thread is still running when the join times out, the poll counts as not ready (`unreadable`) and the wait continues. A thrown exception is the same. The abandoned thread is a daemon, so it does not keep the kernel alive.

The wheelhouse cell (notebook cell 1, official starter plus the empty-wheelhouse fallback) globs `WHEELHOUSE_DIR` immediately. The server cell (notebook cell 5) passes `MODEL_PATH` (`/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`) straight into model setup. Those are directory mounts, not this file check, so they do not use this wait. A real Kaggle mount delay was not reproduced here.

## pair-report protocol hash

`gemma-lab pair-report` checks `protocol_sha256` on a stored `pair_manifest.json` against the protocol file hash (`load_protocol` `_sha256` of the raw file bytes). Three smoke protocols share schedule hash `31398c6c…`, so a schedule match is not enough: an old smoke2 manifest fed to the think256 protocol used to print a report under the wrong protocol. A differing hash is a `ValueError` that names both hashes. The CLI turns that into exit 1 with `Error:` on stderr, no traceback, and no report file.

The hash is the raw protocol bytes. A comment, an extra trailing newline, or a CRLF rewrite changes it even when the YAML meaning does not. The first paired run, `gemma4-paired-v5-vs-single-v1-dev13-r1`, is in that state. `--allow-protocol-mismatch` keeps the report: both hashes are printed on stderr and the same warning is the first text in the report header (`pair_report.md` and `protocol_mismatch_warning` in `pair_report.json`). Without the flag the command still refuses.

This checkout has no stored real `pair_manifest.json`. The report fixtures in tests omit `protocol_sha256`. A manifest that lacks the field, or has it blank, still reports, with a warning that older runs are accepted without that check.
