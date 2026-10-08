# Harness and execution contract

This is our implementation summary, not a redistribution of the official harness.
The authority is the [competition](https://www.kaggle.com/competitions/gemma-4-developer-agent)
and the HARNESS_README/official starter obtained through authorized Kaggle access.

## Layers

| Layer | Responsibility | Source |
| --- | --- | --- |
| Submitted agent | Declarative ADK tree, prompts, sandboxed skills | agents/* |
| Official execution | Compile schema/model, serve Gemma, sandbox tools, budgets | External swegemma/adk-submission/adk-eval-core/google-adk/vLLM |
| Official verification | Fresh sandbox applies patch and grading tests | External official evaluator; labels never agent input |
| Controller | Package/hash, adapt starter, choose frozen cohort, collect/compare, checked uploader | src/gemma_lab |
| Local unit tests | Trusted synthetic fixtures; never benchmark task repositories | tests/ |

Measured worker:4×NVIDIA L4,TP4; model gemma-4-31b-it-qat-w4a16-ct.
Measured versions:swegemma0.2.7,adk-submission0.2.12,adk-eval-core0.1.0,
google-adk1.36.1,vLLM0.19.1. General newer ADK documentation does not override the
competition's locked declarative compiler. Mac environment is locked by uv.lock;
GPU packages and model weights stay on the worker.

## Submitted files and tools

agent.yaml at archive root; YAML sub-agent references/includes, Markdown prompts,
optional sandboxed skills. No host Python agent entrypoint/custom tool imports.
Single declared base model; no adapters currently. Unpacked submission under3GiB.
Official tools:run_command,read_file,edit_file,write_file,get_status,submit_patch,
search_similar_code,get_code_neighbors,get_code_subgraph. Candidate subsets restrict
capabilities. Supported SkillToolset adds official discovery/loading/script tools;
Python scripts live only under skill resources and execute in the official sandbox.

File tools resolve within /workspace, so scratch /tmp files use shell/skill execution.
Never modify root pytest.ini/conftest.py. Scratch/repro files outside /workspace avoid
fallback patch contamination. Repository tests may be reset by fresh verification.

## Budgets and finalization

Current development variant:10min shared task clock,80 counted tools,60 turns,
300s per-command cap bounded by remaining task time. Skills have additional scoped
limits (e.g.1–30s repro subprocess). Prompt handoff deadlines are not hard quotas.
get_status/submit_patch do not consume counted tool allowance. submit_patch captures
the patch and ends execution after the response; use it last after real verification.
If not invoked, the official runner can extract a fallback diff. That can pass
fresh grading even when no verifier ran, and can include scratch/debug/test edits.
Do not equate fallback success with protocol compliance.

The competition-wide generation allowance is12hours including sandbox setup and
excluding grading. The per-task agent clock starts after setup. A10minute ceiling
is useful for development but needs measured averages/setup before promotion.

## Controller fidelity and known limitations

Notebook generation preserves official offline wheel setup, model serving/parsers,
context cache/compaction and evaluator; embeds a deterministic hash-pinned candidate;
records hardware/package/task provenance, incremental results and diagnostics. It
adds alternate wheelhouse mount discovery. It does not change grading semantics.

Current failure summaries classify known time/turn exhaustion and one known fixture
failure. They do not fully represent simultaneous failures: a timed-out task can also
have missing test dependencies. Raw outcomes stay immutable; diagnosis sidecars/docs
correct interpretation. Public recorded error counts are not proof of healthy grading.

Current SkillToolset was verified on an official CPU SDK/executor with synthetic Git
fixtures. That proved tool exposure/script behavior, not model adoption. Generic
SubprocessSandbox defaults TMPDIR to the workspace; our CPU probe must explicitly
set external TMPDIR to match the real SWE worker and avoid false resource-file audits.

No hard stage scheduler guarantees verifier reach. Explicit output_key handoffs and
include_contents:none reduce carried history but can lose details omitted by triage.
No skill automatically certifies test relevance, implements a complete security
boundary, or guarantees the model selects it. Existing helper audit conservatively
blocks new untracked implementation files/test edits and requires manual review.
