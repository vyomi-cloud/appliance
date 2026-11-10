# v4/mesh-laptop-link

Owner: integrator session - Started: 2026-11-10 - Base: origin/v4-on-main (0f644f37) - Status: in progress

## Purpose
Records the decision that the Mesh link always runs on the laptop (vyomi-tunnel connects IN over ssh) and removes the Codespace's outbound `link` container from the mesh boot and compose.

## Architecture
codespace/.devcontainer/mesh/boot-mesh.sh (no start_link, no relay url), docker-compose.mesh.yml (no `link` service), VYOMI-TUNNEL-ARCHITECTURE.md section 1c.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Laptop dials in over ssh (user's gh login) | Hosted wss relay the Codespace dials; portal-minted credential | A Codespace cannot reach a laptop; nothing to host; reuses sshd already in the image |

## Open issues
- [ ] Tunnel ssh transport (connect/forward/relay upstream over gh codespace ssh) - not built
- [ ] Name resolver moves to the laptop side; DNS-rebinding Host allow-list for forwarded requests
- [ ] Remove mesh-dial.mjs from the image after the transport replaces it
- [ ] Overlaps the tunnel session's claim (packaging/tunnel/**, wasm/relay/**): agree before editing those paths

## Testing
bash -n and YAML parse only. By hand on a real Codespace: ssh -L from the laptop reached the simulator /healthz (200). Boot script not re-run end to end after this edit.
