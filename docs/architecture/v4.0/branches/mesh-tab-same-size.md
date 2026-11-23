# v4/mesh-tab-same-size

**Owner:** the collapsed "Vyomi Mesh" button was not the same size as the expanded one (all clouds).

**Cause:** on AWS/GCP service pages the collapsed tab hangs from the header and had a fixed `height:24px` and 12px radius; the expanded tab is `--md-bh` tall (AWS 32 / GCP 36 / Azure 32) with `--md-br` radius.

**Change:** `wasm/nano-mesh-drawer.js` - the hanging tab drops the fixed height and uses `var(--md-br)`: same box, only the corners flip (flat top when collapsed, flat bottom when expanded). Hashes updated.

**Measured (Chrome, 1440x900, expanded -> collapsed):** AWS 167x32 -> 167x32, GCP 161x36 -> 161x36, Azure 156x32 -> 156x32, on both Home and service pages (padding 20/20/16 and font 14px identical).
