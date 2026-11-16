# Branch: v4/ai-uiaws (Bedrock "Coming soon" pages, round 7)

- Owner: AI session (lane uiaws). Base: local `v4/ai-integration` (1e7125dcd). Not merged; pushed to `origin/v4/ai-uiaws` only.
- Purpose: finish the Bedrock console pages that showed "Coming soon": flows, automated-reasoning, guardrails, prompt-management,
  prompt-optimization, data-automation, evaluations, settings, model-access.

## Page -> backend

| Page | Built on | Notes |
|---|---|---|
| Guardrails (+ detail, versions, Test panel) | existing `core/bedrock_guardrails_core.py` | Create/Update/Delete, CreateGuardrailVersion, ApplyGuardrail from the Test panel (INPUT/OUTPUT, grounding source + query) |
| Prompt management (+ detail) | new thin store `core/bedrock_build_core.py` | CreatePrompt/Update/Get/List/Delete, CreatePromptVersion; draft + immutable versions; test run through the existing Converse path |
| Flows (+ detail) | new store + runner in `core/bedrock_build_core.py` | CreateFlow/Prepare/Version/Alias, InvokeFlow eventstream (also test alias `TSTALIASID` on the prepared draft) |
| Model evaluations (+ detail) | new, runs on the local-LLM seam like batch inference | CreateEvaluationJob/Get/List/Stop; per-record scores + `report.json` in S3 |
| Settings | new control-plane ops | Put/Get/DeleteModelInvocationLoggingConfiguration; delivery hook in the router writes S3 (gzip JSON, AWSLogs layout) and CloudWatch Logs |
| Model access | new GetFoundationModelAvailability over `ListFoundationModels` | all served models AUTHORIZED; no entitlement workflow |
| Advanced prompt optimization | new OptimizePrompt (eventstream) over the local model | meta-prompt rewrite |
| Automated Reasoning | not in scope | needs an SMT-solver pipeline; guardrails already reject `automatedReasoningPolicyConfig` |
| Data Automation | not in scope | needs managed multimodal extraction models; the local model is text only |

## OSS / thumb-rule record

| Piece | Choice | Why |
|---|---|---|
| Control-plane stores (prompts, flows, eval jobs, logging config) | plain dict records in the persisted account bag (pure Python, no dependency) | No OSS library implements Bedrock prompt/flow/evaluation control planes (moto has none). They are metadata; all behaviour runs on existing engines. Hand-built for that reason only. |
| Model calls (flows, evals, optimize) | existing `core/llm_core` seam (llama.cpp Mesh, WebLLM Nano) | no new backend |
| Evaluation scoring | token F1 (SQuAD style, ~20 lines), perturbation consistency, guardrail lexicon | simple OSS-style metrics; heavier scorers (BERTScore, rouge-score) need torch/numpy and are not pure Python for Nano |
| Log delivery | existing `core/s3_object_core`, `core/logs_core` | no new backend |
| Substrate | both. Pure Python, mirrored to `wasm/core` (`python3 wasm/build_cores.py`) | Nano replays the request for each async WebLLM call (`NeedAsync`), so evaluation jobs are stored only when finished and use a deterministic id |

## Wire shapes
bedrock-agent (`/prompts/`, `/flows/`), bedrock-agent-runtime (`/flows/{id}/aliases/{alias}`, `/optimize-prompt`), bedrock (`/evaluation-jobs`,
`/logging/modelinvocations`, `/foundation-model-availability/{id}`), all under signing name `bedrock`. Verified with real boto3 clients.

## Tests
- `tests/conformance/test_bedrock_build.py`: 30 checks (prompts, flows incl. InvokeFlow, evaluations, logging delivery to S3 and CloudWatch, availability, OptimizePrompt, guardrail create/version/apply/delete). 30 passed.
- `consoles/tests/smoke-aws-uiaws.mjs`: Playwright against the Nano preview (stub in-browser model registered with `vyomiRegisterLLM`).

## Declared limits
- Flows: node types Input, Output, Prompt (inline or managed prompt ARN), Condition (`==`, `!=`, `contains`, `true`), Collector. Lambda/KB/Agent/Lex/Storage/Retrieval/Iterator/loop nodes are rejected. No drag-and-drop canvas (nodes are shown in a table and edited as JSON). No execution tracing.
- Evaluations: automated model evaluation, custom prompt dataset only, at most 25 records, metrics Builtin.Accuracy (token F1), Builtin.Robustness, Builtin.Toxicity (lexicon). Not the managed scorers. Human, RAG and LLM-as-a-judge jobs rejected. Output layout is `report.json` + `<dataset>.jsonl`, not the managed layout.
- Prompt management: TEXT variants only; no chat variants, tools or comparison view; CMK ignored.
- Invocation logging: image/video/embedding delivery flags stored but not produced; no large-data overflow bucket.
- Model access: no agreement/entitlement workflow.
- OptimizePrompt: quality is that of the local model; optimization jobs over datasets are not simulated.

## Open issues
- Batch inference (pre-existing) is not replay-safe on Nano for the same reason evaluations needed the deterministic id.
- Breadcrumbs on Bedrock pages show "Amazon Bedrock" twice (existing pattern in the routes file, not touched).
