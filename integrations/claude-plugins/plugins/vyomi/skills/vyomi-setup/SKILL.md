---
name: vyomi-setup
description: Use when the user wants to run, test or develop cloud code locally instead of against real AWS, GCP or Azure - "run this against Vyomi", "test locally without the cloud", "set up a local cloud", "use Vyomi instead of LocalStack", or asks whether Vyomi supports the services a project uses.
---

# Set a project up to run against Vyomi

Vyomi is a local simulator of AWS, GCP and Azure. Real cloud SDKs, CLIs and
Terraform talk to it instead of the real cloud during development; production
keeps running on the real cloud. The `vyomi` MCP server (bundled with this
plugin) knows what Vyomi emulates and how to point code at it.

## Workflow

1. **Check the simulator.** Call `vyomi_status`.
   - Not running: tell the user to run `vyomi up` (it can take a few minutes the
     first time while images download), then continue with the offline steps.
   - `readiness` below 100% right after `vyomi up` only means backend containers
     are still starting.
2. **Scan the project.** Call `vyomi_scan_repo` with the absolute path of the
   project root. Report back briefly, per cloud:
   - services that are emulated (status `released`),
   - services that are **not emulated** - those keep using the real cloud (or a
     stub) during local runs,
   - every `warning` verbatim in substance (for example: Azure Service Bus is
     REST-only, no AMQP; Cosmos DB and Key Vault need TLS on :9443; GCP Pub/Sub
     and Firestore are separate emulators; Azure OpenAI is simulated output),
   - `already_wired`: existing endpoint overrides to reuse, not duplicate.
3. **Get the exact settings.** Call `vyomi_env` for each cloud found, with the
   `lang` the scan suggests. Use its values; never invent endpoints, ports, keys
   or account names.
4. **Propose the change, then ask.** Prefer the least invasive option:
   - a `.env.vyomi` file (`vyomi_write_env`) loaded only for local runs,
   - a docker compose override or test fixture that sets the variables,
   - code changes only where an SDK cannot be pointed at an endpoint through
     configuration.
   Show what will change and get the user's OK before writing anything.
5. **Verify.** Run the project's own tests or a smoke command with the
   variables loaded, and report what passed and what failed. If a failure looks
   like a missing API in Vyomi, say so plainly rather than working around it.

## Rules

- Never modify production configuration, deployment manifests or secrets. Add
  local/dev overrides only.
- Services marked not emulated must not be silently pointed at Vyomi.
- Respect the scan and env warnings; they describe real protocol limits.
- If the `vyomi` MCP tools are unavailable, the CLI is probably not installed:
  macOS/Linux `brew install vyomi-cloud/tap/vyomi-docker`, Windows the MSI from
  https://github.com/vyomi-cloud/appliance/releases (see https://vyomi.cloud/downloads).
  Then restart Claude Code.
