# Mesh / vyomi-tunnel: next steps (hand-off, 2026-11-09)

Author: the mesh/tunnel session, which is now concluded. Design lives in `VYOMI-TUNNEL-ARCHITECTURE.md`; this file lists only what is still to do.
Nothing here is verified live unless it says so. Nothing goes to `main`, tags or deploys without the owner's go.

Naming: the product is **Vyomi Mesh** everywhere user-facing. Some code identifiers still say `booster` on the trunk (files `wasm/relay/booster-*.mjs`, `booster-link.js`, env `BOOSTER_RELAY_URL`, the `/booster` relay path). They are kept as-is so nothing breaks; a rename of those is a separate, tested change. Use "Mesh" in any new text, UI or docs.

## Landed on the trunk
Mesh SSH over the relay (`wasm/relay/booster-hub.mjs` `/connect`, `booster-dial.mjs` TCP forward, `mesh-cli.mjs` connect/login/config, `test-mesh-ssh.mjs`),
Worker `/egress` + browser-VM use of it, tunnel architecture doc, P1 Nano back-port (`vyomi-appbar.js`, `booster-link.js`).

## To build (in order)
1. **Portal `/mesh/cli-login`** (+ VM list/token endpoint) so `vyomi-tunnel login` works without `--token`. Portal repo, topic `portal/mesh-cli-login`.
2. **Hosted relay as a Cloudflare Durable Object with WebSocket hibernation**: the Mesh hub (`/booster`, `/connect`) exists only in the Node relay. Blocks hosted SSH. Cost note in the architecture doc (hibernation ~$60 vs ~$420/month at 300 concurrent).
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
- DO env `BOOSTER_RELAY_URL` and `GITHUB_APP_SLUG=vyomi-mesh` (do-spec-v4-ready.yaml); rotate the GitHub App client secret.
- Sync the devcontainer sshd and Mesh naming to `vyomi-cloud/sandbox` (needs the owner's OK). Clean up old `vyomi-booster-*` Codespaces.
- Release items stay in `RELEASE-READINESS.md` (on `docs/v4-release-plan-mesh`, not yet on the trunk).

## Branches left (integrator decides)
- `docs/v4-release-plan-mesh`: keep until `RELEASE-READINESS.md` is on the trunk or release/v4.0.0.
- `v4/vm-egress`: superseded (its features were re-applied to the trunk); safe to delete.
- `v4/docs-branch-arch`: already on the trunk; safe to delete.
- `fix/nano-tunnel-arm`: WIP Nano CLI check (28/62); owner unclear.
