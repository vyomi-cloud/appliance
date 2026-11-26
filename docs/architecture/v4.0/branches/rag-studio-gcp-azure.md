# v4/rag-studio-gcp-azure

Owner: claude (rag studio reuse) - Started: 2026-11-25 - Base: origin/v4-on-main (b3c5bf98c) - Status: foundation done; GCP and Azure UIs are built by other branches

## Purpose
Make the AWS Bedrock RAG Studio reusable by the GCP and Azure consoles without changing AWS behaviour: move the cloud-neutral logic to `consoles/src/common/ragstudio/`, define the neutral design document `vyomi.rag-design/v1` and the adapter interface each cloud backend implements.

## Architecture
- `consoles/src/common/ragstudio/`: `engine.js` (tokenizer, chunking, BM25, hashEmbed, fusion, rerankScore, lintDesign, applyFix, metrics, PII/lang/duplicates, provenance, presets, defaults, golden set), `project.js` (UMAP), `fake.js` (`CORPUS`, `createFakeCore`: neutral retrieval/trace/ingest core), `document.js` (`toDocument`/`fromDocument`/`validate`), `adapter.js` (JSDoc interface + `checkAdapter`), `ragstudio.test.mjs` (`node --test`).
- AWS folder `consoles/src/aws/services/bedrock/studio/`: `bedrockMap.js` (designToApi/apiToDesign, Bedrock shapes), `fake.js` (core wrapped in bedrock shapes, retrieve/rag), `backend.js` (live wires), thin shims `engine.js` and `project.js` re-exporting the common code. AWS backends gained `listCorpora()` (alias of `listKbs`) to conform to the adapter.
- Spec: `docs/architecture/v4.0/RAG-DESIGN-DOCUMENT.md`.
- Adapter: `listCorpora/applyDesign/ingest/chunks/trace/retrieve/rag`, `mode` live|live-limited|fake, `label`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Neutral core + per-cloud wrapper; `designToApi`/`apiToDesign` stay in AWS | Moving them too | They are Bedrock request shapes (ARNs, chunkingConfiguration) |
| Re-export shims at the old AWS paths | Rewriting every import | Zero AWS behaviour change, small diff |
| Document keeps `golden` and `sources` inline | Separate files | One file for course chapters to read |
| Built outputs not committed here | Committing wasm/v4 | Rule 6: regenerated after the merge |

## Open issues
- [ ] GCP and Azure adapters + UIs (owner: other branches)
- [ ] Studio "export/import design document" buttons not wired in any console yet (owner: GCP/Azure UI branches; AWS follow-up)
- [ ] `createFakeCore` demo corpus is facilities-themed; a per-cloud corpus can be passed in

## Testing
- `cd consoles && node --test src/common/ragstudio/ragstudio.test.mjs`: 6/6 pass (document round-trip x3 clouds, validation, AWS mapping via shim, AWS fake conforms and answers, neutral core + metrics).
- `node build.mjs` succeeds (all three consoles). Headless Chrome against `consoles/dev_server.py` on port 8741 (not :8099): AWS `#/bedrock/knowledge-bases/studio` renders RAG Studio with the Design/Validate tabs and the backend banner, no page errors.
- Not run: live KB path with the inspect API, Playwright suites, GCP/Azure UIs.
