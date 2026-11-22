# Listing Vyomi in the OpenAI plugin directory (ChatGPT + Codex): plan

Status: plan, not started · Written 2026-11-22 against `v4-on-main` · Owner: Rohith
Builds on: `HOSTED-MCP-DESIGN.md` (D-H1 decided: build phase 1 now). Related: `AGENT-DISTRIBUTION-NOW.md`,
`integrations/claude-plugins/SUBMISSION.md`, `HUMAN-GATES.md` G9.

## 0. Summary

Vyomi works in Codex today via the marketplace repo, but it is not discoverable in OpenAI's plugin directory and does
not reach ChatGPT at all. The only route in is a **remote MCP server** submitted as **"With MCP"**:

- OpenAI limits local MCP submissions to approved partners, and asks for bundled servers (no `npx`).
- A skills-only listing is a trap: "Adding an MCP server to an existing skills-only plugin is not currently supported."

So this plan ships phase 1 of the hosted MCP (`https://mcp.vyomi.cloud/mcp`, anonymous, read-only), a
`plugins/vyomi-cloud` package that meets OpenAI's listing rules, and the review pack OpenAI asks for. The same server
also clears the Claude directory block (G9) and reaches claude.ai and Cowork.

What is different from today:

| | Today | After this plan |
|---|---|---|
| Codex | Installs from our marketplace repo (local `npx` server) | Also listed in the OpenAI directory; installs in one click |
| ChatGPT | Not possible | Listed; knowledge tools work on web and mobile |
| MCP server | Local stdio only (`vyomi-tunnel mcp`) | Plus a hosted Streamable HTTP server on `mcp.vyomi.cloud` |
| Writers | `vyomi_write_env` writes `.env.vyomi` locally | Hosted server has **no writer**; it proposes, the agent writes after a yes |

## 1. What OpenAI requires (read 2026-11-22)

| Requirement | Source | Our answer |
|---|---|---|
| Verified individual or business identity; publishing under an unverified name is rejected | app-review | Gate O-G1 (you) |
| Owner or "Apps Management: Write" role for the submitter | submit-plugins | Gate O-G1 |
| Server "hosted on a publicly accessible domain"; no local or test endpoints | app-review | `https://mcp.vyomi.cloud/mcp` (WP-O2) |
| Connection, scan and domain verification pass; findings resolved | submit-plugins | WP-O6 |
| Changing the origin (scheme, host, port) later needs a **new plugin** | app-review | Lock `mcp.vyomi.cloud` before submitting |
| `readOnlyHint`, `destructiveHint`, `openWorldHint` as explicit booleans on every tool; must match behaviour | guidelines 6.3, app-review | WP-O1 + a test |
| Tool names: unique, plain-language verbs (e.g. `get_order_status`); descriptions say purpose, behaviour, when to use, side effects | guidelines 6.1 | WP-O1 (decision O-D2) |
| Each public tool operates independently; no generic executor | guidelines 6.2 | WP-O1 (scan split: see risk R2) |
| Return only what the request needs; never ask for secrets, API keys, passwords | guidelines 4.2, 6.4 | WP-O1 |
| No tracking/profiling (incl. IP addresses, query patterns) unless disclosed, narrow, user-controllable | guidelines 3.3 | Logs without IPs or arguments (O-D4) |
| Privacy policy: data categories, purposes, recipients, retention, user controls | guidelines 4.1 | Gate O-G4 (you) |
| No subscription plans, no upgrade promotion, no digital-goods commerce | guidelines 3.x, 5.x | Hosted text states availability, never upsells (WP-O1) |
| Works reliably on desktop and mobile ChatGPT | guidelines 1.x | WP-O4 tests |
| Don't append "MCP", "MCP Server" or "Plugin" to the name | guidelines 1.5 | Display name "Vyomi" |
| Listing: `displayName` ≤ 30, `shortDescription` ≤ 30, `longDescription` ≤ 4000, `developerName` ≤ 80, `category`, `capabilities` | submit-plugins | WP-O3 (our current short description is ~63 chars) |
| `logo` and `composerIcon`: square, ≥ 48 px, PNG/JPEG/WebP/SVG, ≤ 5 MiB | submit-plugins | Existing 1024 px icon |
| Website, support, privacy policy, terms of service URLs (all HTTPS) | submit-plugins | `/`, `/support`, `/privacy`, `/terms` all load today |
| Exactly 5 positive + 3 negative test cases; positive ones name `tools_triggered` and `expected_behavior` | submit-plugins | WP-O4 |
| Demo recording URL a reviewer can open | submit-plugins | Gate O-G5 (you) |
| Commerce declaration (`review.commerce`) | submit-plugins | "No commerce" |
| ZIP with exactly one plugin root, no sibling files, no lifecycle hooks, no `apps`/`.app.json` | submission-errors | WP-O3 packaging script |
| Review: one version live + one in review; tool changes go through continuous review; server-only changes that keep the contract need no resubmission | app-review | WP-O7 release rules |

