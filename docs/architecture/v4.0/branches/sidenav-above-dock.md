# v4/sidenav-above-dock

**Problem:** with the Vyomi Mesh drawer expanded the console is pushed down, but the side navs were still sized as if they started at the header, so on AWS (z-index above the dock) and GCP the nav ran under the bottom dock (Spaces / Health / ...), covering its left end and hiding the last nav items.

**Change:** `wasm/nano-mesh-drawer.js` `fit()` — measures the dock (`#vy-appbar .vy-notch`) and ends each side nav at its top: AWS `awsui_navigation-container` / `awsui_tools-container` height, GCP `nav.MuiBox-root` max-height, Azure resource blade `bottom` (was a fixed 44px). Runs on place(), scroll and resize. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Verified in Chrome (1440x900):** AWS EC2 Instances nav bottom 822 = dock top 822 (was 1163); GCP VM instances 822 (was 1166); after scrolling 400px both still end at/above the dock. **Azure not browser-verified:** it has no side nav on list pages; the blade fix needs a resource blade (e.g. an existing storage account) to confirm.
