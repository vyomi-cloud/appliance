# v4/gcp-nav-drawer

**Owner report (GCP service pages):** (1) the "Vyomi Mesh" row cut the side nav's top; (2) the Mesh drawer was narrower than the sections below; (3) collapsing the service nav left its expand (hamburger) button half cut off. **Rule given:** each console's Home keeps its own drawer width, but on service pages the drawer is edge to edge (E2E) - applied to AWS, GCP and Azure.

**Change:** `wasm/nano-mesh-drawer.js` - GCP detects its left nav (`nav.MuiBox-root`) and Azure any non-home route, setting the existing `nav` mode: drawer spans the page with its own gutters (AWS 24px, GCP 16px, Azure 20px); on GCP a collapsed drawer hangs from the header (tab row 0px) so the nav starts right under it; AWS Home width follows the real content column (1280 -> 1620px on very wide windows). `wasm/vyomi-appbar.js` - GCP collapsed nav: `Expand navigation` button shifted into the 64px rail. Hashes updated.

**Measured in Chrome (drawer banner vs page, 1440 / 1920):** AWS EC2 24..1416 / 24..1896; GCP VM instances 16..1424 / 16..1904; Azure storage 20..1420 / 20..1900; homes unchanged (AWS 80..1360, GCP 222..1218, Azure 194..1246 at 1440). GCP: drawer collapsed -> nav top 64 (was 108); nav collapsed -> toggle 18..47 inside the 64px rail (was 50..79).

**Follow-up (owner: hamburger overlaps the service icon):** shifting the Expand button into the rail put it on top of the service icon (both sat in one 48px row). `wasm/vyomi-appbar.js` now stacks them in the collapsed rail (`nav.MuiBox-root>div:has(>button[aria-label="Expand navigation"])` -> column): icon at y 74..96, button at 102..131, list starts at 137 (was 112). No overlap.
