---
name: vyomi-mesh
description: Use when the user works with a Vyomi mesh (Pro/Max) - "mesh", "Pro", "Max", "Codespace", "k3s", "kubectl against Vyomi", "ssh host.vyomi" or "ssh <vm>.vyomi", "datacenter unreachable" - or when a feature is flagged as available on a Vyomi mesh only (AKS and GKE clusters). Gets the mesh reachable, then hands back to the vyomi-setup workflow.
---

# Work against a Vyomi mesh

A mesh is the Vyomi simulator with real compute behind it: Kubernetes clusters (k3s behind AKS / GKE / EKS), VMs
reachable over ssh, databases and AI models. It runs either **locally** (the headless appliance on
`http://127.0.0.1:9000`, TLS on `9443`) or in the user's own **GitHub Codespace**, reached from their machine
through `vyomi-tunnel` over their `gh codespace ssh` session.

This skill works with either Vyomi MCP server. With the **local** server (you have `vyomi_status` and
`vyomi_reach`) call those first: they find the mesh, say whether it is serving or locked, and give the exact
forward commands. With the **hosted** server (`https://vyomi.cloud/mcp`; you have `get_scan_rules`) none of that
can be detected for you — it cannot see the user's machine or their account — so check locally and ask.

## Workflow

1. **Is a mesh serving on this machine?** With your own shell:
   ```sh
   curl -s --max-time 2 http://127.0.0.1:9000/healthz
   ```
   An answer means a mesh or the appliance is up: go back to `vyomi-setup` with `home=mesh` (or `home=offline`
   for the plain appliance — ask the user which it is if it matters; the wiring differs).

2. **Nothing answers, and the mesh is local.** The user starts it themselves with `vyomi up` in the appliance
   checkout and keeps it running. Never start, stop or restart it for them. Re-check `/healthz`.

3. **Nothing answers, and the mesh is in a Codespace.** The user needs, in their own terminals:
   - `gh codespace ssh` access to the Codespace that runs the mesh (the Vyomi portal shows which one), and
   - `vyomi-tunnel forward` for the mesh API, kept open, which puts the mesh on a local port — plus the TLS
     forward as well for Cosmos DB and Key Vault, which need `https`.

   `vyomi-tunnel` **1.3.0 or newer** is required (`vyomi-tunnel --version`; `brew install
   vyomi-cloud/tap/vyomi-tunnel` or `npm i -g vyomi-tunnel`). The MCP never starts a forward, and neither should
   you without being asked: show the command and let the user run it.

   Ask the user which local port the forward is using, then pass `home=mesh` and `host=127.0.0.1:<that port>` to
   `get_sdk_settings`, `get_code_snippet` and `propose_env_file`, so the settings name the port the code can
   actually reach.

4. **The mesh is locked.** A mesh refuses API calls while it is locked (no entitlement, or an expired session).
   The Vyomi portal is where the user clears that; nothing here can. Say so plainly and stop rather than
   generating settings that will be refused.

## What a mesh adds

Features flagged as available on a Vyomi mesh need one: AKS and GKE clusters, VM ssh, k3s and `kubectl`, the
mesh's databases and models. `check_capability` says which, per feature, and `summarize_scan_hits` flags a
service whose main feature needs a mesh when you scan with `home=nano` or `home=offline`, so the project is never
silently wired to a home that cannot run it.

A mesh has TLS on `9443`, so Azure Cosmos DB and Key Vault work there (trust its certificate); GCP Pub/Sub and
Firestore are separate gRPC emulators with their own ports — `get_sdk_settings` returns those values and the
warnings with them.

Then go back to the `vyomi-setup` workflow with `home=mesh`.
