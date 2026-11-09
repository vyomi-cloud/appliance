# vyomi-tunnel — architecture (v4.0.0 + Mesh SSH)

Status: 2026-11-09. Branch `v4/vm-egress`. Written from the code on that branch; every claim is tagged
**[built+tested]**, **[built, untested live]** or **[planned]**. Nothing here is deployed.

## 1. What vyomi-tunnel is

One small Node program (`packaging/tunnel/`, npm `vyomi-tunnel`, Homebrew tap `vyomi-cloud/homebrew-tap`) with two jobs:

| Job | Command | Who uses it |
|---|---|---|
| **Local relay** for Nano: lets tools on the user's machine (aws CLI, SDKs, `psql`, `ssh`) reach things that live inside a browser tab | `vyomi-tunnel` (no args) | Nano users |
| **SSH/TCP client** for Mesh and browser VMs: carries the bytes of an `ssh` session through the relay | `vyomi-tunnel connect <vm>`, `login`, `config`, `status` | Mesh (Pro/Max) users, later Nano VM users |

The tunnel never terminates SSH. `ssh` does the handshake, key authentication and encryption end to end with the VM's
sshd. The tunnel, the relay and the Mesh agent carry encrypted bytes only, so they cannot read the user's key or data.

## 1b. The three tunnels (product decision, 2026-11-10)

vyomi-tunnel must support exactly three kinds of target:

| # | Tunnel | Reaches | Path | Status on this trunk |
|---|---|---|---|---|
| 1 | To the **Codespace** | the Codespace host's sshd (reserved target `host` / `codespace`) | `/connect` to the Mesh agent, which answers the reserved name (section 9c) | built, local tests only; needs sshd in the Codespace image (now in the appliance copy; sandbox PR pending) |
| 2 | To a **browser VM** | an instance running in the Nano tab (v86) | VM worker -> local relay `/vm`, then `127.0.0.1:22000-22999` (section 5) | built+tested on the local relay; hosted relay version planned |
| 3 | To **Docker inside the Codespace** | `vyomi-i-<id>` instance containers and the k3s API (`vyomi-k3s-<id>`, port 6443) | `/connect` to the Mesh agent, which resolves the name on `vyomi-net` (sections 4, 9c) | built+tested (Mesh SSH, 20 checks) and `forward` for k3s (19 checks); no real Codespace run yet |

Tunnels 1 and 3 both depend on the Mesh agent being linked to a relay the Codespace can reach (open item 9 in section 11). Tunnel 2 does not: it runs entirely on the laptop.

## 1c. Link direction (decision 2026-11-10): the link always runs on the laptop

The Codespace dials nothing. A Codespace cannot reach a laptop, but a laptop can reach a Codespace, so the laptop's `vyomi-tunnel` opens ONE ssh
session to the Codespace host (the sshd devcontainer feature) and carries all three tunnels over it:

| Tunnel | Over the one ssh session |
|---|---|
| 1. Codespace | the session itself (shell, scp) and the keeper's idle-timer writes |
| 3. Docker in the Codespace | `-L`/`-W` to the instance container's address on `vyomi-net` (the tunnel resolves the name with `docker inspect` over the same session), k3s API on 6443 |
| Nano compute calls | the local relay proxies Nano's HTTP to the simulator at `<container-ip>:9000` through a forward |

Consequences: no hosted relay and no `wss://` endpoint for the Mesh, no `BOOSTER_RELAY_URL`, no outbound `link` container (removed from
`codespace/.devcontainer/booster/`), no inbound port. Authentication to the Codespace is the user's own GitHub login (`gh codespace ssh`).
Open: a portal-minted short-lived credential instead of `gh` (not built). Proven by hand on 2026-11-10: `gh codespace ssh -- -N -L 9009:<simulator
container ip>:9000` gave `200` on `/healthz` from the laptop. Not yet built: the tunnel's own ssh transport (`connect`/`forward`/relay upstream
over `gh codespace ssh`), the resolver moving from the agent (`booster-dial.mjs` `resolveReserved`) to the laptop, the DNS-rebinding Host allow-list for
forwarded requests, and removing `booster-dial.mjs` from the image once the new transport replaces it. Section 11 item 9 (where the relay runs) is answered by
this section; sections 2 to 4 still describe the outbound design until the transport is built.

