# Vyomi plugin for every coding agent + AGENTS.md: design history

Status: design record, 2026-11-14 to 2026-11-22 · Owner: Rohith · Exported from the Claude doc "Vyomi plugin for every coding agent
+ AGENTS.md — plan", with later decisions folded in. The execution plan is `AGENT-DISTRIBUTION-NOW.md`; where the two differ, that
file wins. Branch: `v4/agent-plugins` (`branches/agent-plugins.md`).

## Summary

Ship plugin 4.2.0 and vyomi-tunnel 1.4.0 so the full Vyomi plugin (MCP server plus the three skills) installs with one command in
Claude Code, Codex, GitHub Copilot, Cursor and VS Code. Before this, only Claude Code got the skills.

A new read-only MCP tool, `vyomi_agents_md`, proposes a short Vyomi section for the user's `AGENTS.md`. The agent writes it with its
own edit tool, after the user approves. Once the file is committed, every agent that opens the repo knows to run against Vyomi,
including teammates' agents and cloud agents with no plugin installed.

The guardrail stays intact: the MCP's only write path is still `.env.vyomi`. The tool surface grows from 7 read-only tools to 8,
still with one writer.

## How the idea started (2026-11-14)

- **One package, thin wrapper per agent.** Agent Plugins 1.0 (Aug 2026; Codex, Cursor, Copilot, VS Code, Kiro, ChatGPT) packages
  skills + MCP servers in a root `plugin.json`. Copilot CLI and Codex also read `.claude-plugin/marketplace.json`. Older Codex and
  Cursor need `.codex-plugin/` and `.cursor-plugin/` manifests. Gemini CLI uses `gemini-extension.json` at a repo root (deferred).
- **AGENTS.md is the bigger lever.** Not an `AGENTS.md` in the plugin repo, but a Vyomi section written into the user's project
  `AGENTS.md`: zero install, read by every agent, spreads to teammates through `git pull`. Marker-delimited so re-runs update it in
  place; home-agnostic (no endpoints, which stay in `.env.vyomi`); always shown and approved before writing.
- **Product notes:** make the CLI the installer (later: gap 2, `vyomi-tunnel init`), keep skills agent-neutral, generate all
  manifests from one source with a drift check, skip hooks (not portable), measure which agents users come from (later: gap 8).

## What changed by 2026-11-22, and how it reshaped the design

