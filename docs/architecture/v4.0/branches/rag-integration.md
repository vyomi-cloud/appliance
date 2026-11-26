# Branch v4/rag-integration

Integration of the RAG Studio work for review before the trunk. Merges, in order: `v4/mcp-matrix-harness` (render-harness stubs + regenerated MCP files), `v4/rag-studio-gcp-azure` (shared core `consoles/src/common/ragstudio/`, the `vyomi.rag-design/v1` document), `v4/rag-studio-gcp` (Vertex AI RAG Studio + `/_vyomi/gcp-rag/` inspect API), `v4/rag-studio-azure` (AI Search RAG Studio + inspect API + knowledge_core lock fix), `v4/labs-design-rag` (Vyomi Labs chapter 14 "Design the RAG", later chapters read `rag-design.json`).

Merge notes: only `SESSION-CLAIMS.md` conflicted (kept every row); `wasm/core/*` regenerated with `python3 wasm/build_cores.py` after the merge.

Not on the trunk: needs the owner's go. Built bundles (`wasm/v4/*`) are not committed (rule 6).
