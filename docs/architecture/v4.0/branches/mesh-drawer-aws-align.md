# v4/mesh-drawer-aws-align

**Problem:** on AWS service pages the Vyomi Mesh drawer spanned the whole window (24px gutters) while AWS's content column is centred and capped at 1280px, so on wide windows the drawer's right edge was far past the cards below (1896 vs 1741 at 1920px). GCP and Azure were fine.

**Change:** `wasm/nano-mesh-drawer.js` `place()` — with the side nav open, the drawer's right padding (`--md-pr`) = window width minus the breadcrumb row's right edge (the row spans the content column), min 24px. Left edge unchanged (24px, the nav's gutter). Home page and GCP/Azure unchanged. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Measured in Chrome:** 1920px: drawer 24..1740 vs cards 461..1741 (was 24..1896); 1440px: 24..1416 = cards right 1416 (unchanged); 1280px: 24..1256 (unchanged).

**Follow-up (owner: still misaligned on larger screens):** (1) service pages: when the content column is capped and floats clear of the nav (wide windows) the drawer also takes the column's LEFT edge (`--md-pl`), so it is exactly as wide as the cards below; narrower windows keep the nav gutter. (2) Console Home: the content wrapper is 1280px up to ~2000px but 1620px at 2560+, so the drawer width (`--md-cw`) is now measured from `main > div` instead of fixed at 1280.

**Measured in Chrome (drawer banner vs cards):** EC2 1920: 461..1740 vs 461..1741; 2560: 611..2230 vs 611..2231; 3440: 1051..2670 vs 1051..2671; 1440: 24..1416 vs 305..1416 (nav+content, unchanged). Home 2560: 470..2090 = content (was 640..1920); 3440: 910..2530.
