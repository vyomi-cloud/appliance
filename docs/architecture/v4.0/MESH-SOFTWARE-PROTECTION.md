# Protecting Vyomi's software and config on a Mesh Codespace

Status: batch 1 built on branch `v4/mesh-protect`, tested locally, NOT yet tried on a real Codespace. Written 2026-11-14.

## 1. Problem

A Mesh runs in the user's own GitHub Codespace. The user owns the machine but not our software. Anything they can reach
(terminal, `docker exec`, `docker inspect`, the files, an AI tool in their editor, or `vyomi-tunnel`) can be used to read our
source, our config and our keys, or to copy the product. That puts revenue at risk.

## 2. Principle

Customer workloads are the user's: their VMs (`vyomi-i-*`) and k3s clusters (`vyomi-k3s-*`). Vyomi's own stack is ours:
`simulator`, `llm`, `llm-chat`, `llm-embed`, the compose files and the config. One allow-list says what a user may touch,
and it is enforced in two places: on the Codespace (the real control) and in the tunnel (clear errors, no leaks).

## 3. What may be reached

| Container | User (terminal, ssh, tunnel) | Vyomi's own paths |
|---|---|---|
| `vyomi-i-*` VMs | shell, ssh, port forward | same |
| `vyomi-k3s-*` | Kubernetes API via the tunnel | same |
| `simulator`, `llm*` | never | fixed internal calls only (the console's API tunnel, the instance key) |
| Images and config | never listed or readable | n/a |

## 4. Layers

| # | Layer | State |
|---|---|---|
| 1 | `vyomi-gate`: root-owned script, run by the user only through one sudo rule. Fixed verbs `ip`, `list`, `k3s`, `compose simulator`, `instance-key`; every name checked against the allow-list; anything else exits 2 and never reaches docker. | **built, tested** |
| 2 | Tunnel (`mesh-ssh.mjs`): resolves only `vyomi-i-*` / `vyomi-k3s-*`; the `vyomi-<name>` and bare-name fallbacks are removed; `list` hides core containers and image names; runs docker questions through the gate when the Codespace has it (older Codespaces fall back). | **built, tested** |
| 3 | `vyomi-lockdown`: removes the user's docker group and general sudo, leaves only the gate rule, makes `/opt/vyomi` root-only; skipped on admin Codespaces. | **built, tested against a scratch root; not wired into boot** |
| 4 | Compiled, source-free Mesh image (Cython; `setup_cython.py` exists, not applied). | next |
| 5 | Ed25519 session tokens, so the Codespace holds only a public key. | next |
| 6 | Portal integrity check (image digest and devcontainer hash) with a hard stop on mismatch; per-session leak marker. | next |

## 5. Why layer 3 is not on yet

`boot-mesh.sh` runs as the Codespace user and calls `docker compose` many times, including on every restart. Removing that
user's docker access breaks boot and resume until boot runs through a root helper. That needs a real Codespace to prove, so
the gate and tunnel ship first (they are harmless on their own) and the lockdown is switched on after a real-Mesh test.

## 6. Residual risk (stated plainly)

- The owner can rebuild the Codespace with an edited devcontainer. Layer 6 detects this; it cannot prevent it.
- Compiled code can be reverse engineered with effort; it removes casual reading, not a determined attacker.
- The gate answers one thing the user must have: the IP of their own VMs. Nothing about core containers.
- The simulator API is still reachable on the Codespace's network by IP; it requires the session token.
- The `host` / `codespace` tunnel target is the Codespace's own sshd. It stays until layer 3 is on, since it is the user's shell on their own machine.

## 7. Local checks (done)

- `wasm/relay/test-mesh-gate.mjs`: 23 refusals (core container names, `simulator`, `llm`, injection strings, extra args, unknown verbs) never reach docker; allowed verbs work; lockdown plan / apply / admin-skip.
- `wasm/relay/test-mesh-ssh-transport.mjs`: core containers are not targets however typed and not listed; no image names.
- Existing `test-mesh-ssh`, `test-mesh-link`, `test-mesh-lazy-hub`, `test-mesh-shell` still pass.

## 8. Real-Mesh checklist (before enabling lockdown)

1. Build the Mesh image from this branch; start a Mesh; `vyomi-tunnel list` shows only the user's VMs and k3s.
2. `ssh <vm>.vyomi` and `forward vyomi-k3s-<id> 6443:6443` still work through the gate.
3. `sudo /usr/local/sbin/vyomi-gate ip vyomi-mesh-simulator-1` is refused.
4. Wire boot through a root helper, then `vyomi-lockdown apply`; confirm `docker ps` fails for the user and Mesh still boots and resumes after a Codespace restart.
5. Admin devcontainer keeps full access.
