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
| `/connect?vm=&port=` | laptop | raw TCP stream to a VM behind the same session's agent | Bearer session token | [built+tested] (Node relay only) |
| `/egress?u=` | browser VM host | allow-listed GET/HEAD/POST fetch for pip/apk/git | Origin check + per-IP limit | [built+tested] in Worker (9 checks); not deployed |

## 4. Mesh SSH data path

Frames between the hub and the Mesh agent (one WebSocket, many streams):

- control (JSON text): `{type:"tcp-open", sid, vm, port}` hub→agent; `{type:"tcp-opened"|"tcp-error"|"tcp-close", sid}` agent→hub;
  `{type:"tcp-close", sid}` either way.
- data (binary): `[u32 big-endian sid][payload]` in both directions.
- laptop↔hub: the `/connect` WebSocket carries raw bytes as binary messages, no framing (one WebSocket = one stream).

Steps for `ssh my-vm.vyomi`:

1. `ssh` reads `~/.ssh/config` → `Include ~/.vyomi/ssh_config` → `Host *.vyomi` → `ProxyCommand vyomi-tunnel connect %h`.
2. `connect` strips `.vyomi`, loads `~/.vyomi/session.json` (relay URL + token), opens `wss://<relay>/connect?vm=my-vm&port=22`
   with `Authorization: Bearer <token>`.
3. The hub verifies the token (signature, audience, expiry, tier Pro/Max/enterprise), looks up the agent by `session_id`,
   requires the same account (`sub`), enforces the stream cap, and sends `tcp-open` to the agent.
4. The agent resolves the VM to an address (Docker DNS for `vyomi-i-<id>`, then `docker inspect`), opens TCP to port 22, and
   answers `tcp-opened`. Bytes sent early by the laptop are queued until then. If nothing answers in 20 s the stream is closed.
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
- Resolver only tries `vyomi-i-<name>`, `vyomi-<name>`, `<name>` (name matched against `[A-Za-z0-9._-]{1,80}`): it cannot be pointed at
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

## 9b. Codespace host sshd as a target — design for review [agent side built, unit-tested; devcontainer/compose/boot/portal parts planned]

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

TTL renewal (guideline 2026-11-09): the keeper (section 9c) uses THIS path to run the renewer commands. Earlier text claimed a relayed
sshd session does not count as SSH activity for GitHub's idle timer; that was an inference and was never measured. It is now the
acceptance gate in section 16 (T1). If T1 fails, the fallback is the `gh codespace ssh` channel of section 9.

Test plan for the builder: extend `wasm/relay/test-mesh-ssh.mjs` with a fake host sshd (TCP echo) and a resolver returning it for
`codespace`; check that the name is reserved, other accounts get 403, and that `docker exec` access works on a real Codespace once
sshd and the key injection exist. Estimate: about half a day plus the live check.

## 9c. Keeper in the tunnel — `vyomi-tunnel keep` [built, unit-tested with a fake ssh; not run on a real Codespace]

Commit `5de35d76` on `v4/tunnel-keeper` (`wasm/relay/keeper.mjs`, `test-keeper.mjs`, `keep` command in `mesh-cli.mjs`, copies in `packaging/tunnel/bin/`).

- Holds ONE `ssh` session to `codespace.vyomi` (section 9b target) with the system `ssh` and `ProxyCommand=vyomi-tunnel connect codespace`;
  the remote command is `cat > /dev/null`, so the traffic that counts is client-to-server writes.
- Writes `vyomi-keepalive <iso time>` every `--interval` seconds (default 240, +-10 % jitter). First write ~500 ms after connect.
- Reconnects with back-off 2/5/15/30/60 s; gives up after 10 consecutive failed connects; stops at the token `session_end`; one session per Codespace.
- Status object `{state, lastWriteAt, writes, failures, reason}` for the portal `keepalive` field. The token is read from the environment/session file by
  `connect` and never appears in `ssh` arguments or logs.
- Runs anywhere that holds the session token and can reach the relay (gateway host preferred; laptop works while it is open). It needs a
  dedicated keeper key, injected like the user's key by the 9b step 4 and removed at session end.

## 12. Agent roles and runner targets [hub + agent built, unit-tested locally; runner workflow, keys and portal parts planned]

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

## 13. `vyomi-tunnel forward` — non-SSH TCP [built, unit-tested against a fake TCP echo; not run with kubectl/Lens]

`vyomi-tunnel forward <target>[.<role>] <local>:<remote>` binds `127.0.0.1:<local>` and bridges each accepted connection to a `/connect`
stream. This is what makes kubectl and Lens work: `forward <cluster> 6443:6443`, kubeconfig server `https://127.0.0.1:6443`.

- Binds loopback only; refuses ports below 1024 unless told; exits with the same codes as `connect`.
- The k3s API certificate must list `127.0.0.1` and the stable cluster name (k3s `--tls-san`), so no `insecure-skip-tls-verify`.
- Runs while the process runs; reconnects streams, not the session; stops at `session_end`.

## 14. Real k3s lifecycle (cloud skins AKS/EKS/GKE) [planned]

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

## 10. Test coverage