## 2. Decisions

| # | Decision | Recommendation |
|---|---|---|
| D-H2..D-H6 | Remaining hosted-MCP decisions (separate DO app, anonymous phase 1, folder `vyomi-cloud`, new names for changed tools, logs) | Approve as recommended in `HOSTED-MCP-DESIGN.md` §11, with O-D2 and O-D4 below |
| O-D1 | Publish as individual or business | Business ("Vyomi") if Vyomi is a registered company; else individual. `developerName` must match |
| O-D2 | Hosted tool names | Verb names, per OpenAI 6.1: `list_services`, `check_capability`, `get_code_snippet`, `get_sdk_settings`, `get_scan_rules`, `summarize_scan_hits`, `propose_env_file`, `propose_agents_md_section`. The local server keeps its `vyomi_*` names |
| O-D3 | Surfaces | ChatGPT + Codex. If the portal lets us choose, still pick both: the knowledge tools work everywhere, and test cases use only those on ChatGPT |
| O-D4 | Request logs | 30 days; method, tool name, status, latency only. No arguments, no IP addresses (rate limiting uses in-memory counters) |
| O-D5 | Country availability | All (leave `publication.countries` unset) |

## 3. Work packages

Owner key: **CLI** = Claude Code session in auto mode on a topic branch; **You** = Rohith; **Me** = this chat.

### WP-O0 — Accounts and infrastructure (You, start today; runs in parallel)
- OpenAI Platform: choose the publishing organization; complete individual or business verification (O-D1); give the
  submitter the Apps Management: Write role if it isn't the owner.
- Open the plugin submission portal once and confirm "Create plugin → With MCP" is offered, and note the surface and
  country fields it shows (closes open question Q1).
- Approve a new DigitalOcean App Platform app (one basic container) and add DNS for `mcp.vyomi.cloud` when WP-O2 asks.

### WP-O1 — Hosted mode of the MCP server (CLI, size M)
Branch `v4/hosted-mcp` via `scripts/v4-session-start.sh hosted-mcp`.
- `vyomi mcp --http :PORT --hosted`: Streamable HTTP on `POST /mcp` (JSON responses, no SSE), `405` for `GET`,
  stateless, honours `MCP-Protocol-Version`, `GET /healthz` for the platform.
- Reuse `handleMessage`; the hosted mode exposes only the hosted tool set (O-D2):
  - Knowledge: `list_services`, `check_capability`, `get_code_snippet`, `get_sdk_settings` (home named by the caller:
    `nano`, `mesh`, `appliance`, or a relay URL used only as text).
  - Scan without code: `get_scan_rules(languages)` returns rule id, globs, regex; `summarize_scan_hits(hits)` takes
    `[{rule, file, line}]` and returns the services, coverage and warnings. No file contents ever.
  - Proposals: `propose_env_file(clouds, home)` returns `.env.vyomi` text; `propose_agents_md_section(agents_md,
    claude_md?)` returns the marker block and a replace/insert plan. Neither writes anything.
- Every tool: `title`; explicit `readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: false`; description
  with purpose, when to use, inputs, and "no side effects". Hosted text never mentions prices or upgrades; tier-only
  features are stated as "available on a Vyomi mesh", nothing more.
- Safety: never connect to a host or URL a caller supplies (SSRF); request size limit (e.g. 256 KiB) and per-call hit
  cap; per-client rate limit in memory; no disk writes; no outbound network at all in hosted mode.
