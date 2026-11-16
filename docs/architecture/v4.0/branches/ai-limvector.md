# Branch v4/ai-limvector: search limits across clouds (round 8)

Owner: AI session (round 8, lane `limvector`). Base: local `v4/ai-integration` @ 5feeae0e6. Not merged.

## Purpose
Close the declared limits of vector / hybrid / semantic search for Azure AI Search, GCP RAG Engine + Vertex AI Search and Bedrock Knowledge Bases,
using the embedder the platform already serves (all-MiniLM-L6-v2 on Nano, nomic-embed-text on the Mesh, through `core/llm_core.embed`) and SQLite FTS5 BM25
(`core/knowledge_core`). Every claim below is tested; remaining limits stay listed in `core/capabilities/**` and `consoles/src/common/scopeHelp.js`.

## OSS choices (thumb rule)
| Need | Chosen | License / size | Substrate | Why / rejected |
|---|---|---|---|---|
| Keyword ranking (Azure, GCP, Bedrock) | SQLite FTS5 `bm25()` (via `knowledge_core.bm25`) | public domain, stdlib | both (Pyodide sqlite3, hand BM25 fallback exists) | replaces Azure's TF-IDF; no new dependency |
| Dense retrieval (all three) | exact cosine over `llm_core.embed` vectors | n/a | both | already served; HNSW libs (hnswlib, faiss) are native, not Pyodide-safe, and corpora here are small |
| Hybrid fusion | reciprocal rank fusion (k=60), weighted (Azure `weight`, GCP `alpha`) | n/a, 10 lines | both | RRF is what Azure documents; Bedrock/GCP do not publish theirs |
| Multipart parsing (GCP upload) | stdlib `email.parser` | stdlib | both | no multipart lib needed |
| Document text (GCS import) | existing `knowledge_core.parse_document` (pypdf, zip+xml) | existing | both (PDF needs pypdf on Nano) | reuses the Bedrock KB parsers |
| Cross-encoder rerank (Bedrock) | OPTIONAL external `/v1/rerank` server (`VYOMI_RERANK_ENDPOINT`), e.g. `llama-server --reranking` + a bge-reranker GGUF | MIT / Apache models, 100-600 MB | Mesh only, operator-provided | an ONNX cross-encoder needs onnxruntime (native wheel, not Pyodide); shipping a second GGUF is a separate decision, so the default stays the embedding blend |
| Cosmos / SQL indexer sources | the simulated `CosmosStore` and Azure SQL `SqlStore` (existing engines) | existing | both | no new backend |
| Semantic ranker (Azure) | embedding cosine + term coverage, declared approximation | n/a | both | Microsoft's L2 ranker is a proprietary cross-encoder; no OSS equivalent runs in Pyodide |
| Generated summary (GCP Search) | `llm_core.chat` (llama.cpp / WebLLM) | existing | both | no Gemini; response says `vyomiModel: local chat model` |

Hand-written code is the wire adapter only: request/response shapes, validation, state.

## What now works (tested through the real wire)
### Azure AI Search (`core/azure_search_core.py`, `azure_search_vector_core.py`, new `azure_search_sources_core.py`)
- BM25 keyword scoring (was TF-IDF).
- Vector fields + `vectorQueries` (vector/text kinds, `weight`), hybrid = BM25 + vector RRF (these existed; weights added).
- `queryType: semantic` + `semanticConfiguration` (index `semantic.configurations` validated): `@search.rerankerScore` 0-4, `@search.captions`, `@search.answers`. Approximation (see limits).
- Skillsets: SplitSkill (pages or sentences, `maximumPagesToTake`), MergeSkill (offsets, pre/post tags), AzureOpenAIEmbeddingSkill with index projections; `outputFieldMappings`.
- Data sources + indexers: `cosmosdb` (reads the simulated Cosmos container, optional Cosmos SQL query with `@HighWaterMark`) and `azuresql` (table/view of the simulated Azure SQL database), plus blob. `fieldMappings` (+ base64Encode/Decode, urlEncode/Decode, jsonArrayToStringCollection), `HighWaterMarkChangeDetectionPolicy` (incremental; tracking state in status), `SoftDeleteColumnDeletionDetectionPolicy`. `SqlIntegratedChangeTracking` is rejected by name.
- Wiring fix: `AwsWireRouter` built a second `AzureArm` that dropped `blob_store` / `sql_store`; they are re-attached (plus `cosmos_store`) after that line. Without it indexers saw no stores under the router.
- Console: Skillsets panel; Cosmos/SQL data source templates; Indexers table shows skillset, has a Status button; explorer has a Semantic query type.

