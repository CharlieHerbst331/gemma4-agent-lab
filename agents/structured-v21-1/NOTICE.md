# Notice

This directory is a derivative of the public notebook
`gemma-4-baseline-lb-0-24` by verracodeguacas. That notebook states that its
`agent.yaml`, sampling config, and `eval_config.yaml` were copied from
`flexonafft/gemma-4-budget-aware-coding-agent-v2`.

The public-ideas audit reports the Budget-Fit public lineage under the
Apache License, Version 2.0. The rebuilt notebook zip did not contain an
upstream LICENSE file, so that report is unverified here. `LICENSE.txt` in
this directory is the Apache License, Version 2.0, included so a recipient
of this archive has the licence that report names and the licence that
covers this lab's own changes.

Changes from the notebook bundle: the agent was renamed, the three graph
tools and `write_file` were removed, and `prompts/system.md` was edited.
`configs/sampling.yaml` and `eval_config.yaml` are unchanged from that
bundle. Sampling stays temperature 0.2, top_p 0.95, max output 8192,
thinking budget 4096. The cap stays 28 tool calls and 8 minutes.

Gemma 4 Agent Lab changes are copyright 2026 Charles Herbst and are
licensed under the Apache License, Version 2.0.
