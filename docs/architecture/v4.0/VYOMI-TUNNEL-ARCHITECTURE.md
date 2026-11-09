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

## 10. Test coverage

| Area | Test | Result |
|---|---|---|
| Worker `/egress` | `wasm/relay/test-worker-egress.mjs` | 9 checks pass |
| Mesh SSH path + client + config | `wasm/relay/test-mesh-ssh.mjs` | 20 checks pass (round trip incl. 2 MB, parallel streams, stream cap, unknown VM, auth failures, agent drop, config edits) |
| Booster HTTP link | `wasm/relay/test-booster-link.mjs` | passes (needs `WS_PKG`) |
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
7. Per-stream bandwidth cap and audit log; a hosted TCP gateway remains optional post-v4 for zero-install.
