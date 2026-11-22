# Hosted Vyomi MCP: design

Status: proposal, not approved · Written 2026-11-22 against `v4-on-main` @ `5d042d5f6` · Owner: Rohith
Related: `AGENT-DISTRIBUTION-NOW.md` (the "Later" phase lists a hosted MCP), `integrations/claude-plugins/SUBMISSION.md` §0,
`HUMAN-GATES.md` G9.

## 1. Why

- **The Claude directory refuses the plugin today.** It accepts MCP servers that run on the user's computer only from
  Verified organizations (finding (a), G9). A server Claude reaches at a public HTTPS URL is accepted from any
  organization. Validate on 2026-11-22 (`d9fb835`, plugin 4.2.1) left exactly that one block.
- **A local server never reaches claude.ai or Cowork.** The directory notes it: "Local MCP server: not on claude.ai". A
  remote server works there, and in Claude Code, Codex, Cursor and Copilot.
- **It needs no Node.js, npx or tunnel install** for the knowledge part.

If Anthropic grants G9, the local plugin is accepted as it is, and this design is about claude.ai reach only. Decide
D-H1 (§11) with that in mind.

## 2. Goals and non-goals

Goals:
- A remote MCP server at `https://mcp.vyomi.cloud/mcp` that the directory accepts from an unverified organization.
- The same user experience as the local plugin for "Set this project up to run against Vyomi": find the simulator,
  scan, propose `.env.vyomi`, propose the `AGENTS.md` section, write nothing without a yes.
- No new data on our side beyond what each call needs; nothing stored by default.
- Same tool names and annotations where behaviour is the same, so skills and docs stay shared.

Non-goals:
- Replacing the local plugin. `plugins/vyomi` (npx) stays the default for marketplace installs; it sees more and works
  offline.
- Reaching the user's localhost from our servers. A hosted server never connects to the user's machine (§4).
- Running the simulator in the cloud. This is about the MCP only.

## 3. What exists (facts this design builds on)

| Piece | Today | Where |
|---|---|---|
| MCP server | Go, JSON-RPC over stdio: `serve(os.Stdin)` -> `handleLine` -> `handleMessage(raw)`. `handleMessage` does not depend on the transport | `cmd/vyomi/mcp.go` |
| Tools | 9: 8 read-only + `vyomi_write_env`; every tool has a title, `readOnlyHint`/`destructiveHint` set; surface pinned | `cmd/vyomi/mcp_tools.go`, `mcp_guardrails_test.go`, `tools/guardrails/run.sh` |
| Knowledge | Embedded with `go:embed`: `mcp_matrix.json`, `mcp_caps.json.gz`, `mcp_docs.json.gz`; generated from the appliance | `cmd/vyomi/mcp_knowledge.go`, `mcp_caps.go`, `scripts/gen_mcp_matrix.py` |
| Home detection | Probes `127.0.0.1:8090/health` (Nano tunnel), `127.0.0.1:9000/healthz` (mesh/appliance), `VYOMI_ENDPOINT` (relay); runs `vyomi-tunnel list mesh --json` when credentials exist | `cmd/vyomi/mcp_homes.go` |
| Scan | Walks the project, matches per-language line rules (Python, Node.js, Java, Go, Terraform), returns `file:line` hits per service | `cmd/vyomi/mcp_scan.go` |
| Relay | Cloudflare Worker `vyomi-nano-relay` on `relay.vyomi.cloud`, Durable Object `RelaySession` | `wasm/relay/worker.js`, `wrangler.toml` |
| Portal | FastAPI on DigitalOcean App Platform (deploys on every portal `main` merge, paid) | `vyomi-cloud/portal` |
| Portal auth | An OAuth **client** (Google, GitHub, LinkedIn, email); HMAC-signed access keys (`POST /api/tunnel/session`); JWT minting (`jwt_signer`); an approve-in-browser flow for appliances (`/activate`). It is **not** an OAuth authorization server for third parties | portal `app/oauth.py`, `app/tunnel_credentials.py`, `app/activate.py` |
| Mesh sessions | Rows in the portal DB (`mesh_session`), Ed25519 session tokens; the portal knows each user's Codespace mesh | portal `app/mesh_session.py` |
| Nano relay session | Its id lives only in the browser (`localStorage` `nano_session`); the portal does not know it | portal `app/docs_routes.py` |

