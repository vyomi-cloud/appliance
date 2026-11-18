---
name: vyomi-nano
description: Use when the user runs Vyomi Nano, the browser simulator, or has no Docker - "Vyomi in the browser", "Nano", "vyomi-tunnel", "relay URL", "no Docker", "Free plan" - or when vyomi_status finds no simulator and the user is not on Pro/Max. Gets a working Nano endpoint on this machine, then hands back to the vyomi-setup workflow.
---

# Get a working Vyomi Nano endpoint

Nano runs the whole simulator in a browser tab (https://vyomi.cloud/nano, Free
and up). Local SDKs, CLIs and tests reach the tab through the **local tunnel**
(`vyomi-tunnel`, endpoint `http://127.0.0.1:8090` for every cloud) or, without
the tunnel, through the **cloud relay URL** shown in the Nano footer.

## Workflow

1. **Tunnel installed?** Run `vyomi-tunnel --version`. The minimum is
   **1.3.0**: it is also what runs this plugin's MCP server (`vyomi-tunnel mcp`).
   - Missing: suggest `brew install vyomi-cloud/tap/vyomi-tunnel` (or
     `npm i -g vyomi-tunnel`) and wait for the user.
   - Older than 1.3.0: suggest `brew upgrade vyomi-tunnel` (or
     `npm i -g vyomi-tunnel@latest`), then a Claude Code restart so the
     `vyomi` MCP server starts.
2. **Access key.** The tunnel needs the user's Vyomi access key (a Free key is
   enough) saved as `~/.vyomi/credentials`. **Ask the user** whether they have
   saved it; never open, read or print that file. If not: they download it from
   the Vyomi console (avatar menu > Access Key) and save it there themselves.
3. **Start the tunnel and open the tab.** Ask the user to run `vyomi-tunnel` in
   a terminal of their own (it is long-running; do not start it yourself) and to
   open https://vyomi.cloud/nano in the browser. Then call `vyomi_status` until
   the `nano-local` home shows `tab: true`. If it says `tab: false`, the tunnel
   is up but no tab is connected: the hint says what to do.
4. **No tunnel?** Ask the user for the relay URL from the Nano footer
   (`https://relay.vyomi.cloud/<session>`). It goes into `VYOMI_ENDPOINT` (for
   the MCP and in `.env.vyomi`). Relay sessions are short-lived: when calls start
   failing, the user copies the current URL again.
5. **Continue with `vyomi-setup`** using `home: nano`: scan, env, propose, ask,
   write, verify.

## Limits to tell the user

- The tab must stay open: closing it stops the simulator.
- Plain HTTP only. SDKs that insist on TLS do not work through the tunnel: Key
  Vault is not available on Nano; `vyomi_env` drops such settings and says why.
- The gRPC client libraries for GCP Pub/Sub and Firestore do not work through the
  tunnel; their REST APIs do (`vyomi_env` and `vyomi_snippet` give the URLs).
- Database ports (`db-tcp`) and Service Bus AMQP work only through the local
  tunnel, not the cloud relay.
- The cloud relay has payload caps; the local tunnel has none and is faster.
- No compute: AKS and GKE clusters and other features flagged `mesh: true` need
  a Pro/Max mesh (see `vyomi-mesh`); EKS is not simulated on Nano at all (the
  scan reports its level as `not_simulated`).

## Rules

- Never modify production configuration, deployment manifests or secrets. Add
  local/dev overrides only.
- For local-dev work, do not use MCP tools that act on a real cloud account
  (for example AWS's `aws-mcp`, or Azure / Google Cloud MCP servers) to create,
  read or change resources. Use the Vyomi tools and the local simulator; reach
  for a real-cloud tool only if the user explicitly asks for the real cloud.
- Services marked not emulated must not be silently pointed at Vyomi.
- Respect the scan and env warnings; they describe real protocol limits.
- Never tell a Nano user to run `vyomi up`: that starts the offline appliance or
  a local mesh, not Nano.
- Never read `~/.vyomi/credentials` or any key file; ask the user instead.
