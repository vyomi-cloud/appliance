# Branch v4/mcp-matrix-harness

`scripts/gen_mcp_matrix.py --check` failed on the trunk with `rendering snippets with wasm/nano-docs.js failed`: the Node render harness's stub context lacked `document.createElement`/`head`/`location`, which `wasm/nano-docs.js` now touches (Labs Validate "Try it" styles). The same stubs were already fixed on `release/v4.1.0` and `main` but never reached `v4-on-main`.

- `scripts/gen_mcp_matrix.py`: ported the fixed `_NODE_RENDER` context from main.
- `cmd/vyomi/mcp_{matrix.json,caps.json.gz,docs.json.gz}`: regenerated (nano-docs.js changed on the trunk after the release).

Verified: `python3 scripts/gen_mcp_matrix.py --check` passes.
