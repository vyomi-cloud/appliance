---
name: vyomi-mesh
description: Use when the user works with a Vyomi mesh (Pro/Max) - "mesh", "Pro", "Max", "Codespace", "k3s", "kubectl against Vyomi", "ssh host.vyomi" or "ssh <vm>.vyomi", "datacenter unreachable" - or when vyomi_status reports a mesh-local or mesh-codespace home, a locked mesh, or features flagged mesh-only (AKS and GKE clusters). Gets the mesh reachable, then hands back to the vyomi-setup workflow.
---

# Work against a Vyomi mesh

A mesh is the Pro/Max simulator with real compute: Kubernetes clusters (k3s
behind AKS / GKE / EKS), VMs reachable over ssh, databases and AI models. It
runs either **locally** (the headless appliance on `:9000`, TLS on `:9443`) or
in the user's own **GitHub Codespace**, reached from this machine through
`vyomi-tunnel` over their own `gh codespace ssh` session.

**Requires `vyomi-tunnel` 1.3.0 or newer** (`vyomi-tunnel --version`): it runs
this plugin's MCP server (`vyomi-tunnel mcp`) and lists the Codespace mesh. A
Codespace mesh also needs a Pro or Max access key in `~/.vyomi/credentials`;
ask the user, never read the file.

## Workflow

1. **Status.** Call `vyomi_status`.
   - `locked: true` (on the mesh home): the trial or subscription ended. Explain
     it, offer the options (renew, or use a Nano space; browser-homed spaces
     still work) and **stop**: write nothing.
   - `spaces_warning`: the mesh hosts several spaces and direct SDK calls land
     in the active one; confirm with the user that it is the space they want.
2. **Local mesh** (`mesh-local`): `vyomi mesh status` shows the same state on
   the command line. If no mesh answers and the user has one installed, suggest
   `vyomi up`.
3. **Codespace mesh** (`mesh-codespace`): call `vyomi_reach` with scope `mesh`
   (the same rows as `vyomi-tunnel list mesh`). It lists the host, instances,
   k3s, LLM and services, each with the command to connect. Then propose, for the user to run **in another terminal** (forwards
   are long-running; never start one yourself):
   - the API: the exact `vyomi-tunnel forward …` command from the
     `vyomi_status` hint (it names the target and picks a free local port,
     e.g. `9100:9000` when an offline appliance already holds :9000),
   - Kubernetes, when the project uses it: `vyomi-tunnel forward <k3s target> 6443:6443`,
     then `kubectl --server https://127.0.0.1:6443` with the kubeconfig the
     console gives,
   - databases: the forward line `vyomi_reach` prints for each,
   - VMs: `ssh <vm>.vyomi` (or `ssh host.vyomi` for the Codespace host). Once
     per machine this needs `vyomi-tunnel config`, which adds an `Include` line
     to `~/.ssh/config`: ask before suggesting it (listing never edits ssh
     config; a `vyomi_reach` note says when it is missing). VM logins use the
     mesh's own key and user: `vyomi-tunnel help ssh`.
   Call `vyomi_status` again: the Codespace home is `serving` once the API
   forward is up.
4. **Continue with `vyomi-setup`** using `home: mesh`: scan, env, propose, ask,
   write, verify. On a mesh, Cosmos DB and Key Vault use TLS on `:9443` (trust
   its certificate), and Pub/Sub and Firestore are separate gRPC emulators, as
   `vyomi_env` says.
5. **AI models.** For Bedrock, Vertex AI or Azure OpenAI code, call
   `vyomi_capability` with `bedrock`, `vertex` or `azure openai` and check
   `ai.state` in `vyomi_status`: the mesh serves real local models behind those
   APIs.

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
- Never start forwards, tunnels, Codespaces or `vyomi up` yourself, and never
  through Bash, not even in the background; give the exact command and let the
  user run it in their own terminal.
- Never read `~/.vyomi/credentials` or any key file; ask the user instead.
