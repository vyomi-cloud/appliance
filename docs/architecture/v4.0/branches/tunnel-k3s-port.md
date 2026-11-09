# v4/tunnel-k3s-port

Owner: k8s port session - Started: 2026-11-10 - Base: origin/v4-on-main (64648525) - Status: in progress

## Purpose
Reconcile the old v4/tunnel-keeper and v4/tunnel-k3s work with the trunk's redesigned tunnel so a Pro/Max user can reach a Codespace host (ssh) and a k3s API server (kubectl) through vyomi-tunnel.

## Architecture
`wasm/relay/booster-dial.mjs`: `resolveReserved` (host / codespace / `vyomi-k3s-<10 hex>` / `k3s`) in front of the trunk's `resolveVm`. `wasm/relay/mesh-cli.mjs` (+ copy in `packaging/tunnel/bin/`): `forward`, `keep`. `wasm/relay/keeper.mjs`. Doc: `VYOMI-TUNNEL-ARCHITECTURE.md` section 9c.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Port by hand onto the trunk's stream framework | Cherry-pick `dbab8a5d` (3 conflicting files) | The trunk rewrote the dial path (streams, DNS-only resolver) |
| No agent roles | Hub keyed by (session, role) | The hub's `role` already means runner-role tokens; roles only matter for the runner option, which is not built |
| k3s target is `vyomi-k3s-<10 hex>`, port 6443 only | Single `vyomi-k3s` name | Each cluster has its own server container; a pattern keeps the agent from reaching arbitrary containers or ports |

## Open issues
- [ ] sshd in the Codespace image (vyomi-cloud/sandbox) + 9b host-sshd path (owner OK needed)
- [ ] Real Codespace run: ssh to `host`, `forward` to a real k3s, kubectl (not done)
- [ ] Keeper acceptance gate T1 (needs 9b deployed)
- [ ] kubeconfig server rewrite to the forwarded port; Lens check
- [ ] Runner agent / handoff (not built)

## Testing
2026-11-10, local relay + fake sshd/k3s: `test-tunnel-k3s` 19 checks, `test-keeper`, `test-mesh-ssh`, `test-booster-link`, `test-booster-shell`, `test-booster-session-derived`, `test-worker-egress` all pass. NOT run: any real Codespace, real k3s through the tunnel, the keeper against a live Codespace.
