# v4/dock-mobile-fit

**Problem (owner, mobile):** the bottom dock (Spaces / Health / ... / Marketplace) did not fit the screen and scrolled sideways: the notch is `position:absolute` with `width:auto` plus 44px side padding, so on a phone it was wider than the viewport (e.g. 568px box in a 520px window).

**Change:** `wasm/vyomi-appbar.js` — at max-width 640px the notch is `left:0;right:0` (exactly the viewport width), flat (no clip-path slants), icons spread with `space-between`, separators hidden, tighter padding, Marketplace shown as an icon. Desktop layout unchanged. Hashes in `wasm/v4/{aws,gcp,azure}/index.html` updated.

**Measured in Chrome (AWS, GCP):** 640, 430, 390, 360, 320px: notch = [0, viewport], every icon inside. Test: `tests/conformance/test_mesh_drawer_push.mjs`.
