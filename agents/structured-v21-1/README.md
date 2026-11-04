# structured-v21-1

Unevaluated single-agent candidate. The directory is `agents/structured-v21-1`.
The agent name is `structured_v21_1`. This is a copy of `agents/structured-v21`.
That directory was not modified. No score is claimed. No submission.

## Provenance and licence

The files started from the public notebook `gemma-4-baseline-lb-0-24` by
verracodeguacas (author-stated public score 0.24, not reproduced here).
That notebook says its `agent.yaml`, sampling, and `eval_config.yaml` were
copied from `flexonafft/gemma-4-budget-aware-coding-agent-v2`. Rebuilding
that notebook's zip in this workspace produced SHA-256
`205a677fdcbd122f50ac3138b1cda0403aeb625453c93edf4c53b7b691926186`.
That hash is the unmodified bundle, not this candidate.

The public-ideas audit reports that lineage under the Apache License,
Version 2.0. An upstream LICENSE file was not in the rebuilt notebook zip,
so the report is unverified here. This archive includes that licence in
`LICENSE.txt` and the attribution in `NOTICE.md`. This lab's edits are
Apache License 2.0 as well.

## Hypothesis

Keeping the bundle's single agent, thinking budget 4096, temperature 0.2,
8192 output tokens, and the 28-call / 8-minute cap, then unregistering
`write_file` and the three graph tools, refusing `pytest.ini` and `tox.ini`
in the heredoc, and dropping the documentation-tree hint, should stop one
path that writes graded extra files without shortening the cap. No score is
claimed. The 0.24 figure is the bundle author's stated score.

Submission is not ready. The 12 hour gate is unproven for this cap. See
`docs/STATUS.md`.

## Archive

SHA256: `cefbcfe540ad99c0a24f6face5ea0edd40dc19166b838536a1ed2930d53e0291`

The hex above is the `gemma-lab pack` digest of this directory when that
hex is 64 zeros. Restore the zeros and pack again to recompute it. The
digest of the zip that contains the hex, which is the submission archive,
is in `docs/STATUS.md` and the pull request. This file is inside that zip,
so those two digests differ.

```bash
uv run gemma-lab pack agents/structured-v21-1 --output /tmp/structured-v21-1.zip
```
