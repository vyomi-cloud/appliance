# Booster LLM mesh (private WireGuard network over the relay)

Status: network layer built + proven in a local multi-container harness (branch `v4/ngmesh`). Not yet run on real GitHub
Actions / Codespaces (section 9). Builds on [BOOSTER-RUNNER-LLM.md](BOOSTER-RUNNER-LLM.md) (the relay-only runner pool) and
[BOOSTER-CODESPACES-GITHUB-APP.md](BOOSTER-CODESPACES-GITHUB-APP.md) section 6.4 (outbound-only relay link).

Owner-accepted risk (one line): running our own workflow on the user's GitHub-hosted runners to host a model may be read as
outside GitHub's intended Actions use; the user runs it in their own account and accepts that.

## 1. What it is for

The booster Codespace plus up to 10 GitHub-hosted runners (user's own account, public repo, ubuntu, 4 vCPU/16 GB, outbound only,
root, 6 h cap, ephemeral) join ONE private network so that

* (a) the booster gateway reaches the Ollama server on each runner directly (`http://100.96.1.N:11434`, the model API), and
* (b) two runners can pool RAM for one model that fits neither (llama.cpp RPC, section 7), with the RPC port bound to the mesh address only.

The relay-only hub of the runner pool stays as the rendezvous and the fallback; the mesh is the transport that model and RPC traffic ride.

## 2. Topology (star, everything dials out)

```
 Codespace (booster 100.96.0.2)        GH runner r1 (100.96.1.1)   ... r10 (100.96.1.10)
   wg iface  <-udp-> 127.0.0.1:P          wg iface <-udp-> 127.0.0.1:P
   agent bridge                           agent bridge
        \                                      |
         \________ wss://relay/mesh  __________|          (each node dials OUT; one WebSocket per node,
                           |                                binary frame = one WireGuard datagram)
                  relay host: per-node UDP socket  -> hub wg iface 100.96.0.1 (ip_forward=1)
```

* Hub = the relay host. It owns the `wgmesh` interface (100.96.0.1/16, listen 51820 on loopback side only; the port is never published).
  Each WebSocket gets its own loopback UDP socket, so the hub's WireGuard sees one distinct endpoint per node.
* Node-to-node traffic goes node -> hub -> node (hub routes). One extra hop; booster -> runner RTT was 4.4 ms vs 0.2 ms plain in the harness.
* No node listens on a routable address or accepts any inbound connection. A node's WireGuard UDP socket exists but only ever talks to the
  loopback bridge (and, if enabled, answers authenticated handshakes on the direct path).
* MTU 1280 (datagrams ride TCP; staying small avoids fragmentation entirely). PersistentKeepalive 25.
* Optional direct UDP: if the hub advertises `VYOMI_MESH_DIRECT=host:51820` the agent first points WireGuard straight at it and waits
  `directWaitMs` for a handshake; no handshake -> it switches to the WebSocket bridge. WS is always the guaranteed path. (Hosted runners and
  Codespaces usually cannot hole-punch; the default is WS-only.)

## 3. Files

| File | Role |
|---|---|
| `core/booster_mesh.py` | portal side: address plan, `mint_mesh_session(session_id, nodes)`, rotation re-mint, token verify, `wg show dump` parser, `runner_urls()` |
| `wasm/relay/booster-mesh.mjs` | `createMeshHub` (relay) + `meshAgent` (every node) + CLI `node booster-mesh.mjs agent` |
| `wasm/relay/local-relay.mjs` | wires `/mesh` (WS) and `/mesh/_peers` (GET) when `VYOMI_MESH=1` |
| `docker/booster-runner-llm/mesh-up.sh` | node entrypoint (runner and booster): `up` / `down` / `status`, idempotent, masks the token |
| `codespace/.devcontainer/booster/mesh-up.sh` | booster-side wrapper (+ `capAdd: NET_ADMIN` in `devcontainer.json`) |
| `docker/booster-mesh-test/` | harness images/relay; `tests/conformance/test_booster_mesh.py` (+ `_rpc.py`) |

## 4. Address plan

CGNAT space `100.96.0.0/16` (cannot clash with runner `10.x`, Docker `172.x`, Codespaces nets).

| Address | Node |
|---|---|
| 100.96.0.1 | hub (relay) |
| 100.96.0.2 | the booster Codespace |
| 100.96.1.1 - 100.96.1.10 | runner slots 1..10 (stable per runner id; a rotated runner keeps its slot) |

The portal allocates; a node can never choose its address (it comes from the signed token, section 5).

## 5. Key flow (no long-lived keys, nothing secret in the portal's mesh data)