## 2. Components

```
                         ┌────────────────────────── relay ───────────────────────────┐
 laptop                  │  local relay (Node, local-relay.mjs)  — runs on the laptop │
 ┌───────────────┐       │  hosted relay (Cloudflare Worker + Durable Object)         │
 │ ssh / scp /   │       │     relay.vyomi.cloud                                      │
 │ VS Code       │       └────────────────────────────────────────────────────────────┘
 │   │ProxyCmd   │                    ▲                   ▲                  ▲
 │ vyomi-tunnel  │── WS /connect ─────┘                   │                  │
 │   connect     │                                         │ WS /booster      │ WS /register, /vm, /db
 └───────────────┘                                         │ (outbound)       │ (outbound)
                                              ┌────────────┴─────┐      ┌─────┴───────────┐
                                              │ Mesh agent        │      │ Nano tab         │
                                              │ (booster-dial.mjs │      │ (Pyodide cores,  │
                                              │  in the Codespace)│      │  v86 VMs)        │
                                              └────────┬──────────┘      └─────┬────────────┘
                                                       │ TCP :22                │ virtual NIC
                                                 Docker VM (vyomi-i-<id>)   browser VM sshd
```

| Component | File | Runs where | Role |
|---|---|---|---|
| Local relay | `wasm/relay/local-relay.mjs` (packaged as `packaging/tunnel/bin/vyomi-tunnel.mjs`) | user's laptop | HTTP relay to the Nano tab, TCP bridge to browser VMs (`/vm`) and DBs (`/db`), `/egress`, Mesh hub |
| Hosted relay | `wasm/relay/worker.js` + `wrangler.toml` | Cloudflare (`relay.vyomi.cloud`) | per-session HTTP relay to a Nano tab (Durable Object), `/egress` |
| Mesh hub | `wasm/relay/booster-hub.mjs` | inside the Node relay | pairs a Mesh agent with the same session's clients; `/booster` + `/connect` |
| Mesh agent | `wasm/relay/booster-dial.mjs` | `link` container in the Mesh Codespace | dials OUT to the relay with the signed session token; serves HTTP requests and opens TCP to VMs |
| SSH client | `wasm/relay/mesh-cli.mjs` (copied to `packaging/tunnel/bin/`) | user's laptop | `connect` / `login` / `config` / `status` |
| Egress proxy | `wasm/relay/egress.mjs` | both relays | allow-listed package/git downloads for browser VMs |
| Session token | `wasm/relay/booster-session.mjs` | hub, agent, client | signed `v1.<payload>.<hmac>` token, same format as `core/booster_session.py` |

## 3. Planes (what each WebSocket path does)

| Path | Dialer | Purpose | Auth | Built |
|---|---|---|---|---|
| `/register` | Nano tab | tab receives forwarded HTTP (`{id,method,path,query,headers,body}`) | Origin check | [built+tested] |
| `/<session>/…` | any HTTP client | external app talks to the tab through the hosted relay | session id | [built+tested] |
| `/vm?vm=<id>&port=22` | browser VM worker | local relay opens a host port 22000-22999 and bridges TCP to the VM | loopback only | [built+tested] (local relay only) |
| `/db` | browser DB worker | same for DB ports 25000-25999 | loopback only | [built+tested] (local relay only) |
| `/booster` | Mesh agent | agent links to the hub; hub forwards HTTP to the Codespace simulator | Bearer session token | [built+tested] |
| `/shell` | Nano tab | interactive PTY into a Docker VM (other session's work; first-message token auth) | token in first message | [built+tested] (Node relay only) |
| `/connect?vm=&port=` | laptop | raw TCP stream to a VM behind the same session's agent (stream framework, `kind:"tcp"`) | Bearer session token, role-less | [built+tested] (Node relay only) |
| `/egress?u=` | browser VM host | allow-listed GET/HEAD/POST fetch for pip/apk/git | Origin check + per-IP limit | [built+tested] in Worker (9 checks); not deployed |

## 4. Mesh SSH data path

TCP streams ride the hub's existing **stream framework** (the same one the Nano "Open shell" PTY uses, see the header of
`booster-hub.mjs`), distinguished by `kind:"tcp"`:

