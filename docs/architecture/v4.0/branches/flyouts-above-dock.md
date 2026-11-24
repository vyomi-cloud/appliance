# v4/flyouts-above-dock

**Problem (owner screenshot, all clouds):** the services / navigation flyout (AWS "Recently visited / All services" panel, GCP nav drawer, Azure portal menu) ran down over the bottom dock (Spaces / Health / ...), covering its left end.

**Change:** `wasm/nano-mesh-drawer.js` — `fit()` publishes `--vy-dock` (px from the window bottom to the dock top) on `<html>`; CSS ends the flyouts there: AWS `.vy-dark-chrome[style*="position: fixed"]` (the header bar also carries `.vy-dark-chrome` as `position:relative`, so it is excluded), GCP `.MuiDrawer-paper` height, Azure `.vy-portal-menu` bottom. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Verified in Chrome (1440x900):** AWS panel bottom 868 -> 822 (dock top 822), header unchanged; GCP drawer paper 900 -> 822; Azure menu 900 -> 822. Test: `tests/conformance/test_mesh_drawer_push.mjs`.