1. Portal calls `mint_mesh_session(session_id, nodes, relay_url, session_end)` -> per node `{address, env: {VYOMI_RELAY_URL, VYOMI_MESH_TOKEN, ...}, mask}`.
   The token is the existing booster session token (same HMAC, `core/booster_session.py` wire format) with `role: "mesh-node"` and claims
   `node`, `mesh_addr`, `mesh_role`, `session_id`, `session_end`. There is no WireGuard key in it.
2. The node entrypoint masks the token (`::add-mask::`), starts the agent with the token in the environment only (never argv; the CLI deletes it
   from `process.env` right after reading it).
3. The agent generates an X25519 keypair in-process, writes the private key to a 0600 file in tmpfs for the single `wg set private-key` call and
   unlinks it immediately. The private key never leaves the node and is never logged.
4. Agent dials `wss://relay/mesh` with `Authorization: Bearer <token>` and sends `{type:"join", pubkey}`.
5. Hub verifies signature/expiry/role/session, pins the session id (one mesh = one session per hub), takes the address from the claims, adds
   the peer (`allowed-ips <addr>/32`, endpoint = that socket's loopback UDP port), and replies with its public key, cidr, MTU and the peer list.
6. Agent configures its interface (address, hub peer `allowed-ips 100.96.0.0/16`) and starts the bridge. Handshake happens on the first packet.

Rejected at the WebSocket upgrade: no token or forged (401), expired (410), non-mesh role such as an `llm-runner` token (403), address outside
the plan or the hub address (403), another session's token on a hub already serving one (409).

## 6. Peer table, leave/drain, re-key

* `GET /mesh/_peers` (any valid mesh token of the session): `{peers:[{id, address, role, up, last_handshake_s, connected_s, rx_bytes, tx_bytes, pubkey(8 chars)}]}`;
  `up` = WS open and a WireGuard handshake in the last 200 s. The same list is pushed to every node on change (`{type:"peers"}`); the gateway
  uses `core.booster_mesh.runner_urls(peers)` to learn which runner Ollamas to call.
* Leave: node sends `{type:"leave"}` (or the WS closes) -> hub removes the peer, closes its UDP socket, broadcasts. `mesh-up.sh down` and SIGTERM do this.
  Hub-initiated `drain(id)` sends `{type:"drain"}`; the agent leaves.
* Re-key on rotation: a runner rotates every ~5.5 h. The successor runs the same entrypoint with a fresh token for the SAME node id/slot,
  generates a NEW keypair and joins; the hub adds the new peer first (WireGuard moves the `/32` to it) and then removes the old key. Other peers
  are untouched (verified: continuous booster -> r2 ping, 0 packets lost while r1 left and rejoined with a new key). `agent.rekey()` does the same
  in-process (second WS with a new key, old one closed after 3 s).
* Reconnects: a dropped WS makes the agent reconnect with exponential backoff and a FRESH keypair, so a reconnect is also a re-key.
* TTL: hub drops a node at the token's `session_end`.

## 7. llama.cpp RPC over the mesh (pooled RAM)

`rpc-server -H 100.96.1.N -p 50052` on each of the two runners (bound to the mesh address, never 0.0.0.0), and `llama-server --rpc
100.96.1.1:50052,100.96.1.2:50052 -ngl 99` on the driver (a third node, or runner 1 itself). The stock `ghcr.io/ggml-org/llama.cpp:server`
image has no `rpc-server`; build llama.cpp with `-DGGML_RPC=ON` (client and servers must be the same build). RPC has no authentication or
encryption of its own: the mesh is the access control, which is why the bind address matters. Results: section 8.

Practical limits to plan around: RPC ships the weights from the driver to the servers at mesh speed (see throughput below); a 18 GB model at
~20 MB/s is ~15 min of load, so cache (`rpc-server -c`) and keep the pooled model resident for the whole 5.5 h window. Every token crosses the
mesh twice per RPC hop, so decode speed is bounded by mesh RTT x layers per hop; MoE with few active experts helps, dense models suffer most.

## 8. Measured (local harness: Docker Desktop VM, 8 CPUs; relay 1 cpu; runners `--cpus 2 --memory 1g`, booster `--cpus 1 --memory 768m`)

Mesh (`tests/conformance/test_booster_mesh.py`, 55/55 checks):

| Metric | Value |
|---|---|
| Join, 4 nodes (script start -> linked) | 1.6 - 3.4 s total |
| RTT booster -> r1 over WS-tunnelled WG (via the hub, 2 WS hops) | ~4.4 - 5.1 ms (plain docker path to the relay: 0.2 ms) |
| TCP throughput booster -> r1 (iperf3, 6 s) | 9.5 - 21.4 MB/s up, 7.0 - 21.5 MB/s down (varies with host load; Docker VM shared with ~100 other containers) |
| Re-key: r1 leaves and rejoins with a new key while booster pings r2 | 0 / 48-50 packets lost |
| Direct UDP attempt: reachable endpoint / black hole | joins via `direct-udp` / falls back to `ws-bridge` after the wait (3 s in test, 8 s default) |

Also asserted: no published ports, no TCP listener on a routable address, a service bound to a runner's WG address is not reachable on its docker
address, runners cannot reach each other except through the mesh, token-less/forged/expired/wrong-role/other-session joins are refused (401/410/403/409),
the token appears in no log and no process command line, `mesh-up.sh` is idempotent.

llama.cpp RPC (`tests/conformance/test_booster_mesh_rpc.py`; Qwen2.5-1.5B-Instruct Q4_K_M, 1.1 GB; r1/r2 run `rpc-server` on their WG address,
r3 runs `llama-server --rpc`; every container `--cpus 2`, `-t 2`; llama.cpp b12124 + libggml-rpc built as a loadable backend):

| | Load | Decode | Prompt |
|---|---|---|---|
| Single node (r3 alone) | 10 s | 2.77 tok/s | 5.05 tok/s |
| 2 RPC servers over the mesh | 116 s | 0.36 tok/s | 1.27 tok/s |

The split is real: r1 and r2 received 460 MB and 592 MB over the mesh (together ~ the whole 1.1 GB model) and tokens came back correctly. But RPC over the
WS-tunnelled mesh is ~8x SLOWER than one node for a model that fits locally: load is bound by mesh throughput (~10 MB/s effective) and decode by
per-token round trips (~2.8 s/token). So pooling only makes sense for a model that does NOT fit one runner (qwen3:30b), where the alternative is not running it
at all, and it needs the follow-ups in 10 (cache weights on the servers, measure on real hosts, consider direct UDP/bigger MTU path). We did not get a clean
attribution (RPC vs. WS tunnel): a plain-docker single-server control run crashed inside libggml-rpc on the client, so that control is still open.

## 9. Failure modes

| Failure | Behaviour |
|---|---|
| WS to relay drops | agent reconnects with backoff + new key; peers see the node `down` until the next handshake; gateway falls back to the relay-only LLM plane for that runner |
| Relay restarts | hub state is rebuilt from rejoining agents (a few seconds); no keys are persisted anywhere |
| WS back-pressure (TCP stalls) | datagrams are dropped when >1 MiB is queued (UDP semantics), so TCP-in-TCP meltdown is bounded; MTU 1280 |
| Runner dies at 6 h / cancelled | WS closes -> peer removed; rotation successor already joined under the same address with a new key |
| Two nodes claim one address | second join is refused unless it is the same node id (a re-key) |
| No kernel WireGuard | agent falls back to `wireguard-go` (needs `/dev/net/tun`); neither -> join fails loudly, runner uses the relay-only plane |
| Compromised runner | holds only its own key and token; the token is bound to one address, one session and expires; it can reach other mesh nodes' services (all are the user's own) |
| Relay compromised | sees ciphertext only (WireGuard end-to-end between nodes... except it IS the hub: node-to-node traffic is decrypted/re-encrypted at the hub). Known limit of the star, see 10 |

