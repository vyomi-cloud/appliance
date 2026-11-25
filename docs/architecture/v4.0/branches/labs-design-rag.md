# v4/labs-design-rag

Owner: claude (Vyomi Labs session) - Started: 2026-11-26 - Base: origin/v4-on-main (0e35f9a33) - Status: in progress

## Purpose
Add Vyomi Labs chapter "Design the RAG" (layer id 14, built right before Knowledge Pipeline) where the learner designs a RAG in the cloud's RAG Studio, validates it on the golden set and saves a `vyomi.rag-design/v1` JSON. Later chapters (Knowledge Pipeline, Knowledge Search, Response Generation, Agent, Models) read it through a `rag_design.py` loader; defaults equal today's constants so behaviour is unchanged without the file.

## Architecture
See docs/architecture/v4.0/branches/vyomi-labs.md. Touches vyomilabs/content/*, vyomilabs/deployer.py, wasm/labs/labs.js, generated wasm/labs/data|img|project and courses/.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| ORDER = [10,3,7,14,12,6,11,9,4,5,1,2,8,13] | append at end | design precedes ingestion |
| Loader deep-merges file over DEFAULTS, bad values warn and fall back | fail hard | labs must never crash on a bad file |

## Open issues
- [ ] Portal Mesh route /mesh/labs/deploy/<cloud>/<layer> (portal repo) must accept id 14 and the new ORDER (owner: portal session)
- [ ] GCP/Azure RAG Studios are being built on v4/rag-studio-gcp-azure; chapter text is written to be true for all three

## Testing
see below (updated at end)
