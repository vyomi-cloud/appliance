# v4/mesh-rename-visible

Owner: integrator session - Started: 2026-11-10 - Base: origin/v4-on-main (a3d4e320) - Status: in progress

## Purpose
Product name is Vyomi Mesh, not mesh. This branch renames the words people read (console descriptions, model-availability labels, README, Codespace display name). Internal identifiers stay (core/mesh*.py, /api/mesh, MESH_* env, DB tables, .devcontainer/mesh/ path, stored data values such as space.home.type) and move later with aliases.

## Architecture
scripts-free: prose-only regex over consoles/src, README files, a few hand-written wasm scripts; generated catalogue label changed in core/ai_model_catalog.py and consoles ai-model-catalog.json regenerated; two conformance tests updated.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Rename visible prose only, per user choice 'Visible names first' | Mass rename incl. identifiers | Stored values (space.home.type), routes and DB tables would break live data |

## Open issues
- [ ] Internal identifiers (modules, routes, env vars, tables, sandbox path) still say mesh
- [ ] Built wasm bundles were NOT regenerated; UI strings in wasm/v4 bundles update on the next consoles build
- [ ] docs/architecture design docs keep the old word

## Testing
test_ai_model_catalog 24 passed; test_gcp_vertex_core 53 passed. No browser check.
