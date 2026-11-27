# Vyomi

Run and test AWS, GCP and Azure code locally against [Vyomi](https://vyomi.cloud), a local cloud simulator:
Vyomi Nano in a browser tab, or a Pro/Max mesh on your machine or in your own GitHub Codespace. The plugin adds
one MCP server, `vyomi`, and three skills (`vyomi-setup`, `vyomi-nano`, `vyomi-mesh`). Ask your agent:
"Set this project up to run against Vyomi." It finds your simulator, scans the project for cloud SDK and
Terraform usage, shows what Vyomi emulates, and proposes a dev-only `.env.vyomi`. It writes nothing until you
say yes, and it never changes production config.

## What it runs

The MCP server starts with:

```
npx -y vyomi-tunnel@1.4.1 mcp
```

- npx downloads the `vyomi-tunnel` npm package, version 1.4.0 exactly, on the first start and runs it from the
  npm cache afterwards. Node.js 18 or newer must be on the PATH your agent sees.
- The package contains the tunnel (JavaScript) and a prebuilt MCP server binary for each supported platform
  (macOS arm64/x64, Linux arm64/x64, Windows x64). `mcp` starts that binary on stdin/stdout.
- If `vyomi-tunnel` 1.3.0 or newer is already installed on your machine, the npx copy hands over to the
  installed one, so `npx` and an installed `vyomi-tunnel mcp` always run the same server. Set
  `VYOMI_MCP_DELEGATE=0` to always run the npx copy.
- The skills are instructions for the agent only. The plugin has no hooks, commands or background processes.

## What it connects to

| Host | When | Why |
|---|---|---|
| registry.npmjs.org | First start (then cached) | npx downloads `vyomi-tunnel@1.4.1` |
| 127.0.0.1 | Each status or reach call | Health checks of your local simulator: the Nano tunnel on port 8090 (`/health`) and a local mesh or offline appliance on port 9000 (`/healthz`). The settings it proposes point your SDKs at 127.0.0.1 (ports 8090, 9000, and 9443 for TLS). |
| vyomi.cloud | Only when Vyomi tunnel credentials exist (`~/.vyomi/credentials`) | The status and reach tools run `vyomi-tunnel list mesh`, which asks the Vyomi portal for your Mesh session. The request is signed with your access key; the secret key is never sent. The MCP server itself only checks that the credentials file exists and never reads it. |
| relay.vyomi.cloud | Only when you set `VYOMI_ENDPOINT` to a Nano cloud relay URL | Health check of that relay |
| api.github.com | Only for a mesh in your own GitHub Codespace | `vyomi-tunnel` uses your GitHub CLI (`gh`) login to list the Codespace and reach the mesh through `gh codespace ssh` |

Nothing else is contacted, and the plugin sends no telemetry. The project files that the scan reads stay on your
machine; only the tool results go to your agent.

## What it writes

Of the 9 tools, 8 are read-only and one writes:

- `vyomi_write_env` writes `.env.vyomi` in your project, after you agree. It refuses any path outside the
  project and any file name other than `.env.vyomi`, and does not overwrite unless asked.
- `vyomi_agents_md` writes nothing. It proposes a short "Local cloud: Vyomi" section for `AGENTS.md`, plus an
  `@AGENTS.md` import line when a `CLAUDE.md` would otherwise hide it. Your agent applies it with its own edit
  tool, and only after you say yes.

## Tools

| Tool | What it does |
|---|---|
| `vyomi_status` | Whether a simulator is running, its endpoint, tier, active space and readiness |
| `vyomi_reach` | What this machine can reach (Nano tunnel, in-browser VMs and databases, mesh hosts) and the command for each |
| `vyomi_services` | The emulated services for each cloud: status, actions, data plane, SDK support |
| `vyomi_capability` | Searches Vyomi's capability registry for a feature and its limits |
| `vyomi_snippet` | A ready-to-run CLI, Python, JavaScript or curl call for one operation |
| `vyomi_env` | Environment variables, SDK config and a Terraform block for one cloud |
| `vyomi_scan_repo` | Finds cloud SDK and Terraform usage in a project and maps it to Vyomi coverage |
| `vyomi_write_env` | Writes `.env.vyomi` (the only writer) |
| `vyomi_agents_md` | Proposes the `AGENTS.md` section (writes nothing) |

## Install

Claude Code:

```
/plugin marketplace add vyomi-cloud/claude-plugins
/plugin install vyomi@vyomi
```

Codex:

```
codex plugin marketplace add vyomi-cloud/claude-plugins
codex plugin add vyomi@vyomi
```

GitHub Copilot CLI:

```
copilot plugin marketplace add vyomi-cloud/claude-plugins
copilot plugin install vyomi@vyomi
```

Cursor: teams can import the [plugin repository](https://github.com/vyomi-cloud/claude-plugins) as a team
marketplace and install `vyomi` from it. Everyone else can add the MCP server to `~/.cursor/mcp.json`:

```
{ "mcpServers": { "vyomi": { "command": "npx", "args": ["-y", "vyomi-tunnel@1.4.1", "mcp"] } } }
```

To reach Vyomi Nano you also need the tunnel running on your machine; the `vyomi-nano` skill walks you through it.

## License

MIT. See the LICENSE file in the [plugin repository](https://github.com/vyomi-cloud/claude-plugins).
