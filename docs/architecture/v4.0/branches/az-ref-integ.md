# v4/az-ref-integ

Integration of the Azure reference-architecture lanes (az-ref-ai, -gateway, -runtime, -messaging, -data, -app) for v4.0.9.

## Changes
- Merge of the six lane branches; conflicts resolved by keeping both sides (Foundry + Content Safety routes, AI Search wire + indexer capability entries, ARM `_sb_mirror` + Table 200 status); generated files (`mcp_*`, `wasm/core` mirrors) regenerated.

## Design decisions
- Lane 7 (Key Vault kid, Container Apps) merges when it lands.

## Open issues
- Full 13/13 run with a real model pending; trunk parity fix is PR #664.

## Capability ids introduced by the lanes (named here so the claims register can trace them)
- `azure.contentsafety.analyze-text` (az-ref-messaging)
- `azure.aisearch.wire` (az-ref-ai)
- `azure.aisearch.indexer.blob-fill` (az-ref-messaging)
- `azure.foundry.on-your-data` (az-ref-ondata)
