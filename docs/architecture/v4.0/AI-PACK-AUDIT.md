# AI pack audit - Bedrock / Vertex AI / Azure AI on a booster-hosted local model

Status: AUDIT ONLY (2026-11-07), branch `v4/ai`. Nothing was built. Read from code at `origin/v4-on-main`.

Purpose reminder: the AI pack is for DEV TESTING of agents and apps (wire shapes, tool loops, streaming, error codes, token
accounting), not for model quality. Booster = 2-core / 32 GB CPU Codespace, no GPU, OpenAI-compatible endpoint from llama.cpp/Ollama.

## 0. How I verified

- Read: `core/llm_core.py`, `core/llm_runtime.py`, `core/ai_models_core.py`, `core/bedrock_agents_core.py`, `core/gcp_vertex_core.py`,
  `core/azure_cognitiveservices_core.py`, `core/azure_search_vector_core.py`, `core/aws_wire_router.py` (routing at ~L119, L340,
  L445, L1430, L1689-1706), `core/booster.py`, `wasm/booster-link.js`, `wasm/nano-boot.js` (L267+), `tests/conformance/test_local_llm_seam.py`.
- Probed: called the dispatchers directly (`bedrock_dispatch`, `vertex_dispatch`, `azure_openai_dispatch`) with a stub
  `llm_core` backend, using `../s3_simulator/.venv/bin/python`. This confirms request-validation behaviour and status codes
  below (marked "probed"). Disk was 52 GB free.
- NOT verified: no real boto3 / google-genai / openai SDK call over HTTP, no llama.cpp or Ollama run, no model speed
  measurement (all tokens/sec numbers in section 3 are estimates from general knowledge, not measured here), no booster
  end-to-end session. `core/capabilities/*/{bedrock,vertex-ai,cognitiveservices}.json` are console-capability maps; I did not
  audit them for wire parity. No Foundry agents/threads/runs code exists to read (grep found none).

## 1. Current architecture (what actually happens today)

Single seam: `core/llm_core.py` exposes `chat(messages, system, max_tokens, temperature, stop)` and `embed(texts)`. Every AI wire
adapter in `core/ai_models_core.py` calls it. Backend selection, first match wins (`llm_core.chat`, `_endpoint`):

1. `set_backend(fn)` - in-process Python callable (tests).
2. `set_async_backend(afn)` - Nano only: WebLLM via `vyomiRegisterLLM` / `vyomiEnableWebLLM` in `wasm/nano-boot.js` L267-300;
   requires WebGPU; goes through `llm_core.arun` because the browser engine is async (router L1430 wraps bedrock/gcp-aiplatform/az-openai).
3. OpenAI-compatible HTTP: `VYOMI_LLM_ENDPOINT` or default `http://vyomi-llm:8080` (urllib, offline substrate only). On Pyodide
   (`import js` succeeds) it returns no endpoint unless env is set, so Nano never reaches an HTTP model by default.
4. None -> `LlmUnavailable` -> Bedrock `ModelNotReadyException` 429 / Vertex `UNAVAILABLE` 503 / Azure `ServiceUnavailable` 503. No canned fallback (good). Embeddings fall back to a labelled feature-hash embedding (256-d).

`core/llm_runtime.py` starts one docker container `vyomi-llm` (llama.cpp `ghcr.io/ggml-org/llama.cpp:server`, default
SmolLM2-360M-Instruct Q8_0, `-c 2048 --embeddings`, refuses under 20 GB free disk). This is the offline path only.

Booster path today (`wasm/booster-link.js`): the Nano tab classifies calls as "compute" (`COMPUTE_SCOPE` includes
`bedrock|bedrock-runtime|bedrock-agent|bedrock-agent-runtime|sagemaker`; `COMPUTE_PATH` includes
`/publishers|/endpoints|/models`, `aiplatform`, `Microsoft.CognitiveServices|MachineLearningServices`) and forwards them to the
paired booster / portal relay. So the routing for AI calls to the booster ALREADY exists in the browser. The booster itself is the
offline appliance, so those calls land in the same `ai_models_core` and use steps 3-4 above. WebLLM is therefore only the
fallback when no booster is linked.

