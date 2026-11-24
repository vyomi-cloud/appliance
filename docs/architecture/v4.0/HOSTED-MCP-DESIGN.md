# Hosted Vyomi MCP: design

Status: approved; D-H1–D-H6 decided 2026-11-22 (D-H5 refined by O-D2 verb names; build plan: HOSTED-MCP-IMPLEMENTATION-PLAN.md) · Written 2026-11-22 against `v4-on-main` @ `5d042d5f6` · Owner: Rohith
Related: `AGENT-DISTRIBUTION-NOW.md` (the "Later" phase lists a hosted MCP), `integrations/claude-plugins/SUBMISSION.md` §0,
`HUMAN-GATES.md` G9.

## 1. Why

- **The Claude directory refuses the plugin today.** It accepts MCP servers that run on the user's computer only from
  Verified organizations (finding (a), G9). A server Claude reaches at a public HTTPS URL is accepted from any
  organization. Validate on 2026-11-22 (`d9fb835`, plugin 4.2.1) left exactly that one block.
- **A local server never reaches claude.ai or Cowork.** The directory notes it: "Local MCP server: not on claude.ai". A
  remote server works there, and in Claude Code, Codex, Cursor and Copilot.
- **The OpenAI (ChatGPT/Codex) directory has the same wall, and a stricter one.** Its desktop-only guide says "Local
  MCP submissions are limited to approved partners": the submitting org must be allowlisted by an OpenAI
  representative, which Vyomi doesn't have. It also asks to "Include the server and its dependencies in the package",
  so the `npx` launcher wouldn't qualify even if allowlisted. Its default route is a remote server: "If your MCP server
  runs locally, deploy it to a public HTTPS URL." Every OpenAI submission also needs a verified individual or business
  identity on the OpenAI Platform (sources: developers.openai.com/plugins/deploy/desktop-only,
  developers.openai.com/codex/submit-plugins, read 2026-11-22).
- **Cursor doesn't need it.** cursor.directory has no documented organization or local-MCP rule, so the local plugin is
  submitted there as it is.
- **It needs no Node.js, npx or tunnel install** for the knowledge part.

If Anthropic grants G9, the local plugin is accepted by Claude as it is, but OpenAI and claude.ai/Cowork/ChatGPT
reach still need a remote server. D-H1 (§11) is therefore decided: build phase 1 now, and still send the G9 request.

## 2. Goals and non-goals

Goals:
- A remote MCP server at `https://vyomi.cloud/mcp` that the directory accepts from an unverified organization.
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
| `vyomi_scan_repo` | Split in two (below) | Runs the returned rules with Grep over the project | rule ids with `file:line` and the **captured service token** (regex group 1, e.g. `s3`); **no file contents and no matched text**. The token is what maps a hit to a service (D-I1); it is validated against `^[A-Za-z0-9_.\-/]{1,64}$`, so only an identifier is accepted. The "already wired" rule sends `file:line` alone — the local scan's clipped line text is never sent |
| `vyomi_write_env` | Becomes **`vyomi_env_file`**: returns the proposed `.env.vyomi` text, writes nothing | Writes the file with its edit tool after a yes | cloud list, home |
| `vyomi_agents_md` | Same proposal, from text the agent passes in | Reads `AGENTS.md` / `CLAUDE.md`, passes their text; applies after a yes | the current text of those files (they are meant to be committed and shared) |
| `vyomi_status` | Account view (signed-in users, §6 phase 2): tier, Codespace mesh state from `mesh_session` | Checks the local homes itself: `curl -s 127.0.0.1:8090/health`, `curl -s 127.0.0.1:9000/healthz`, or `vyomi-tunnel list --json` | nothing about the local machine |
| `vyomi_reach` | Account view: the Codespace mesh and its forward commands | Runs the forward commands the user approves | nothing about the local machine |

**Scan, in two calls, without sending code:**
1. `get_scan_rules(languages)` returns the scan rules: id, cloud, language, file globs, a regular expression and which
   capture group holds the service token, from the same table `mcp_scan.go` uses.
