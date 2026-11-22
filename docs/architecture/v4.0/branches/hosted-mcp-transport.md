# v4/hosted-mcp-transport

Owner: claude (hosted MCP, PR 1) - Started: 2026-11-22 - Base: origin/v4-on-main (72bdafc36) - Status: in progress

## Purpose
PR 1 of `HOSTED-MCP-IMPLEMENTATION-PLAN.md`: the hosted Vyomi MCP server. One Go binary, two modes. The local stdio
server is unchanged; `vyomi mcp --hosted --listen :8080` serves a smaller, read-only tool set over Streamable HTTP
(JSON over `POST`, no SSE) so ChatGPT, claude.ai, Cowork, Claude Code, Codex, Cursor and Copilot can reach the Vyomi
knowledge by URL with nothing installed. It will be served at `https://vyomi.cloud/mcp` as a separate component in
the portal's DigitalOcean app (D-H2 = B'), behind a route that trims the `/mcp` prefix.

This PR carries the transport plus the four knowledge tools (`list_services`, `check_capability`,
`get_code_snippet`, `get_sdk_settings`). PR 2 (`v4/hosted-mcp-scan-proposals`, stacked on this branch) adds the scan
split and the proposal tools, taking the hosted surface to 8. PR 3 (deploy) and PR 4 (plugin folder) follow.

## Architecture
```
agent (claude.ai, ChatGPT, Cowork, Claude Code, Codex, Cursor, Copilot)
   |  Streamable HTTP: POST <base>, JSON-RPC in, application/json out
   v
vyomi.cloud/mcp  ->  App Platform trims /mcp  ->  `vyomi mcp --hosted` (stateless, knowledge embedded)
```

| File | What it holds |
|---|---|
| `cmd/vyomi/mcp.go` | `mcpServer.hosted`; `newHostedMCPServer()` (no `out`, HTTP clients on a transport that always errors); hosted `initialize` (`mcpHostedInstructions`, `serverInfo.title` "Vyomi", tools capability only) and empty `resources/*`; `--hosted` / `--listen` parsing in `runMCP` |
| `cmd/vyomi/mcp_http.go` (new) | `mcpHTTPServer`: the path set (D-I6), body cap, batch rejection, notifications, `Origin` and `MCP-Protocol-Version` checks, per-request timeout, `recover()`, graceful SIGTERM |
| `cmd/vyomi/mcp_hosted_tools.go` (new) | `buildHostedTools()` and the four handlers; `hostedTarget()` applies `host` / `account` / `relay_url` to a named home |
| `cmd/vyomi/mcp_homes.go` | `namedHome(arg)` (pure: nano \| mesh \| offline, default nano) and `selectHome(arg)`, the per-mode resolver hook |
| `cmd/vyomi/mcp_ratelimit.go` (new) | In-memory token buckets keyed by a salted hash of the client address (D-I4: 60/min burst 20 per key, 50 req/s global) |
| `cmd/vyomi/mcp_log.go` (new) | One JSON line per request: time, HTTP method, path, JSON-RPC method, tool, status, latency, bytes. No arguments, no IPs (O-D4) |
| `cmd/vyomi/mcp_tools.go` | `toolEnv` split so `envResult()` is shared with `get_sdk_settings`; `selectHome` at the resolver call sites |
| `tools/mcp-hosted-smoke.sh` (new) | End-to-end smoke against a base URL (`http://localhost:8080/mcp` or `https://vyomi.cloud/mcp`) |
| `tools/guardrails/run.sh` | Hosted rows: surface pin, no outbound, no file access, HTTP limits, log hygiene |

Hosted handlers never call `probeHomes`, `getJSON`, `runTunnelList` or the probing paths of
`resolveHome` / `homeTarget`: `selectHome` routes to `namedHome` whenever `hosted` is set. A relay URL is rendered
into the generated settings and never fetched.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| One hand-written `http.HandlerFunc` switching on `r.URL.Path`, no `http.ServeMux` subtree patterns | `mux.Handle("/mcp/", ...)` | `ServeMux` answers `/mcp` with a 301 to `/mcp/`, and a redirect turns a client's POST into a GET. D-I6 needs `""`, `/`, `/mcp` and `/mcp/` to all take POST with no redirect |
| `selectHome()` hook on `mcpServer` (hosted -> `namedHome`, local -> `resolveHome`) | A separate hosted copy of each knowledge handler | Hosted and local answers are then identical by construction, which is what PR 2's parity tests assert; one hook instead of four forks |
| `Origin` allowlist: absent, `vyomi.cloud`, `www.vyomi.cloud`, loopback, plus `VYOMI_MCP_ALLOWED_ORIGINS` | Reject every `Origin` (plan's "allowlist: none by default") | Server-to-server clients send none, so the plan's intent holds; loopback keeps the MCP Inspector working and `vyomi.cloud` keeps a same-origin portal page possible. Any other browser origin is still 403 |
| `relay_url` is an explicit input of `get_sdk_settings` | Smuggling a URL through `host` | `host` is `host[:port]` in local mode; a separate, validated, https-only input makes "echoed, never fetched" testable |
| Rate-limit keys are `sha256(per-process salt || client address)`, truncated | Keying on the raw address | O-D4: no IP reaches memory beyond the hash or the log |

## Open issues
- [ ] PR 2 raises the hosted pin to 8 tools and updates the `run.sh` label (owner: this session, next branch)
- [ ] `packaging/tunnel/server.json` gets its `remotes` entry only after the first production deploy (PR 3) (owner: Rohith)
- [ ] `cmd/vyomi/{mcp.go,mcp_tools.go}` and `tools/guardrails/run.sh` are also claimed by `v4/agent-plugins`; the edits here are additive (a field, a resolver hook, a `toolEnv` split, new rows) (owner: Rohith to sequence the merges)

## Testing
Run on macOS (darwin/arm64), 2026-11-22, Go 1.27.1.

| What | Command | Result |
|---|---|---|
| Go suite | `go -C cmd/vyomi test -count=1 ./...` | `ok` (whole package, local pin included) |
| Guardrail suite | `WS_PKG=... PY=... bash tools/guardrails/run.sh` | the six new hosted rows PASS; every pre-existing row PASS except the Mesh boot-script row (see below) |
| Hosted server | `go -C cmd/vyomi build -o /tmp/vyomi . && /tmp/vyomi mcp --hosted --listen :8080` | serves 4 read-only tools, knowledge v4.0.10 |
| Smoke | `tools/mcp-hosted-smoke.sh http://localhost:8080/mcp` | 22/22 PASS |

One environment note, pre-existing and reproduced on `HEAD` without this branch's changes:
`tools/guardrails/check-boot-mesh.sh` fails on macOS with `sed: 1: ...: invalid command code ^` (BSD sed; the
script's address form needs GNU sed). It runs on `ubuntu-latest` in CI, where it is green. Untouched by this branch.

`TestMCPEnvRendersTargetAndWarnings` and `TestMCPScanRepo` used to fail on a machine with a `vyomi-tunnel`
listening on 127.0.0.1:8090, because they call tools with `home=auto` and the resolver then picked the real tab.
They are hermetic now: `probelessHomes(t)` points the home-choosing probes at ports nothing listens on while
keeping the rendering defaults, so the result no longer depends on what is running locally. Verified with the
tunnel up and no environment overrides.

Not run here: Docker, the real Docker stack, Nano on the localhost portal (:8099) — this PR is the HTTP transport
and embedded knowledge only, and the hosted server by construction reaches neither. The container, staging and
real-client checks are PR 3 and PR 4.