- Tests: a pin test for the hosted tool list and annotations; a test that hosted mode opens no outbound connection
  and writes no file; JSON-RPC round trips over HTTP; `tools/guardrails/run.sh` rows for the hosted surface (0
  writers). Local mode unchanged: the existing 8 + 1 pin still passes.

### WP-O2 — Deploy (CLI, size S; DNS and billing are your gates)
- Container build of the Go binary (distroless/static), `.do/mcp-hosted.yaml` app spec, one basic instance, health
  check `/healthz`, region near the portal.
- `mcp-hosted-release.yml`: deploys on tag `mcp-hosted-v*` only (not on merges), after guardrails and Go tests.
- Uptime check on `https://mcp.vyomi.cloud/healthz`; logs per O-D4.
- Smoke after deploy: MCP Inspector or a scripted `initialize` + `tools/list` + one call per tool against the public URL.

### WP-O3 — The `vyomi-cloud` plugin package (CLI, size S)
In `integrations/claude-plugins/plugins/vyomi-cloud/` (synced to `vyomi-cloud/claude-plugins`):
- `mcp.json` / `.mcp.json`: `{"mcpServers": {"vyomi": {"type": "http", "url": "https://mcp.vyomi.cloud/mcp"}}}`.
- `.codex-plugin/plugin.json` with OpenAI listing fields, within limits:
  - `displayName`: "Vyomi"; `shortDescription` (≤ 30): "Local AWS, GCP, Azure simulator"
  - `longDescription`: what it answers and proposes, and that it never reads or sends source code
  - `developerName`: the verified identity (O-D1); `category`, `capabilities`
  - `websiteURL`, `supportURL`, `privacyPolicyURL`, `termsOfServiceURL`; `logo`, `composerIcon`
  - up to 3 starter prompts (≤ 128 chars, no @mentions)
- `.claude-plugin/plugin.json` for the Claude directory, plus README (disclosure table from `HOSTED-MCP-DESIGN.md` §8),
  LICENSE.
- Skills: one source that branches on the tools present (local `vyomi_*` vs hosted verbs). In ChatGPT (no local file
  tools) the skills stay with knowledge answers and proposals the user can copy.
- `scripts/package_openai_plugin.sh` builds `dist/vyomi-cloud-openai.zip`: one plugin root, no siblings, no hooks.
- `check_agent_plugins.py` covers both folders; a check enforces the OpenAI length limits.

### WP-O4 — Review pack (Me drafts, CLI wires into the package, You check)
- 5 positive cases, each answerable on ChatGPT (web and mobile) and Codex, with `tools_triggered` and
  `expected_behavior`, for example:
  1. "Does Vyomi support SQS FIFO queues?" → `check_capability`
  2. "Which GCP services does Vyomi emulate?" → `list_services`
  3. "Show Python boto3 code to put an object in S3 on Vyomi Nano." → `get_code_snippet`
  4. "What environment variables point the Azure SDK for Python at a Vyomi mesh?" → `get_sdk_settings`
  5. "Write a .env.vyomi for a project using AWS and GCP on Nano." → `propose_env_file`
- 3 negative cases (the plugin should not trigger, or should decline clearly):
  1. "Deploy my app to production AWS." (not a simulator task)
  2. "What's the weather in Bangalore?" (unrelated)
  3. "Here are my real AWS keys, store them for me." (never collects secrets)
- Release notes; the commerce declaration ("none").

### WP-O5 — Legal pages and demo (You)
- Privacy policy: add the hosted MCP — categories (tool arguments, scan hits as file paths and line numbers,
  AGENTS.md text passed in), purpose (answer the request), recipients (hosting providers), retention (not stored;
  request metadata 30 days, no IPs), user controls (contact support). Terms: confirm they cover the hosted service.
- Demo video, 2–3 minutes: install in Codex and ChatGPT, run three of the positive cases; upload unlisted and keep
  the link reachable.

### WP-O6 — Submit (You; I can drive the browser with you)
- Plugin portal → Create plugin → **With MCP** → server URL → domain verification → connect and scan → fix findings.
- Upload `vyomi-cloud-openai.zip`; confirm the normalized `.codex-plugin/plugin.json`; enter test cases, demo URL,
  commerce "none"; attestations; submit.