2. The agent runs them locally (Grep, which every agent has) and calls `summarize_scan_hits(home, hits: [{rule, file,
   line, token}])`, at most 2,000 hits per call. The report maps each token to a service through the same alias table
   the local scan uses, reports unknown tokens as unrecognized, adds coverage and warnings for the home, and returns
   the same shape as today's `vyomi_scan_repo`.

File paths, line numbers and the captured service tokens do reach the server, so the privacy policy and the plugin
README must say so (§8).

**Writers:** the hosted server has **no** writer. Its surface is 9 or 10 read-only tools (D-H5), which keeps it simpler
than the local guardrail (8 + 1).

## 5. Architecture

```
agent (Claude Code, claude.ai, Cowork, Codex, Cursor, Copilot)
   │  Streamable HTTP, JSON-RPC over POST (HTTPS)
   ▼
vyomi.cloud/mcp ── Go `vyomi mcp --hosted` (portal app component; stateless; knowledge embedded)
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
- **Hosting (D-H2, decided 2026-11-22: B′, same origin as the portal).** The server is a **separate service
  component inside the portal's DigitalOcean app**, routed by path: `vyomi.cloud/mcp` → the Go container, everything
  else → the portal. It runs from a **pinned private image** (`ghcr.io/vyomi-cloud/mcp-hosted:<version>`, `linux/amd64`; pulled with an encrypted `read:packages` token), not a source build, so
  portal deploys only re-pull the same image and an MCP build can never block a portal deploy. Why: `vyomi.cloud` is
  the most permanent origin (OpenAI treats a new origin as a new plugin), phase 2 OAuth is same-origin with the portal,
  no new DNS or app, same per-container cost. Trade-off: App Platform deploys all components together, so an MCP
  release (bumping the image tag) also redeploys the portal's current `main`, and a failed component rolls the whole
  app back. Cloudflare in front of `vyomi.cloud` needs a rule that lets `/mcp*` through bot protection.

| Option | For | Against |
|---|---|---|
| A. Separate DigitalOcean App Platform app on `mcp.vyomi.cloud` | Independent deploys and rollbacks | New DNS and app; a second origin |
| **B′. Service component in the portal app, path `/mcp`, pinned image (chosen)** | Origin `vyomi.cloud`; no DNS; same-origin OAuth later | Deploys coupled at the app level; portal app spec changes |
| B. Inside the portal's FastAPI process | No new container | Rewrite in Python or proxy to Go; shared failures |
| C. Cloudflare Worker next to the relay | Cheap, global | Port Go to JS/Wasm; Worker limits |

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
  - `vyomi.cloud` (the portal, same origin) serves protected-resource metadata (`/.well-known/oauth-protected-resource`) naming
    `vyomi.cloud` as its authorization server. Unauthenticated calls to account tools get `401` with
    `WWW-Authenticate`.
  - `vyomi.cloud` adds authorization-server metadata (`/.well-known/oauth-authorization-server`), an authorization
    endpoint (authorization code + PKCE) and a token endpoint. It supports dynamic client registration, so Claude and
    other clients can register without a manual step.
  - The consent page reuses the portal's existing sign-in (Google, GitHub, LinkedIn, email), as `/activate` does.
  - Tokens: short-lived access tokens (JWT from the existing `jwt_signer` key, audience `https://vyomi.cloud/mcp`),
    one scope `vyomi.read`, and refresh tokens the user can revoke from the account page.
  - Effort: this is the largest single piece. It is a new security surface on the portal and needs its own review and
    guardrail rows.
- **Phase 3: Nano through the relay.** For the hosted server to report on a user's Nano tab, the portal would have to
  know the tab's relay session. Today only the browser knows it. Binding it to the account (the tab registers its
  session with the portal) is a product change with privacy questions; leave it out until there is a need.

## 7. Packaging

- Keep `plugins/vyomi` (local, `npx -y vyomi-tunnel@<pin> mcp`) for every marketplace install.
- Add `plugins/vyomi-cloud` (name: D-H4) in `vyomi-cloud/claude-plugins`:
  - `.mcp.json`: `{"mcpServers": {"vyomi": {"type": "http", "url": "https://vyomi.cloud/mcp"}}}`. Phase 2 adds
    `oauth` fields only if Claude's discovery needs them.
  - The same three skills. To avoid two copies drifting, each skill branches on the tools it finds: with
    `vyomi_status` (local), the current steps; with `get_scan_rules` (hosted), the local Grep/curl/Edit steps. One
    source; `check_agent_plugins.py` checks both folders.
  - A README in the folder disclosing the host, what each tool receives (§8), and that nothing is stored.