What must change to route to a booster-hosted llama.cpp/Ollama:

- Mostly configuration, not code: on the booster set `VYOMI_LLM_ENDPOINT` (llama.cpp `:8080` or Ollama `:11434`; both serve
  `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`) and start the model there. Today nothing starts `vyomi-llm` inside a
  booster session (no reference in booster boot code), and the Codespace is not necessarily a docker-compose host; decide
  sidecar container vs host process. (Not verified how the booster appliance is launched in the Codespace.)
- `llm_core.chat()` has no `tools`, no `stream`, no per-request model selection beyond the `model=` kwarg (which no adapter passes), no
  `response_format`, no `top_p`/`seed`. These must be added (section 2.0).
- Do NOT make the booster depend on WebLLM; keep WebLLM as the no-booster Nano fallback and make `status()` report which one answered.
- Model name leak: adapters ignore the requested cloud model id and answer with the one local model (documented honest limit). Keep, but surface the real model in a response header (e.g. `x-vyomi-local-model`) so tests can tell.
- Wire router resource gate: `booster.py` has a 50% "ai" RAM bucket (`AI_SHARE`, `memory_split_mb["ai"]`, about 11 GB of 32 GB at the 70% cap) but nothing calls `allocate("ai", ...)`; model load is not admitted against it (grep: only definitions).

## 2. Parity matrix

Legend: SERVED = works on the wire for text; PARTIAL = works with gaps; MISSING = 404/400 today. Status codes were probed unless noted.

### 2.0 Shared seam gaps (affect every cloud)

| Capability | State | Evidence |
|---|---|---|
| Tool/function calling through the seam | MISSING | `llm_core._norm_messages` flattens content to text and drops everything else; no `tools` param |
| True token streaming | MISSING (fake) | Adapters generate the whole reply then slice with `_chunks()`; llama.cpp `stream:true` not used; time-to-first-token is wrong for timeout/cancel tests |
| Per-request sampling params (top_p, top_k, seed, penalties, stop) | PARTIAL | only max_tokens, temperature, stop (max 4) |
| JSON / structured output (`response_format`, grammar) | MISSING | Azure rejects `json_schema` with 400; llama.cpp supports GBNF/json_schema natively |
| Usage accounting | PARTIAL | real counts from backend `usage` when present, else `len/4` estimate; no ledger/meter of tokens per space/account |
| Model registry per cloud id -> local model | MISSING | one model answers all ids |
| Concurrency / queueing | MISSING | `urllib` blocking call inside the request thread, no slot limit, 120 s timeout; llama-server default 1 parallel slot on 2 cores |
| Error injection (429 throttling, 5xx, context overflow) | MISSING | agents need to test retry paths; context-length overflow is not mapped to each cloud's error |

### 2.1 AWS Bedrock

