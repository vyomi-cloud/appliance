# v4/mcp-v4-knowledge

Owner: overnight Claude session for Rohith - Started: 2026-11-14 - Base: origin/v4-on-main (41161ac3e) - Status: in progress

## Purpose
Make `vyomi mcp` (the Go MCP server in `cmd/vyomi`) work for v4, where the simulator lives in a Nano browser tab, a local mesh
or a Codespace mesh, not only a Docker appliance on `:9000`. This branch carries these steps of
`vyomi-mcp-v4-implementation-plan.md` (owner's specs folder, outside the repo):
- D0 discovery, items 1 and 3: Nano SDK wiring through the local relay, and `vyomi-tunnel list --json`.
- K1–K2: knowledge v2, from `core/capabilities/**` and `wasm/docs/**`.
- H1–H3: home detection and home-aware tools.

Out of scope for this branch: distribution (T1/T2, `vyomi-tunnel mcp`), the plugin manifest, and release work.

## Architecture
- `docs/architecture/v4.0/MCP-V4-DISCOVERY.md`: D0 evidence (Nano SDK wiring through the local relay, `vyomi-tunnel list --json`).
- (K1–H3 sections are added as each step lands.)

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| D0 static server on `:8017` instead of `:8000` | stopping the process on `:8000` | `:8000` belonged to an unrelated local app and `:8001` to Docker; the harness takes `TAB_URL` |
| D0 item 3 run against a local fake portal with dummy env keys, `HOME`/`VYOMI_HOME` in a temp dir | reading the real key; calling vyomi.cloud | the session rules forbid both; this still exercises every `list` branch except a live Codespace |
| Regenerated `cmd/vyomi/mcp_matrix.json` in its own commit first | leaving `--check` red until K1 | the base was red only because `VERSION` moved to 4.0.0; every later commit must be green |

### Decisions taken unattended
(Defaults taken without the owner because the session ran overnight; each is reversible.)

## Open issues
- [ ] D0 item 2 (Codespace mesh API target) and item 4 (space semantics on a mesh) need a Pro/Max key and a Mesh Codespace (owner: Rohith)
- [ ] `vyomi-tunnel list --json` envelope is `{targets, notes}` with no `schema`; the spec says `{rows, notes}` + `schema: 1` (T1, owner: tunnel session)
- [ ] Nano `/health` lists RDS proxies under `vms[]`, never `dbs[]` (owner: tunnel session)
- [ ] Nano RDS Data API loses state between statements; `e2e-relay.mjs` step 7 fails on the trunk (owner: Nano core)
- [ ] No claim row in `SESSION-CLAIMS.md`: this branch edits only non-shared paths (`cmd/vyomi/**`, `scripts/gen_mcp_matrix.py`, `scripts/mcp_wiring.json`, docs), and the claims file lives on the trunk (owner: integrator, if a row is wanted)

## Testing
- Base (`41161ac3e`): `cd cmd/vyomi && go test ./...` 28 PASS / 0 FAIL; `python3 scripts/gen_mcp_matrix.py --check` red (stale version stamp only).
- D0: headless Nano tab via Playwright + local relay; real Python SDKs; results in `MCP-V4-DISCOVERY.md`. Not run: the local portal on `:8099` with the service worker, a real Chrome tab, the cloud relay.
