# RAG design document: `vyomi.rag-design/v1`

The cloud-neutral JSON a RAG Studio produces. Code: `consoles/src/common/ragstudio/document.js` (`toDocument`, `fromDocument`, `validate`); test: `ragstudio.test.mjs` in the same folder.

**Who writes it:** the Studio's "export design" action in the AWS, GCP and Azure consoles (`toDocument(design, cloud)`).
**Who reads it:** the course chapters' generated code (`courses/<slug>/<cloud>/`), which turns the document into the cloud SDK calls (chunking config, retrieve request, rerank, grounding check), and the Studio's "import design" (`fromDocument`).

## Fields
| Field | Type | Notes |
|---|---|---|
| `schema` | string | always `"vyomi.rag-design/v1"` |
| `name` | string | design name |
| `cloud` | `aws` \| `gcp` \| `azure` | cloud the design was authored against |
| `createdAt` | ISO date | |
| `chunking` | `{strategy, maxTokens, overlapPct}` | strategy: `FIXED_SIZE`, `SEMANTIC`, `HIERARCHICAL`, `NONE` (maxTokens/overlapPct ignored for `NONE`) |
| `embedding` | `{model, dimensions?}` | model id as the Studio lists it |
| `retrieve` | `{topK, searchType, hybridWeight, filter}` | searchType `HYBRID`/`SEMANTIC`; hybridWeight 0..1 = vector share; filter `{key,value}` or `null` |
| `rerank` | `{enabled, topN}` | topN must be < topK when enabled |
| `generate` | `{model, citations, groundingThreshold, guardrailId}` | groundingThreshold 0..1 |
| `clean` | `{piiScan, stripHtml, dedupe}` | |
| `store` | string | vector store label |
| `sources` | `[{bucket, prefix}]` | object-store location(s) (bucket = GCS bucket / Blob container on GCP/Azure) |
| `golden` | `[{question, expectedSources[], expectedAnswer}]` | evaluation set |

`validate(doc)` returns `[]` or a list of `path: message` problems. Cloud-specific request shapes (Bedrock `chunkingConfiguration`, rerank ARNs, ...) are NOT in the document; each cloud maps it in its own folder (AWS: `bedrockMap.js`).
