# Hosted Vyomi MCP server: implementation plan (phase 1)

Status: approved 2026-11-22 (Rohith: D-I1–D-I5, D-H3–D-H6, O-D2, O-D4; D-H2 = B′, `https://vyomi.cloud/mcp`); PRs 1–2 next · Written 2026-11-22 against `v4-on-main` · Owner: Rohith
Design: `HOSTED-MCP-DESIGN.md` (D-H1: build now). Listing: `OPENAI-DIRECTORY-PLAN.md`. This doc is the build plan
for the server itself: what code changes, in which PRs, and how each piece is tested.

## 0. What this delivers

One Go binary, two modes. The local stdio server stays exactly as it is; a new **hosted mode** serves a smaller,
safer tool set over Streamable HTTP at `https://vyomi.cloud/mcp`.

| | Local mode (today, unchanged) | Hosted mode (new) |
|---|---|---|
| Start | `vyomi-tunnel mcp` / `vyomi mcp` (stdio) | `vyomi mcp --hosted --listen :8080` (HTTP) |
| Transport | JSON-RPC lines on stdin/stdout | Streamable HTTP: `POST /mcp`, JSON responses, no SSE |
| Who uses it | Claude Code, Codex, Cursor, Copilot, any local MCP client | Same clients by URL, plus ChatGPT, claude.ai, Cowork |
| Tools | 9: `vyomi_*` (8 read-only + `vyomi_write_env`) | 8, verb names, all read-only, **no writer** |
| Sees the user's machine | Yes: probes 127.0.0.1, runs `vyomi-tunnel list`, reads the project | **Never.** No outbound network, no file access |
| Knowledge | Embedded (`mcp_matrix.json`, caps, docs) | Same embedded knowledge, same build |
| State | Home-probe cache per process | None. Any instance answers any request |
| Sign-in | n/a | None in phase 1 |

What users get: the knowledge answers (what Vyomi emulates, feature support, SDK settings, code snippets) and the
proposals (`.env.vyomi`, the AGENTS.md block, a repo-scan summary) from any MCP client without installing anything.
The agent still does local steps itself (grep, write the file after a yes).

## 1. What exists in the code (facts the plan builds on)

| Piece | Where | Matters because |
|---|---|---|
| `mcpServer` struct: `matrix`, `tools`, `byName`, `client`, `probeClient`, `homeCache`, `out` | `cmd/vyomi/mcp.go:68` | Hosted mode needs a server with no HTTP clients and no output writer |
| `handleMessage(raw) (rpcResponse, bool)` and `dispatch(method, params)` | `mcp.go:182`, `mcp.go:210` | Transport-independent: the HTTP handler calls it directly |
| `handleLine` accepts JSON-RPC **batches** | `mcp.go:157` | HTTP mode rejects batches (removed from current MCP) |
| `mcpTool{Name, Title, Description, Schema, ReadOnly, Destructive, OpenWorld, handler}`; `describe()` already emits `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` | `mcp_tools.go:16-43` | Annotations are already explicit booleans |
| `buildTools()` returns the 9 local tools | `mcp_tools.go:61` | Hosted mode gets its own `buildHostedTools()` |
| Knowledge tools call `resolveHome` / `homeTarget`, which **probe** local homes, and `getJSON` for live state | `mcp_tools.go:641-806`, `mcp_homes.go:767,825` | Hosted handlers must use a **named-home** resolver that never probes |
| Homes: `nano-local`, `nano-cloud`, `mesh-local`, `mesh-codespace`, `offline`; `wiringHome()` maps to `nano`/`mesh`/`offline` | `mcp_homes.go:30-56` | Hosted `home` argument is `nano`, `mesh` or `offline` |
| Scan: rules from `matrix.Scan` (cloud, lang, regex), `scanLangExts`, `resolveAlias(cloud, token)`, `summarize()`, `scanMaxHits = 5` | `mcp_scan.go` | The rule table and the summary are reusable; the file walk is not |
| AGENTS.md: `agentsMDSection`, `spliceAgentsMD(existing, exists, section)`, `importsAgentsMD`; file reads in `readProjectFile` | `mcp_agents_md.go` | Splice logic is pure; only the reads move to the agent |
| Env: `envVars(cloud, home, target)`, `formatEnv(cloud, vars, format)` | `mcp_knowledge.go` | `propose_env_file` reuses them |
| Resources `vyomi://settings`, `vyomi://services/<cloud>`, `vyomi://env/<cloud>` | `mcp_tools.go:884-929` | Hosted v1 exposes no resources (D-I2) |
| Guardrail pin: tool list and annotations; `tools/guardrails/run.sh` release gate | `mcp_guardrails_test.go` | Add hosted rows; local pin unchanged |