- hub→agent (JSON on the agent's one WSS): `{type:"stream", op:"open", kind:"tcp", sid, vm, port}`, then `data{d:b64}`, `pause`,
  `resume`, `close`.
- agent→hub: `opened{container}`, `data{d:b64}`, `close{reason}`, `error{code,message}`.
- laptop↔hub (`/connect`): raw bytes as binary WebSocket messages, one WebSocket = one stream; the hub never sends JSON to a `tcp`
  client. The client splits writes into 32 KiB messages (the hub caps frames at 64 KiB).
- Backpressure (pause/resume when the tab or link is slow), the open timeout (20 s), the token-expiry close (4410) and the idle timer
  come from the shared framework. TCP streams use a longer idle limit (`VYOMI_TCP_IDLE_MS`, default 1 h; ssh keepalives count as traffic).
- Caps: `VYOMI_MAX_STREAMS` (default 20) TCP streams per Mesh session, separate from the 4-shell cap.

Steps for `ssh my-vm.vyomi`:

1. `ssh` reads `~/.ssh/config` → `Include ~/.vyomi/ssh_config` → `Host *.vyomi` → `ProxyCommand vyomi-tunnel connect %h`.
2. `connect` strips `.vyomi`, loads `~/.vyomi/session.json` (relay URL + token), opens `wss://<relay>/connect?vm=my-vm&port=22`
   with `Authorization: Bearer <token>`.
3. The hub verifies the token (signature, audience, expiry, tier Pro/Max/enterprise), looks up the agent by `session_id`,
   requires the same account (`sub`), enforces the stream cap, and sends `tcp-open` to the agent.
4. The agent resolves the VM by Docker DNS name (`vyomi-i-<id>`, `vyomi-<name>`, `<name>`; no Docker CLI or socket, per the booster
   rule that the agent holds no Docker access), opens TCP to port 22 and answers `opened`. Bytes sent early by the laptop are queued
   at the hub until then. If nothing answers in 20 s the stream is closed.
5. `ssh`'s own handshake and key auth now run end to end with the VM's sshd.
6. Either side closing ends the stream and sends `tcp-close`. If the agent drops or the session ends, all its streams close.

Many VMs in one Codespace: one agent connection, many streams, each tagged by `sid`. VM names map to containers
`vyomi-i-<instance id>` on `vyomi-net`, where the agent's `link` container can reach them by name.

## 5. Browser (Nano) VMs

Today [built+tested]: the VM worker connects to the local relay's `/vm`; the relay opens `127.0.0.1:22000-22999` and bridges each
accepted connection to the VM's sshd; the user runs `ssh -p <port> user@127.0.0.1`. This needs `vyomi-tunnel` running locally
and the Nano tab open.

Planned [planned]: the tab registers `my-vm` with the hosted relay and `vyomi-tunnel connect my-vm` reaches it through `/connect`,
so the same `ssh my-vm.vyomi` works for both VM kinds. Browser VMs still die when the tab closes.

### Package downloads (egress)

The browser VM has git, python3 and pip in its image (`wasm/vm/image/rootfs.cpio.gz`) but no TLS, so its network is the browser's
`fetch` through `<relay>/egress?u=<url>`. `egress.mjs` allows only package/source hosts (Alpine, PyPI, npm, Maven, Go, Rust,
GitHub, GitLab, …), blocks IPs/localhost, follows redirects hop by hop, upgrades http→https upstream, streams the body.
`vm-worker.js` probes the hosted relay at each boot/restore (Plan A) and falls back to the local tunnel relay (Plan B).

Browser VM state lives in IndexedDB: saved on Stop and every 5 minutes; new VMs start from the clean image.

## 6. Client commands and files

| Command | What it does |
|---|---|
| `vyomi-tunnel` | start the local relay (port 8090, loopback) |
| `vyomi-tunnel login` | opens `<portal>/mesh/cli-login?port=&state=`; the portal redirects to `http://127.0.0.1:<port>/cb` with the token **[portal endpoint planned]**; `login --token <t> [--relay <url>]` works now |
| `vyomi-tunnel config [--yes\|--remove]` | writes `~/.vyomi/ssh_config`, adds one `Include` line first in `~/.ssh/config` after asking; idempotent |
| `vyomi-tunnel connect <vm>[.vyomi] [port]` | ProxyCommand mode: stdin/stdout ↔ relay stream |
| `vyomi-tunnel status` | shows sign-in and session end |

Files (`VYOMI_HOME`, default `~/.vyomi/`, mode 0700/0600): `session.json`, `ssh_config`, `known_hosts`.
Env: `VYOMI_RELAY_URL`, `VYOMI_SESSION_TOKEN`, `VYOMI_PORTAL_URL`, `WS_PKG`.
`connect` exit codes: 0 clean close, 1 refused/failed, 2 not signed in or session ended. Refusals print a reason
(401 sign-in expired, 403 not allowed, 410 ended, 502 Mesh not running, 429 too many connections).

Install never edits `~/.ssh`: Homebrew's installer is sandboxed and npm `postinstall` editing dotfiles is bad practice, so the
config change happens only in `login`/`config`, with a prompt.

## 7. Security model

- End-to-end SSH: key never leaves the laptop; relay/agent see ciphertext.
- Session token: HMAC-signed by the portal, carries `sub`, `tier`, `session_id`, `session_end`; the hub rejects bad signature,
  wrong audience, future `iat`, expired, non-Pro/Max/enterprise tiers.
- A `/connect` client can only reach the agent of **its own session** and only if the account matches.
- Mesh agent opens outbound only: the Codespace publishes no port.
- The agent holds no Docker access: the resolver only tries `vyomi-i-<name>`, `vyomi-<name>`, `<name>` (name matched against `[A-Za-z0-9._-]{1,80}`): it cannot be pointed at
  arbitrary hosts. VM port is 1-65535 but only on VM containers.
- Caps: 20 streams per Mesh session (`VYOMI_MAX_STREAMS`), 20 s open timeout, token `session_end` closes the link.
- `/egress`: allow-list only, no IPs/localhost, GET/HEAD/POST, Origin check, per-IP rate limit (Workers binding, optional).
- Not yet: per-stream bandwidth cap, per-user stream cap across sessions, audit log.

## 8. Cost (rough, at 300 concurrent sessions; unverified usage assumptions)

- Cloudflare Workers Paid $5/mo base; Durable Object requests $0.15/M (incoming WebSocket messages billed 20:1), duration
  $12.50/M GB-s; egress free. With WebSocket **hibernation** about $55-60/mo including a $4-6 DO droplet; without it about $420.
- The existing Worker `RelaySession` already uses hibernation (`acceptWebSocket`). The Mesh hub/`/connect` port to a Durable Object
  must too.

## 9. Keep-alive client (renew the Codespace TTL) — design

Finding (2026-11-07/08 tests): GitHub's Codespace idle timer is reset only by a **connected SSH session with traffic**
(one line every 240 s kept a 5-minute-timeout Codespace alive); relay WebSocket traffic, terminal output and forwarded-port
requests do not. 240 minutes is the hard ceiling from the last counted activity.

Plan [planned, not in the tunnel yet]: an SSH client component, "keeper", that holds a real SSH session to the Codespace and
sends a small write every ~240 s while a Mesh session is active.

- Today the portal worker does this with `gh codespace ssh -c <name> -- echo …` per running session (`app/booster_keepalive.py`,
  10 unit tests; **not verified against a real Codespace**; needs the sshd devcontainer feature synced to `vyomi-cloud/sandbox`
  and proof that `gh` accepts the stored token type).
- Where the keeper runs is the open decision: (a) the portal worker on DO (current), (b) a small always-on host (the future
  gateway droplet), (c) `vyomi-tunnel` on the user's laptop (dies with the laptop, so not enough alone).
- Requirements either way: key the Codespace trusts, per-session schedule, stop at `session_end`, jitter, back-off on failure,
  never log tokens, one probe in flight per Codespace, status exposed to the portal (`keepalive` in the session view).
- Open: GitHub acceptable-use for sparse automated SSH; behaviour at thousands of sessions.

## 9b. Codespace host sshd as a target — design for review [planned, nothing built]

Goal: `ssh codespace.vyomi` reaches the **Codespace host's own sshd** through the same `/connect` path, in addition to the Docker VMs.
Requested 2026-11-09; handed to a separate session to review and build.

What it needs:
1. **sshd on the host.** The booster devcontainer already lists the `ghcr.io/devcontainers/features/sshd:1` feature
   (`codespace/.devcontainer/booster/devcontainer.json`, local); it must be synced to `vyomi-cloud/sandbox` (new Codespaces only).
2. **Reserved target name** (proposal: `codespace`, or `host`) handled by the agent resolver in `booster-dial.mjs`
   (`dockerResolve`/`vmCandidates`) before the container lookup. It must not be creatable as a VM name; the portal's
   unique-VM-name rule has to reserve it.
3. **Network reach from the `link` container to the host.** The agent runs in a container on `vyomi-net`
   (`docker-compose.booster.yml`, service `link`); options: `extra_hosts: host.docker.internal:host-gateway`, or the bridge gateway
   IP, or `network_mode: host` for `link` (changes how it reaches `simulator:9000`, so prefer the first).
4. **A key the host trusts.** Pass the user's public key from the portal at session start and have the boot script
   (`boot-booster.sh`) append it to the Codespace user's `authorized_keys`; remove it at session end. Password auth stays off.
5. **Client:** no protocol change. The hub, `/connect` and `vyomi-tunnel connect` already carry any `vm` name and port.
   `Host *.vyomi` covers `codespace.vyomi`.

Security: host sshd gives access to the Docker socket (effectively root inside that Codespace). Acceptable because the Codespace is the
user's own and the hub already requires token + same account + same session. Keep the existing 20-stream cap; log opens of the
reserved target; do not expose it to any other account or to shared/enterprise tenancy without a separate decision.

Not a TTL renewal: a connection that leaves the Codespace to our relay and returns does not count as SSH activity for GitHub's idle
timer (only a session through GitHub's own channel, e.g. `gh codespace ssh`, does; see section 9). The keeper must keep using that
path. This feature is for access and debugging.

Test plan for the builder: extend `wasm/relay/test-mesh-ssh.mjs` with a fake host sshd (TCP echo) and a resolver returning it for
`codespace`; check that the name is reserved, other accounts get 403, and that `docker exec` access works on a real Codespace once
sshd and the key injection exist. Estimate: about half a day plus the live check.

## 9c. Reserved targets, `forward` and the keeper - built 2026-11-10 (local tests only)

Built on the trunk's stream framework (`kind:"tcp"`); no new agent roles (the hub's `role` means runner-role tokens, which is a different thing).

- **Reserved targets**, answered by the agent before any container lookup, client port ignored (`resolveReserved` in `wasm/relay/booster-dial.mjs`):
  `host` / `codespace` -> this machine's sshd (`VYOMI_HOST_SSH_ADDR`, default `host.docker.internal:22`); `vyomi-k3s-<10 hex>` -> that k3s API
  server on port 6443 only (`core/k3s_runtime.py` `server_name`); `k3s` -> `VYOMI_K3S_ADDR` when set. A VM cannot shadow them. Each open is an audit log line.
- **`vyomi-tunnel forward <target> <local>:<remote>`**: loopback listener, one `/connect` stream per accepted socket
  (`vyomi-tunnel forward vyomi-k3s-<id> 6443:6443`, then `kubectl --server https://127.0.0.1:6443`).
- **`vyomi-tunnel keep`** (`wasm/relay/keeper.mjs`): holds an ssh session to the Codespace host and writes a line about every 240 s (+/-10%) to renew GitHub's idle timer.
- Tests: `test-tunnel-k3s.mjs` (19 checks), `test-keeper.mjs`. NOT verified: a real Codespace, a real k3s API through the tunnel, the T1 keeper acceptance gate.
- **Still needed for a Pro/Max user to reach k3s from their machine:** sshd in the Codespace image (`vyomi-cloud/sandbox`) + the 9b host-sshd path;
  reachability of `vyomi-net` from the agent container; kubeconfig `server:` rewrite to the forwarded port; the runner agent/handoff (not built).

## 10. Test coverage

| Area | Test | Result |
|---|---|---|
| Worker `/egress` | `wasm/relay/test-worker-egress.mjs` | 9 checks pass |
| Mesh SSH path + client + config | `wasm/relay/test-mesh-ssh.mjs` | 20 checks pass (round trip incl. 2 MB, parallel streams, stream cap, unknown VM, auth failures, agent drop, config edits) |
| Booster HTTP link, shell streams, derived session keys | `test-booster-link.mjs`, `test-booster-shell.mjs`, `test-booster-session-derived.mjs` | pass after the merge onto v4-on-main (needs `WS_PKG`; shell test needs a Python with uvicorn) |
| Real Codespace + real sshd | — | **not run** |
| Browser VM boot + pip/git via hosted `/egress` | — | **not run** |
| Cloudflare deploy (`wrangler deploy --dry-run`, rate-limit binding syntax) | — | **not run** |

## 11. Still to build

1. Portal: `/mesh/cli-login` (mint token, redirect to loopback) and a VM-list endpoint for the Connect tab.
2. Hosted relay: port the Mesh hub (`/booster`, `/connect`) to the Cloudflare Durable Object with WebSocket hibernation.
3. Nano tab registers browser VMs with the hosted relay (one `ssh my-vm.vyomi` for both kinds).
4. Honour the user's key pair at VM launch (the Docker backend injects a generated key).
5. Keeper (section 9), live verification, devcontainer sync to `vyomi-cloud/sandbox`.
6. `vyomi-tunnel forward <vm> <local>:<remote>` for non-SSH TCP (HTTP/ws/db).
7. Codespace host sshd target (section 9b, handed to another session for review/build).
8. Per-stream bandwidth cap and audit log; a hosted TCP gateway remains optional post-v4 for zero-install.
9. **[Answered in 1c: the link runs on the laptop, nothing is hosted.]** Originally: decide where the relay the Mesh agent dials runs. `BOOSTER-CODESPACES-GITHUB-APP.md` 6.4 says the booster dials out to "our relay" and that the relay already ships inside the appliance image; the go-live checklist says to deploy `local-relay.mjs` behind wss://. No hosted instance exists (`relay.vyomi.cloud` is the Cloudflare Worker, which has no Mesh hub and answers 503 on `/booster`), and a laptop-local relay is not reachable from a Codespace. Until this is decided and built, no real Codespace can link. Also needed: the published `vyomi/appliance` image rebuilt so `/app/relay` exists (the 2026-11-10 `:latest` has none).

---

## 12-16. Restored sections

> Restored 2026-11-10 from `archive/v4-tunnel-k3s-20261110` (commit `eacf1ecd`). They were dropped when the tunnel work was ported onto this trunk and the doc was rewritten. Status notes are on each heading. Section 12 (agent `role` label) conflicts with 9c, which deliberately adds **no** agent roles (the hub's `role` means runner-role tokens); decide which shape wins before building the runner agent. Sections 15 and 16 are still plan only.

## 12. Agent roles and runner targets [planned; trunk chose a different shape, decision pending]

A Pro/Max session can have several Mesh agents: one in the Codespace and one per GitHub runner that hosts a k3s cluster.

- Agent registration gains a `role` label: `codespace`, `runner-<cluster>`. The hub keys agents by `(session_id, role)`. Today it keys by `session_id` only.
- `/connect?vm=<target>&port=<p>[&role=<r>]`: default role is `codespace`; the client names the role for runner targets.
  Targets resolve inside the agent that owns the role, so a name can never reach another role's network.
- Reserved targets per agent: `host` (the machine's own sshd: `codespace` keeps working as an alias on the codespace role), `k3s` (the k3s
  server container, API port 6443), and `vyomi-i-<id>` containers as today.
- Runner agent lifecycle: started as a workflow step; dials OUT with the session token; the workflow ends when the agent exits, so the
  agent lifetime is the job lifetime (max 6 h on a hosted runner, nothing can extend it).
- Keys: the workflow receives the user's public key (and the keeper key when relevant) as dispatch inputs, appends them to `authorized_keys`, never logs them.
- Caps: the 20-stream cap applies per session across roles; an audit line is written for every open of `host` and `k3s`.

## 13. `vyomi-tunnel forward` — non-SSH TCP [built 2026-11-10, local tests only; see 9c]

`vyomi-tunnel forward <target>[.<role>] <local>:<remote>` binds `127.0.0.1:<local>` and bridges each accepted connection to a `/connect`
stream. This is what makes kubectl and Lens work: `forward <cluster> 6443:6443`, kubeconfig server `https://127.0.0.1:6443`.

- Binds loopback only; refuses ports below 1024 unless told; exits with the same codes as `connect`.
- The k3s API certificate must list `127.0.0.1` and the stable cluster name (k3s `--tls-san`), so no `insecure-skip-tls-verify`.
- Runs while the process runs; reconnects streams, not the session; stops at `session_end`.

## 14. Real k3s lifecycle (cloud skins AKS/EKS/GKE) [partly built: core/k3s_runtime.py, KubeBackend seam, EKS core; Nano side not built]

One k3s per simulated cluster, same lifecycle on three substrates:

| Substrate | Where k3s runs | How the API is reached |
|---|---|---|
| Booster, Codespace-local (default) | `rancher/k3s` privileged container on `vyomi-net` in the Codespace's Docker | agent resolves target `k3s` to the container |
| Booster, runner | k3s container in the runner's Docker | runner agent, role `runner-<cluster>`, target `k3s` |
| Offline appliance (Pro/Max) | container on the appliance's Docker | published port / compose network |

- The cloud APIs (ARM, EKS, Container API) create/delete the k3s container(s), store the endpoint on the cluster resource, and serve
  `get-credentials` / `update-kubeconfig` / `get-credentials` from a per-cluster kubeconfig (client cert, TLS SAN as in section 13).
- `core/kube_state_core.py` `RealK8sBackend` (the seam left by the AKS backup work) implements `export_resources` / `apply` / `health` against the
  real API; backups and restores then act on real objects.
- Node pools >1 become k3s agent containers on the same network. Persistent volumes use a StorageClass backed by simulator storage so they
  survive a runner handoff.
- Cloud integrations (OIDC issuer, STS/Entra token exchange, load balancer and disk objects) resolve against the simulator cores over the tunnel.

## 15. Runner handoff at ~5 h [planned]

1. Controller (the session owner) dispatches runner B at about T+4h45m with the same cluster id.
2. B's agent registers as `runner-<cluster>-b`; B joins as a second server (k3s started with `--cluster-init` from the start, embedded etcd).
3. Drain and cordon A; wait for pods to be Ready on B; remove A from etcd; cancel A.
4. The stable endpoint (role alias `runner-<cluster>`) is repointed to B's agent; clients reconnect, kubeconfig is unchanged.
5. Objects and simulator-backed volumes survive; pods are recreated (as on any node replacement); `emptyDir`, `hostPath` and container filesystem writes do not.
Fallback: snapshot (k3s data dir + volume data via the backup layer) at ~5 h and restore on B; pods restart, 1-3 min gap (not measured).
Abort rule: if the controller is lost mid-handoff, A keeps running until its own timeout.

## 16. Acceptance gates [none run yet]

| Id | Check | Pass |
|---|---|---|
| T1 | Keeper through the 9b relay path against a real Codespace with a 5-minute idle setting | stays Running >= 3 periods on keeper traffic only; stops within 1 period after the keeper stops |
| T2 | Fallback only if T1 fails: `gh codespace ssh -- echo` every ~240 s | same as T1 |
| T3 | `ssh <cluster>.vyomi` to a runner host and `forward <cluster> 6443:6443` + `kubectl get nodes` | node Ready, no TLS bypass |
| T4 | Lens connects through `forward` | cluster listed, workloads visible |
| T5 | Handoff: app + PVC (file written) + Secret + CRD instance survive | object list equal, file present, app answers |
| T6 | Tenant isolation: another account's token cannot open `host`/`k3s` of this session | 403 |
