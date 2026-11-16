# v4/ai-observability (lane C8: AgentOps and observability)

Owner: AI reference-implementation lane `observability`. Base: `origin/v4-on-main`. Purpose: an agent run (Strands/LangGraph/boto3) emits
OTLP spans supervisor -> sub-agent -> tool -> model; they appear in X-Ray, CloudWatch Logs (+ Logs Insights) and CloudWatch metrics, and
AgentCore Evaluations score runs against a golden set. Real boto3 clients throughout.

## What was added
| Piece | File | Notes |
|---|---|---|
| OTLP -> X-Ray / Logs / Metrics fan-out | `core/otel_bridge.py` | hooks the existing `/_obs/v1/traces\|logs` receiver (observability_core); rebuilds each trace from all stored spans (children arrive before parents) |
| OTLP protobuf decode | same | uses `opentelemetry-proto` + protobuf when importable (Mesh); Nano stays OTLP/JSON |
| Logs Insights over JSON | `core/logs_core.py` | JSON field auto-discovery (dotted paths), `stats count/sum/avg/min/max/count_distinct/pct/stddev ... by f, bin()`, numeric-aware `sort`, dotted `filter` fields |
| X-Ray control plane | `core/xray_admin_core.py` | groups, sampling rules (Default protected), GetTraceGraph, GetTimeSeriesServiceStatistics, trace retrieval, tags, resource policies, encryption, trace-segment destination (XRay/CloudWatchLogs), indexing rules |
| X-Ray service graph | `core/xray_core.py` | edges now include nested remote/aws subsegments |
| AgentCore Evaluations | `core/agentcore_eval_core.py` | CreateEvaluator/Get/List/Update/Delete + data-plane `Evaluate`; 13 built-in evaluator ids |
| Shared edits | `core/aws_wire_router.py` (+9 lines: /_obs bridge hook, evaluator route before `agentcore_dispatch`), `wasm/build_cores.py` (3 module names), `wasm/core/*` regenerated |

Mapping: span per service.name = X-Ray segment; same-service child = subsegment; cross-service child = `remote` subsegment on the caller +
segment with `parent_id`; gen_ai `chat` = `bedrock-runtime` aws subsegment; `execute_tool` = remote subsegment named after the tool.
Logs: one JSON event per span in group `aws/spans`. Metrics namespace `Bedrock-AgentCore`: Invocations/Latency/Errors (dim Service,AgentName),
ModelInvocations/ModelLatency/ModelErrors/InputTokenCount/OutputTokenCount (Service,ModelId), ToolInvocations/ToolLatency/ToolErrors (Service,ToolName).

## OSS choices
| Need | Chosen | License / size | Substrate | Why / limit |
|---|---|---|---|---|
| OTLP wire format + GenAI semantic conventions | OpenTelemetry (opentelemetry-proto, python SDK in tests) | Apache-2.0; proto pkg 70 KB | Mesh (protobuf), Nano (JSON) | existing receiver reused; no tracing backend written |
| Trace store | existing observability_core span store + xray trace bag | n/a | both | already persistent on both substrates |
| Logs Insights | extended the existing CWLI evaluator (stdlib) | n/a | both | DuckDB-wasm/SQLite rejected: CWLI is not SQL (needs a translator anyway), DuckDB-wasm is multi-MB; honest limit: no `parse`, `dedup`, `unnest`, `fields ... as` |
| Evaluation metrics | token-F1 + `llm_core.embed` cosine + trajectory/assertion matchers + `llm_core.chat` LLM-as-judge | n/a | both (judge needs a model) | ragas/deepeval pull heavy deps (pandas/langchain); not used |

## Tests
`PYTHONPATH=. python3 tests/conformance/test_ai_observability.py` (probe venv; add `opentelemetry-proto` on PYTHONPATH for the protobuf leg): 40/40 with
real OTel SDK spans (three services, W3C propagation) and boto3 xray/logs/cloudwatch/bedrock-agentcore(-control). Uses a temp
`CLOUDLEARN_STATE_FILE`.

## Probe before -> after (routed %)
xray 18.4 -> 97.4 (7 -> 37 of 38); bedrock-agentcore-control 17.7 -> (+4 evaluator ops; Create/Evaluate show as probe_error because the
probe cannot build their required nested params, they are covered by the real-client test); logs, cloudwatch unchanged (46.0 / 76.1: the
unserved ops are outside this slice).

## Declared limits / open issues
- StartBatchEvaluation / online evaluation configs / code-based (Lambda) evaluators: not implemented (Evaluate takes spans inline).
- Judge-style scoring needs a reachable model (Mesh llama.cpp, Nano WebLLM bridge); without one the evaluator falls back to the deterministic
  metric and says so in `explanation`. A <1 GB/3B model is a toy judge.
- X-Ray: no insights generation, no adaptive sampling. Spans are stored in the capped OTLP store (MAX_SPANS); X-Ray trace cap 1000.
- Nano: pure Python and mirrored to `wasm/core`, but NOT browser-verified; browser OTLP exporters must use the JSON encoding.
- Real AgentCore also writes runtime logs to `/aws/bedrock-agentcore/runtimes/<id>-<endpoint>/runtime-logs`; only OTLP log records go there here.
