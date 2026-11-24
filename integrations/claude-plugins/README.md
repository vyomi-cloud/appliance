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

**Two plugins, one marketplace.** Pick by where you want the MCP server to run:

| Plugin | Server | Install needed | Sees your machine |
|---|---|---|---|
| **`vyomi`** | on your machine (`npx -y vyomi-tunnel mcp`) | Node.js 18+, and the tunnel for Nano | Yes: finds your simulator, scans the project itself, writes `.env.vyomi` after you approve |
| **`vyomi-cloud`** | Vyomi's hosted server, `https://vyomi.cloud/mcp` | nothing | No. Read-only knowledge and proposals; your agent greps and writes files. Works on claude.ai, ChatGPT and Cowork, where a local server cannot run |

Both can be installed at once; the skills notice which tools they have and
follow the right flow. `plugins/vyomi-cloud/README.md` lists exactly what each
hosted call receives and what is kept.

## 1. Before you start

- **Node.js 18 or newer.** The plugin starts the MCP server with
  `npx -y vyomi-tunnel mcp`. If `vyomi-tunnel` is installed, that runs your
  installed copy, so `npx -y vyomi-tunnel mcp` and `vyomi-tunnel mcp` are always
  the same server; with nothing installed it runs the npm copy.
- **The Vyomi tunnel, to use Nano** (1.3.0 or later; 1.4.0 or later for the
  `AGENTS.md` step): `brew install vyomi-cloud/tap/vyomi-tunnel` or
  `npm i -g vyomi-tunnel`. Check with `vyomi-tunnel --version`.

## 2. Add the plugin to your agent

The plugin (MCP server plus the three skills), from this GitHub marketplace:

| Agent | Add the marketplace | Install the plugin |
|---|---|---|
| **Claude Code** | `/plugin marketplace add vyomi-cloud/claude-plugins` | `/plugin install vyomi@vyomi` |
| **Codex** (CLI, IDE, app) | `codex plugin marketplace add vyomi-cloud/claude-plugins` | `codex plugin add vyomi@vyomi` |
| **GitHub Copilot CLI** | `copilot plugin marketplace add vyomi-cloud/claude-plugins` | `copilot plugin install vyomi@vyomi` |
| **Cursor** | Teams: import this repo as a team marketplace (`.cursor-plugin/marketplace.json`) | Install `vyomi` from it. Everyone else, until the Cursor Marketplace listing is live: add the MCP server below to `~/.cursor/mcp.json` |

Claude Code also takes the shell form: `claude plugin marketplace add vyomi-cloud/claude-plugins`
then `claude plugin install vyomi@vyomi`.

For the hosted plugin, install `vyomi-cloud` instead of `vyomi` in any of those
commands — it needs no Node.js and no tunnel.

The MCP server on its own (no skills), for any MCP client:

| Agent | Command or config |
|---|---|
| **Claude Code** | `claude mcp add --scope user vyomi -- npx -y vyomi-tunnel mcp` |
| **Codex** | `codex mcp add vyomi -- npx -y vyomi-tunnel mcp` |
| **GitHub Copilot CLI** | `copilot mcp add vyomi -- npx -y vyomi-tunnel mcp` |
| **Cursor** | the JSON below in `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project) |
| **Anything else** (Gemini CLI, Windsurf, Zed, VS Code, ...) | the JSON below in the agent's MCP config |

```json
{ "mcpServers": { "vyomi": { "command": "npx", "args": ["-y", "vyomi-tunnel", "mcp"] } } }
```

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
`<!-- vyomi:end -->`. The MCP only proposes the text (`vyomi_agents_md`); your
agent shows it to you and writes it with its own edit tool after you say yes.
If the project has a `CLAUDE.md` (or `.claude/CLAUDE.md`, `CLAUDE.local.md`),
it also proposes an `@AGENTS.md` import there, because Claude Code ignores
`AGENTS.md` otherwise. With a tunnel older than 1.4.0 the agent writes the same
marked section by hand, again only after your OK.

The MCP server needs no access key. Using Nano through the local tunnel needs
your Vyomi access key in `~/.vyomi/credentials` (a Free key is enough); a Mesh
Codespace needs a Pro or Max key.

## What's inside

| Component | What it does |
|---|---|
| MCP server `vyomi` (`npx -y vyomi-tunnel mcp`) | 9 tools. Read-only: `vyomi_status` (which home: Nano, local mesh, Codespace mesh, offline), `vyomi_reach`, `vyomi_services`, `vyomi_capability`, `vyomi_snippet`, `vyomi_env`, `vyomi_scan_repo`, `vyomi_agents_md` (proposes the `AGENTS.md` section; the agent applies it with its own edit tool after you approve). The one writer: `vyomi_write_env` (`.env.vyomi`, only after you approve) |
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

All manifests carry the same name, version, MCP server and tunnel requirement,
and share one icon (`plugins/vyomi/.claude-plugin/icon.png`);
`scripts/check_agent_plugins.py` in the appliance repo enforces that and, in CI,
validates the files against the Agent Plugins 1.0.0 and Cursor JSON Schemas.

This repository is generated from
[`vyomi-cloud/appliance` / `integrations/claude-plugins`](https://github.com/vyomi-cloud/appliance/tree/main/integrations/claude-plugins)
on every release. Open issues and pull requests there.
