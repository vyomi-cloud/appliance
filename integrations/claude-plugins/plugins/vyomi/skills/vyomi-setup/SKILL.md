---
name: vyomi-setup
description: Use when the user wants to run, test or develop cloud code locally instead of against real AWS, GCP or Azure - "run this against Vyomi", "test locally without the cloud", "set up a local cloud", "use Vyomi instead of LocalStack", or asks whether Vyomi supports the services a project uses.
---

# Set a project up to run against Vyomi

Vyomi is a local simulator of AWS, GCP and Azure. Real cloud SDKs, CLIs and
Terraform talk to it instead of the real cloud during development; production
keeps running on the real cloud. The `vyomi` MCP server (bundled with this
plugin) knows what Vyomi emulates, where the user's simulator lives and how to
point code at it.

**Requires `vyomi-tunnel` 1.3.0 or newer**: the plugin runs its MCP server as
`vyomi-tunnel mcp`, which first shipped in 1.3.0 (check with
`vyomi-tunnel --version`).

In v4 the simulator lives in one of these **homes**:

- **Nano** (`nano-local`, `nano-cloud`): a browser tab at https://vyomi.cloud/nano
  (Free and up), reached from this machine through the `vyomi-tunnel` local
  tunnel (`http://127.0.0.1:8090`) or the cloud relay URL shown in the Nano footer.
- **Local mesh** (`mesh-local`): the headless Pro/Max appliance on `:9000`.
- **Codespace mesh** (`mesh-codespace`): a Pro/Max mesh in the user's own
  GitHub Codespace, reached through `vyomi-tunnel forward`.
- **Offline** (`offline`): a v4.0.0 or v3 Docker appliance on `:9000`.

## Workflow

1. **Find the home.** Call `vyomi_status`.
   - `selected` is set: use that home. Pass its kind as `home` (`nano`, `mesh`
     or `offline`) to every later tool call.
   - `selected` is null and several homes are listed: ask the user *"Which space
     are you working in — the one in your browser (Nano) or your mesh?"* and use
     the answer.
   - `selected` is null and nothing is reachable: hand off to the `vyomi-nano`
     skill (the default), or to `vyomi-mesh` if the user says they are on
     Pro/Max. Knowledge, scan and env still work without a running simulator.
   - Follow the `hint` it returns. It is specific to the home (open the Nano
     tab, run a forward, renew a locked mesh).
   - `readiness` below 100% right after start-up only means backend containers
     are still starting.
2. **Scan the project.** Call `vyomi_scan_repo` with the absolute path of the
   project root and the `home`. Report back briefly, per cloud:
   - services that are emulated, with their `level` in this home (`full`,
     `limited`, `config_only`),
   - services that carry a `tier` of `pro` (they need a Pro licence),
   - services that **need a Pro/Max mesh** (`mesh: true`) when the home is Nano
     or offline - never wire them to that home,
   - services that are **not emulated** - those keep using the real cloud (or a
     stub) during local runs,
   - every `warning` verbatim in substance (they differ per home: for example on
     Nano, Key Vault is not available and Pub/Sub / Firestore need their REST
     APIs; offline, Cosmos DB and Key Vault need TLS on :9443),
   - `already_wired`: existing endpoint overrides to reuse, not duplicate.
   For a single feature ("does Vyomi do S3 object lock?") call `vyomi_capability`.
3. **Get the exact settings.** Call `vyomi_env` for each cloud found, with the
   `lang` the scan suggests and the `home`. Use its values and pass on its
   `warnings`; never invent endpoints, ports, keys or account names.
4. **Propose the change, then ask.** Prefer the least invasive option:
   - a `.env.vyomi` file (`vyomi_write_env` with the `home`) loaded only for
     local runs,
   - a docker compose override or test fixture that sets the variables,
   - code changes only where an SDK cannot be pointed at an endpoint through
     configuration.
   Show what will change and get the user's OK before writing anything.
5. **Verify.** Run the project's own tests or a smoke command with the
   variables loaded, and report what passed and what failed. `vyomi_snippet`
   gives a one-line CLI / SDK / curl call aimed at the home's endpoint for a
   quick check. If a failure looks like a missing API in Vyomi, say so plainly
   rather than working around it.

## Rules

- Never modify production configuration, deployment manifests or secrets. Add
  local/dev overrides only.
- For local-dev work, do not use MCP tools that act on a real cloud account
  (for example AWS's `aws-mcp`, or Azure / Google Cloud MCP servers) to create,
  read or change resources. Use the Vyomi tools and the local simulator; reach
  for a real-cloud tool only if the user explicitly asks for the real cloud.
- Services marked not emulated must not be silently pointed at Vyomi.
- Respect the scan and env warnings; they describe real protocol limits.
- Tell the user to run `vyomi up` only when `vyomi_status` reports the
  `offline` or `mesh-local` home.
- The MCP never starts anything (tunnel, forwards, Codespaces, `vyomi up`). Give
  the user the exact command and let them run it, long-running ones in their own
  terminal.
- If the `vyomi` MCP tools are unavailable: install or upgrade the tunnel
  (`brew install vyomi-cloud/tap/vyomi-tunnel` or `npm i -g vyomi-tunnel`;
  version 1.3.0 or newer, the first with `vyomi-tunnel mcp`; check with
  `vyomi-tunnel --version`), then restart Claude Code. v4.0.0 offline users:
  `vyomi mcp` from the `vyomi-docker` install keeps working.
