# v4/nav-behind-dock

**Replaces** the height-capping in `sidenav-above-dock` / `flyouts-above-dock` (owner: "awkward — a margin below the sidenav; keep it full height and let it go BEHIND the drawer").

**Change:** side navs and services flyouts run full height again, and the bottom dock is drawn on top of them. `wasm/vyomi-appbar.js`: `#vy-appbar` z-index 70 -> 1600 (above AWS flyout 1500, GCP drawer 1200, AWS nav 830, Azure menu 150; below the 3000+ modals); AWS nav/tools container height `100vh - 40px` (was capped at the dock top); Azure blade `bottom:0` (was 44px). `wasm/nano-mesh-drawer.js`: the `fit()` / `--vy-dock` code and flyout CSS removed. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Verified in Chrome (1440x900):** AWS EC2 nav box 347..1207 (full height) with the dock drawn over it; AWS services flyout runs to the bottom with the whole dock in front; GCP/Azure flyouts full height. Test: `tests/conformance/test_mesh_drawer_push.mjs`.
