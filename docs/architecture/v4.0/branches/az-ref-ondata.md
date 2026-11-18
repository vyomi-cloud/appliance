# az-ref-ondata: Azure OpenAI "On Your Data"

Branch `v4/az-ref-ondata` (base `v4/az-ref-integ`). Lane 8 of the Azure reference-app build.

## Changes
- `core/ai_models_core.py`: chat/completions with `data_sources` (type `azure_search`) retrieves from the simulator's AI Search core
  (`azure_search_core.search`), builds a grounding system prompt with numbered `[docN]` sources, calls the model through the existing local-LLM
  seam, and returns `message.context = {citations[{content,title,url,filepath,chunk_id}], intent}`. `stream=true` sends the context in the first delta.
- Other data source types (cosmos_db, elasticsearch, azure_ml_index, mongo_db, pinecone) return 400 `BadRequest`; wrong api-key / missing index / unknown service return 400.
- `tests/conformance/test_azure_openai_on_your_data.py` (real `openai` + `azure-search-documents` SDKs, local-LLM stub seam): 9 PASS.
- Capability entry `azure.foundry.on-your-data` (nano + offline: limited); MCP knowledge regenerated.

## Design decisions
- No new backend or module: reuse the search engine and the model seam, so no Nano CORES lists change (`wasm/core` mirror synced by `build_cores.py`).
- Service resolved like the search data plane: `/azure-data/search/<svc>`, ARM-extension path, `<svc>.search.*` host, or the sole service.
- Vector query types embed the question with the local embedding model and fuse via the existing vector/hybrid ranking.

## Open issues
- `strictness` accepted, not applied; no `rerank_score` in citations; `intent` is the user question (no query rewrite).
- Nano shares the core but was not browser-tested; it answers only with a loaded WebLLM model.
- Real-model answer quality (coordinator's Qwen3-4B run) not exercised here.
