# v4/mesh-tab-no-gap

**Problem:** on AWS service pages the Vyomi Mesh tab row stayed 40px tall when the drawer was collapsed, so the side navigation's vertical divider started 40px below the console header.

**Change:** `wasm/nano-mesh-drawer.js` — with the side nav open and the drawer collapsed (`#vy-md.c-aws.nav:not(.open)`) the tab row is 0px tall and the "Vyomi Mesh" tab hangs from the header edge. Expanded drawer, Home page (no side nav), GCP and Azure are unchanged. Cache-buster hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Test:** `tests/conformance/test_mesh_drawer_push.mjs` (new check). Measured in Chrome on `#/ec2/instances`: collapsed, nav top = 40px (header bottom), drawer height 0.
