# v4/rag-studio-gcp

Owner: claude (rag studio gcp) - Started: 2026-11-26 - Base: origin/v4/rag-studio-gcp-azure (foundation, on v4-on-main) - Status: built, verified locally, pushed; not merged

## Purpose
RAG Studio in the GCP v4 console under Agent Platform (Vertex AI) > Agents > Build > RAG Studio (`#/vertex-ai/rag-studio`): Design / Validate / Test / Corpus (pre-RAG) / Query analysis (post-RAG), live against the simulator's Vertex AI RAG Engine or the in-browser fake, exporting/importing the `vyomi.rag-design/v1` document (cloud = `gcp`).

## Architecture
- Backend (`core/gcp_agentplatform_core.py`, vendored copy via `python3 wasm/build_cores.py`):
  - `_retrieve` refactored into `_retrieve_core` -> `(contexts, trace)`; `:retrieveContexts` output unchanged.
  - Inspect API, distinct prefix `/_vyomi/gcp-rag/{project}/{location}/{corpusId}/`: `GET chunks?vectors=true` (count, dimensions, embeddingModel, chunks[{id, ragFileId, documentUri, text, tokenCount, metadata{file,source,chunk_index}, section, pii, projection2d, vector?}]) and `POST retrieve-trace` (body = a `:retrieveContexts` request; -> `{contexts, trace{candidates[{chunkId,fileId,displayName,uri,vector_score/rank,bm25_score/rank,fused_score/rank,rerank_score/rank,returned,final_rank,filtered_out_reason}], searchType, alpha, reranked, latencyMs, embeddingModel, dimensions}}`). Routed by `STUDIO` in `handles()` so `aws_wire_router._gcp_service` sends it to `gcp-agentplatform` (same on Nano: `llm_core.arun` path).
  - `ragEmbeddingModelConfig.vertexPredictionEndpoint.model` accepted on corpus create, validated (must resolve to the embedding model; a chat model is 400), echoed on GET. Vyomi has ONE local embedder, so it is not passed per call (same as the Bedrock KB `embeddingModelArn` check).
- Console `consoles/src/gcp/services/vertex-ai/studio/`: `backend.js` (adapter: live / live-limited / fake; `seedDemoCorpus`), `gcpMap.js` (design <-> `ragFileTransformationConfig` / `ragRetrievalConfig` / `ragEmbeddingModelConfig`; trace rows; filter -> ragFileIds; groundingMetadata -> citations; GCP lint), `fake.js` (common fake core over a `gs://` copy of the demo corpus), MUI tabs `Studio/Design/Validate/Test/Corpus/PostRag.jsx`, `EmbeddingMap.jsx`, `ui.jsx`. Registered as a page of the existing `vertex-ai` service (no new service id).
- Mapping notes: chunkSize = maxTokens x 5 chars (the core chunks at size // 5 tokens); hybrid `alpha` = dense share (= design hybridWeight); rerank = `ranking.rankService`, topK sent = rerank topN (engine reranks 3 x topK candidates); only `fixedLengthChunking` exists, so SEMANTIC/HIERARCHICAL warn in lint; metadata filter keys are `file` / `source` (mapped to `ragFileIds`).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| New prefix `/_vyomi/gcp-rag/` | Reuse `/_vyomi/kb/` | `/_vyomi/kb/` routes to Bedrock; GCP must not fall into the S3/Bedrock handler |
| Chunking applied at ingest (delete GCS-imported files, `ragFiles:import` again; demo files re-uploaded) | Corpus-level chunk config | RAG Engine chunks per file; directly uploaded non-demo files cannot be re-chunked and the UI says so |
| MUI + local helpers, no Cloudscape | Reuse AWS tab files | GCP console kit is MUI; AWS tabs import Cloudscape |
| Pure helpers in `gcpMap.js` | Keep in `backend.js` | node tests can import them without `wire.js` (needs `document`) |
| Nothing changed under `common/ragstudio/` | - | `EMBED_MODELS` is extended at runtime from `gcpMap.js` instead |

## Open issues
- [ ] `ragEmbeddingModelConfig` is validated/stored but the one local embedder is used for all corpora.
- [ ] RAG Engine requests are not IAM-mapped (`:retrieveContexts` and the inspect routes return no required permissions), same as before.
- [ ] No Playwright suite registered; verification below was a one-off headless run.
- [ ] Built outputs (`wasm/v4/gcp`) not committed (rule 6); rebuilt after merge.

## Testing
- `PYTHONPATH=. python3 tests/conformance/test_gcp_rag_studio.py`: 19 checks (embedding config, inspect chunks/trace, parity with `:retrieveContexts`, rerank/threshold/file-filter reasons, `generateContent` + `tools[].retrieval.vertexRagStore` -> `groundingMetadata`). `test_gcp_rag_limvector.py` and `test_gcp_agentplatform_core.py` still pass.
- Nano substrate: vendored `wasm/core` imported as the `core` package and driven through `AwsWireRouter.ahandle` (async, as Nano does): chunks, retrieve-trace and grounded generateContent answer. Not run in real Pyodide/browser worker.
- `cd consoles && node --test src/gcp/services/vertex-ai/studio/studio.test.mjs` (8/8) and `src/common/ragstudio/ragstudio.test.mjs`.
- Headless Chrome against `consoles/dev_server.py` (own port, local LLM stub): fake mode (export/import design, test, post-RAG waterfall, corpus, evaluation) then live after "Seed demo corpus" (23 chunks, grounded cited answer, map, evaluation hit rate 86%, ingest with 20-token chunks -> 65 chunks).
