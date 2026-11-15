# Branch v4/ai-ragstudio: RAG Studio

Owner: ragstudio lane (enterprise agentic AI). Base: origin/v4-on-main. Purpose: a Nano/Mesh console area to design, validate, test and visualise (pre/post query) the RAG pipeline of `facilities-kb` (components C6/C12).
Open: AWS console -> Amazon Bedrock -> Build -> RAG Studio (`#/bedrock/knowledge-bases/studio`, also "Open RAG Studio" on the Knowledge bases list).

## What it does
- Design: xyflow node graph source -> parse -> clean -> chunk -> embed -> index -> retrieve -> rerank -> generate; per-node params, presets, JSON save/load; Apply = UpdateDataSource (chunking) + StartIngestionJob; retrieval/rerank config rides on every Retrieve/RetrieveAndGenerate (AWS has no persistent retrieval config; the design JSON is kept in localStorage per KB).
- Validate: design linter (16 rules, auto-fix), golden-set eval with 7 deterministic metrics, per-metric thresholds, run history, A/B compare (a run of a different preset re-chunks and re-ingests first).
- Test: query playground with per-stage scores, filters, latency per stage, cited answer, guardrail result.
- Pre-RAG: counts, token histogram, coverage by source/metadata, duplicate clusters, language/PII flags, UMAP map coloured by document/metadata/language/PII.
- Post-RAG: query on the map with linked retrieved chunks, score waterfall (promoted/dropped/filtered), provenance overlay (ungrounded sentences flagged), evaluation dashboard.

## Backends
`studio/backend.js`: live (real bedrock-agent + bedrock-agent-runtime wires + Vyomi inspect extension) or fake (`studio/fake.js`, in-browser demo corpus, identical shapes). Auto-detect: live `facilities-kb` else demo with a banner; header button toggles. `live-limited` = KB found but no inspect API (apply/ingest/test work; corpus and stage views limited).
Inspect API expected from the knowledge lane (under the wire prefix, outside the AWS namespace):
- `GET {wire}/_vyomi/kb/{kbId}/chunks` -> `{embeddingModel, chunks:[{id, uri, text, tokens, metadata, embedding:[...], pii?:[], lang?, position?:[x,y]}]}`
- `POST {wire}/_vyomi/kb/{kbId}/retrieve-trace` body `{query, options:{numberOfResults, searchType, hybridWeight, rerank, rerankTopN, filter:{key,value}|null, threshold}}` -> `{query, queryEmbedding, confidence, latencyMs:{embed,vector,bm25,fuse,rerank,total}, results:[{id, uri, text, tokens, metadata, vector_score, vector_rank, bm25_score, bm25_rank, fused_rank, rerank_score, filtered_out_reason, final_rank}]}`
Not tested against the real knowledge backend: v4/ai-knowledge was not on origin when this lane finished.

## OSS choices
| Need | Chosen | License / size | Substrate | Why / rejected |
|---|---|---|---|---|
| Pipeline modeller | @xyflow/react 12.3.5 | MIT, ~7 MB installed incl. deps (adds ~0.2 MB gz to bundle) | browser (Nano + Mesh UI) | small node-graph lib vs writing an editor. Flowise/Langflow/Dify/RAGFlow rejected: separate heavy servers, not runnable in the browser |
| Embedding projection | umap-js 1.4.0 | MIT, pure JS | browser | supports transform() so the query lands in the same map. embedding-atlas rejected: WebGPU + large dep tree; druid.js similar but no transform |
| Map / waterfall rendering | hand-written SVG (~100 lines) | - | browser | Cloudscape charts have no scatter type |
| Histograms, coverage, A/B, dashboard | Cloudscape BarChart (already bundled) | - | browser | no new chart library |
| Metrics | plain code (hit-rate, MRR, AP precision, token-recall, citation match, sentence grounding) | - | both | ragas/deepeval definitions need an LLM judge; a judge hook through the llm seam is NOT wired |
Overlay deps live in `consoles/rag-overlay/` (own small node_modules, not committed; `npm install --no-package-lock --omit=peer` there); `build.mjs` adds `nodePaths` so the shared node_modules stays untouched.

## Tests
- `node consoles/tests/rag-studio-engine.test.mjs`: 40 checks (metrics, linter, API mapping, chunker, duplicates, fake end to end) ALL PASS.
- `consoles/tests/smoke-aws-ragstudio.mjs` (Playwright against `nano_preview.mjs --port 8745 --tier pro`): 24 checks, all five capabilities in a browser against the demo corpus, ALL PASS.

## Declared limits
- Faithfulness / answer relevance are token-overlap proxies, not LLM-judged; WebLLM judge quality on Nano would be low anyway. Citation match is by URI substring.
- UMAP runs on the main thread: fine to ~1500 chunks; above that a deterministic sample is shown (a backend-supplied `position` is used as is). Query position via umap transform.
- Demo fake: hashed n-gram vectors, term-coverage reranker, extractive answers (no LLM): shows the mechanics, not production retrieval quality.
- Design retrieval settings are client-side (localStorage); only chunking is persisted in the KB.
- Committed wasm/v4/aws bundle is rebuilt: expect a merge conflict on minified main.js/main.css with other console lanes; rebuild after merge.
