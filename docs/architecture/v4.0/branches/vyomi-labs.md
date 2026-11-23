# Branch v4/vyomi-labs (draft for owner review)

**Vyomi Labs**: a guided build of the 13-layer enterprise agentic AI app, once per cloud with that cloud's native services.
Branched from `origin/v4-on-main`. Draft: not merged, not released.

## What it is
- Entry: a "Vyomi Labs" item in the BOTTOM drawer (the app bar: Spaces, Health, Knowledge Center, Vyomi Labs, SDK & CLI usage, API reference) of the AWS, GCP and Azure v4 Nano consoles (`wasm/vyomi-appbar.js`, Nano only). It opens the same kind of view as the other items, showing the Labs pages for that console's cloud. `wasm/nano-mesh-drawer.js` (the top Vyomi Mesh drawer) is unchanged from trunk.
- Labs page: left = the reference diagram of the 13 layers (clickable); right = an e-book: a contents page of 13 chapter tiles, then one chapter at a time
  (learn, build it, how it fits, how it is checked, what the simulator simplifies, reference solution), with previous/next. Progress is kept in the browser.
- Three courses, same 13 layers and build order (10,3,7,12,6,11,9,4,5,1,2,8,13): AWS (Bedrock), Google Cloud (Vertex AI), Azure (Azure OpenAI / Foundry).
  Every step is something the reference app in `examples/enterprise-facilities-agent` does for that cloud. Where a cloud has no native equivalent it says so
  (Azure: no managed long-term memory, no Cedar, no hosted agent runtime; GCP and Azure approval is assembled from parts).
- Source of truth for the text: `vyomilabs/content/build_courses.py` -> `wasm/labs/data/*.json`. The diagrams are our own artwork (own icons, palette and layout; no third-party image is embedded), drawn per cloud by `vyomilabs/content/build_diagrams.py`, which also emits the click hotspots.
  (`vyomilabs/content/build_diagrams.py`) with the same geometry.
- Optional local server `python -m vyomilabs serve` (and `python -m vyomilabs.demo` with a pre-built simulator) adds a Check button; checkers exist for AWS layers 2 and 10 only.

## Verified here
- Labs page rendered for all three clouds; drawer card + dialog exercised with the real drawer script (harness page) for the three clouds.
- 16 unit tests (content integrity x3 clouds, reference files exist, API). AWS checkers 2 and 10: PASS on the reference run, FAIL on an empty simulator.

## Not verified / not done
- Not seen inside the booted v4 consoles (the in-browser Python runtime did not boot headless); `wasm/v4/*/index.html` only had the drawer script hash refreshed, as a rebuild would.
- Checkers for the other 11 AWS layers and for all GCP/Azure layers; the guides are outlines, not full tutorials; the AWS picture is the owner's, GCP/Azure are simplified drawings.
- No claims-register rows.

Rules: topic branch only; nothing to trunk, tags, portal or main without the owner's explicit go.
