# structured-v21

Unevaluated single-agent candidate. The directory is `agents/structured-v21`.
The agent name is `structured_v21`. Evaluated candidates were not modified.
No score is claimed.

## Provenance

The files started from the public notebook
`gemma-4-baseline-lb-0-24` (author-stated public score 0.24, not reproduced
here). That notebook says its `agent.yaml`, sampling, and `eval_config.yaml`
were copied from `flexonafft/gemma-4-budget-aware-coding-agent-v2`. Rebuilding
that notebook's zip in this workspace produced SHA-256
`205a677fdcbd122f50ac3138b1cda0403aeb625453c93edf4c53b7b691926186`.
That hash is the unmodified bundle, not this candidate.

## Hypothesis

Keeping the bundle's single agent, thinking budget 4096, temperature 0.2,
8192 output tokens, `edit_file`, and the 28-call / 8-minute cap, then
unregistering the three graph tools, using the heredoc only after `edit_file`
fails once, forcing an edit if the diff is still empty around call 18, grepping
tests in the first search, and compiling plus running the target test on the
final command, should cut empty diffs and untested syntax breaks. No score is
claimed. The 0.24 figure is the bundle author's stated score.

## Archive

SHA256: `see docs/STATUS.md and the pull request`

```bash
uv run gemma-lab pack agents/structured-v21 --output /tmp/structured-v21.zip
```