## 10. Known limits / follow-ups

* Hub is a router: a hostile relay host could read node-to-node traffic. For the booster-appliance relay (the user's own) that is acceptable;
  the public relay should carry only the bridged ciphertext with the hub inside the booster (then the Codespace is the hub) - a topology switch,
  not a protocol change.
* Per-pair firewall at the hub (only booster -> runner:11434 and runner <-> runner:50052) is not implemented; all nodes can reach each other.
* HMAC shared-key tokens (same caveat as booster_session.py): an asymmetric signature would stop a compromised relay minting tokens.
* A 5 s `wg dump` poll per node; fine for 11 nodes.

## 11. What needs a real GitHub validation

1. `ip link add type wireguard` and `wireguard-tools` apt install on `ubuntu-latest` runners (expected yes; fallback wireguard-go) and in the Codespace
   devcontainer (DinD privileged; confirm `/dev/net/tun`, kernel wg or wireguard-go).
2. Real WS path RTT/throughput runner <-> relay <-> Codespace (the harness numbers are a LAN best case).
3. Runner-to-runner RPC performance across the real internet-routed relay; rotation overlap at 5.5 h with real timing.
4. Direct-UDP attempt: expected to fail on hosted runners (no inbound, NAT); confirm the fallback is quick.
5. The mesh token injection path in the dispatch workflow (portal -> workflow input -> masked env) and that `::add-mask::` hides it in the public log.
