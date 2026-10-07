# Initial implementation evidence

All evaluations below use the official starter/swegemma harness on four NVIDIA L4s.
The Mac only packages and controls jobs. Holdout has not been evaluated.

| Candidate | Cohort | Resolved | Important caveats |
| --- | --- | --- | --- |
| Baseline smoke B0 | Starter's two train IDs | 0/2 | Context error and timeout; infrastructure check only |
| Baseline | Fixed dev3 | 0/3 | Three agent timeouts; Requests verification fixture errors |
| Initial AgentTool v1 | Same dev3 | 1/3 | Two timeouts; Requests scratch/debug pollution; not submitted |
| Shorter AgentTool R1 | Same dev3 | 0/3 | Three timeouts; no investigator dispatched |
| AgentTool R1 | Full frozen dev14 | 3/14 | All wins FastAPI; ten budget failures; Requests fixture failure; Rich grading patch failed after agent test edit |
| Sequential v2 | Unaffected dev2 pilot | 1/2 | No reported runner errors; no patch pollution; FastAPI used fallback patch capture |
| Sequential v2 | Full usable dev13 | Pending | Requests excluded prospectively for known official fixture error |

The dev3 IDs are `fastapi_11194`, `requests_7502`, `rich_3105`. The unaffected pilot
keeps FastAPI/Rich IDs. Dev13 contains every ID from the frozen dev partition except
`requests_7502`. These are different cohorts: do not compare their rates as paired
performance improvements. On the identical unaffected pilot, baseline resolved 0/2
versus v2's 1/2, one win and no regression. Bundled architecture, sampling, prompt,
and budget changes prevent attributing that win to a single component.

Requests diagnostics show recursive dependency in the official `httpbin` fixture,
so Requests patch correctness is inconclusive. Raw official rows/results remain
unchanged in ignored run directories. Older summaries omitted returned runner errors
or mislabeled turn-budget exhaustion. The checked uploader now reads diagnostics
and distinguishes budget failure from grading errors; it preserves grading errors
when a task also times out. Changes to repository tests remain an agent behavior
failure even when the grader subsequently reports patch application problems.

The v2 smoke resolved FastAPI with a 993-character implementation patch and left
Rich unchanged because its issue contains only a historical issue number. All three
roles executed, but localization still exceeded the prompt's soft exploration cap.
Successful verification in the fresh official sandbox establishes that one patch's
correctness; it does not establish generalization or reliable explicit submission.

Exact archives, task IDs, source checksums, package versions, hardware, trace audits,
and comparisons are recorded under `runs/experiments/simple-v1` and `runs/kaggle`.
See STATUS.md for the currently selected archive and actual submission state.
