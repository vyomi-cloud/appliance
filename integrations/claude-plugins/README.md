# Vyomi plugins for Claude Code

[Vyomi](https://vyomi.cloud) is a local AWS / GCP / Azure simulator. This
marketplace ships the `vyomi` plugin: the Vyomi MCP server plus a setup skill,
so Claude Code can scan a project, tell you which cloud services Vyomi emulates,
and wire your SDKs to the simulator for local runs.

## Install

1. Install the Vyomi CLI (it provides the MCP server):
   - macOS / Linux: `brew install vyomi-cloud/tap/vyomi-docker`
   - Windows: the MSI from the [latest release](https://github.com/vyomi-cloud/appliance/releases)
2. In Claude Code:
   ```
   /plugin marketplace add vyomi-cloud/claude-plugins
   /plugin install vyomi@vyomi
   ```
3. Start the simulator with `vyomi up`, then ask Claude:
   *"Set this project up to run against Vyomi."*

Without the plugin you can register only the MCP server:
`claude mcp add --scope user vyomi -- vyomi mcp`.

## What's inside

| Component | What it does |
|---|---|
| MCP server `vyomi` (`vyomi mcp`) | `vyomi_status`, `vyomi_services`, `vyomi_env`, `vyomi_scan_repo`, `vyomi_write_env` |
| Skill `vyomi-setup` | The workflow: check status, scan, get exact settings, propose dev-only changes, ask before writing, verify with your tests |

This repository is generated from
[`vyomi-cloud/appliance` / `integrations/claude-plugins`](https://github.com/vyomi-cloud/appliance/tree/main/integrations/claude-plugins)
on every release. Open issues and pull requests there.
