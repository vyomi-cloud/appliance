# v4/mesh-drawer-push

**Owner ask:** the "Vyomi Mesh" top drawer on the Nano consoles should be expanded by default, must not overlap the console (it pushes the view down) and must not have a shadow.

**Files:** `wasm/nano-mesh-drawer.js` (the one shared script; v4 AWS / GCP / Azure pages), the three `wasm/v4/{aws,gcp,azure}/index.html` cache-busters (`?v=` = sha256[:12] of the script, same rule `consoles/build.mjs` applies), `tests/conformance/test_mesh_drawer_push.mjs`.
`clouds.html`, `index.html` and the classic `*-console.html` pages do not carry this drawer (no include), so nothing changed there.

## Before
- Closed by default: `open = LS("g") === "1"`, so a first visit saw a collapsed drawer.
- `#vy-md` was `position:fixed` under the header, so the open panel **covered** the console; the tab pill hung 8px/40px over the page content; the open panel had a drop shadow (`--md-shadow`, bigger on GCP/Azure), GCP's pill an elevation shadow.

## After
- **Default expanded**: `open = LS("g") !== "0"`. The remembered per-cloud state stays (`vyomi.meshDrawer.<cloud>`): a user's explicit collapse (`"0"`) is kept across loads; a fresh user, or one who last left it open, sees it expanded.
- **Pushes, never overlaps**: the drawer is a normal-flow element inserted as the next sibling of the console header (`place()` re-inserts it if React re-creates the header; fallback: top of `<body>`). It takes real height, so:
  - AWS (`#root > #vyomi-top + div`, document scroll): the page below starts under the drawer and the page grows.
  - GCP (min-height:100vh flex column): the content area starts under the drawer; the document scrolls (one scrollbar).
  - Azure (`.vy-app` flex column, `main.vy-main` flex:1 with its own scroller): `main` shrinks, page height unchanged.
- The tab row now has real height (`--md-bh + 8px`) instead of floating over the console, so collapsed = a 41-45px slim bar (handle + 1px border), not 0.
- **No shadow**: every shadow variable is `none`, the panel/pill rules no longer set one, and a final `#vy-md,#vy-md *{box-shadow:none!important}` + `filter:none` guards it. The only edge is `border-bottom:1px`.
- `--mesh-drawer-h` (ResizeObserver) publishes the drawer's height on `<html>` for any shell that wants it.
- Panel body max-height `min(56vh, 100vh - 220px)` (was `100vh - 150px`, sized for an overlay) so an expanded drawer cannot take the whole viewport of a pushed layout.
- Unchanged: what the drawer shows (welcome, video banner, Global Mesh card), the Mesh logic, the wait-for-`vyomi-nano-ready` spinner, no new splash.

## Verification
Real Chrome (Playwright-core + system Chrome), `wasm/` served statically, aws/gcp/azure x 1440x900 and 390x844: expanded on first load, header above drawer above content (content top >= drawer bottom, expanded and collapsed), collapse/re-expand, computed `box-shadow`/`filter` = none, no new horizontal scroll (the 390px consoles already scroll sideways at baseline: 860/654/712px wide, unchanged), no page errors. Static contract: `node tests/conformance/test_mesh_drawer_push.mjs`.

## Notes / risks
- The drawer is injected into React-owned containers; `place()` (1.5 s) repairs it if the header is re-created.
- Someone who previously collapsed the drawer keeps it collapsed (stored `"0"`); everyone else now starts expanded.
- On phones the expanded drawer is up to ~56% of the viewport; users collapse it with the tab.
- The portal's vendored Nano bundle (`app/nano`) picks this up only through the usual Nano sync at the next release.
