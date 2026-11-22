# v4/agent-plugins

Owner: Rohith (prepared by Claude, 2026-11-22) - Started: 2026-11-22 - Base: origin/v4-on-main (0df22d4e0) - Status: in review (WP0-WP8 done; WP6 GREEN, see `../../../../VERIFY.md`; human gates in `../../../../HUMAN-GATES.md`)

## Purpose
Put Vyomi into every major coding agent, not just Claude Code. One plugin package (MCP server + three skills) installs with one
command in Claude Code, Codex, GitHub Copilot and Cursor. A read-only MCP tool proposes a Vyomi section for the user's `AGENTS.md`,
so agents with no plugin (teammates', cloud and PR agents) also run against Vyomi. The plugin starts the MCP with
`npx -y vyomi-tunnel mcp`, which hands over to an installed `vyomi-tunnel`, so both commands always run the same server. Execution
plan: `../AGENT-DISTRIBUTION-NOW.md`. Product context: `../AGENT-DISTRIBUTION-PRODUCT-GAPS.md`. Design history:
`../AGENT-DISTRIBUTION-PLUGIN-AND-AGENTS-MD.md`.

## Architecture
| Change | Where |
|---|---|
| Read-only `vyomi_agents_md`: proposes a marker-delimited section (`<!-- vyomi:start -->` / `<!-- vyomi:end -->`), the action (created / appended / updated / unchanged), the block to replace and the proposed file; proposes `@AGENTS.md` for an existing `CLAUDE.md`; never writes | `cmd/vyomi/mcp_agents_md.go`, `mcp_agents_md_test.go`, `mcp_tools.go`, `mcp.go`, `cmd/vyomi/README.md` |
| Tool surface pin 7 + 1 -> 8 read-only + 1 writer; new Threat A gate row "never writes" | `cmd/vyomi/mcp_guardrails_test.go`, `tools/guardrails/run.sh`, `../MCP-GUARDRAILS-INCIDENT-DESIGN.md` §2 |
| One package for every agent: portable `plugin.json` + `mcp.json` (Agent Plugins 1.0), `.codex-plugin/`, `.cursor-plugin/`, shared `.mcp.json`; Claude manifest has no inline `mcpServers`; Codex and Cursor marketplaces; version 4.2.0 | `integrations/claude-plugins/**` |
| Manifest drift guard: names, versions, MCP servers, skills, marketplace entries agree; gates the release sync and CI | `scripts/check_agent_plugins.py`, `scripts/sync_claude_plugins.py`, `.github/workflows/tunnel-mcp-checks.yml` |
| Plugin MCP via `npx -y vyomi-tunnel mcp`; skills and README updated (Node/PATH, Windows `cmd /c`, offline fallback) | `integrations/claude-plugins/plugins/vyomi/{mcp.json,.mcp.json,skills/*}`, `integrations/claude-plugins/README.md` |
| Sync handover: an npx copy runs the installed `vyomi-tunnel` (>= 1.3.0) `mcp` with stdio, args, signals and exit code passed through; `VYOMI_MCP_DELEGATE=0` opts out and is set on the child (no loops); passes `VYOMI_TUNNEL_VERSION` / `VYOMI_TUNNEL_LATEST` | `wasm/relay/mcp-launch.mjs` (source), `packaging/tunnel/bin/mcp-launch.mjs` (copy), `wasm/relay/test-mcp-launch.mjs` |
| `vyomi_status.tunnel`: installed version, and `upgrade` when npm is newer (read-only) | `cmd/vyomi/mcp_tunnel_sync.go`, `mcp_tunnel_sync_test.go` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| `vyomi_agents_md` is read-only; the agent applies the proposal with its own edit tool | A writer tool (`vyomi_write_agents_md`, built 2026-11-14) | The guardrail allows one write path (`.env.vyomi*`); agents' own edit tools already show a diff and ask |
| Never create `CLAUDE.md`; propose `@AGENTS.md` only when one exists | Always write a `CLAUDE.md` import | Claude Code 2.1.277+ reads `AGENTS.md` when there is no `CLAUDE.md`; an existing `CLAUDE.md` hides it |
| One package: portable core + legacy shims, shared `.mcp.json` | A repo or fork per agent; inline MCP in the Claude manifest | One skill set; inline + `.mcp.json` would register the server twice in Claude Code |
| Plugin starts the MCP with `npx -y vyomi-tunnel mcp` (D4) | `vyomi-tunnel mcp` on PATH | No install needed for the MCP; GUI editors often lack the tunnel on PATH |
| npx copy hands over to an installed tunnel | Always run the npx copy | The MCP calls a tunnel back (`VYOMI_TUNNEL_BIN`); the installed one is the tunnel the user runs, so both commands stay the same server |
| MCP Registry name `io.github.vyomi-cloud/vyomi` (D2) | `cloud.vyomi/vyomi` | GitHub OIDC from the release job; no DNS record or key secret |
| MIT for `vyomi-cloud/claude-plugins` (D5) | No license | Open source is required by the Cursor Marketplace; the tunnel is MIT |

## Open issues
- [ ] Claims row on the trunk: `| agent-plugins | v4/agent-plugins | appliance | integrations/claude-plugins/**, cmd/vyomi/mcp_agents_md*.go, cmd/vyomi/mcp_tunnel_sync*.go, wasm/relay/mcp-launch.mjs, packaging/tunnel/{package.json,server.json,README.md,bin/mcp-launch.mjs}, tools/guardrails/run.sh, scripts/check_*.py | 2026-11-22 |` (owner: Rohith)
- [x] WP1-WP8 of `../AGENT-DISTRIBUTION-NOW.md` (2026-11-22; VERIFY.md GREEN)
- [x] Windows and macOS handover verified in CI (`tunnel-npx-smoke.yml`, green on all four OSes)
- [ ] Release dry run, npm/registry publish, merges and the Claude directory submission: `HUMAN-GATES.md` G2-G6 (owner: Rohith)
- [ ] Cursor Marketplace and OpenAI directory submissions paused (plan §7) (owner: Rohith)

## Testing
On Rohith's Mac (darwin/arm64, Go 1.27.1, Node 26), 2026-11-22, after `git am` of the five commits:
- `gofmt -l`, `go vet ./...`, `go test ./...` in `cmd/vyomi`: pass.
- `tools/guardrails/run.sh` with the CI test dependencies: all 8 implemented checks PASS (3 Threat A rows incl. "never writes"); GAP rows unchanged.
- `node --test` of `test-mcp-launch`, `test-list-json`, `test-tunnel-prune`, `test-mcp-codespace-e2e`: 27/27.
- `scripts/check_agent_plugins.py`, `scripts/sync_tunnel_bin.py`, `claude plugin validate integrations/claude-plugins`: pass.
Earlier, in the Linux sandbox: real installs from the local marketplace in Claude Code (1 MCP server, no duplicate), Codex 0.169,
Codex 0.140 and Copilot CLI; schema checks; the drift guard caught 9/9 mutations; a real `npx` run handed over to an installed
vyomi-tunnel 1.3.3 (8 tools served). NOT run yet: macOS/Windows npx smoke in CI, Cursor client install, the tunnel release dry run.