## 4. The constraint, and the split

A server on vyomi.cloud cannot see the user's machine: not `127.0.0.1`, not the project's files, not the file system to
write `.env.vyomi`. So the hosted server **supplies knowledge and proposals, and the agent does the local steps with its
own tools** (Read, Grep, Bash, Edit), as the skills tell it. `vyomi_agents_md` already works this way: it proposes, and
the agent applies after a yes.

| Tool | Hosted behaviour | Local step the agent does | What the server receives |
|---|---|---|---|
| `vyomi_services` | Same | none | cloud name |
| `vyomi_capability` | Same | none | the search text |
| `vyomi_snippet` | Same, for a home the agent names | none | cloud, service, operation, home |
| `vyomi_env` | Same, for a home the agent names (`nano`, `mesh`, `appliance`, or a relay URL the user gives) | none | cloud, language, home |
| `vyomi_scan_repo` | Split in two (below) | Runs the returned rules with Grep over the project | rule ids with `file:line`; **no file contents, no matched text** |
| `vyomi_write_env` | Becomes **`vyomi_env_file`**: returns the proposed `.env.vyomi` text, writes nothing | Writes the file with its edit tool after a yes | cloud list, home |
| `vyomi_agents_md` | Same proposal, from text the agent passes in | Reads `AGENTS.md` / `CLAUDE.md`, passes their text; applies after a yes | the current text of those files (they are meant to be committed and shared) |
| `vyomi_status` | Account view (signed-in users, §6 phase 2): tier, Codespace mesh state from `mesh_session` | Checks the local homes itself: `curl -s 127.0.0.1:8090/health`, `curl -s 127.0.0.1:9000/healthz`, or `vyomi-tunnel list --json` | nothing about the local machine |
| `vyomi_reach` | Account view: the Codespace mesh and its forward commands | Runs the forward commands the user approves | nothing about the local machine |

**Scan, in two calls, without sending code:**
1. `vyomi_scan_rules(languages)` returns the scan rules: id, language, file globs and a regular expression, from the
   same table `mcp_scan.go` uses.
2. The agent runs them locally (Grep, which every agent has) and calls `vyomi_scan_report(hits: [{rule, file, line}])`.
   The report maps rule ids to services, adds coverage and warnings for the home, and returns the same shape as today's
   `vyomi_scan_repo`.

File paths and line numbers do reach the server, so the privacy policy and the plugin README must say so (§8).

**Writers:** the hosted server has **no** writer. Its surface is 9 or 10 read-only tools (D-H5), which keeps it simpler
than the local guardrail (8 + 1).

## 5. Architecture

```
agent (Claude Code, claude.ai, Cowork, Codex, Cursor, Copilot)
   │  Streamable HTTP, JSON-RPC over POST (HTTPS)
   ▼
mcp.vyomi.cloud/mcp ── Go `vyomi mcp --http` (stateless; knowledge embedded)
   │  phase 2 only: token check, account lookups
   ▼
vyomi.cloud (portal): OAuth authorization server, mesh_session, tiers
```

- **Transport: Streamable HTTP.** One endpoint takes `POST` with a JSON-RPC message and answers `application/json`. No
  server-sent events are needed: no tool streams or calls back. Stateless, with no session id, so any instance can
  answer. It honours the `MCP-Protocol-Version` header and returns `405` for `GET` (no SSE stream).
- **Code reuse:** a new `--http :PORT` flag on `vyomi mcp` wraps the existing `handleMessage(raw)` in an `net/http`
  handler. Tool code stays shared. A build tag or a `hosted` mode turns off the tools that touch the local machine
  (`homeProbe`, `runTunnelList`, file walks, file writes) and turns on the hosted variants from §4. A test pins which
  tools each mode exposes.
- **Never fetch a URL the caller supplies (SSRF).** Unlike the local server, the hosted one must never probe a host
  named in a request. `home: <relay URL>` is used only to render settings; the server does not connect to it.
