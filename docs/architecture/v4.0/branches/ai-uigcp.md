# ai-uigcp: finish the "Coming soon" Agent Platform (Vertex AI) pages

Owner: AI session (lane `uigcp`). Base: `v4/ai-integration` (1e7125dcd). Round 7. Branch `v4/ai-uigcp`.

## Result

| Page | Built on | Notes |
|---|---|---|
| Sessions | `reasoningEngines/ID/sessions` over the Agent Engine's own sessions (`gcp_agentengine_core`) | list, create, delete, events |
| Memory Bank | new `memories` adapter, embeddings + chat from `llm_core` | create, list, delete, `:retrieve` (cosine), `:generate` (local chat model) |
| RAG Engine | `ragCorpora` / `ragFiles` / `:retrieveContexts`, chunking + FTS5 BM25 from `knowledge_core` | files come in as text via `ragFiles:upload` |
| Search | discoveryengine `dataStores` / `documents` / `servingConfigs:search`, FTS5 BM25 | inline documents |
| App Builder | discoveryengine `engines` (apps) over the same data stores | opens on the Apps tab |
| Agent Retrieval | RAG `retrieveContexts` + Search `:search` in one query | per-source results |
| Evaluation | `evaluateInstances` + `evaluationRuns`; generation by `llm_core`, scoring exact match / BLEU / ROUGE | no model autorater |
| Metadata | existing `metadataStores/default` artifacts, executions, contexts (`gcp_vertex_core`) | create, list, delete |
| Monitoring | new `modelDeploymentMonitoringJobs` collection in `gcp_vertex_core` | PENDING -> RUNNING, pause / resume |
| Agent Registry | live `reasoningEngines` of all regions with model + tools from the spec | read view |
| ADK | deploys a reasoning engine from a Vyomi agent spec | not the Google ADK runtime |
| Topology | SVG graph agent / model / tools from live engine specs | read view |
| Training clusters, Provisioned Throughput, Ray, MCP Servers, Policies, Gateways, Security | not in scope | each page states the reason and what to use instead |

Sidebar: `App Builder` (Build) and `Training clusters` (More services) added to the fixed nav in `services/vertex-ai/index.jsx`; the old special case that hid the nav on `/app-builder` is removed.

## OSS choices (thumb rule)

| Piece | OSS | License | Substrate | Why / limit |
|---|---|---|---|---|
| Lexical retrieval (RAG, Search) | SQLite FTS5 `bm25()` via `core/knowledge_core` (pure-Python BM25 fallback) | public domain | Nano Pyodide + Mesh | already in both substrates; no vector DB, so retrieval is lexical |
| Chunking / parsing | `core/knowledge_core.split_text`, `parse_document` | in-repo | both | reused, not rewritten |
| Memory similarity + extraction | `core/llm_core` embed / chat seam (llama.cpp on Mesh, WebLLM on Nano, labelled hash-embed fallback) | n/a | both | 503 when no chat model runs |
| Evaluation generation | `llm_core.chat` | n/a | both | local small model |
| Metric scoring | ~40 lines (exact match, BLEU with smoothing, ROUGE-N / L) | in-repo | both | hand-written because the OSS options (`nltk`, `rouge-score`) are not pure Python on Nano or are large; deterministic and unit-tested |

Hand-built: only the wire adapters (`core/gcp_agentplatform_core.py`) and the record stores in the account bag. No backend engine was built.

## Wire changes to shared files (small, additive)

- `core/aws_wire_router.py`: one route `gcp-agentplatform` before the Vertex handler, one dispatch branch, name added to the async-bridge tuple.
- `core/gcp_agentengine_core.py`: delegates `/memories` and `/sessions` children to the new module.
- `core/gcp_vertex_core.py`: `modelDeploymentMonitoringJobs` (+ pause/resume, continuous lifecycle, endpoint validation).
- `wasm/build_cores.py`, `wasm/nano-boot.js`, `wasm/relay/relay-shared-worker.js`: the new module (and `gcp_agentengine_core`, which build_cores did not mirror) are in the CORES lists; `wasm/core/` mirrored.

## Tests

- `tests/conformance/test_gcp_agentplatform_core.py` (through the wire router): RAG corpus + upload + retrieve, evaluateInstances, evaluationRuns, discoveryengine store/import/search/app, memories + sessions, monitoring pause/resume.
- `consoles/tests/smoke-uigcp.mjs`: Playwright on the Nano preview, every built page driven by the UI and cross-checked on the wire, plus the not-in-scope pages.

## Declared limits

RAG and Search are lexical (BM25); no Cloud Storage / BigQuery import; no multipart upload; no generative summary. Memory `:generate` needs a running chat model. Evaluation has no Gemini autorater. Monitoring computes no drift statistics. ADK runs Vyomi agent specs, not the Google ADK framework.

## Open

Capability registry entries (`core/capabilities/gcp/vertex-ai.json`) for the new pages are not added. No `wasm/v4` bundle is committed (build only).
