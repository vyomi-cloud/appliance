# v4/ai-knowledge: C6 knowledge search (RAG) + C12 knowledge pipeline

Owner: AI session (lane `knowledge`). Base: `origin/v4-on-main`. Purpose: facilities-kb fed from S3 SOP docs, ingestion with chunks + metadata,
Retrieve with hybrid search + metadata filter + rerank + citations, OpenSearch / OpenSearch Serverless control + data plane, through real boto3 / opensearch-py.

## OSS choices
| Need | Chosen | License / size | Substrate | Why / limit |
|---|---|---|---|---|
| BM25 lexical | SQLite FTS5 `bm25()` (stdlib `sqlite3`) | public domain, 0 extra | Mesh + Nano (inline BM25 fallback if the Pyodide sqlite lacks FTS5) | no engine written; PGlite/pgvector was rejected: needs a DB round trip + extra RAM for <10k chunks, and one code path for both substrates is simpler |
| Vector kNN | exact cosine over vectors from `core/llm_core.embed` | stdlib | both | exact scan, fine to ~10k chunks; no HNSW (declared) |
| Fusion | Reciprocal Rank Fusion (6 lines) | - | both | standard |
| Rerank | embedding similarity (0.7) + term coverage (0.3) behind `knowledge_core.rerank` | - | both | no model download; upgrade path on Mesh = llama.cpp `/v1/rerank` with a bge-reranker GGUF. Not a cross-encoder (declared) |
| Parse | text natively, `.docx` via zipfile, `.pdf` via optional pure-Python `pypdf` (BSD) | - | both | PDF needs pypdf installed (not bundled) |
| Chunking | in-repo splitter (FIXED_SIZE window; SEMANTIC/HIERARCHICAL = heading+paragraph-aware packer) | - | both | langchain-text-splitters drags langchain-core+pydantic, too heavy for Pyodide. Not model-driven semantic chunking |
| PII scan | existing `bedrock_guardrails_core.evaluate` | - | both | same policies as runtime guardrails |

## What is wired
- `core/knowledge_core.py` (shared primitives), `core/opensearch_core.py` (OpenSearch + Serverless), `core/bedrock_agents_core.py` (KB ingestion/retrieve upgraded). Mirrored to `wasm/core/` via `wasm/build_cores.py`; CORES lists updated in nano-boot.js, relay/*.
- Router (additive): signing names `es`/`aoss` and target prefix `OpenSearchServerless` -> `opensearch`; unsigned `_search/_bulk/_doc/...` paths -> `opensearch`; `/_vyomi/kb/*` -> `bedrock`.
- OpenSearch Serverless: collections (real rule: needs a matching encryption policy), security/access policies, tags, account settings. OpenSearch Service: domains, config, tags, versions, health.
- Data plane (opensearch-py): index create/get/head/delete, mapping, settings, doc CRUD, `_bulk`, `_search`, `_count`, `_delete_by_query`, `_cat/indices`, `_cluster/health`. DSL: match_all, match, multi_match, match_phrase, term(s), range, exists, ids, prefix, wildcard, query_string (simple), bool, knn (+filter), hybrid (min-max mean).
- KB: data source chunking (FIXED_SIZE/SEMANTIC/HIERARCHICAL/NONE) honoured; `.metadata.json` sidecars; ingestion mirrors chunks into the KB's configured `vectorIndexName` using `fieldMapping`, so opensearch-py searches the same data; Retrieve honours `overrideSearchType` (HYBRID default / SEMANTIC), `filter`, `rerankingConfiguration`; `Rerank` API; results carry `x-amz-bedrock-kb-*` metadata.
- C12 pipeline: ingestion reads optional `.vyomi-pipeline.json` at the bucket root `{"guardrailIdentifier","guardrailVersion"}` -> each document is scanned by the guardrail (blocked docs fail with reason, PII anonymised before chunking). Event-driven trigger = the real AWS pattern: S3 notification -> Lambda -> `bedrock-agent start_ingestion_job` (all existing services; not separately re-tested here).
- RAG Studio inspect API (Vyomi extension, outside AWS namespace): `GET /_vyomi/kb/{kbId}/chunks[?vectors=true]` (id, documentUri, text, tokenCount, metadata, section, pii, 2-D PCA projection, optional vector); `POST /_vyomi/kb/{kbId}/retrieve-trace` (same body as Retrieve + optional `hybridWeight` 0..1; returns results + `trace.candidates[]` with vector_score, bm25_score, fused_rank, rerank_score, filtered_out_reason, and `trace.latencyMs` per stage embed/filter/search/rerank).

## Tests
`tests/conformance/test_knowledge_rag.py` (real boto3 + opensearch-py, in-process server): 26 pass. `test_bedrock_agents_core.py` still OK.
Run: `PYTHONPATH=.:<dir with opensearch-py> python3 tests/conformance/test_knowledge_rag.py`.

## Probe (routed %, before -> after)
opensearch 0.0 -> 35.2; opensearchserverless 0.0 -> 41.3; bedrock-agent 63.9 -> 63.9; bedrock-agent-runtime 19.4 -> 22.6 (Rerank).

## Declared limits / open
- One flat index namespace shared by all domain/collection endpoints; no aggregations, highlighting, scroll, search pipelines (hybrid is native in the query).
- Domains/collections are metadata; no cluster process. kNN exact scan.
- KB embedding model must resolve to the local embed seam; with the hash-embed fallback ranking is mostly lexical (the Mesh llama.cpp embed or WebLLM improves it).
- RetrieveAndGenerate needs the local LLM running (unchanged). Nano: same Python under Pyodide, not browser-tested here.
- Unsigned `GET /` still resolves to S3 (use a SigV4 signer with service `es`/`aoss`, as real clients do).
