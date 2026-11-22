# v4/mesh-tab-on-border

**Change:** `wasm/nano-mesh-drawer.js` — with the drawer EXPANDED the "Vyomi Mesh" tab sits on the drawer's bottom border with a flat bottom edge (rounded top corners, overlapping the 1px line by 1px). It mirrors the collapsed tab (flat top, rounded bottom, hanging from the header). All three consoles (shared script); cache-buster hashes updated.

**Test:** new check in `tests/conformance/test_mesh_drawer_push.mjs`; measured/screenshotted in Chrome on AWS EC2 Instances.