| Feature | State | Detail / refs |
|---|---|---|
| ListFoundationModels / GetFoundationModel | SERVED | `ai_models_core.bedrock_dispatch` L187+; 12 static models (Claude 3/3.5/4, Titan, Nova, Llama, Mistral). No Claude 3.7/4.5 families, no Cohere/AI21/DeepSeek/gpt-oss/Pixtral |
| Inference profiles (list/get, `us.` ids in InvokeModel) | PARTIAL | `us./eu./apac./global.` prefixes and ARNs are stripped in `_resolve_model` so invoking works; `GET /inference-profiles` 404 (probed) so `list_inference_profiles` fails |
| Converse (text only) | SERVED | system, inferenceConfig (maxTokens, temperature, stopSequences), usage, metrics. Missing: `topP`, `additionalModelRequestFields`, `performanceConfig`, `guardrailConfig`, `promptVariables`, `requestMetadata` (accepted silently, ignored) |
| Converse tool use (`toolConfig`, `toolUse`, `toolResult`, `toolChoice`) | MISSING | 400 "toolConfig is not supported" and 400 on toolUse/toolResult blocks (probed). THE blocker for agents |
| Converse image/document/video blocks | MISSING | 400 (probed text-only guard) |
| ConverseStream | PARTIAL | real `vnd.amazon.eventstream` framing (CRC verified by test), events messageStart/contentBlockDelta/contentBlockStop/messageStop/metadata; fake streaming; no toolUse deltas (`contentBlockStart` with toolUse, `input` JSON fragments) and no `reasoningContent` |
| InvokeModel (Claude Messages body) | PARTIAL | text only; `tools` -> 400 (probed); no `tool_use`/`tool_result` blocks, no `thinking`, images |
| InvokeModel (Titan Text, Nova, Llama, Mistral bodies) | SERVED | `_bedrock_text_request` / `_bedrock_response`. Nova toolConfig in body not handled |
| InvokeModelWithResponseStream | PARTIAL | wraps the full JSON response in `chunk` frames (not the per-family incremental chunk format: Claude `content_block_delta` events, Titan `outputText` deltas) |
| Embeddings (Titan Embed v2) | SERVED | dims 256/512/1024, `normalize`/`embeddingTypes` ignored; Titan v1, Cohere Embed, Nova multimodal embeddings missing; vector comes from the local embedding model (padded/truncated to dims) or hash fallback |
| CountTokens | MISSING | `POST /model/{id}/count-tokens` 404 (probed) |
| ApplyGuardrail / Guardrails control plane / `guardrailConfig` | MISSING | 404 (probed); no `bedrock` guardrail store |
| InvokeModel async (StartAsyncInvoke), batch (`CreateModelInvocationJob`), prompt management, model evaluation, custom model import | MISSING | not routed |
| Knowledge Bases control plane + ingestion | SERVED | `bedrock_agents_core.py`: CreateKnowledgeBase/Get/List/Delete, data sources (S3), ingestion jobs; real chunk+embed; text-like files only; PDF/Office counted failed; vector store type ignored |
| Retrieve | SERVED | exact cosine kNN with S3 location and score (L300-375); filters supported via `vs.filter` (depth unverified) |
| RetrieveAndGenerate | SERVED | retrieve + `llm.chat` + citations (L380-401); only `KNOWLEDGE_BASE` type; no `EXTERNAL_SOURCES`; no streaming variant (`RetrieveAndGenerateStream`) |
| Agents control plane (CreateAgent, aliases, KB association, action groups, Prepare) | SERVED | stored faithfully; action groups stored only |
| InvokeAgent | PARTIAL | eventstream `chunk` with attribution; model is called once with KB passages (L487-535). Action groups never invoked (no tool-call emission), no `returnControl`, no `trace`, no `sessionState`/session memory beyond request, no `InvokeInlineAgent`, no multi-agent collaboration |
| AgentCore control plane (runtimes, gateways, targets) | SERVED | `agentcore_dispatch` L874+ |
| AgentCore Gateway MCP (initialize, tools/list, tools/call) | PARTIAL | Lambda targets really invoked (L867); openApiSchema/smithyModel/mcpServer targets registered but not callable |
| AgentCore InvokeAgentRuntime | MISSING (by design) | returns 424 `RuntimeClientError` (L892-896); no container runs. A booster could run it (agent container on the compute side) - see 4.6 |
| AgentCore Memory, Identity, Code Interpreter, Browser, Observability | MISSING | not found in `bedrock_agents_core.py` |
| SageMaker runtime `InvokeEndpoint` for a hosted open model | NOT AUDITED | `sagemaker` is classified compute in the link but I did not read a sagemaker adapter |

### 2.2 GCP Vertex AI

