# v4/mesh-ssh-transport

Owner: Mesh session (user: vyomi-admin) - Started: 2026-11-10 - Base: origin/v4-on-main (3bf6256c) - Status: ready for review

## Purpose
The Mesh link always runs on the laptop. The Codespace dials nothing; the laptop's vyomi-tunnel opens ONE ssh session
(`gh codespace ssh`, the user's own gh login) and carries host sshd (tunnel 1), Docker instances/k3s (tunnel 3) and the
simulator HTTP API (Nano compute calls) over it. Browser VMs (tunnel 2) are unchanged (local relay `/vm`).

## Architecture
- `wasm/relay/mesh-ssh.mjs`: `createSshTransport` (gh `--config` + ssh ControlMaster, one stream = `ssh -W ip:port`, ~0 ms once the master is up;
  names resolved with `docker inspect` over ssh, names regex-validated), `createSshHub` (drop-in for `createHub`: `/connect`, Mesh-plane HTTP -> simulator
  container with `Host: simulator:9000`, `/shell` -> 501, `/booster` -> 410), `connectSsh` / `forwardSsh` for the CLI.
- `local-relay.mjs`: `VYOMI_MESH_CODESPACE=<name>` selects the ssh hub. `mesh-cli.mjs`: `connect|forward ... --codespace <name>` (or the env) goes straight over ssh, no relay/token.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| gh `--config` + plain ssh ControlMaster | `gh codespace ssh -- -W` per stream | gh re-handshakes every call (~3.7 s/stream) |
| No session token in ssh mode; origin allow-list kept | portal-minted credential | the ssh login is the user's own; laptop is the trust boundary |
| Short ControlPath dir under /tmp | os.tmpdir() | macOS unix-socket path limit (255 on exec with long tmpdir) |

## Open issues
- [ ] `/shell` PTY plane (agent-based) is not carried over ssh yet - returns 501 (owner: Mesh)
- [ ] `booster-dial.mjs` stays (hosted relay + existing tests use it); remove from the image once nothing needs it
- [ ] Published `vyomi/appliance:latest` lacks /app/relay; needs rebuild (owner go)
- [ ] Simulator on the stale image answers S3-style NoSuchBucket for unknown paths

## Testing
Live against Codespace vyomi-mesh-jrjpj6jvggrvfqjjr: resolve host/simulator, CLI `connect host` and `forward` returned the sshd banner, WS `/connect`
returned the banner, relay HTTP with the Mesh header reached the simulator (`/healthz` 200). Unit: `test-mesh-ssh-transport.mjs` (fake ssh) passes;
test-mesh-ssh, test-booster-link, test-booster-shell, test-keeper still pass. NOT run: k3s/instance containers (none running), personal GitHub Free account.
