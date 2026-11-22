---
name: vyomi-nano
description: Use when the user runs Vyomi Nano, the browser simulator, or has no Docker - "Vyomi in the browser", "Nano", "vyomi-tunnel", "relay URL", "no Docker", "Free plan" - or when nothing answers on 127.0.0.1 and the user is not on a mesh. Gets a working Nano endpoint on the user's machine, then hands back to the vyomi-setup workflow.
---

# Get a working Vyomi Nano endpoint

Nano runs the whole simulator in a browser tab (https://vyomi.cloud/nano, Free and up). Code on the user's
machine reaches that tab in one of two ways:

- the **local tunnel** (`vyomi-tunnel`), which serves every cloud at `http://127.0.0.1:8090`; or
- the **cloud relay URL** shown in the Nano footer, with no install at all.

This skill works with either Vyomi MCP server. With the **local** server (you have `vyomi_status`) call it first
and follow its `hint`. With the **hosted** server (`https://vyomi.cloud/mcp`; you have `get_scan_rules`) nothing
can be detected for you — the server cannot see the user's machine — so check it yourself or ask.

## Workflow

1. **Is a tunnel already serving the tab?** With your own shell:
   ```sh
   curl -s --max-time 2 http://127.0.0.1:8090/health
   ```
   An answer means the tunnel is up. Confirm a Nano tab is actually open, then go back to `vyomi-setup` with
   `home=nano`.

2. **No answer, and the user wants the tunnel.** `vyomi-tunnel --version`; the minimum is **1.3.0**.
   - Missing: suggest `brew install vyomi-cloud/tap/vyomi-tunnel`, or `npm i -g vyomi-tunnel` (Node.js 18+), and
     wait for the user.
   - Then: they run `vyomi-tunnel` in its own terminal and keep it open, and open https://vyomi.cloud/nano in a
     browser tab and keep that open too. The tunnel forwards to the tab; with the tab closed, calls fail.
   - Re-check `http://127.0.0.1:8090/health`.

3. **No install wanted, or no Node.js and no Homebrew: use the relay.** Ask the user to open
   https://vyomi.cloud/nano and copy the **relay URL from the footer of the tab**.
   - Pass `nano_access=relay` (hosted server) to `get_sdk_settings`, `get_code_snippet` and `propose_env_file`.
     The answers come back with the literal placeholder `${VYOMI_RELAY_URL}`.
   - Substitute it yourself in the files and commands you produce, or have the user
     `export VYOMI_RELAY_URL='<the URL from the footer>'` so their shell and dotenv loader do it.
   - **Never send that URL to the hosted server, and never put it in a committed file.** Anyone holding it can
     drive the user's tab. The server has no input that accepts it, which is why there is a placeholder.
   - The relay carries HTTP only: Service Bus AMQP and the gRPC Pub/Sub and Firestore clients need the local
     tunnel. Payload caps apply, and it is slower than the tunnel.

4. **Nothing works.** The tab has to be open and signed in. Ask the user to reload https://vyomi.cloud/nano and
   confirm the simulator shows as running there. Do not offer `vyomi up`: that starts an appliance or a mesh, not
   Nano.

## What Nano cannot do

Nano is plain HTTP with no TLS endpoint, so services whose SDKs insist on TLS (Azure Cosmos DB, Key Vault) are
not reachable there; `check_capability` says so per feature, and `get_sdk_settings` returns the warning instead
of a value it cannot honour. Features that need real compute (AKS and GKE clusters, VMs over ssh, k3s) are
available on a Vyomi mesh — see the `vyomi-mesh` skill.

Then go back to the `vyomi-setup` workflow with `home=nano`.