Routing: `aws_wire_router.py` L118 matches only `/v1(beta1)?/projects/*/locations/*/publishers/*/models/*:op`.

| Feature | State | Detail / refs |
|---|---|---|
| generateContent (text) | SERVED | `vertex_dispatch` L282+; models gemini-1.5/2.0/2.5 flash/pro; `generationConfig.maxOutputTokens/temperature/stopSequences` only; usageMetadata correct shape |
| streamGenerateContent | PARTIAL | JSON array or `alt=sse`; fake streaming (post-hoc chunks of 24 chars); usageMetadata only on last chunk (real API sends it on every/last, acceptable) |
| Function calling (`tools.functionDeclarations`, `functionCall`/`functionResponse` parts, `toolConfig`) | MISSING | 400 on `tools` and on any non-text part (probed) |
| Structured output (`responseMimeType`, `responseSchema`) | MISSING | ignored silently (worse than rejecting; JSON-mode agents would get prose) |
| systemInstruction | SERVED | |
| Multimodal (inlineData/fileData) | MISSING | 400 |
| Safety settings / `safetyRatings` / `promptFeedback` | MISSING | not emitted; agents that read `finishReason == SAFETY` cannot be tested |
| countTokens | PARTIAL | `len/4` estimate, not the model tokenizer; `totalBillableCharacters` ok |
| computeTokens | MISSING | |
| embedContent / `:predict` on text-embedding-00x, gemini-embedding-001 | SERVED | `taskType`, `outputDimensionality`, `title` ignored; `batchEmbedContents` not routed |
| Gemini Developer API (`/v1beta/models/...:generateContent`, `?key=`) | MISSING | 404 (probed). `google-genai` with `vertexai=False` (the default!) hits this path. Cheap to add as an alias |
| google-genai with `vertexai=True` + `http_options.base_url` | LIKELY OK | path form matches the regex; not verified with the real SDK |
| Custom-model / deployed endpoint `:predict`, `:rawPredict`, `:streamRawPredict`, `:chatCompletions` | MISSING (by design) | `gcp_vertex_core.py` L587 answers 501 UNIMPLEMENTED. For dev-testing, route a deployed Model Garden model (e.g. llama-3.1-8b-instruct deploy in catalog L88) to the local model |
| Endpoints / models / jobs control plane, Model Garden catalog | SERVED | `gcp_vertex_core.py` stored resources, LRO ops |
| Vector Search (indexes, indexEndpoints, findNeighbors) | SERVED | brute-force cosine |
| Agent Builder / Agent Engine (`reasoningEngines` create/query/streamQuery) | MISSING | grep: no `reasoningEngine`/`agent_engine` code at all |
| RAG Engine (`ragCorpora`, import files, retrieveContexts, `tools.retrieval.vertexRagStore`) | MISSING | no code; can reuse the Bedrock KB chunk+embed+kNN engine |
| Grounding with Google Search / Vertex AI Search datastore | MISSING | not expected for dev testing; reject with a clear error |
| Context caching, tuning (`tuningJobs` exist as control plane), batch prediction | CONTROL PLANE ONLY | resources stored; do not run |
| OpenAI-compatible endpoint on Vertex (`/endpoints/openapi/chat/completions`) | MISSING | |

### 2.3 Azure OpenAI / AI Foundry

IMPORTANT: there are TWO Azure OpenAI implementations and they disagree.

