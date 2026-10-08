# Verified competition contract

Reviewed October 6, 2026 using the [overview](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview), [rules](https://www.kaggle.com/competitions/gemma-4-developer-agent/rules), [data description](https://www.kaggle.com/competitions/gemma-4-developer-agent/data), official starter notebook, and downloaded `data/competition/HARNESS_README.md`. Recheck announcements before a submission; organizers may update these requirements.

| Constraint | Current requirement |
| --- | --- |
| Submission | `submission.zip`, `agent.yaml` at archive root |
| Evaluation | Fraction of issues whose generated patches pass fresh verification |
| Model | `gemma-4-31b-it-qat-w4a16-ct` for every evaluated agent |
| Runtime | Offline, four NVIDIA L4s, 96 GB aggregate GPU memory |
| Total patch-generation time | 12 hours including sandbox setup; verification excluded |
| Per-task budgets | Optional `evaluation` overrides in `eval_config.yaml` |
| Archive size | Less than 3 GiB unpacked, including adapters |
| Allowed file types | `.yaml`, `.yml`, `.md`, `.txt`, `.py`, `.json`, `.safetensors` |
| Context ceiling | 32,768 tokens; budget reasoning and output together with prompt/history |
| LoRA | PEFT adapter directories; starter serving supports rank <=128 and up to eight loaded adapters |
| Tools | Nine harness tools, declarative AgentTools, sandboxed ADK skills |
| Submission allowance | One per day; up to two final selections |
| Team size | Up to five |

Deadline times are 23:59 UTC, corresponding to 3:59 PM Pacific Standard Time on these dates:

- Optional paper: November 12, 2026.
- Entry and team merger: November 25, 2026.
- Final submission: December 2, 2026.

The prediction prizes total $65,000 ($37,000 / $18,000 / $10,000). A separate optional [paper track](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper) offers $35,000. It is a useful portfolio opportunity, with its own submission process.

The 129 public tasks contain `patch` and `test_patch`; neither is agent input. The repository distribution is FastAPI 67, Rich 48, Requests 13, HTTPX 1. The hidden tasks come from private repositories; leaderboard tuning alone is a weak generalization strategy.

Code sharing during the competition must follow the rules: do not privately share with other teams; if publishing competition code, also share it through the competition forum or notebooks. The owner requested this GitHub handoff release and will add the Kaggle sharing notebook later; that step is pending. Competition data must not be redistributed to people who have not accepted the rules. The new toolkit code uses Apache 2.0; third-party assets retain their own licenses.

The downloaded sample uses placeholder LoRA files and an analyzer AgentTool. Our baseline uses no adapter and no delegation, providing a simpler comparison point. The real harness accepts plain tool-name strings, rather than standard ADK's broader import-capable tool syntax.