- Do **not** create a skills-only draft for Vyomi at any point.

### WP-O7 — After approval (CLI + You)
- Publish from the portal; add the listing link to the plugin README, `/docs/agents` and `AGENT-DISTRIBUTION-NOW.md`.
- Release rules: server-only changes that keep the tool contract deploy freely; changing tools, descriptions, schemas
  or annotations triggers OpenAI's continuous review (the old definition stays live meanwhile); listing or skills
  changes need a new version and a new review. Never change the origin.
- Same server, in parallel: submit `plugins/vyomi-cloud` to the Claude directory (clears G9's block without
  verification) and add `remotes` to the MCP Registry `server.json`.

## 4. Order and gates

```
You:  O-G1 identity ─────────────────────────────────────────────┐
You:  approve D-H2..D-H6, O-D1..O-D5 ──┐                         │
CLI:                                   WP-O1 ── WP-O3 ──┐        │
You:  O-G2 DO app + O-G3 DNS ──────────── WP-O2 deploy ─┤        │
Me:                                    WP-O4 drafts ────┤        │
You:                                   O-G4 privacy, O-G5 demo ──┤
You:                                                    WP-O6 submit ── review ── WP-O7
```

| Gate | What | Owner | Blocks |
|---|---|---|---|
| O-G1 | OpenAI identity verification + role | You | WP-O6 |
| O-G2 | DigitalOcean app (billing) | You | WP-O2 |
| O-G3 | DNS `mcp.vyomi.cloud` | You | WP-O2 |
| O-G4 | Privacy policy update live | You | WP-O6 |
| O-G5 | Demo video link | You | WP-O6 |
| O-G6 | Final submit click | You | Review |

## 5. How to test it

| Check | How | Pass |
|---|---|---|
| Hosted tool surface | Go pin test + guardrails | 8 tools, 0 writers, annotations explicit and correct |
| No outbound, no writes | Go test in hosted mode | No dial, no file created |
| Protocol | Scripted `initialize`, `tools/list`, one call per tool over HTTPS | All succeed; `GET /mcp` is 405 |
| Abuse limits | Oversized body, burst of calls | 413 / 429, server stays up |
| Codex | Add the remote server in Codex, run the 5 positive prompts | Expected tools trigger; answers correct |
| ChatGPT | Add as a custom connector where the plan allows; run the 5 positive and 3 negative prompts on web and mobile | Same; negatives don't trigger or decline |
| Package | `package_openai_plugin.sh` + limits check | ZIP passes portal upload validation |
| Listing | Portal scan | No unresolved findings |

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | ChatGPT has no local file tools, so scan and file proposals are weaker there | Test cases use knowledge tools on ChatGPT; scan flow is documented as Codex-first |
| R2 | Reviewers read the two-step scan (`get_scan_rules` → `summarize_scan_hits`) as tools that don't operate independently | Each returns a complete, useful answer alone (rules list; summary of any hits passed in); if challenged, drop the scan pair from the hosted surface for v1 |
| R3 | Tier wording read as upgrade promotion | Hosted text states availability only; reviewed in WP-O1 |
| R4 | Origin change later forces a new listing | Lock `mcp.vyomi.cloud` before WP-O6 |
| R5 | Anonymous endpoint abuse | Size limits, rate limits, no outbound calls, no state |
| R6 | Review time unknown ("Review timelines may vary") | Submit early; WP-O7 Claude submission runs in parallel |

## 7. Open questions

- Q1: Does the portal let us choose surfaces (ChatGPT, Codex) per plugin? Check in WP-O0.
- Q2: Can ChatGPT on your current plan add a custom MCP connector for pre-submission testing? If not, test in Codex
  and rely on the portal's connection scan.

## Sources

- https://developers.openai.com/codex/submit-plugins
- https://developers.openai.com/plugins/deploy/app-review
- https://developers.openai.com/plugins/app-guidelines
- https://developers.openai.com/plugins/deploy/desktop-only
- https://developers.openai.com/plugins/deploy/submission-errors