- `ai_models_core.azure_openai_dispatch` (router L340 `/openai/...` -> real local model). Used when the SDK's `azure_endpoint` is the wire root.
- `azure_cognitiveservices_core.inference()` (L435+): deterministic `[SIMULATED by Vyomi - no real model ran] You said: ...`, with no
  LLM call, reached via ARM-proxy `.../accounts/{n}/openai/deployments/...` and the documented offline endpoint
  `/azure-data/openai/{account}/...` (returned by the account's endpoint metadata, L408). An SDK pointed at the endpoint the
  account advertises gets canned text, not the model. Two answers for the same deployment is a trap for agent testing.
  (I confirmed the path text; I did not confirm that `/azure-data/openai` is wired in the offline app in this checkout.)

| Feature | State | Detail / refs |
|---|---|---|
| Account/deployment control plane (ARM) | SERVED | `azure_cognitiveservices_core.py` models catalog (gpt-4o, 4.1, o1, o3-mini, embeddings, dalle, whisper), deployments, RAI policies, keys |
| chat/completions (text, non-stream) | SERVED | `azure_openai_dispatch`; `api-key`/`Authorization` required, DeploymentNotFound, OperationNotSupported mapping, `/openai/v1` with `model` in body |
| chat/completions streaming | PARTIAL | proper SSE with `[DONE]`; fake streaming; `stream_options.include_usage` not honoured (probed: no usage chunk); no `prompt_filter_results`/`content_filter_results` |
| Tools / function calling, `tool_choice`, parallel tool calls | MISSING | 400 (probed) |
| JSON mode / `response_format` json_schema | PARTIAL/MISSING | json_schema rejected 400; `json_object` silently ignored |
| `completions` (legacy) | SERVED | |
| embeddings | SERVED | `dimensions` honoured by truncate+renorm; `encoding_format=base64` not handled (unverified) |
| `/openai/v1/responses` | MISSING | falls into chat path and returns 400 "'messages' required" (probed). `openai` SDK `responses.create` against Azure v1 endpoint breaks |
| Assistants / threads / runs (`/openai/assistants`, `/threads`, `/runs`) | MISSING | 404 (probed); the classic Azure OpenAI assistants path |
| Azure AI Foundry Agent Service (`azure-ai-projects` / `azure-ai-agents`: agents, threads, messages, runs, tools, vector stores, files) | MISSING | no code; capability flag "assistants" exists only as model metadata. Protocol is assistants-like, one engine can serve both |
| Foundry project endpoint (`https://{acct}.services.ai.azure.com/api/projects/{p}`) data plane, connections, evaluations | MISSING | ARM `_projects` bag exists (cogsvc L270), no data plane |
| AI Search vector/hybrid + integrated vectorization | SERVED | `azure_search_vector_core.py`; embedding via local seam, dims padded/truncated; no semantic ranker, no agentic retrieval, no HNSW |
| "On your data" (`data_sources` in chat/completions) | MISSING | |
| Content filtering / `finish_reason: content_filter` | MISSING | |
| Rate limiting (`429` + `Retry-After`, TPM quotas from deployment capacity) | MISSING | quota number stored on deployment, never enforced |

### 2.4 Tool-call format translation (the core of the pack)

llama.cpp `llama-server` with `--jinja` (and Ollama) accept OpenAI `tools` and return `choices[0].message.tool_calls[]` with
`function.name` and JSON-string `function.arguments`, `finish_reason: "tool_calls"`. Streaming returns `delta.tool_calls` fragments.
Proposed seam change: `llm_core.chat(..., tools=None, tool_choice=None)` returns `{text, tool_calls:[{id,name,arguments(dict)}], finish_reason}` and
one translator module per cloud:

| Cloud | Request side (cloud -> OpenAI) | Response side (OpenAI -> cloud) |
|---|---|---|
| Bedrock Converse | `toolConfig.tools[].toolSpec{name,description,inputSchema.json}` -> `tools[].function{parameters}`; assistant `toolUse{toolUseId,name,input}` -> assistant `tool_calls`; user `toolResult{toolUseId,content[]/status}` -> `role:tool` message; `toolChoice{auto,any,tool}` -> `auto`/`required`/named | `content:[{toolUse:{toolUseId,name,input:obj}}]`, `stopReason:"tool_use"`; stream: `contentBlockStart{start.toolUse}` + `contentBlockDelta{delta.toolUse.input: "<json fragment>"}` |
| Bedrock InvokeModel (Claude) | `tools[].input_schema`, `tool_use`/`tool_result` blocks | `content:[{type:"tool_use",id,name,input}]`, `stop_reason:"tool_use"`; stream: `content_block_start`, `input_json_delta` |
| Vertex Gemini | `tools[].functionDeclarations`, `toolConfig.functionCallingConfig.mode` AUTO/ANY/NONE, `functionResponse{name,response}` parts | `parts:[{functionCall:{name,args:obj}}]` (args is an object, no ids), `finishReason: STOP` |
| Azure OpenAI | near pass-through (same shape), plus Azure extras | `message.tool_calls`, `finish_reason:"tool_calls"`; stream `delta.tool_calls[index]` fragments |

Reliability caveat: a 1.5-3B model emits malformed or hallucinated calls more often. The translator must (a) validate arguments
against the schema and return valid JSON always; (b) if llama.cpp returns plain text for a forced `tool_choice`, use a GBNF
grammar (llama.cpp builds one from the tool schemas under `--jinja`) rather than faking a call.

## 3. Model recommendation for a 2-core / 32 GB CPU booster

Memory budget: the AI bucket is about 11 GB (70% cap x 50% AI share, `booster.py` L286). A single 3-4B Q4 model plus KV cache
fits easily; a 7B Q4 (about 5 GB) fits; two loaded models fit if small. CPU, not RAM, is the constraint. All speeds below are
rough ESTIMATES for 2 vCPU AVX2, llama.cpp, Q4_K_M, short context - NOT measured here; measure on a real booster before promising anything.

| Role | Model (GGUF) | Size | Est. gen speed | Est. prompt eval | Use |
|---|---|---|---|---|---|
| Default tool-calling agent | Qwen2.5-3B-Instruct Q4_K_M | ~2.0 GB | 4-7 tok/s | 25-60 tok/s | best small-model tool-call behaviour under llama.cpp `--jinja` in my experience; recommended default (unverified on this stack) |
| Fast / smoke tests | Qwen2.5-1.5B-Instruct Q4_K_M or Llama-3.2-1B-Instruct Q4_K_M | ~1.0 / 0.8 GB | 10-18 tok/s | 60-120 tok/s | CI-style runs; tool calls flakier |
| Higher fidelity (opt-in) | Qwen2.5-7B-Instruct Q4_K_M (or Llama-3.1-8B Q4_K_M) | ~4.7 GB | 1.5-3 tok/s | 8-20 tok/s | slow; a 6-step agent loop with 500-token prompts would take minutes |
| Embeddings | nomic-embed-text-v1.5 (768-d, 274 MB) or bge-small-en-v1.5 (384-d, ~130 MB) | small | 100s of short docs/min | n/a | replaces the hash fallback; keep dimension padding to the cloud's declared dims |
| Current default | SmolLM2-360M-Instruct Q8_0 | ~380 MB | 25+ tok/s | fast | too weak for tool calling; fine for plain chat plumbing |

Honest limits:

- On 2 cores, prompt processing dominates agent loops: each turn re-sends the whole history (system + tool schemas + prior calls).
  Expect 5-30 s per agent step on a 3B model; enable llama.cpp prompt caching (`--cache-reuse`, keep slot per session) and keep `-c` at 4096-8192.
- One parallel slot realistically (`-np 1`); concurrent agents queue. Return cloud-correct 429/ThrottlingException when the queue is full rather than hanging.
- Tool-call accuracy of 1-3B models is mediocre; multi-tool parallel calls and deeply nested schemas will often fail. Good enough to test
  that YOUR code handles tool_use/toolResult loops, retries and malformed-call recovery; not good enough to test agent task success.
- Reasoning/thinking blocks, vision, long context (>8k), and 100k-token docs are out of scope. Do not claim parity for these.
- Context overflow must map to each cloud's real error (Bedrock ValidationException "Input is too long", Vertex INVALID_ARGUMENT, Azure `context_length_exceeded`).

## 4. Prioritised build plan (ordered by what a tool-calling agent needs first)

Effort in agent-days for one focused agent with the existing test harness (`test_local_llm_seam.py` pattern). "Parallel" = independent after item 1.

| # | Item | Why now | Effort | Depends | Parallel? |
|---|---|---|---|---|---|
| 1 | Seam v2 in `llm_core`: `tools`/`tool_choice`/`response_format`/sampling pass-through, real upstream streaming (generator), usage return, per-request model, context-overflow error, queue/slot limit + throttle error, token meter hook (see 4.7). Add OpenAI-style tool-call normalisation and schema validation. Keep sync + async (Nano) paths working | everything below needs it | 3-4 | none | no (foundation) |
| 2 | Bedrock Converse + ConverseStream tool use (toolSpec, toolUse, toolResult, toolChoice, stream toolUse deltas, `stopReason: tool_use`), `topP`, `requestMetadata`, usage | most common Bedrock agent loop (boto3 `converse`, Strands, LangGraph) | 3 | 1 | yes (AWS agent) |
| 3 | Azure chat/completions tools + `tool_choice` + streaming `tool_calls` deltas + `stream_options.include_usage` + `json_object`/`json_schema` + 429/Retry-After; ALSO unify the duplicate simulated path (`cogsvc.inference`/`/azure-data/openai`) onto `azure_openai_dispatch` | OpenAI SDK agents; fixes the canned-text trap | 2-3 | 1 | yes (Azure agent) |
| 4 | Vertex generateContent/stream function calling (functionDeclarations, functionCall/functionResponse parts, ANY/AUTO/NONE), `responseSchema`/`responseMimeType`, safety fields, plus Gemini Developer API alias `/v1beta/models/*` so default google-genai works | google-genai agents / ADK | 3 | 1 | yes (GCP agent) |
| 5 | Real streaming end to end for all three (Bedrock eventstream incl. InvokeModelWithResponseStream per-family chunks, Vertex SSE, Azure SSE) | time-to-first-token / cancellation tests | 2 | 1 | split inside items 2-4 |
| 6 | Bedrock `InvokeAgent` with action groups (model emits tool call -> invoke Lambda action group -> feed result -> final answer; `returnControl`; `trace`; sessionState), `RetrieveAndGenerateStream`, `InvokeInlineAgent` | the Bedrock-native agent path; engine overlaps with item 2 | 4-5 | 1,2 | after 2 |
| 7 | Azure AI Foundry Agent Service + classic Assistants (agents, threads, messages, runs with `requires_action` -> `submit_tool_outputs`, run steps, file/vector stores) and `/openai/v1/responses` | `azure-ai-projects` agents; one engine can serve assistants + agents + responses | 6-8 | 1,3 | yes, big |
| 8 | Vertex Agent Engine (`reasoningEngines` create/query/streamQuery, simplest: store a pickled-agent record, run via compute booster) and RAG Engine (`ragCorpora`, importRagFiles, retrieveContexts) reusing the KB chunk/embed/kNN code | ADK deploy-and-query, RAG | 5-6 (RAG 2, engines 4) | 1,4 | yes (two sub-agents) |
| 9 | Embedding upgrade: real embedding model (nomic/bge) in the booster, Titan v1/Cohere embed ids, `batchEmbedContents`, Azure `encoding_format`, dimensions rules | RAG quality plumbing; hash fallback is deterministic but semantically weak | 1-2 | 1 | yes |
| 10 | Bedrock gaps: CountTokens, inference-profile list/get, ApplyGuardrail + Guardrails CRUD (regex/denied-topic/PII filters, deterministic; no ML content filters), `guardrailConfig` on Converse/Invoke, model catalogue refresh (Claude 3.7/4.x, Nova 2, Llama 3.x) | agents commonly guard + count tokens | 4 | 1,2 | yes |
| 11 | Booster glue: start/stop llama-server/Ollama inside the booster session (`llm_runtime` variant without docker-compose network, disk guard exists), admit model RAM via `booster.allocate("ai", ...)`, `status()` surfaced in `/healthz` and Nano chip, model download/caching, health gating (`ModelNotReady` until warm), `VYOMI_LLM_ENDPOINT` auto-set | required for any of the above to run on a booster | 2-3 | none (can start now) | yes, with 1 |
| 12 | AgentCore: InvokeAgentRuntime executing the user's agent container on the booster compute side, gateway openApi/mcpServer targets callable, Memory API | Bedrock AgentCore-native agents | 6-8 | 1,2,11 | yes, big |
| 13 | Vertex custom endpoint `:predict`/`:rawPredict`/`:chatCompletions` to the local model for deployed Model Garden models | makes "deploy llama on Vertex" tests work | 1-2 | 1 | yes |
| 14 | Test layer: SDK-level conformance (boto3 `converse` tool loop, google-genai function calling, `openai.AzureOpenAI` tools) against a real llama-server in CI, with deterministic tiny model plus a scripted stub backend for hermetic runs | the proof; keep hermetic stub for PR CI, real model on the booster runner only | 3-4 | 2,3,4 | yes |

Approximate total: 50-65 agent-days sequential; about 3 parallel lanes (AWS, GCP, Azure) after item 1 compress to roughly 3-4 weeks wall-clock.
Suggested lanes: Foundation (1, 5, 9, 11) -> AWS lane (2, 6, 10, 12) / GCP lane (4, 8, 13) / Azure lane (3, 7) -> Tests (14).

### 4.7 Token / usage accounting for the booster ledger

Today: each adapter returns per-request usage (backend `usage` if present, else `ceil(chars/4)`), and `booster.py` only tracks RAM
(`_LEDGER` kinds `compute|ai`); there is no token or request ledger, and no per-space attribution. Proposal:

- `llm_core` emits a usage event `{ts, cloud, op, model_id_requested, local_model, input_tokens, output_tokens, latency_ms, status, space/account}` through a registered
  sink; the booster registers a sink that keeps rolling counters and an event log, exposed by `/booster/...` status and the Nano chip.
- Use the llama.cpp `usage`/`timings` fields (exact tokenizer counts); keep the `len/4` estimate only for WebLLM/no-usage backends and label it `estimated`.
- Report cloud-shaped usage back to the SDK (already done) AND a simulated cost line (cloud list prices x tokens) for the cost meter; the real cost to us is wall-clock CPU, so also meter `compute_seconds`.
- Ledger is a tally for display and fair-use caps (e.g. tokens per session hour), not billing; sessions already end on a timer (`booster-link.js` countdown).

## 5. Findings worth flagging

1. Tool calling is rejected everywhere (probed 400s on all three clouds) and `llm_core` cannot carry it: item 1 is the critical path.
2. Two Azure OpenAI implementations disagree (real-model path vs `[SIMULATED ...]` canned path); the one the account advertises (`/azure-data/openai/...`) is the canned one.
3. Silent-ignore hazards (worse than errors): Vertex `responseSchema`, Azure `json_object`, Converse `guardrailConfig`/`performanceConfig`.
4. `google-genai` default (Developer API) path `/v1beta/models/...` is not served; only the Vertex form is. Also unverified with the real SDK.
5. Streaming is cosmetic for all clouds. Fine for parsing tests; wrong for latency/cancel tests.
6. AI RAM bucket exists but nothing admits models against it.
7. Booster routing for AI calls is already in `booster-link.js`; the missing piece is starting a model on the booster and pointing `VYOMI_LLM_ENDPOINT` at it.
8. Not verified: any real SDK round trip, llama.cpp/Ollama behaviour, tokens/sec, the booster boot path in a real Codespace, and the console capability JSONs.
