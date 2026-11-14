# Vyomi plugins for Claude Code

[Vyomi](https://vyomi.cloud) is an AWS / GCP / Azure simulator for development.
In v4 it runs as **Nano** in your browser tab (Free and up) or as a **mesh**
(Pro/Max: locally or in your own GitHub Codespace). This marketplace ships the
`vyomi` plugin: the Vyomi MCP server plus three skills, so Claude Code can find
your simulator, scan a project, tell you which cloud services Vyomi emulates in
that place, and wire your SDKs to it for local runs.

## Install

1. Install the Vyomi tunnel, **version 1.3.0 or later** (the first with
   `vyomi-tunnel mcp`, which runs the MCP server; it is bundled, nothing else to install):
   - `brew install vyomi-cloud/tap/vyomi-tunnel`, or
   - `npm i -g vyomi-tunnel`

   Check with `vyomi-tunnel --version`; upgrade with `brew upgrade vyomi-tunnel`
   or `npm i -g vyomi-tunnel@latest`.
2. In Claude Code:
   ```
   /plugin marketplace add vyomi-cloud/claude-plugins
   /plugin install vyomi@vyomi
   ```
3. Ask Claude: *"Set this project up to run against Vyomi."* It finds where your
   simulator runs and tells you the next step (for Nano: save your access key,
   run `vyomi-tunnel`, keep https://vyomi.cloud/nano open).

The MCP server needs no access key. Using Nano through the local tunnel needs
your Vyomi access key in `~/.vyomi/credentials` (a Free key is enough); a Mesh
Codespace needs a Pro or Max key.

Without the plugin you can register only the MCP server:
`claude mcp add --scope user vyomi -- vyomi-tunnel mcp`.

**v4.0.0 offline users:** `vyomi mcp` from your `vyomi-docker` install keeps
working. Without the tunnel, register it directly:
`claude mcp add --scope user vyomi -- vyomi mcp`.

## What's inside

| Component | What it does |
|---|---|
| MCP server `vyomi` (`vyomi-tunnel mcp`) | `vyomi_status` (which home: Nano, local mesh, Codespace mesh, offline), `vyomi_reach`, `vyomi_services`, `vyomi_capability`, `vyomi_snippet`, `vyomi_env`, `vyomi_scan_repo`, `vyomi_write_env` |
| Skill `vyomi-setup` | The workflow: find the home, scan, get exact settings for that home, propose dev-only changes, ask before writing, verify with your tests |
| Skill `vyomi-nano` | Get a working Nano endpoint: the tunnel, the access key, the tab, or the cloud relay URL; Nano's limits |
| Skill `vyomi-mesh` | Reach a local or Codespace mesh: status, forwards for the API, k3s and databases, `ssh <vm>.vyomi`, locked meshes, AI models |

This repository is generated from
[`vyomi-cloud/appliance` / `integrations/claude-plugins`](https://github.com/vyomi-cloud/appliance/tree/main/integrations/claude-plugins)
on every release. Open issues and pull requests there.