## 2. Hosted tool set

Names per OpenAI's plain-verb guidance (O-D2). Every tool: `readOnlyHint: true`, `destructiveHint: false`,
`openWorldHint: false`, `idempotentHint: true`, a title, and a description that states purpose, when to use it,
inputs and "no side effects". No input is a file path.

| Hosted tool | Title | Reuses | Inputs | Returns |
|---|---|---|---|---|
| `list_services` | Services Vyomi emulates | `toolServices` with `live=false` | `cloud`, `home` | Services, levels per home, actions, data planes, SDK support |
| `check_capability` | Does Vyomi support a feature? | `toolCapability` (already offline) | `query`, `cloud` | Up to 20 matches with levels and limitations |
| `get_code_snippet` | Code example for a Vyomi operation | `toolSnippet` with a named home | `cloud`, `service`, `op`, `lang`, `home` | A ready-to-run call aimed at that home's standard endpoint |
| `get_sdk_settings` | SDK settings for Vyomi | `toolEnv` with a named home | `cloud`, `lang`, `format`, `home`, `host`, `account` | Env vars, client settings, Terraform block, gotchas |
| `get_scan_rules` | Rules to find cloud SDK usage | rule table from `matrix.Scan` + `scanLangExts` | `languages` (optional) | `[{id, cloud, lang, globs, regex, token_group}]` plus how to run them with grep |
| `summarize_scan_hits` | Summarize cloud usage found in a repo | `resolveAlias`, `summarize()` | `home`, `hits: [{rule, file, line, token}]` (max 2,000) | Same shape as today's `vyomi_scan_repo`: per service, emulated or not, where used, warnings |
| `propose_env_file` | Propose a .env.vyomi file | `envVars`, `formatEnv` | `clouds`, `home`, `host`, `account` | `{filename, content}`; writes nothing |
| `propose_agents_md_section` | Propose the Vyomi section for AGENTS.md | `agentsMDSection`, `spliceAgentsMD`, `importsAgentsMD` | `agents_md` (text or absent), `claude_md` (text or absent), `clouds`, `env_file` | `{action, replace_block, proposed_content}` and the CLAUDE.md import advice |

