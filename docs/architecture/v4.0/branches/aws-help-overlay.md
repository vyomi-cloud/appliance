# v4/aws-help-overlay

Owner: Azure session (Sudhir) - Started: 2026-11-14 - Base: origin/v4-on-main (96b140bf7) - Status: in progress

## Purpose
The AWS console help panel was a narrow Cloudscape tools column that pushed the page content. It is now an overlay that floats over the content, can be dragged wider and toggled to an expanded width, so long help reads comfortably.

## Architecture
`consoles/src/aws/App.jsx`: AppLayout uses `toolsHide`; a new `HelpOverlay` component (fixed, right-docked, below `#vyomi-top`, above the footer) renders the same HelpPanel content. Left-edge drag handle (min 320px, max 80vw, keyboard arrows nudge), expand/collapse button (65vw), close button and Esc. Width is remembered in localStorage (`vyomi.v4.helpW`). The top bar Help button still toggles it. Built output in `wasm/v4/aws`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Own fixed overlay | Cloudscape `tools` slot | The slot always reserves a column and reflows content; overlay was the requirement |

## Open issues
- [ ] Not verified in a real browser (build only); check drag, expand, Esc, dark mode (owner: Azure session)
- [ ] Per-service Info links, if any are added later, should call setToolsOpen(true)

## Testing
`node build.mjs` succeeds. No browser run yet.