| Change on trunk | Effect on this work |
| --- | --- |
| `v4/mcp-v4-knowledge` merged. Plugin 4.1.2 and tunnel 1.3.3 published, with a plugin icon and Mesh skill updates | The 14 Nov branch was stacked on it; rebased straight onto `v4-on-main`. The only conflicts were version strings |
| Tool surface pinned at 7 read-only + 1 writer (#676). The guardrail says the only write is one `.env.vyomi*` file | The 14 Nov writer tool `vyomi_write_agents_md` failed 2 guardrail tests. Redesigned as read-only `vyomi_agents_md`: it proposes, the agent writes with its own edit tool |
| Guardrails release gate (#698) is a hard dependency of every release workflow | The new pin (8 + 1) and a "never writes" check go into the gate in the same change |
| Claude Code 2.1.277 reads `AGENTS.md` when the project has no `CLAUDE.md`; an existing `CLAUDE.md` hides it unless it imports it | Never create a `CLAUDE.md`. Propose `@AGENTS.md` only when a `CLAUDE.md` exists. The `claude_md` argument is gone |

Decisions made on 2026-11-22 (details in `AGENT-DISTRIBUTION-NOW.md` §6): tool surface 8 + 1 approved; MCP Registry name
`io.github.vyomi-cloud/vyomi`; tunnel 1.4.0; plugin and snippets use `npx -y vyomi-tunnel mcp`, with the npx copy handing over to an
installed tunnel so both commands run the same server; MIT license for `vyomi-cloud/claude-plugins`; Cursor and OpenAI directory
submissions paused.

## Today vs after

| Area | Before (plugin 4.1.2, tunnel 1.3.3) | After (plugin 4.2.0, tunnel 1.4.0) |
| --- | --- | --- |
| Claude Code | Plugin: MCP + 3 skills, via `/plugin install` | Same; MCP from the shared `.mcp.json` via `npx -y vyomi-tunnel mcp`. Skills offer the AGENTS.md step |
| Codex 0.146+ | MCP only, by hand. No skills | `codex plugin add vyomi@vyomi`: MCP + 3 skills, from the portable `plugin.json` |
| Codex before 0.146 | MCP only, by hand | Same one command, through the `.codex-plugin/` fallback |
| GitHub Copilot CLI / VS Code | MCP only, by hand | `copilot plugin install vyomi@vyomi`: MCP + 3 skills |
| Cursor | MCP only, by hand | Team marketplace import now; Cursor Marketplace listing later (paused). Older Cursor uses `.cursor-plugin/` |
| Gemini CLI, Windsurf, others | MCP only, by hand | MCP snippet (npx). They still get the AGENTS.md section |
| Agents with no plugin (cloud, PR, teammates') | Know nothing about Vyomi | Read the committed `AGENTS.md` section |
| MCP tool surface | 7 read-only + `vyomi_write_env` | 8 read-only (adds `vyomi_agents_md`) + `vyomi_write_env` |
| Manifest drift protection | `claude plugin validate` + version-bump guard | Adds `check_agent_plugins.py`, gating CI and the release sync |

## How the pieces fit

- **Shared core:** `vyomi-tunnel mcp` (8 read-only tools + `vyomi_write_env`) and 3 skills (setup, nano, mesh).
- **Four ways in:** Agent Plugins 1.0 (`plugin.json`, `mcp.json`: Codex 0.146+, Cursor 3.13+, Copilot, VS Code); Claude Code
  (`.claude-plugin/` + shared `.mcp.json`; Copilot CLI reads its marketplace too); legacy shims (`.codex-plugin/`,
  `.cursor-plugin/`); MCP by hand for everything else (no skills).
- **No install at all:** the `AGENTS.md` section in the user's repo, proposed by `vyomi_agents_md` and written by the agent's own
  edit tool after a yes.

## Spike evidence (2026-11-22, on `0df22d4e`)

| Run | Result |
| --- | --- |
| 14 Nov commits replayed on trunk | Tool commit applied cleanly; plugin commit conflicted only on version strings |
| 14 Nov writer tool vs the guardrail | Failed `TestMCPToolSurfaceIsPinned` and `TestMCPToolAnnotationsOnTheWire`: confirmed the redesign |
| Read-only `vyomi_agents_md`: `go vet`, `gofmt`, full `go test` | Pass |
| `tools/guardrails/run.sh`, Threat A | 3/3 PASS |
| Real installs (14 Nov) | Claude Code (1 MCP server, no duplicate), Codex 0.169, Codex 0.140, Copilot CLI |
| On Rohith's Mac after `git am` (Go 1.27.1) | Go suite, full guardrail gate (8/8 implemented checks), 27/27 tunnel tests, drift check, `claude plugin validate`: pass |

## Sources

- [Agent Plugins 1.0.0 announcement (Vercel)](https://vercel.com/changelog/introducing-agent-plugins-1-0-0)
- [Codex: build plugins](https://developers.openai.com/codex/plugins/build/)
- [Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Claude Code AGENTS.md support (Apidog)](https://apidog.com/blog/claude-code-agents-md/)
- [Claude Code adds AGENTS.md fallback (DevOps.com)](https://devops.com/claude-code-adds-agents-md-fallback-cutting-instruction-file-sprawl/)
- [CLAUDE.md hides AGENTS.md unless imported (SSW rule)](https://www.ssw.com.au/rules/symlink-agents-to-claude)
