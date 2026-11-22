# v4/dock-mobile-fit

**Problem (owner, mobile):** the bottom dock (Spaces / Health / ... / Marketplace) did not fit the screen and scrolled sideways: the notch is `position:absolute` with `width:auto` plus 44px side padding, so on a phone it was wider than the viewport (e.g. 568px box in a 520px window).

**Change:** `wasm/vyomi-appbar.js` — at max-width 640px the notch is `left:0;right:0` (exactly the viewport width), flat (no clip-path slants), icons spread with `space-between`, separators hidden, tighter padding, Marketplace shown as an icon. Desktop layout unchanged. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Measured in Chrome (AWS, GCP):** 640, 430, 390, 360, 320px: notch = [0, viewport], every icon inside. Test: `tests/conformance/test_mesh_drawer_push.mjs`.

**Follow-up (owner: AWS console cards not centred on a phone):** the AWS top bar's controls added up to ~860px, so on a phone the whole page was 860px wide (cards left-aligned in a wider page / sideways scroll). `wasm/vyomi-appbar.js` (AWS block, max-width 640px): bar clipped to the viewport, logo 92px, search takes the spare width, bell / help / settings / region hidden, account shows its icon only.

**Measured in Chrome at 390px:** page scrollWidth 860 -> 390 on Console Home and EC2 Instances; cards 20..370 (centred); wide tables scroll inside their own card.