- **Hosting (D-H2):**

| Option | For | Against |
|---|---|---|
| **A. Separate DigitalOcean App Platform app**, one small container from the same Go build (recommended) | Same vendor as the portal; reuses the Go code as is; deploys on its own trigger, not on portal merges | One more service to watch |
| B. Inside the portal app | No new app | Couples MCP uptime to portal deploys, and every portal merge is a paid deploy |
| C. Cloudflare Worker next to the relay | Cheap, global, already in use | Needs the Go server ported to JavaScript or WebAssembly; the knowledge files would have to fit Worker limits |

- **Versioning:** the hosted server reports `serverInfo.version` = the appliance knowledge version it was built from.
  It deploys from `v4-on-main` with the same gates as the tunnel (guardrails, Go tests). A release tag such as
  `mcp-hosted-vX` keeps deploys deliberate.

## 6. Auth, in phases

- **Phase 1: anonymous.** The knowledge, scan and proposal tools need no account, so phase 1 has no sign-in and
  stores nothing. The directory requires OAuth only for a remote server that connects to a remote service and needs
  authentication (policy 5D), which phase 1 does not. Abuse control: per-IP rate limits and request size limits (the
  scan report and the `AGENTS.md` text are the large inputs).
- **Phase 2: OAuth 2.1 with the portal as the authorization server**, for account-aware tools (tier, Codespace mesh).
  It follows the MCP authorization spec:
  - `mcp.vyomi.cloud` serves protected-resource metadata (`/.well-known/oauth-protected-resource`) naming
    `vyomi.cloud` as its authorization server. Unauthenticated calls to account tools get `401` with
    `WWW-Authenticate`.
  - `vyomi.cloud` adds authorization-server metadata (`/.well-known/oauth-authorization-server`), an authorization
    endpoint (authorization code + PKCE) and a token endpoint. It supports dynamic client registration, so Claude and
    other clients can register without a manual step.
  - The consent page reuses the portal's existing sign-in (Google, GitHub, LinkedIn, email), as `/activate` does.
  - Tokens: short-lived access tokens (JWT from the existing `jwt_signer` key, audience `https://mcp.vyomi.cloud`),
    one scope `vyomi.read`, and refresh tokens the user can revoke from the account page.
  - Effort: this is the largest single piece. It is a new security surface on the portal and needs its own review and
    guardrail rows.
- **Phase 3: Nano through the relay.** For the hosted server to report on a user's Nano tab, the portal would have to
  know the tab's relay session. Today only the browser knows it. Binding it to the account (the tab registers its
  session with the portal) is a product change with privacy questions; leave it out until there is a need.

## 7. Packaging

- Keep `plugins/vyomi` (local, `npx -y vyomi-tunnel@<pin> mcp`) for every marketplace install.
- Add `plugins/vyomi-cloud` (name: D-H4) in `vyomi-cloud/claude-plugins`:
  - `.mcp.json`: `{"mcpServers": {"vyomi": {"type": "http", "url": "https://mcp.vyomi.cloud/mcp"}}}`. Phase 2 adds
    `oauth` fields only if Claude's discovery needs them.
  - The same three skills. To avoid two copies drifting, each skill branches on the tools it finds: with
    `vyomi_status` (local), the current steps; with `vyomi_scan_rules` (hosted), the local Grep/curl/Edit steps. One
    source; `check_agent_plugins.py` checks both folders.
  - A README in the folder disclosing the host, what each tool receives (§8), and that nothing is stored.
- Submit **only `plugins/vyomi-cloud`** to the directory: one submission per folder. The local folder stays
  installable from the marketplace for everyone.
- The MCP Registry can list the remote server too (`remotes` in `server.json`) beside the npm package.

## 8. Data handling and disclosure

| Input | From | Kept |
|---|---|---|
| Tool arguments (cloud, language, home, search text) | every call | Not stored. Request logs keep method, tool name, status and latency only, for 30 days (proposed, D-H6) |
| Scan report: rule ids, file paths, line numbers | `vyomi_scan_report` | Not stored, and not logged |
| `AGENTS.md` / `CLAUDE.md` text | `vyomi_agents_md` | Not stored, and not logged |
| Account id, tier, mesh state | phase 2 token | Read from the portal per call; not copied |

