# v4/rag-studio-azure

Owner: claude (rag studio azure) - Started: 2026-11-26 - Base: origin/v4/rag-studio-gcp-azure (foundation 9ad488081) - Status: built and verified locally; unmerged

## Purpose
RAG Studio inside the Azure v4 console, as a panel of the existing AI Search blade (AI Search > service > RAG > RAG Studio): Design / Validate / Test / Corpus (pre-RAG) / Query analysis (post-RAG). It runs live against the simulator's Azure AI Search + Azure OpenAI, or against the in-browser fake, and reads/writes the neutral `vyomi.rag-design/v1` document (`cloud: "azure"`, Export/Import design buttons).

## Architecture
- Console `consoles/src/azure/services/aisearch/studio/`: `Studio.jsx` (shell, tabs, Export/Import via `common/ragstudio/document.js`), `Design/Validate/Test/Corpus/PostRag/EmbeddingMap.jsx`, `ui.jsx` (Fluent building blocks; no Cloudscape), `azureMap.js` (design <-> Azure shapes), `backend.js` (adapter over `../api.js`), `fake.js` (`createFakeCore` behind Azure shapes), `studio.test.mjs`.
- Registered as a page (`ragstudio`) in `SearchServiceBlade.jsx` MENU; no new service id (inventory + IAM gates untouched).
- Design mapping: chunking -> SplitSkill `pages` (`maximumPageLength` = tokens x 4 chars, min 300; overlap %); embedding -> AzureOpenAIEmbeddingSkill + vector field `dimensions` + vectorSearch profile/vectorizer; `retrieve.searchType` HYBRID -> hybrid (search + vectorQueries, weight = vector share), vector share 0 -> text only, SEMANTIC -> vector only; rerank -> `queryType: semantic` + the `ragstudio-semantic` configuration (title + chunk); generate -> chat `data_sources[azure_search]` (on your data). Objects are `ragstudio-chunks|parents|ds|skills|indexer`; Apply recreates them.
- Backend: `core/azure_search_core.py` `inspect_index` / `inspect_dispatch`. `GET .../indexes/{ix}/chunks[?vectors=true]` (AWS shape: count, dimensions, chunks[{id, documentUri, text, tokenCount, metadata, section, pii, projection2d, vector?}]) and `POST .../indexes/{ix}/retrieve-trace` (a normal docs/search body; returns `value` + `trace.candidates[]` with keyword/vector/fused/reranker score+rank and final_rank). `search()` got an optional `_trace` dict; plain output is unchanged (asserted).
- Reachable two ways: (1) ARM extension path `.../Microsoft.Search/searchServices/{svc}/indexes/{ix}/chunks|retrieve-trace` (what the console uses; works offline AND in Nano with no new routing, because the Azure Nano ARM core already dispatches `microsoft.search` to `azure_search_core`), (2) `/_vyomi/azure/search/{svc}/indexes/{ix}/chunks|retrieve-trace` on the offline appliance (`routes/azure_dataplane_unified.py`, needs an admin api-key or bearer).
- On your data: `core/ai_models_core.py` already implemented `data_sources[azure_search]` (citations, intent). One fix: the ARM-proxy caller passed a one-account state so the search service was never found; `_az_on_your_data` now gets `net_state or arm_state`.
- `core/knowledge_core.py`: the cached FTS5 `:memory:` connection was shared across threads without a lock; concurrent trace + chat requests segfaulted the dev server (python 3.9). Added an RLock around the query and the cache. Applies to every BM25 caller (AWS KB, GCP, Azure).
- Nano: `wasm/core/*` regenerated with `python3 wasm/build_cores.py` (azure_search_core, ai_models_core, knowledge_core); `--check` clean. The embedding skill's `resourceUri`/`deploymentId` are never contacted; the local embedding model answers on both substrates.

## Design decisions
| Decision | Rejected | Why |
|---|---|---|
| Studio is a panel of the aisearch blade | new service id | the Studio targets one search service; keeps inventory/IAM gates green |
| Console uses the ARM-extension inspect path | only `/_vyomi/azure/search/...` | works in Nano with zero routing work and carries the ARM auth already |
| Own Fluent kit, no React Flow / Cloudscape | porting AWS components | Azure console has no Cloudscape; stage cards + CSS/SVG charts are enough |
| Azure embedding models added to `EMBED_MODELS` from `azureMap.js` | editing `common/ragstudio/engine.js` | additive, AWS bundle never loads it |
| Vector share 0 = keyword-only, SEMANTIC = vector-only | extending the document's searchType enum | keeps `vyomi.rag-design/v1` unchanged |

## Honest gaps (shown in the UI)
Semantic/hierarchical chunking approximated by pages; semantic ranker is an approximation (0-4 scale, not the cross-encoder); only blob/cosmos/sql sources; no OCR/image skills; metadata filters only on index fields (title, parent_id); exact cosine scan, no HNSW; projection is server-side PCA, not UMAP.

## Open issues
- [ ] Console changes are source-only; `wasm/v4/azure` is rebuilt after merge (rule 6), not committed here
- [ ] Cosmos / SQL data-source pickers in the Design panel (blob only today)
- [ ] Studio panel in a Nano browser session not exercised (service worker path); offline dev server + vendored cores tested
- [ ] `common/ragstudio/*` unchanged

## Testing
- `PYTHONPATH=. python3 tests/conformance/test_azure_rag_studio.py` and the same with `PYTHONPATH=wasm` (vendored Nano cores): indexer (split + embedding skill + projections) -> chunks inspect shape, retrieve-trace stages (keyword/vector/fused/reranker/final), plain search unchanged, `$filter`, `inspect_dispatch` (+ auth/404), chat on your data through the ARM proxy (citations, intent, 400 on unknown index), 8-thread concurrent search, 30 x 1536-dim projection < 3 s. OK on both.
- `cd consoles && node --test src/azure/services/aisearch/studio/studio.test.mjs` 11/11 (mapping, round-trip, fake adapter, trace rows); `src/common/ragstudio/ragstudio.test.mjs` 6/6.
- Headless Chrome (playwright) against `consoles/dev_server.py --port 8793` with a seeded search service + storage blobs + OpenAI account and a stub chat model (the dev box has no LLM): live mode applies, ingests (19 chunks), answers with citations, shows all trace stages, waterfall, map, evaluation (hit rate 86%), Export (cloud azure) / Import; fake mode runs the same flow. Not run: Nano browser session (service worker), the Playwright suites, real embedding model (hash fallback answered).
- `wasm/build_cores.py --check`, `gen_service_inventory.py --check`, `gen_iam_coverage.py --check`, `test_iam_onboarding_gate.py` green.