- Submit **only `plugins/vyomi-cloud`** to the directory: one submission per folder. The local folder stays
  installable from the marketplace for everyone.
- The MCP Registry can list the remote server too (`remotes` in `server.json`) beside the npm package.

## 8. Data handling and disclosure

| Input | From | Kept |
|---|---|---|
| Tool arguments (cloud, language, home, search text) | every call | Not stored. Request logs keep method, tool name, status and latency only, for 30 days (proposed, D-H6) |
| Scan hits: rule ids, file paths, line numbers, captured service tokens | `summarize_scan_hits` | Not stored, and not logged. The token is an identifier such as `s3` or `storage-blob`, never source text; "already wired" hits carry no text at all |
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
| Remote MCP `https` URL | `https://vyomi.cloud/mcp` |

## 10. Plan

| Phase | Delivers | Size | Clears |
|---|---|---|---|
| 0 | This doc approved; D-H1 decided 2026-11-22 (build now); D-H2–D-H6 to decide | — | — |
| 1a | `vyomi mcp --http` with hosted mode, scan rules/report split, `vyomi_env_file`; tests and guardrail rows for the hosted surface (no writer, no outbound fetch of caller URLs) | M | — |
| 1b | `/mcp` component in the portal's DigitalOcean app (pinned image), deploy workflow on a tag, rate limits, uptime check | S | — |
| 1c | `plugins/vyomi-cloud` folder, skills branching on tools, README, drift-check support | S | — |
| 1d | Privacy policy update (human), then directory Validate and submission (human) | — | Directory block (a) without G9; claude.ai and Cowork |
| 1e | OpenAI identity verification (human), then OpenAI submission of `plugins/vyomi-cloud` as "With MCP" (human) | — | OpenAI directory (ChatGPT and Codex) without an approved-partner allowlist |
| 2 | Portal as OAuth authorization server; account-aware `vyomi_status` / `vyomi_reach` | L | Account features in the hosted plugin |
| 3 | Nano relay binding (only if wanted) | M | Nano status from the hosted server |

Phase 1 alone is enough for the directory. Phases 2 and 3 are optional.

## 11. Decisions needed

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D-H1 | Build now, or wait for G9 | Build phase 1 now / wait for Anthropic's answer | **Decided 2026-11-22 (Rohith): build phase 1 now.** OpenAI limits local MCP to approved partners and wants bundled servers, so only a remote server reaches its directory whatever G9 says. Still send the G9 request (free) |
| D-H2 | Hosting | A separate DO app / B′ component in the portal app / B inside FastAPI / C Cloudflare Worker | **B′, decided 2026-11-22** (`https://vyomi.cloud/mcp`) |
| D-H3 | Phase 1 without sign-in | Anonymous / sign-in from day one | Anonymous: nothing account-specific is exposed in phase 1 |
| D-H4 | Folder and listing name | `vyomi-cloud` / `vyomi-remote` / other | `vyomi-cloud` (check the directory's look-alike rule against `vyomi`) |
| D-H5 | Hosted tool names | Keep `vyomi_scan_repo` with a new input shape / new `vyomi_scan_rules` + `vyomi_scan_report`; `vyomi_write_env` -> `vyomi_env_file` | New names: different behaviour should not hide behind the same name |
| D-H6 | Request logs | None / 30 days without arguments | 30 days without arguments, for abuse and uptime work |

## 12. Human gates

- Approving this doc and D-H1–D-H6.
- Adding the `/mcp` component and route to the portal's DigitalOcean app (production config, billing for one container), and a Cloudflare rule that lets `/mcp*` through bot protection.
- The privacy policy change.
- The directory submission of `plugins/vyomi-cloud`.
- OpenAI Platform identity verification (individual or business) and the OpenAI submission.
- Phase 2: the portal's authorization-server endpoints go live on portal `main` (a paid deploy).
