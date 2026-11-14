# v4/mesh-protect

Owner: Azure session (Sudhir) - Started: 2026-11-14 - Base: origin/v4-on-main (2a7dd1764) - Status: tunnel part ready to release as 1.2.5; Codespace lockdown not enabled

## Purpose
Keep Vyomi's own containers (simulator, llm*) and config out of reach of the Codespace owner, including through `vyomi-tunnel`. Full design: `../MESH-SOFTWARE-PROTECTION.md`.

## What is in it
| Change | Where |
|---|---|
| Tunnel resolves only `vyomi-i-*` / `vyomi-k3s-*`; no `vyomi-<name>` / bare-name fallback; `list` hides core containers and image names | `packaging/tunnel/bin/mesh-ssh.mjs` (+ identical copy `wasm/relay/mesh-ssh.mjs`) |
| Root-owned `vyomi-gate` (fixed verbs, validated names) | `codespace/.devcontainer/mesh/vyomi-gate`, Dockerfile |
| `vyomi-lockdown` (drops the user's docker/sudo; admin skipped), NOT wired into boot | `codespace/.devcontainer/mesh/vyomi-lockdown` |
| Instance key fetched through the gate (falls back to docker on older Codespaces) | `packaging/tunnel/bin/mesh-cli.mjs` |
| Tunnel 1.2.5 | package.json, VERSION constants |

## Design decisions
- One allow-list, enforced on the Codespace (gate, the real control) and in the tunnel (clear errors). A modified tunnel can skip its own check, so the gate matters most.
- The gate and tunnel are harmless alone; lockdown breaks boot/resume (they run as the user and call docker), so it waits for a root boot helper and a real-Codespace test.

## Open issues
- `vyomi-cloud/sandbox` is what Codespaces build from; the gate and Dockerfile lines must be synced there (owner OK) before the gate is used. Until then the tunnel falls back to docker.
- Root boot helper, then enable lockdown; compiled image; Ed25519 tokens; portal integrity check.
- Still reachable: the `host`/`codespace` tunnel target (the user's own shell) until lockdown is on.