### GCP RAG Engine and Vertex AI Search (`core/gcp_agentplatform_core.py`)
- Chunks embedded at upload; `retrieveContexts` is dense by default; `ragRetrievalConfig.hybridSearch.alpha` (0 = BM25 only, 1 = dense only, weighted RRF), `filter.vectorDistanceThreshold` / `vectorSimilarityThreshold`, `ranking` (embedding + lexical rerank), `topK` range check; contexts carry `distance`, `score`, `sparseDistance`.
- `ragFiles:import` from the SIMULATED GCS (`gcsSource.uris`: object or prefix; unchanged objects skipped, changed ones re-imported; per-file failures in operation metadata; Drive/Slack/Jira/SharePoint rejected with INVALID_ARGUMENT).
- `ragFiles:upload` accepts multipart/related (metadata JSON + bytes) and multipart/form-data (`metadata` + `file`) as well as the older JSON body.
- Vertex AI Search: `documents:import` from GCS (`content`, `custom`, `document` schemas; BigQuery etc. rejected), hybrid BM25 + embedding RRF search, `contentSearchSpec.summarySpec` -> cited summary (`summaryWithMetadata.citationMetadata`) from the local chat model, `summarySkippedReasons` when no model runs.
- Stale counts: the server always computed live counts; the console list did not refetch after a file upload / import / delete. It now does (list remount via `onChanged`), proven by Playwright.
- Wiring: `dispatch(..., gcs=self.gcs)` passed from the router (one-line additive edit).

### Bedrock Knowledge Bases (`core/bedrock_agents_core.py`, `core/knowledge_core.py`)
- `overrideSearchType` validated (HYBRID / SEMANTIC); SEMANTIC is vector only with cosine scores, HYBRID is BM25 + vector RRF.
- Full RetrievalFilter validation (one operator per filter, andAll/orAll 2-5 members and nesting depth, typed values per operator, key length) and corrected semantics (`stringContains` matches substrings of strings and list members, type-strict `equals`/`in`, `notEquals`/`notIn` keep documents without the attribute).
- `implicitFilterConfiguration`: the local chat model derives a filter from the question; filters on undeclared attributes are ignored; AND-ed with an explicit filter.
- Reranking: `rerankingConfiguration` on Retrieve/RetrieveAndGenerate (with `metadataConfiguration`), the Rerank API (model ARN checked against `amazon.rerank-v1:0` / `cohere.rerank-v3-5:0`, exactly one TEXT query, 1-1000 INLINE TEXT sources, returns the document, `numberOfResults` capped). Default reranker = embedding + lexical blend (the trace field `rerankBackend` says so); with `VYOMI_RERANK_ENDPOINT` set to a `/v1/rerank` server a real cross-encoder decides (tested against a stand-in server); an unreachable endpoint falls back and is labelled.

## Tests
| Test | Result |
|---|---|
| `tests/conformance/test_azure_search_limvector.py` | 33 checks, 0 fail (router, ARM + Cosmos + Azure SQL wires) |
| `tests/conformance/test_gcp_rag_limvector.py` | 33 checks, 0 fail |
| `tests/conformance/test_bedrock_kb_search_limvector.py` (real boto3 over HTTP) | 45 pass, 0 fail |
| existing: azure_search_core, azure_search_vector_core, gcp_agentplatform_core, bedrock_agents_core, bedrock_kb_runtime_caps | pass |
| `consoles/tests/smoke-limvector.mjs` (Playwright, Nano preview, tier pro) | 14 PASS |
| `test_knowledge_rag.py` | needs opensearch-py (not installed here): its boto3 part ran without failures, the opensearch-py part was not run |

Not measured: AWS probe re-run (tools live on `v4/ai-probe-baseline`); real MiniLM/nomic retrieval quality (tests use a concept-dimension stand-in embedder and the labelled hash embedder, so they prove the plumbing and fusion, not model quality); Nano browser run of the Python (the Playwright smoke runs the Nano Pyodide path with the hash-embed fallback because the MiniLM download is not available offline here).

## Declared limits (also in the capability registry and scopeHelp)
- No HNSW anywhere: exact scan (fine to roughly 10k vectors).
- Azure semantic ranker is NOT Microsoft's: reranker score = 4 x (0.7 x scaled cosine + 0.3 x term coverage); captions pick the best-covering sentence; answers use embedding similarity. Order and scores will differ from Azure.
- Azure vectorizers / embedding skills name an Azure OpenAI deployment that is never called; the local embedder answers and its vector is truncated/padded to `dimensions`.
- Azure: no OCR / entity / language / image / WebApi skills, no knowledge store, no schedules, no SqlIntegratedChangeTracking, azuretable/adlsgen2 sources not read.
- GCP: no Drive/Slack/Jira/SharePoint/BigQuery sources, no RAG metadata filters, reranker is not Google's rank service, summary is the small local model (not Gemini), no PDF layout/OCR.
- Bedrock: the default reranker is not a cross-encoder (Mesh operator can attach one; none shipped; Nano never); implicit filters are the small model's judgement; filter semantics for edge cases (missing attribute with `notEquals`) follow the documented behaviour but were not compared against real Bedrock.
- Nano: vectors from MiniLM are 384-d and Mesh vectors (nomic) 768-d, so indexes are not portable between substrates; a dimension mismatch is re-embedded lazily (GCP, Bedrock).

## Merge notes
Shared-file edits are small and additive: `core/aws_wire_router.py` (gcs kwarg; ARM store re-attach block), `core/azure_arm_core.py` (search dispatch kwargs), `wasm/build_cores.py` + the three Nano CORES lists (new module), `core/capabilities/{aws/bedrock,gcp/vertex-ai}.json` (1 text edit + 2 entries), new `core/capabilities/azure/aisearch.json`, `consoles/src/common/scopeHelp.js` (text only). `wasm/core` is mirrored; no `wasm/v4` bundle committed.
