# v4/az-ref-ai: Azure reference app, lane 2 (OpenAI/Assistants routing, Foundry project endpoint, AI Search native wire)

Base: `origin/v4-on-main` 1e285e638. Evidence: `docs/architecture/v4.0/REF-ARCH-PROBE-AZURE.md` (components 3, 6, 9, 11). All proofs use the real, unmodified
`openai` AzureOpenAI, `azure-ai-projects` 2.11.0, `azure-ai-agents` 1.1.0 and `azure-search-documents` 12.1.0 against the real appliance app (`server.py`, in process).
The model is the local-LLM stub seam (`llm_core.set_backend`), as the sandbox has no model.

## Changes
1. `/openai/*` routing (`routes/aws_s3.py`): the S3 catch-all sent only POST to the Azure OpenAI core, so every GET/DELETE on assistants, threads, messages, runs, run steps,
   vector stores and vector-store files fell through to S3. Every verb now reaches `core/ai_models_core.azure_openai_dispatch`. The core also gained what the SDK calls and was
   missing (`core/azure_openai_agents_core.py`): message get/update/delete, run update, run step get, vector-store file update, file batch `files` + `cancel`, vector store
   `search`, and a `file_search` `tool_calls` run step with the retrieved results. Test: `tests/conformance/test_azure_ref_ai_openai_sdk.py` (create/get/list/update/delete
   assistant, thread, message, run, run steps, vector store, file batches, file list, `file_citation` annotations).
2. Foundry project endpoint `<host>/api/projects/<project>/...` (`ai_models_core._foundry_project`, routing in `routes/aws_s3.py` + `core/aws_wire_router.py`): classic agents
   (`AgentsClient`: assistants/threads/messages/runs/steps/files/vector stores under the project prefix = the same core) and the v2 surface in `azure_openai_agents_core.project_dispatch`:
   agents + versions, `responses.create(extra_body={"agent_reference":...})` (applies the agent's model/instructions/function tools), conversations (+ items, and `conversation=` on
   Responses), connections (derived from ARM accounts/Search services), deployments (from ARM), empty dataset/index/evaluator listings. Test: `test_azure_ref_ai_foundry_sdk.py`.
3. AI Search native wire (`core/azure_search_core.py` `wire_dispatch`, `routes/azure_dataplane_unified.py`): the OData paths the clients send (`indexes('x')`, `docs/search.post.search`,
   `search.index`, `docs('k')`, `docs/$count`, `search.stats`, `servicestats`, datasources/indexers `search.run|status|reset`, skillsets, synonymmaps, aliases) are translated onto the
   existing engine. Reachable three ways: root endpoint (the single service in the space answers), `<host>/azure-data/search/<service>`, `<service>.search.*` Host header. Added engine
   features: suggest + autocomplete, `searchFields`, `searchMode=all`, suggesters kept in the index definition, synonym map and alias CRUD, fuller service statistics. Test:
   `test_azure_ref_ai_search_sdk.py` (SearchIndexClient, SearchClient incl. `vector_queries` and `query_type='semantic'` with captions and answers, SearchIndexerClient).
- Capabilities: `azure.foundry.agents` (extended), new `azure.foundry.project-endpoint`, `azure.aisearch.query` (extended), new `azure.aisearch.wire`; MCP matrix regenerated.

## Design decisions
- No new backend and no new core module: all three fixes reuse existing cores (the four core lists were not needed; `wasm/core/` mirrors were re-synced by `build_cores.py`).
- The Foundry bearer: the SDK's `BearerTokenCredentialPolicy` refuses plain http, so a local test passes `authentication_policy=` a policy that only adds the `Authorization` header. The
  simulator still requires a bearer or `api-key` header (401 otherwise); it does not validate the token (Entra JWT is lane 5).
- AI Search auth is real: admin key or query key (query keys may only read documents and query), otherwise 403. A bearer token is accepted unvalidated.
- The "semantic ranker returned nothing" finding from the probe did not reproduce: with the native SDK, `query_type='semantic'` returns `@search.rerankerScore`, captions and answers
  (local embedding seam). It is an approximation of Microsoft's ranker, as already stated in the capability entry.
- Root-path claiming is narrow on purpose: api-version query plus an api-key/bearer header plus a search root name, so an S3 bucket called `indexes` and the Table `(`-key rule are not affected
  (`routes/azure_graph_unified.table_path` now yields to api-key requests on the search roots).

## Open issues
- ARM still advertises `https://<name>.search.windows.net/` / `https://<acct>.openai.azure.com/` hosts that do not resolve locally; the app lane must use one of the three forms above
  (or a TLS front on Mesh). No change to the advertised endpoints was made.
- Nano (browser shared router) does not route the AI Search wire; the Foundry project paths are in the shared router but not browser-tested.
- Foundry: only prompt agents and function tools; hosted/workflow agents, Bing/AI Search/MCP agent tools, memory stores, evaluations and telemetry are not served. Synonyms are stored, not applied.
- State of agents/threads/responses is process-local (restart loses it), as before.
- Indexer fill from Blob and Event Grid triggering are lane 3.