Not in hosted phase 1: `vyomi_status`, `vyomi_reach` (need the user's machine or an account; phase 2),
`vyomi_write_env` (a writer).

**Named home, no probe.** A new `namedHome(arg)` returns a `homeSel` for `nano`, `mesh` or `offline` (default
`nano`) and the standard endpoints as text (`127.0.0.1:8090`, `127.0.0.1:9000` / TLS `9443`). A relay URL is only
echoed into the generated settings. It never calls `probeHomes`, `getJSON` or `runTunnelList`.

**Scan token (D-I1).** Today a rule match is turned into a service by `resolveAlias(cloud, token)`, where the token is
the captured identifier (for example `s3` in `boto3.client("s3")`). A rule id plus `file:line` is not enough to know
the service, so the agent also sends that captured token (regex group 1). The server accepts only tokens that match
`^[A-Za-z0-9_.\-/]{1,64}$`; known aliases map to services, others are reported as unknown, as the local scan does.
The "already wired" rule (existing endpoint overrides) is reported as `file:line` only; the local scan's clipped line
text is not sent. No other source text is accepted.

**Hosted instructions.** A separate `mcpHostedInstructions` string: what the server knows, that it cannot see the
user's machine, the local steps the agent does (grep with the rules; write files only after a yes), and no tier
pricing or upgrade wording.

## 3. Code changes

| File | Change |
|---|---|
| `cmd/vyomi/mcp.go` | `mcpServer.hosted bool`. `newHostedMCPServer()` builds a server with `client`, `probeClient` = a transport that **always errors** (belt and braces), no `out`. `dispatch`: in hosted mode, `resources/*` return empty lists, `initialize` returns `mcpHostedInstructions` and `serverInfo.title` "Vyomi". `runMCP` parses `--hosted`, `--listen` (default `:$PORT` or `:8080`). |
| `cmd/vyomi/mcp_http.go` (new) | `serveHTTP(addr)`: `POST /mcp` → read body (limit 256 KiB) → reject a JSON array (batch) → `handleMessage` → `200 application/json`, or `202` with no body for notifications. `GET`/`DELETE /mcp` → `405`. `GET /healthz` → `200 {"ok":true,"version":…}`. Validates `Origin` when present (allowlist: none by default; server-to-server clients send none). Accepts and checks `MCP-Protocol-Version`. Per-request timeout 10 s, server read/write timeouts, `recover()` per request, graceful shutdown on SIGTERM. |
| `cmd/vyomi/mcp_hosted_tools.go` (new) | `buildHostedTools()` with the 8 tools; thin handlers that decode args, call `namedHome`, then the shared knowledge functions. |
| `cmd/vyomi/mcp_homes.go` | Add `namedHome(arg)` (pure). No change to probing code. |
| `cmd/vyomi/mcp_scan.go` | Extract `scanRuleTable()` (id, cloud, lang, globs, pattern, token group) from `compileScanRules`; add `summarizeHits(hits, sel)` that builds a `scanReport` from hits and reuses `summarize()`. `scanRepo` (local) keeps working on top of the same table. |
| `cmd/vyomi/mcp_agents_md.go` | Add `proposeAgentsMDFromText(agentsMD, claudeMD *string, clouds, envFile)` reusing the splice logic; the local tool keeps its file-reading path. |
| `cmd/vyomi/mcp_ratelimit.go` (new) | In-memory token bucket keyed by a salted hash of the client address, never logged or stored. Defaults: 60 calls/min burst 20 per key, 50 req/s global (D-I4). `429` with `Retry-After`. |
| `cmd/vyomi/mcp_log.go` (new) | One JSON line per request: time, method, tool, status, latency ms, response bytes. No arguments, no IP (O-D4). |
| `tools/guardrails/run.sh` | New rows: hosted surface pin, no outbound, no file access, HTTP limits. Label "hosted: 8 read-only, 0 writers". |
| `deploy/mcp-hosted/Dockerfile` (new) | Multi-stage: `golang` build with `CGO_ENABLED=0`, `-trimpath`; runtime `gcr.io/distroless/static:nonroot`; `ENTRYPOINT ["/vyomi","mcp","--hosted"]`, `EXPOSE 8080`. |
| `deploy/mcp-hosted/portal-app-component.yaml` (new) | The service component to add to the **portal's** App Platform spec: name `mcp`, source `image` (`registry_type: GHCR`, registry `vyomi-cloud`, repository `mcp-hosted`, pinned `tag`; the package is private, so `add-component.py` adds `registry_credentials` from `GHCR_PULL_CREDENTIALS` at apply time and App Platform stores them encrypted; nothing secret is committed), `basic-xxs`, 1 instance, HTTP port 8080, health check `/healthz`, ingress rule `match.path.prefix: /mcp` (prefix trimmed, so the Go server sees `/` and `/healthz`). Also a runbook for applying it with `doctl apps update --spec` without touching the portal component, including the first-release step: create a `read:packages` pull token and add the component with it. `add-component.py` and `set-image-tag.py` do the merge and the tag bump and refuse to write if anything else in the spec would change. |
| `.github/workflows/mcp-hosted-release.yml` (new) | On tag `mcp-hosted-v*`: guardrails + `go test ./cmd/vyomi/...` → build and push `ghcr.io/vyomi-cloud/mcp-hosted:<version>` (`linux/amd64` only; App Platform runs amd64) and smoke the image in the job → fetch the portal app spec, set the `mcp` component's image tag, `doctl apps update --spec` (this deploys the whole app) → smoke test against `https://vyomi.cloud/mcp`. No registry secrets: GHCR takes the workflow's own `GITHUB_TOKEN` with `permissions: packages: write`. Secrets: `DIGITALOCEAN_ACCESS_TOKEN`, `PORTAL_APP_ID`. |
| `tools/mcp-hosted-smoke.sh` (new) | `initialize`, `tools/list`, one call per tool, `GET /mcp` = 405, oversize = 413; exits non-zero on any miss. Takes a base URL, so it runs against `localhost`, Docker or production. |
| `packaging/tunnel/server.json` | Add `remotes: [{type: "streamable-http", url: "https://vyomi.cloud/mcp"}]` after the first production deploy. |

The plugin package (`integrations/claude-plugins/plugins/vyomi-cloud/`) and the OpenAI ZIP are WP-O3 in
`OPENAI-DIRECTORY-PLAN.md`; they follow PR 3 below.

## 4. Safety rules (what the tests enforce)

1. **No outbound network in hosted mode.** The server's HTTP clients use a transport that returns an error; a test
   swaps in a recording transport and fails if any hosted handler dials.
2. **No file system access.** No hosted tool schema has a `path` property; a test walks every hosted schema. A second
   test runs every hosted tool from an empty temp working directory and checks nothing was created or read
   (`os.DirFS` snapshot before/after, as `mcp_agents_md_test.go` does).
3. **No writer.** Pin: 8 tools, each `readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: false`.
4. **Never fetch a caller URL (SSRF).** Covered by rule 1; a relay URL argument appears only in output text.
5. **Bounded input.** Body ≤ 256 KiB (`413`), `hits` ≤ 2,000, each AGENTS.md/CLAUDE.md text ≤ 256 KiB, strings
   validated by enum or pattern.
6. **No secrets asked or returned.** Descriptions never ask for keys; outputs use the simulator's fixed dummy
   credentials only (as local mode does).
7. **No PII in logs.** Log line fields are fixed (§3); a test checks a logged request contains no argument values.
8. **Local mode unchanged.** The existing `mcp_guardrails_test.go` pin (8 + 1) and all current tests pass untouched.

## 5. PR breakdown

Each PR is one topic branch via `scripts/v4-session-start.sh`, with a SESSION-CLAIMS row and a branch doc.

| PR | Branch | Contents | Size | Done when |
|---|---|---|---|---|
| 1 | `v4/hosted-mcp-transport` | `--hosted`/`--listen`, `mcp_http.go`, `namedHome`, hosted server constructor, rate limit, log line; hosted tools `list_services`, `check_capability`, `get_code_snippet`, `get_sdk_settings`; tests for transport and rules 1–3, 5, 7–8 | M | `go test` + guardrails green; smoke script passes on `localhost` |
| 2 | `v4/hosted-mcp-scan-proposals` | `scanRuleTable`, `summarizeHits`, `get_scan_rules`, `summarize_scan_hits`, `propose_env_file`, `propose_agents_md_section`; parity tests (below) | M | Parity tests green; hosted pin = 8 |
| 3 | `v4/hosted-mcp-deploy` | Dockerfile, portal-app component spec + runbook, release workflow, smoke script in CI, runbook section | S | Image runs locally; smoke passes against the container; first tag deploys after gates O-G2/O-G3 |
| 4 | `v4/vyomi-cloud-plugin` | `plugins/vyomi-cloud` (Claude + Codex manifests, `.mcp.json` with the URL, README, skills branching on tools), drift check, `package_openai_plugin.sh` | S | `claude plugin validate` passes; ZIP built; Claude Code, Codex and Cursor connect to production |

PRs 1 and 2 can be built and fully tested before any infrastructure exists. Only PR 3's deploy step needs the
`/mcp` component in the portal's DigitalOcean app and the Cloudflare rule.

## 6. Testing

**Unit (Go, in CI, every PR)**
- Transport: `initialize` negotiates a version; `tools/list`; `tools/call`; notification → `202` empty; batch → `400`;
  invalid JSON → JSON-RPC parse error; `GET /mcp` → `405`; body > 256 KiB → `413`; bad `Origin` → `403`; unknown
  `MCP-Protocol-Version` → `400`.
- Surface pin: exact 8 names, titles, annotations; no `path` in any schema; hosted `resources/list` empty.
- No outbound / no file access / no logged arguments: rules 1, 2, 7 above.
- Rate limit: burst then `429` with `Retry-After`; a different key is unaffected.

**Parity (Go, PR 2)**: hosted answers must equal local answers where they overlap.
- `list_services`, `check_capability`, `get_code_snippet`, `get_sdk_settings` vs the local tools with
  `home=offline|nano|mesh` and `live=false`: identical JSON.
- Scan: for a new fixture repo under `cmd/vyomi/testdata/scan/` (Python, Node.js, Java, Go and Terraform files using
  all three clouds), run the local `scanRepo`; separately apply `get_scan_rules` with Go's regexp
  over the same files (as an agent's grep would), send the hits to `summarize_scan_hits`; the per-service results
  match.
- AGENTS.md: for each existing `mcp_agents_md_test.go` case, pass the file text to `propose_agents_md_section`; the
  action and proposed content match the local tool.
- `propose_env_file` content equals what `vyomi_write_env` would write.

**Container and staging (PR 3)**
- `docker build` + `docker run -p 8080:8080`; `tools/mcp-hosted-smoke.sh http://localhost:8080`.
- After the first deploy: the same script against `https://vyomi.cloud/mcp`; the portal still answers on `/`; `/mcp/healthz` returns the
  knowledge version.

**Real clients (PR 4, manual checklist in the branch doc)**
- Claude Code: `claude mcp add --transport http vyomi https://vyomi.cloud/mcp`; ask the 5 positive test prompts.
- Codex: add the remote server in its config; same prompts, plus a scan of a sample repo using the rules.
- Cursor: add by URL; one knowledge prompt.
- MCP Inspector: list tools, call each with defaults.
- ChatGPT: custom connector if the plan allows; the knowledge prompts on web and mobile.

**Load sanity**: 50 req/s for 60 s against the container stays under 200 ms p95 for knowledge calls, with no memory
growth (the server is stateless).

## 7. Operations

- Registry: `ghcr.io/vyomi-cloud/mcp-hosted`, `linux/amd64`, one immutable tag per release and no `:latest` (a floating tag would let a portal deploy pick up an unreleased MCP). The package is public, so the portal app pulls it anonymously and holds no credentials.
- Release: tag `mcp-hosted-vX.Y.Z` from `v4-on-main`; the workflow deploys. Never deploy on merge.
- Versioning: `serverInfo.version` = knowledge version + `+git.<sha>`; `/healthz` reports the same.
- Changing tool names, schemas, descriptions or annotations is a **contract change**: OpenAI re-reviews it and
  Claude's listing may too. Server-only fixes that keep the contract deploy freely.
- Never change the origin `vyomi.cloud` or move the path away from `/mcp`: OpenAI treats a new origin as a new plugin (a path change needs a new version).
- Monitoring: App Platform health check + an uptime alert on `/healthz`; the request log for error rates.
- Rollback: set the previous image tag in the portal app spec (`set-image-tag.py`) and `doctl apps update --spec`; every released tag stays in GHCR. Note App Platform deploys all components together, and a failed component rolls the whole app back.
- Cost: one more `basic-xxs` container in the portal app, plus outbound transfer within the plan allowance.

## 8. Decisions for this build

| # | Decision | Recommendation (all approved 2026-11-22) |
|---|---|---|
| D-I1 | Scan hits carry the captured service token (≤ 64 chars, validated against known aliases) | Yes: without it the server cannot map a hit to a service. Update `HOSTED-MCP-DESIGN.md` §4 and the privacy text |
| D-I2 | Resources in hosted mode | None in v1 (tools only): a smaller surface for directory review |
| D-I3 | App Platform region | The portal's region, unless the portal's is far from India and the US; latency matters little for these calls |
| D-I4 | Rate limits | 60 calls/min per client (burst 20), 50 req/s global; revisit after a month of logs |
| D-I5 | Batch requests over HTTP | Reject (current MCP removed batching); stdio keeps accepting them |
| D-I6 | Paths behind the `/mcp` route | The router trims `/mcp`, so the Go server answers on `/` (and `""`) without redirecting, and on `/healthz`; with `--listen` locally it also accepts `/mcp` and `/mcp/healthz`, so the same URLs work in Docker and production |
| — | Earlier: D-H2–D-H6, O-D2, O-D4 | As recommended in the design and the OpenAI plan |

## 9. Human gates

| Gate | When | What |
|---|---|---|
| Approve this plan and D-I1–D-I5 | Before PR 1 | Reply "approve" |
| O-G1b GHCR pull token (package stays private, decided 2026-11-23) | Before adding the component | A classic PAT with only `read:packages`, ideally on a bot account in `vyomi-cloud`; passed once to `add-component.py` as `GHCR_PULL_CREDENTIALS` and stored encrypted by App Platform. Track its expiry: an expired token fails every portal deploy on the image pull (`deploy/mcp-hosted/RUNBOOK.md` §0a–0b) |
| O-G2 Portal app change | Before PR 3's deploy | Add the `mcp` component and `/mcp` route to the portal's DigitalOcean app (from `deploy/mcp-hosted/portal-app-component.yaml`, merged with `deploy/mcp-hosted/add-component.py`); add `DIGITALOCEAN_ACCESS_TOKEN` and `PORTAL_APP_ID` as appliance repo secrets (no registry secrets) |
| O-G3 Cloudflare rule | Before PR 3's deploy | Let `vyomi.cloud/mcp*` through bot protection / challenges (server-to-server clients such as ChatGPT and Claude send no browser headers) |
| First production tag | After PR 3 merges | Push `mcp-hosted-v0.1.0` |
| Privacy policy | Before any directory submission | Add the hosted server (see `OPENAI-DIRECTORY-PLAN.md` WP-O5) |
