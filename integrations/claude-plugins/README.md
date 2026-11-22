# Vyomi plugins for coding agents

[Vyomi](https://vyomi.cloud) is an AWS / GCP / Azure simulator for development.
In v4 it runs as **Nano** in your browser tab (Free and up) or as a **mesh**
(Pro/Max: locally or in your own GitHub Codespace). This marketplace ships the
`vyomi` plugin: the Vyomi MCP server plus three skills, so your coding agent can
find your simulator, scan a project, tell you which cloud services Vyomi
emulates in that place, wire your SDKs to it for local runs, and add a short
Vyomi section to your project's `AGENTS.md` so every other agent knows too.

One package works in Claude Code, Codex, GitHub Copilot, Cursor, VS Code and
other clients that read the [Agent Plugins](https://agent-plugins.org) format.

## 1. Before you start

- **Node.js 18 or newer.** The plugin starts the MCP server with
  `npx -y vyomi-tunnel mcp`. If `vyomi-tunnel` is installed, that runs your
  installed copy, so `npx -y vyomi-tunnel mcp` and `vyomi-tunnel mcp` are always
  the same server; with nothing installed it runs the npm copy.
- **The Vyomi tunnel, to use Nano** (1.3.0 or later):
  `brew install vyomi-cloud/tap/vyomi-tunnel` or `npm i -g vyomi-tunnel`.
  Check with `vyomi-tunnel --version`.

## 2. Add the plugin to your agent

| Agent | Install |
|---|---|
| **Claude Code** | `/plugin marketplace add vyomi-cloud/claude-plugins` then `/plugin install vyomi@vyomi` |
| **Codex** (CLI, IDE, app) | `codex plugin marketplace add vyomi-cloud/claude-plugins` then `codex plugin add vyomi@vyomi` |
| **GitHub Copilot CLI** | `copilot plugin marketplace add vyomi-cloud/claude-plugins` then `copilot plugin install vyomi@vyomi` |
| **Cursor** | Teams: import this repo as a team marketplace. Everyone else, until the Cursor Marketplace listing is live: add the MCP server below to `~/.cursor/mcp.json` |
| **Anything else** (Gemini CLI, Windsurf, Zed, ...) | Register the MCP server below in the agent's MCP config |

The MCP server on its own, for any MCP client:

```json
{ "mcpServers": { "vyomi": { "command": "npx", "args": ["-y", "vyomi-tunnel", "mcp"] } } }
```

Claude Code without the plugin: `claude mcp add --scope user vyomi -- npx -y vyomi-tunnel mcp`.
Codex without the plugin: `codex mcp add vyomi -- npx -y vyomi-tunnel mcp`.

If your agent cannot start `npx` (an editor opened from the Dock that does not
see your Node install, or native Windows, where some agents need
`cmd /c npx -y vyomi-tunnel mcp`), or the machine is offline, install the tunnel
and use `"command": "vyomi-tunnel", "args": ["mcp"]` instead.

**v4.0.0 offline users:** `vyomi mcp` from your `vyomi-docker` install keeps
working. Without the tunnel, register it directly:
`claude mcp add --scope user vyomi -- vyomi mcp` (or `"command": "vyomi", "args": ["mcp"]`).

## 3. Use it

Ask your agent: *"Set this project up to run against Vyomi."* It finds where
your simulator runs and tells you the next step (for Nano: save your access key,
run `vyomi-tunnel`, keep https://vyomi.cloud/nano open). It shows every file
change and waits for your OK before writing.

When local runs work, it offers to add a "Local cloud: Vyomi" section to your
`AGENTS.md`. Commit it, and every agent that opens the repo (your teammates',
or a cloud / PR agent with no plugin installed) knows to load `.env.vyomi` and
keep away from the real cloud. The section holds no endpoints or keys, and
re-running updates it in place between `<!-- vyomi:start -->` and
`<!-- vyomi:end -->`.

The MCP server needs no access key. Using Nano through the local tunnel needs
your Vyomi access key in `~/.vyomi/credentials` (a Free key is enough); a Mesh
Codespace needs a Pro or Max key.

## What's inside

| Component | What it does |
|---|---|
| MCP server `vyomi` (`npx -y vyomi-tunnel mcp`) | `vyomi_status` (which home: Nano, local mesh, Codespace mesh, offline), `vyomi_reach`, `vyomi_services`, `vyomi_capability`, `vyomi_snippet`, `vyomi_env`, `vyomi_scan_repo`, `vyomi_write_env`, `vyomi_write_agents_md` |
| Skill `vyomi-setup` | The workflow: find the home, scan, get exact settings for that home, propose dev-only changes, ask before writing, verify with your tests, offer the `AGENTS.md` section |
| Skill `vyomi-nano` | Get a working Nano endpoint: the tunnel, the access key, the tab, or the cloud relay URL; Nano's limits |
| Skill `vyomi-mesh` | Reach a local or Codespace mesh: status, forwards for the API, k3s and databases, `ssh <vm>.vyomi`, locked meshes, AI models |

### Package layout

One set of skills and one MCP server, described for each client:

| File | Read by |
|---|---|
| `plugins/vyomi/plugin.json`, `mcp.json` | [Agent Plugins 1.0](https://agent-plugins.org) clients: Codex 0.146+, Cursor 3.13+, GitHub Copilot, VS Code, Kiro, ChatGPT |
| `plugins/vyomi/.claude-plugin/plugin.json` | Claude Code |
| `plugins/vyomi/.codex-plugin/plugin.json` | Codex before 0.146 |
| `plugins/vyomi/.cursor-plugin/plugin.json` | Cursor before 3.13 |
| `plugins/vyomi/.mcp.json` | Claude Code, older Codex and older Cursor |
| `plugins/vyomi/skills/` | Every client |
| `.claude-plugin/marketplace.json` | Claude Code, GitHub Copilot CLI |
| `.agents/plugins/marketplace.json` | Codex |
| `.cursor-plugin/marketplace.json` | Cursor team marketplaces |

All manifests carry the same name, version and MCP server;
`scripts/check_agent_plugins.py` in the appliance repo enforces that.

This repository is generated from
[`vyomi-cloud/appliance` / `integrations/claude-plugins`](https://github.com/vyomi-cloud/appliance/tree/main/integrations/claude-plugins)
on every release. Open issues and pull requests there.
