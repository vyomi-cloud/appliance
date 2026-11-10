# Mesh / vyomi-tunnel: next steps (hand-off, 2026-11-09)

Author: the mesh/tunnel session, which is now concluded. Design lives in `VYOMI-TUNNEL-ARCHITECTURE.md`; this file lists only what is still to do.
Nothing here is verified live unless it says so. Nothing goes to `main`, tags or deploys without the owner's go.

Naming: the product is **Vyomi Mesh** everywhere user-facing. Some code identifiers still say `mesh` on the trunk (files `wasm/relay/mesh-*.mjs`, `mesh-link.js`, env `MESH_RELAY_URL`, the `/mesh` relay path). They are kept as-is so nothing breaks; a rename of those is a separate, tested change. Use "Mesh" in any new text, UI or docs.

## Landed on the trunk
Mesh SSH over the relay (`wasm/relay/mesh-hub.mjs` `/connect`, `mesh-dial.mjs` TCP forward, `mesh-cli.mjs` connect/login/config, `test-mesh-ssh.mjs`),
Worker `/egress` + browser-VM use of it, tunnel architecture doc, P1 Nano back-port (`vyomi-appbar.js`, `mesh-link.js`).

## To build (in order)
1. **Portal `/mesh/cli-login`** (+ VM list/token endpoint) so `vyomi-tunnel login` works without `--token`. Portal repo, topic `portal/mesh-cli-login`.
2. **Hosted relay as a Cloudflare Durable Object with WebSocket hibernation**: the Mesh hub (`/mesh`, `/connect`) exists only in the Node relay. Blocks hosted SSH. Cost note in the architecture doc (hibernation ~$60 vs ~$420/month at 300 concurrent).
3. **Nano tab registers its browser VMs with the hosted relay** so `ssh <vm>.vyomi` reaches a browser VM.
4. **Honour the user's key pair at VM launch** (Docker backend injects a generated key via `VYOMI_SSH_PUBKEY` today).
5. **Keeper (Codespace TTL renewal)** and **Codespace host-sshd target** (architecture doc sections 9 and 9b). Reconcile with `v4/tunnel-keeper` / `v4/tunnel-k3s` first; do not merge those as-is.
6. `vyomi-tunnel forward`, per-stream bandwidth cap and audit log.

## Needs live verification (not done)
- A real Codespace SSH round trip; a booted browser VM running `pip` / `git clone` through hosted `/egress`.
- `wrangler deploy --dry-run`: the `[[ratelimits]]` syntax in `wasm/relay/wrangler.toml` is unverified.
- Scratch-portal browser check of the back-ported appbar/link UI (step 6 of `P1-NANO-BACKPORT.md`).
- Keep-alive probe against a live Codespace.

## Owner / deploy-time items
- DO env `MESH_RELAY_URL` and `GITHUB_APP_SLUG=vyomi-mesh` (do-spec-v4-ready.yaml); rotate the GitHub App client secret.
- Sync the devcontainer sshd and Mesh naming to `vyomi-cloud/sandbox` (needs the owner's OK). Clean up old `vyomi-mesh-*` Codespaces.
- Release items stay in `RELEASE-READINESS.md` (on `docs/v4-release-plan-mesh`, not yet on the trunk).

## Branches left (integrator decides)
- `docs/v4-release-plan-mesh`: keep until `RELEASE-READINESS.md` is on the trunk or release/v4.0.0.
- `v4/vm-egress`: superseded (its features were re-applied to the trunk); safe to delete.
- `v4/docs-branch-arch`: already on the trunk; safe to delete.
- `fix/nano-tunnel-arm`: WIP Nano CLI check (28/62); owner unclear.

## Asks to the next session / integrator
1. **Merge this file** into `v4-on-main` (topic branch `v4/mesh-next-steps`), then delete that branch and the `appliance-mesh-next-steps` worktree. Its author is gone; the integrator can do this.
2. **Before any tunnel or relay work:** fetch `origin/v4-on-main`, start with `scripts/v4-session-start.sh <topic>`, add a claim row to `SESSION-CLAIMS.md`, and reconcile with `v4/tunnel-keeper` and `v4/tunnel-k3s` before touching `packaging/tunnel/**` or `wasm/relay/**`. Run `test-mesh-link`, `test-mesh-shell`, `test-mesh-session-derived` and `test-mesh-ssh` (`WS_PKG=<repo>/relay-deps/ws`) before pushing relay changes.
3. **Decide the leftover `mesh` identifiers** (files, `MESH_RELAY_URL`, `/mesh` path, `vyomi-mesh-*` Codespaces): rename in one tested change, or declare them permanent. Until then keep them.
4. **Own the browser check** of the back-ported appbar/link UI (step 6 of `P1-NANO-BACKPORT.md`), the first vendor PR and the `app/nano/**` CI rule. These were already assigned to the integrator.
5. **Decide the branches left:** keep `docs/v4-release-plan-mesh` until `RELEASE-READINESS.md` reaches the trunk or `release/v4.0.0`; check whether `fix/nano-tunnel-arm` still has an owner.
6. **Owner (not a session):** GitHub branch protection and the `v*` tag rule; name the integrator; OK the `vyomi-cloud/sandbox` sync; the DO env and GitHub App secret items above.
