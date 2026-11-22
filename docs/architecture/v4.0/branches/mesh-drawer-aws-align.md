# v4/mesh-drawer-aws-align

**Problem:** on AWS service pages the Vyomi Mesh drawer spanned the whole window (24px gutters) while AWS's content column is centred and capped at 1280px, so on wide windows the drawer's right edge was far past the cards below (1896 vs 1741 at 1920px). GCP and Azure were fine.

**Change:** `wasm/nano-mesh-drawer.js` `place()` — with the side nav open, the drawer's right padding (`--md-pr`) = window width minus the breadcrumb row's right edge (the row spans the content column), min 24px. Left edge unchanged (24px, the nav's gutter). Home page and GCP/Azure unchanged. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Measured in Chrome:** 1920px: drawer 24..1740 vs cards 461..1741 (was 24..1896); 1440px: 24..1416 = cards right 1416 (unchanged); 1280px: 24..1256 (unchanged).