- The privacy policy (https://vyomi.cloud/privacy) must describe the hosted MCP before launch. That is a legal-page
  change and a human gate.
- No telemetry beyond the request log above.
- The plugin README and the directory listing link the privacy policy and state the table above.

## 9. Directory and policy checklist for the hosted server

| Policy item | Plan |
|---|---|
| 5A Graceful errors | JSON-RPC errors with the fix in the message (the local server's style) |
| 5B Frugal tokens | Same outputs as the local tools; the scan report caps hits per service (`scanMaxHits`) |
| 5C Tool names <= 64 chars | Yes |
| 5D OAuth 2.0 when auth is needed | Phase 1 has none; phase 2 uses OAuth 2.1 (§6) |
| 5E Annotations | Every tool `readOnlyHint: true`, a title, no writer |
| 5F Streamable HTTP | Yes (§5) |
| 3A Privacy policy link | Update before launch (§8, human gate) |
| 3B Contact and support | support@vyomi.cloud; `SECURITY.md` |
| 3C Documentation | The plugin README and the portal `/docs/agents` page |
| 3D Test account with sample data | Phase 1: none needed (anonymous). Phase 2: a Free account with a stopped Codespace mesh record |
| 3E Three working prompts | "Set this project up to run against Vyomi."; "Which AWS services does Vyomi emulate on Nano?"; "Show me how to call SQS on Vyomi from Python." |
| 3F Own the endpoint domain | `vyomi.cloud` |
| Remote MCP `https` URL | `https://mcp.vyomi.cloud/mcp` |

## 10. Plan

| Phase | Delivers | Size | Clears |
|---|---|---|---|
| 0 | This doc approved; D-H1–D-H6 decided | — | — |
| 1a | `vyomi mcp --http` with hosted mode, scan rules/report split, `vyomi_env_file`; tests and guardrail rows for the hosted surface (no writer, no outbound fetch of caller URLs) | M | — |
| 1b | DigitalOcean app on `mcp.vyomi.cloud`, deploy workflow on a tag, rate limits, uptime check | S | — |
| 1c | `plugins/vyomi-cloud` folder, skills branching on tools, README, drift-check support | S | — |
| 1d | Privacy policy update (human), then directory Validate and submission (human) | — | Directory block (a) without G9; claude.ai and Cowork |
| 2 | Portal as OAuth authorization server; account-aware `vyomi_status` / `vyomi_reach` | L | Account features in the hosted plugin |
| 3 | Nano relay binding (only if wanted) | M | Nano status from the hosted server |

Phase 1 alone is enough for the directory. Phases 2 and 3 are optional.

## 11. Decisions needed

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D-H1 | Build now, or wait for G9 | Build phase 1 now / wait for Anthropic's answer | Ask Anthropic first (G9 costs nothing). Build phase 1 if G9 is refused, or if claude.ai/Cowork reach is wanted anyway |
| D-H2 | Hosting | A separate DO app / B inside the portal / C Cloudflare Worker | A |
| D-H3 | Phase 1 without sign-in | Anonymous / sign-in from day one | Anonymous: nothing account-specific is exposed in phase 1 |
| D-H4 | Folder and listing name | `vyomi-cloud` / `vyomi-remote` / other | `vyomi-cloud` (check the directory's look-alike rule against `vyomi`) |
| D-H5 | Hosted tool names | Keep `vyomi_scan_repo` with a new input shape / new `vyomi_scan_rules` + `vyomi_scan_report`; `vyomi_write_env` -> `vyomi_env_file` | New names: different behaviour should not hide behind the same name |
| D-H6 | Request logs | None / 30 days without arguments | 30 days without arguments, for abuse and uptime work |

## 12. Human gates

- Approving this doc and D-H1–D-H6.
- Creating `mcp.vyomi.cloud` (DNS) and the DigitalOcean app (billing).
- The privacy policy change.
- The directory submission of `plugins/vyomi-cloud`.
- Phase 2: the portal's authorization-server endpoints go live on portal `main` (a paid deploy).