| Area | Test | Result |
|---|---|---|
| Worker `/egress` | `wasm/relay/test-worker-egress.mjs` | 9 checks pass |
| Mesh SSH path + client + config | `wasm/relay/test-mesh-ssh.mjs` | 20 checks pass (round trip incl. 2 MB, parallel streams, stream cap, unknown VM, auth failures, agent drop, config edits) |
| Booster HTTP link | `wasm/relay/test-booster-link.mjs` | passes (needs `WS_PKG`) |
| Reserved targets, roles, forward, tenant isolation | `wasm/relay/test-tunnel-k3s.mjs` | 52 checks pass locally (fake TCP servers; no docker, no Codespace) |
| Real Codespace + real sshd | — | **not run** |
| Browser VM boot + pip/git via hosted `/egress` | — | **not run** |
| Cloudflare deploy (`wrangler deploy --dry-run`, rate-limit binding syntax) | — | **not run** |

## 16. Acceptance gates [none run yet]

| Id | Check | Pass |
|---|---|---|
| T1 | Keeper through the 9b relay path against a real Codespace with a 5-minute idle setting | stays Running >= 3 periods on keeper traffic only; stops within 1 period after the keeper stops |
| T2 | Fallback only if T1 fails: `gh codespace ssh -- echo` every ~240 s | same as T1 |
| T3 | `ssh <cluster>.vyomi` to a runner host and `forward <cluster> 6443:6443` + `kubectl get nodes` | node Ready, no TLS bypass |
| T4 | Lens connects through `forward` | cluster listed, workloads visible |
| T5 | Handoff: app + PVC (file written) + Secret + CRD instance survive | object list equal, file present, app answers |
| T6 | Tenant isolation: another account's token cannot open `host`/`k3s` of this session | 403 |

### Implementation notes (agent side, as built)

- `booster-dial.mjs`: `resolveReserved()` runs before any resolver (a custom `resolveVm` cannot shadow `host`/`k3s`). `host` and `k3s` ignore the
  client's requested port and always dial ONE configured address (`VYOMI_HOST_SSH_ADDR`, default `host.docker.internal:22`; `VYOMI_K3S_ADDR`, default
  `vyomi-k3s:6443`). `codespace` is an alias of `host` on the `codespace` role only; on any other role it is refused. `vmCandidates` returns nothing for
  reserved names; `isReservedName()` is exported for the backend/portal to refuse them as VM names (that enforcement is NOT in this repo yet).
  Each open of host/k3s emits an audit line through the `audit` option (default: the agent log, prefixed `AUDIT`). Role comes from `role` / `VYOMI_AGENT_ROLE`.
- `booster-hub.mjs`: agents keyed by `(session_id, role)`; the agent dials `/booster?role=<r>`; `/connect` takes `&role=` (default `codespace`; bad label 400,
  no agent for that role 502). The Nano HTTP plane uses the `codespace` role only. A second dial for a taken `(session, role)` slot by a different account is refused (403).
  The stream cap counts streams per session across all roles.
- `mesh-cli.mjs`: `forward <target>[.<role>] <local>:<remote> [--role r] [--allow-privileged]`; `connect()` gained a `role` option (no CLI flag yet).
  Because VM names may contain dots, `a.b` is read as target `a`, role `b`; `--role ""`-style explicit role overrides this.
  Exit codes: 0 stopped / session_end, 1 fatal refusal (401/403/410) or cannot listen, 2 usage / not signed in / session ended. A refusal of a single stream
  (502, 429) only drops that connection. Not implemented from section 13: reconnecting streams (each connection is its own stream, so a new connection simply re-dials).
- Needed outside this repo section (not done): compose `extra_hosts: host.docker.internal:host-gateway` on `link`, `VYOMI_K3S_ADDR` if the container is not `vyomi-k3s`,
  the sshd feature synced to `vyomi-cloud/sandbox`, authorized_keys injection in `boot-booster.sh`, the portal reserving the names, and the packaged
  `vyomi-tunnel` binary (`packaging/tunnel/bin/vyomi-tunnel.mjs` carries no hub; only `mesh-cli.mjs` and the dispatcher list were updated there).
- Dispatcher fix: `keep` and `forward` were not in the subcommand list of `local-relay.mjs` / `vyomi-tunnel.mjs`; added.

## 11. Still to build

1. Portal: `/mesh/cli-login` (mint token, redirect to loopback) and a VM-list endpoint for the Connect tab.
2. Hosted relay: port the Mesh hub (`/booster`, `/connect`) to the Cloudflare Durable Object with WebSocket hibernation.
3. Nano tab registers browser VMs with the hosted relay (one `ssh my-vm.vyomi` for both kinds).
4. Honour the user's key pair at VM launch (the Docker backend injects a generated key).
5. Keeper (section 9), live verification, devcontainer sync to `vyomi-cloud/sandbox`.
6. `vyomi-tunnel forward <vm> <local>:<remote>` for non-SSH TCP (HTTP/ws/db).
7. Codespace host sshd target (section 9b).
8. Keeper (section 9c): built; needs 9b and gate T1.
9. Agent roles + runner targets (section 12), `forward` (section 13), real k3s lifecycle (section 14), runner handoff (section 15), gates (section 16).
8. Per-stream bandwidth cap and audit log; a hosted TCP gateway remains optional post-v4 for zero-install.
