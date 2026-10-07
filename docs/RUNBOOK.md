# Operational runbook

## Account and environment

The repository is `CharlieHerbst331/gemma4-agent-lab` and the Kaggle account is `charlesaherbst`. Run `uv run gemma-lab doctor --online` to verify access without printing tokens. Authentication is managed by the Kaggle CLI. Its token lives outside the repo at `~/.kaggle/access_token` with mode 0600. Refresh through `uv run kaggle auth login` or Kaggle Settings if needed.

The Mac controls experiments and packaging. It has no NVIDIA GPU or Docker runtime and limited free disk. Do GPU/harness execution on a disposable Kaggle worker. The official starter uses subprocess sandboxes there; do not run untrusted task repositories as subprocesses on your personal Mac. Use Docker for evaluation on a separate Linux worker when available.

## One experiment cycle

1. Read the latest rules/discussion and save a research snapshot.
2. Choose one hypothesis from RESEARCH.md. Copy the baseline directory and record it using `docs/templates/EXPERIMENT.md` in an ignored run folder.
3. Freeze a dev cohort. `configs/splits/public-v1.json` has 95 train, 14 dev, and 20 holdout tasks. Groups share `(repo, base_commit)` so duplicated snapshots cannot cross splits. Optionally create a leave-repository-out split using `gemma-lab split --holdout-repo` for stronger transfer evidence. A one-task repository cannot support a useful stand-alone estimate.
4. Export agent inputs with `export-tasks`; use the explicit `--with-labels` option only for grading/training artifacts. The official harness retains full labels for verification, but builds the agent prompt from issue fields.
5. Package, generate a private offline notebook, and run the same task IDs as the baseline. Inspect all infrastructure failures separately from agent failures.
6. Pull outputs into a unique run directory. Summarize, compare paired wins/regressions, inspect patches and traces, and update the experiment record.
7. Evaluate a promising candidate on a larger fixed dev cohort. Check total task generation plus setup fits the 12-hour competition budget; a six-minute agent budget across 120 tasks leaves no setup margin at the worst case. Adjust from observed timings before submitting.
8. Only send a candidate whose package is valid and whose completed evaluation supports the submission. Keep the best archive immutable with its manifest and comparison results.

## Large bundles and adapters

Small candidates are embedded in notebooks. For adapters over 5 MiB, stage and upload a private bundle dataset:

```bash
uv run gemma-lab pack agents/candidate --output artifacts/candidate/submission.zip
uv run gemma-lab upload-bundle artifacts/candidate/submission.zip \
  --owner charlesaherbst --slug gemma4-candidate-v1 \
  --output artifacts/datasets/candidate-v1 --execute
uv run gemma-lab notebook agents/candidate --owner charlesaherbst \
  --slug gemma4-candidate-v1 --bundle-dataset charlesaherbst/gemma4-candidate-v1
```

The dataset zip is named after its dataset slug. Notebook generation pins the entire archive hash, so a changed dataset cannot silently substitute a different candidate. For a dataset version update, use a fresh staging folder and `upload-bundle --version`. Private is the API default; this operation never requests a public dataset.

## Submission and recovery

`gemma-lab submit` validates the archive and prints a plan. `--execute --evaluation runs/candidate` requires matching archive provenance, complete task results, and no infrastructure errors. It checks server history, then holds a local file lock and reserves the UTC daily slot before uploading. Both successful uploads and uncertain network outcomes remain recorded in `runs/submissions.jsonl`.

If upload was interrupted, query `gemma-lab status`. Reconcile the local reserved row only after confirming the server did not receive a submission. Never blindly retry. Team submissions from another machine may consume the slot after the preflight check; Kaggle is the final authority. The toolkit does not select final submissions automatically.

`status --kernel owner/slug` reports the run state. Use the exact URL returned by Kaggle after push. `pull-output` downloads result files and logs. In a failed notebook, inspect the log before editing; the failure may be model access, GPU capacity, installation, schema compilation, sandbox setup, or inference.

For autonomous collection of one existing run, use `gemma-lab wait-run owner/slug --output runs/experiment`. It waits with a bounded timeout, downloads outputs and logs, and writes `collection.json` with any available metrics. It launches no new GPU job and creates no recurring schedule.

## Training

`training/prepare_data.py` accepts normalized chat trajectories with `instance_id`, `resolved`, and `messages`. It selects verified successes only from train IDs and deduplicates messages. Official ATIF traces require a deliberate normalization step; preserve tool-call IDs and distinguish thoughts, actions, and observations. Do not turn holdout/reference answers into agent instructions.

The optional `training/train_lora.py` masks all prompt tokens and trains assistant continuations. It drops overlength examples instead of truncating away their answers, saves safetensors adapters, and records data hashes and dependency versions. Install `training/requirements.txt` on a separate GPU environment. Start with a trainable, architecture-compatible Gemma 4 31B checkpoint on a suitable worker (typically an 80 GB or larger GPU for this unsharded BF16 recipe). The script does not provide distributed weight sharding and is not a four-L4 training solution. No paid hardware has been provisioned.

The quantized competition checkpoint is an inference target, not a presumed trainable checkpoint. Confirm tokenizer/chat-template, architecture, target-module, and LoRA compatibility by loading an exported adapter with the actual competition QAT model. This recipe has not been trained or GPU-validated. RL is deferred until stable evaluation and verified trajectory collection exist.

## Handoff state

Update STATUS.md with the last tested commit, current Kaggle URL/status, latest results, best archive hash, and next experiment. Keep the repo private until a deliberate portfolio release. Future sessions can execute this loop using the established authentication; no recurring automation is configured.
