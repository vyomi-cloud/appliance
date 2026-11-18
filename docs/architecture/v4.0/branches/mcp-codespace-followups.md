# v4/mcp-codespace-followups

Owner: Claude session for Rohith - Started: 2026-11-19 - Base: origin/v4-on-main (1d4964df3) - Status: in progress

## Purpose
Fixes found by testing vyomi-tunnel 1.3.0-rc.3 and the vyomi MCP against a real Mesh Codespace on the owner's Mac
(2026-11-18/19), and keeping the MCP's Codespace flow working under the Mesh software protection (f6674aa), which stopped the
tunnel from listing or forwarding Vyomi's own containers, including the simulator the MCP forwarded.

## Architecture
- `vyomi-tunnel forward api <local>:9000|9443` (`mesh-ssh.mjs` `resolve("api")`): the simulator's two API ports through the same
  fixed `compose simulator` lookup the console's API tunnel uses. Any other port on `api` is refused; core names (`simulator`,
  `vyomi-mesh-simulator-1`, `llm*`) get a message pointing at `forward api` instead of "not found".
- `list mesh` (both `mesh-cli.mjs` copies): an `api` service row when the simulator runs; one free local port per suggestion; a
  row whose target already has a live forward says `already forwarded: 127.0.0.1:<port>`; a forward registered for another
  Codespace is marked `STALE: for Codespace <x> ...; stop it: kill <pid>` (rows keep the schema-1 keys).
- `forward`: the local port is checked before the Codespace is asked; a gh/Codespace failure is reported as itself; a 404 for the
  Codespace says it was not found (deleted?) and to unset `VYOMI_MESH_CODESPACE` / `--codespace`.
- MCP (`mcp_homes.go`): the `api` row is the API target (older tunnels' service row on :9000 still works); STALE forward rows are
  never used and are listed in `detail.stale_forwards`; forward hints say `vyomi-tunnel forward api <free>:9000` / `:9443`;
  the `list mesh` probe limit is 20 s (7 s measured on an awake Codespace; 8 s was too tight).
- Skill `vyomi-mesh`: forward `api` only, report `stale_forwards`, quote a home's reason word for word.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| `api` = raw TCP to the simulator's ports 9000/9443 only (owner, 2026-11-19) | no laptop access to a Codespace Mesh; re-allow forwarding the simulator container | The API is the product; ports-only keeps the shell, files, other ports and llm* out of reach; raw TCP keeps streaming, WebSockets and TLS working |
| Staleness in `connect` text, not a new row key | a `stale` field | schema-1 rows have fixed keys (test-list-json contract) |
| 20 s probe limit, no extra cache | a 60 s cache | the 10 s home cache exists; a longer cache would hide a forward the user just started |

## Release
vyomi-tunnel 1.3.0 went to npm `latest` from the trunk (tag on 1d4964df3, 2026-11-18 18:34 UTC) with the protection but without
these fixes, so on 1.3.0 the MCP's Codespace hint points at a target the tunnel no longer forwards. This branch is **1.3.1**
(all version stamps) with plugin **4.1.1** (the vyomi-mesh skill changed; 4.1.0 is on the marketplace).

## Open issues
- [ ] Real-Codespace run of rc.4 (owner's Mac: `bash ~/Documents/specs/vyomi/codespace-check.sh`, which still uses the old
      target name until updated)
- [ ] Not done: LLM endpoints for laptop SDKs (`llm*` stay unreachable; Bedrock/Vertex/Azure OpenAI go through the simulator API)

## Testing
- Go 65/65 with `-race` (Go 1.25 locally; CI uses 1.26). `TestMCPHomesCodespaceAPIRow` fails on the trunk code.
- Node: launcher + list contract 16/16, incl. a fake live Codespace (fake gh + ssh) for the api row, distinct ports, "already
  forwarded" and the STALE flag (fails on the trunk code); transport tests for `api`, core names, the 404 message and the
  port-first order; relay suites (mesh-link, mesh-shell, mesh-gate, credentials, creds-widget, reset-portal, lazy-hub, keeper).
- Plugin validates; generator `--check`; shellcheck.
