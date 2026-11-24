# vyomi-tunnel — Vyomi-Nano local relay

Reach the **in-browser** Vyomi-Nano cloud simulator (Pyodide + the conformance
cores, running in your browser tab) from any local SDK/CLI — `aws`, `boto3`,
`azure-cli`, native SDKs — by pointing them at a local endpoint.

It's a tiny reverse-tunnel: your Nano tab opens an outbound WebSocket to this
process; external HTTP requests you send to the tunnel are relayed to the tab
and answered by the in-browser handlers.

```
  aws/boto3/SDK ──HTTP──▶ vyomi-tunnel (:8090) ──WS──▶ Nano tab (Pyodide + cores)
```

## Install & run

```bash
brew install vyomi-cloud/tap/vyomi-tunnel
vyomi-tunnel
```

That's it. Open (or refresh) the Nano tab — the frozen footer auto-detects the
tunnel and flips to **“connected · local”**. Point your tools at it:

```bash
aws --endpoint-url http://127.0.0.1:8090 s3 ls
```

## Local vs cloud — you don't have to choose

The Nano bundle prefers this local tunnel when it's present and **falls back to
the hosted Cloudflare tunnel** when it isn't — automatically, both directions:

- Start `vyomi-tunnel` any time (even after the tab is open) → Nano switches **to
  local** within ~15s.
- Stop it → Nano falls back **to cloud** within ~30s.

No reload, no config. So `brew install vyomi-tunnel` is optional: skip it and you
get the cloud tunnel; install it whenever you want the faster, private, offline
local path.

## Options

| Env var      | Default     | Meaning                                            |
|--------------|-------------|----------------------------------------------------|
| `RELAY_PORT` | `8090`      | Port for both the HTTP surface and `/register` WS. |
| `RELAY_HOST` | `127.0.0.1` | Bind address. Set `0.0.0.0` to reach it from LAN.  |

If you change the port, tell the Nano tab (browser console, once):

```js
localStorage.setItem("nano_local_health", "http://127.0.0.1:9000/health");
localStorage.setItem("nano_local_ws",     "ws://127.0.0.1:9000/register");
localStorage.setItem("nano_local_ext",    "http://127.0.0.1:9000");
```

## SSH into Nano VMs (1.1.0+)

With in-browser VM compute on in Nano, every EC2 instance, Compute Engine
instance and Azure VM is a real Linux VM running in your browser tab. The tunnel
gives each one a TCP port on this machine (127.0.0.1:22000-22999, shown in the
instance's Connect tab) and bridges it to the VM's SSH server, so a normal
`ssh` works from your terminal while the Nano tab is open:

```bash
ssh -i ~/.ssh/vyomi-<instance>.pem -p 22000 ec2-user@127.0.0.1
```

`GET /health` lists `"vm-tcp"` in `features` and the bridged VMs under `vms`.
Port range: `VM_PORT_MIN` / `VM_PORT_MAX`.

## Agents: the Vyomi MCP server (1.3.0+): Claude Code, Codex, Cursor, VS Code

`vyomi-tunnel mcp` runs the Vyomi MCP server on stdin/stdout for Claude Code and
other agents. The package bundles it for macOS (arm64, x64), Linux (arm64, x64) and Windows
(x64). Agents start it with `npx -y vyomi-tunnel mcp`, so the MCP needs Node.js 18+ and
no install. If `vyomi-tunnel` is installed (1.3.0+), that command runs your installed copy, so
`npx -y vyomi-tunnel mcp` and `vyomi-tunnel mcp` are always the same server. Keep it at 1.4.0+
(`npm i -g vyomi-tunnel`): an older installed tunnel serves its older MCP, without `vyomi_agents_md`.
From 1.4.0, `vyomi_status` tells the agent when npm has a newer tunnel.

Claude Code (the Vyomi plugin adds this server plus setup skills: `claude plugin install vyomi@vyomi`):

```bash
claude mcp add --scope user vyomi -- npx -y vyomi-tunnel mcp
```

Cursor: `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

```json
{ "mcpServers": { "vyomi": { "command": "npx", "args": ["-y", "vyomi-tunnel", "mcp"] } } }
```

VS Code (Copilot agent mode): `.vscode/mcp.json` in the project, or `code --add-mcp '{"name":"vyomi","command":"npx","args":["-y","vyomi-tunnel","mcp"]}'`:

```json
{ "servers": { "vyomi": { "type": "stdio", "command": "npx", "args": ["-y", "vyomi-tunnel", "mcp"] } } }
```

The portable `.mcp.json` at the project root uses the Cursor shape (`mcpServers`) and works across tools that read it.

OpenAI Codex (CLI, IDE extension and app share `~/.codex/config.toml`):

```bash
codex mcp add vyomi -- npx -y vyomi-tunnel mcp
```

```toml
[mcp_servers.vyomi]
command = "npx"
args = ["-y", "vyomi-tunnel", "mcp"]
```

Offline, or an agent that cannot start `npx` (native Windows agents may need `cmd /c npx -y vyomi-tunnel mcp`):
install the tunnel and register `vyomi-tunnel mcp` instead (command `vyomi-tunnel`, args `["mcp"]`); v4.0.0
offline appliance users can register `vyomi mcp`. Every client gets the same tools and the same built-in instructions
(including: never write `.env.vyomi` without your yes); the setup skills come with the plugin.

It finds your simulator (the Nano tab through this tunnel, a local mesh, or your
Mesh Codespace), says which one it uses, and gives SDK settings, capability levels
and examples for it. It needs no access key; only live Mesh Codespace details do
(through `vyomi-tunnel list`). On a platform without a bundled binary it runs
`vyomi-mcp`, then `vyomi mcp`, from your PATH. The Vyomi Claude Code plugin uses it.

## `vyomi-tunnel list --json`

A stable contract for scripts and the MCP:

```json
{ "schema": 1,
  "rows": [ { "where": "local", "name": "nano-api", "type": "api",
              "address": "http://127.0.0.1:8090", "connect": "aws --endpoint-url ..." } ],
  "notes": [ "mesh: Mesh is not running. Start it in the Vyomi console, then retry." ] }
```

Exit code 0 when there are rows, 1 when there are none, 2 with no credentials or a
usage error. JSON is printed in every case except a usage error. Listing never
edits `~/.ssh/config`: run `vyomi-tunnel config` once for `ssh <name>.vyomi`.

## Notes

- **Safari**: connecting an `https://` page to `ws://localhost` can be blocked;
  Chrome/Edge/Firefox allow it (loopback is exempt from mixed-content). On Safari,
  use the cloud tunnel or serve Nano over `http://localhost`.
- Single active tab (MVP). The hosted Cloudflare tunnel keys per-session via a
  Durable Object; this local build holds one registered tab.

Canonical source: `wasm/relay/local-relay.mjs` in the appliance repo.

## Re-pair the tunnel (`reset`)

If the tunnel's access key was revoked, belongs to another account, or is missing, the Vyomi console shows a strip with **Reset tunnel**.
From a terminal: `vyomi-tunnel reset <code>` (or paste the install link `https://vyomi.cloud/i/<code>`). Get the one-time code from the
console: Setup Tunnel > Get install command. It writes a new key to `~/.vyomi/credentials` (mode 600, old file kept as `credentials.bak.<time>`)
and a running tunnel reloads it by itself.
