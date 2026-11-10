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

## User flow (credentials file, the AWS-CLI model; supersedes the earlier `login` flow)
No login command. The user creates an access key in the console (avatar menu > Tunnel credentials) and saves `~/.vyomi/credentials`. Every command
signs a request to the portal for a short-lived session (plan, Mesh session end, Codespace, GitHub token); the GitHub token goes to `gh` as GH_TOKEN, so
the user never signs in to gh. Contract: `docs/architecture/v4.0/TUNNEL-CREDENTIALS-CONTRACT.md`. Nano also needs a key (Free works); Mesh needs Pro/Max;
streams stop at session_end. The first Mesh command writes the `*.vyomi` ssh block. Tunnel side built and tested against a stub portal that verifies the
signature; the portal side (key store, avatar page, /api/tunnel/session, GitHub token vending) is NOT built. NOT verified: a real Codespace with these
credentials; that the user's ssh key is accepted by the Codespace sshd on :2222.
Hidden/legacy: `--codespace`, `--relay-mode`, `relay-login`, `config`, `status`, `keep`.

## Discovery: `vyomi-tunnel list [nano|mesh|all|type] [--json]`
Every transport line is listable so users can self-serve: types api (Nano endpoint), vm, db (browser), host, instance, k3s, llm, service (Mesh Codespace,
via `docker inspect` over the ssh session), forward (running `forward` processes, tracked in ~/.vyomi/forwards/<pid>.json, dead pids pruned).
Each row carries the command to use it. Unit-tested with a fake ssh; browser rows verified against a running local relay; Mesh rows NOT yet seen live
(Codespace stopped). Not yet listed: reverse forwards, Docker daemon, runner-backed k3s (those transports are not built).

## Idle timeout (automatic)
GitHub resets a Codespace's idle timer on ssh traffic the client sends. The transport therefore runs a trivial command on the host every 4 min
(`keepaliveMs`) for as long as it is in use (connect, forward, or the relay with VYOMI_MESH_CODESPACE), starting on first use and stopping on close.
Users do nothing; `vyomi-tunnel keep` remains only as a hidden advanced command and is no longer in the help. Unit-tested with a fake ssh; NOT yet
proven against a real idle timeout (needs a >30 min live run on a fresh Codespace).

## GitHub CLI handling
`wasm/relay/gh-manager.mjs`: use a system `gh` (>= 2.40) if present, else a managed copy in `~/.vyomi/bin`, else download the pinned official release
(v2.103.3; SHA-256 embedded in code; macOS/Linux/Windows, x64/arm64) and unpack there. Never touches PATH/Homebrew. `vyomi-tunnel gh-login` signs in
(browser, `codespace` scope); `GH_TOKEN` is honoured. Without a login the CLI says so instead of surfacing a raw ssh error.
Packaged copies of mesh-cli/mesh-ssh/gh-manager are in `packaging/tunnel/bin`; the generated `vyomi-tunnel.mjs` relay is NOT regenerated here
(tunnel session owns it) so the relay-side Nano HTTP/shell hub needs that regeneration before a release.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| gh `--config` + plain ssh ControlMaster | `gh codespace ssh -- -W` per stream | gh re-handshakes every call (~3.7 s/stream) |
| No session token in ssh mode; origin allow-list kept | portal-minted credential | the ssh login is the user's own; laptop is the trust boundary |
| Short ControlPath dir under /tmp | os.tmpdir() | macOS unix-socket path limit (255 on exec with long tmpdir) |

## Open issues
- [x] `/shell` PTY plane now carried over the ssh stream (tab <-> simulator `/booster/shell`); unit-tested, NOT yet live (Codespace was reaped by the idle timer, then came back without sshd)
- [x] Image `COPY` fixed: ships mesh-ssh.mjs, runner-llm-hub.mjs, booster-mesh.mjs (trunk's local-relay imports them; the list lacked two); booster-dial.mjs no longer shipped
- [ ] Image rebuild/publish so `vyomi/appliance` has /app/relay and the /booster/status route (owner go)
- [ ] Live e2e of `/shell` + instance/k3s containers on a fresh Codespace, personal GitHub Free account (needs a new Mesh start)

## Testing
Live against Codespace vyomi-mesh-jrjpj6jvggrvfqjjr: resolve host/simulator, CLI `connect host` and `forward` returned the sshd banner, WS `/connect`
returned the banner, relay HTTP with the Mesh header reached the simulator (`/healthz` 200). Unit: `test-mesh-ssh-transport.mjs` (fake ssh) passes;
test-mesh-ssh, test-booster-link, test-booster-shell, test-keeper still pass. NOT run: k3s/instance containers (none running), personal GitHub Free account.
