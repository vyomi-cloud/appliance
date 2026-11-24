# v4/mesh-expanded-border

**Change:** `wasm/nano-mesh-drawer.js` — an EXPANDED Vyomi Mesh drawer gets a 1px bottom border (`#vy-md.open{border-bottom:1px solid var(--md-line)}`), full width, so the console/side nav below it has a clear edge instead of looking like it has a margin. Collapsed stays borderless (v4.0.9). Applies to AWS, GCP and Azure (shared script). Cache-buster hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Test:** `tests/conformance/test_mesh_drawer_push.mjs` — the old "1px border is the only edge" check (red on trunk since v4.0.9) now asserts border when expanded, none on the root. All checks pass. Measured in Chrome (AWS EC2 Instances): expanded → `1px solid rgb(198,198,205)`; collapsed → none.
