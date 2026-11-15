# v4/aws-help-edge-trigger

Owner: Mesh session (Sudhir) - Started: 2026-11-15 - Base: origin/v4-on-main (996479893) - Status: ready for review, not merged

## Purpose
`v4/aws-help-overlay` (3f8825117) hid Cloudscape's built-in right-edge help toggle (`toolsHide`) and replaced the panel with a floating overlay, but left only the top-bar Help button to open it. The right-edge info icon the AWS console had disappeared.

## Change
`consoles/src/aws/App.jsx`: `HelpOverlay` takes `onOpen`; while closed it renders `#vyomi-help-toggle`, a 40x40 docked tab (info icon, rounded on the left, themed with the Cloudscape CSS variables) fixed to the right edge just below `#vyomi-top`. Clicking it opens the same overlay; it is replaced by the overlay while open and returns on close/Esc. The top-bar Help button is unchanged. Rebuilt `wasm/v4/aws`.

## Tests
Playwright against `consoles/nano_preview.mjs` (Nano bundle, no portal): toggle present and 40x40 at the right edge; click -> overlay; close button -> toggle back; Esc -> toggle back; top-bar Help still opens the overlay; no page errors. Not checked: dark mode, narrow viewport, GCP/Azure (they have no overlay).
