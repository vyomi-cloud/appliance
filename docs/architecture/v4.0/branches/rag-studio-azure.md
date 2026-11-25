# v4/rag-studio-azure

Owner: claude (rag studio azure) - Started: 2026-11-26 - Base: origin/v4/rag-studio-gcp-azure (foundation) - Status: in progress

## Purpose
RAG Studio inside the Azure v4 console (AI Search > RAG Studio): Design / Validate / Test / Corpus (pre-RAG) / Query analysis (post-RAG), live against the simulator's Azure AI Search + Azure OpenAI, or the in-browser fake. Reads/writes `vyomi.rag-design/v1` (cloud = "azure").

## Architecture
- Console: `consoles/src/azure/services/aisearch/studio/` (own kit, not Cloudscape); `backend.js` implements `common/ragstudio/adapter.js` over `aisearch/api.js`.
- Backend: inspect API `/_vyomi/azure/search/{svc}/indexes/{ix}/chunks|retrieve-trace` in `core/azure_search_core.py`; Azure OpenAI chat "on your data" in `core/azure_cognitiveservices_core.py`.
- Vendored Nano copies via `python3 wasm/build_cores.py` only.

## Design decisions
| Decision | Rejected | Why |
|---|---|---|
| Studio is a page of the existing aisearch service | new service id | keeps inventory/IAM gates green |
| Additive only to common/ragstudio | edits | GCP branch works in parallel |

## Open issues
(see end of branch work)

## Testing
(filled at the end)
