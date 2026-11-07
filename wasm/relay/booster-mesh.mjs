/* LLM MESH network layer (hub + node agent). Design: docs/architecture/v4.0/BOOSTER-LLM-MESH.md
 *
 * A private WireGuard star: the relay host runs the HUB (wg interface, 100.96.0.1); the booster Codespace and every GitHub
 * Actions runner run a NODE AGENT. Nothing is inbound anywhere: every node dials OUT to wss://<relay>/mesh, and the WireGuard
 * UDP datagrams ride that WebSocket (one binary frame per datagram):
 *
 *   node wg  --udp-->  127.0.0.1:P (agent bridge) --ws--> relay  --udp--> 127.0.0.1:<hubport> (hub wg)
 *
 * Node-to-node traffic is routed by the hub (ip_forward), so A reaches B at B's WG address without any node accepting a
 * connection from the internet. An optional direct-UDP attempt (hub advertises VYOMI_MESH_DIRECT) runs first; if no handshake
 * within DIRECT_WAIT_MS the agent falls back to the bridge. The WS is always the rendezvous (and the fallback).
 *
 * KEYS: each node generates its X25519 keypair IN PROCESS (never leaves the node, never logged, no long-lived keys); only the
 * public key goes to the hub inside the join frame, authenticated by the portal-signed mesh token (role "mesh-node"; claims:
 * node id, mesh_addr, session_id). The hub never trusts the node for its address: it comes from the token.
 *
 * Control (JSON text frames):   node -> hub {type:"join", pubkey}   {type:"leave"}   {type:"hb"}
 *                               hub -> node {type:"joined", address, cidr, hub_pubkey, hub_address, mtu, keepalive, direct, peers}
 *                                           {type:"peers", peers}  {type:"drain"}
 * Data: binary frames = raw WireGuard UDP datagrams.
 *
 * Re-key: the same node id joining again (new pubkey, e.g. a rotated runner or agent.rekey()) takes over the node's
 * address; the old peer is removed afterwards. No other peer's keys/sessions change.
 */
import crypto from "node:crypto";
import dgram from "node:dgram";
import { execFile } from "node:child_process";
import fs from "node:fs";
import { verify, SessionError } from "./booster-session.mjs";

export const ROLE = "mesh-node";
export const CIDR = "100.96.0.0/16";
export const HUB_ADDR = "100.96.0.1";
const MTU = 1280;                       // datagrams ride TCP: stay well below any path MTU, avoid fragmentation entirely
const KEEPALIVE = 25;
const MAX_QUEUED = 1 << 20;             // drop datagrams (UDP semantics) when the WS is backed up more than 1 MiB
const UP_HANDSHAKE_S = 200;             // wg re-handshakes ~every 120 s while traffic (incl. keepalives) flows

// ---------------------------------------------------------------- wg / ip helpers (injectable for tests)
export function sh(cmd, args, { input } = {}) {
  return new Promise((resolve, reject) => {
    const p = execFile(cmd, args, { timeout: 15000 }, (err, stdout, stderr) => {
      if (err) { err.message = `${cmd} ${args[0] || ""} failed: ${String(stderr || err.message).trim().slice(0, 200)}`; reject(err); } else resolve(String(stdout));
    });
    if (input !== undefined) { p.stdin.on("error", () => {}); p.stdin.end(input); }
  });
}
const b64u = (b) => Buffer.from(b).toString("base64url");

/** X25519 keypair in WireGuard's base64 (std) encoding. */
export function genKeypair() {
  const { privateKey, publicKey } = crypto.generateKeyPairSync("x25519");
  const priv = privateKey.export({ format: "der", type: "pkcs8" }).subarray(-32);
  const pub = publicKey.export({ format: "der", type: "spki" }).subarray(-32);
  return { priv: priv.toString("base64"), pub: pub.toString("base64") };
}
export const validPub = (s) => typeof s === "string" && /^[A-Za-z0-9+/]{43}=$/.test(s) && Buffer.from(s, "base64").length === 32;

/** Create the interface: kernel WireGuard first, userspace wireguard-go as fallback. Returns "kernel"|"userspace". */
export async function ensureIface(iface, run = sh) {
  try { await run("ip", ["link", "show", iface]); return "existing"; } catch { /* create */ }
  try { await run("ip", ["link", "add", iface, "type", "wireguard"]); return "kernel"; }
  catch (e1) {
    try { await run("wireguard-go", [iface]); for (let i = 0; i < 20; i++) { try { await run("ip", ["link", "show", iface]); return "userspace"; } catch { await new Promise((r) => setTimeout(r, 100)); } } }
    catch { /* fallthrough */ }
    throw new Error("cannot create a WireGuard interface (no kernel wireguard, no wireguard-go / NET_ADMIN / /dev/net/tun): " + e1.message);
  }
}
/** wg only takes the private key from a file: write it 0600 into tmpfs, apply, unlink immediately. */
async function setPrivateKey(iface, priv, run) {
  const dir = fs.existsSync("/dev/shm") ? "/dev/shm" : "/tmp";
  const f = `${dir}/.vyomi-wg-${process.pid}-${crypto.randomBytes(4).toString("hex")}`;
  fs.writeFileSync(f, priv + "\n", { mode: 0o600 });
  try { await run("wg", ["set", iface, "private-key", f]); } finally { try { fs.unlinkSync(f); } catch { /* */ } }
}

// ---------------------------------------------------------------- HUB
export function createMeshHub({ WebSocketServer, key = process.env.VYOMI_BOOSTER_SESSION_KEY || "", iface = process.env.VYOMI_MESH_IFACE || "wgmesh",
                                hubPort = Number(process.env.VYOMI_MESH_WG_PORT || 51820), direct = process.env.VYOMI_MESH_DIRECT || "",
                                run = sh, log = () => {}, now = () => Date.now() } = {}) {
  const wss = new WebSocketServer({ noServer: true, maxPayload: 4096 });
  const nodes = new Map();                    // node id -> entry
  let sessionId = null, hubPub = null, ready = null, mode = null;
  const enabled = () => !!key;

  async function init() {                     // lazily on first join; idempotent
    if (ready) return ready;
    ready = (async () => {
      const kp = genKeypair();
      mode = await ensureIface(iface, run);
      await setPrivateKey(iface, kp.priv, run);
      await run("wg", ["set", iface, "listen-port", String(hubPort)]);
      await run("ip", ["addr", "replace", `${HUB_ADDR}/16`, "dev", iface]);
      await run("ip", ["link", "set", iface, "mtu", String(MTU), "up"]);
      try { fs.writeFileSync("/proc/sys/net/ipv4/ip_forward", "1"); } catch { await run("sysctl", ["-w", "net.ipv4.ip_forward=1"]); }
      hubPub = (await run("wg", ["show", iface, "public-key"])).trim();
      log(`mesh hub up (${mode})`);
    })().catch((e) => { ready = null; throw e; });
    return ready;
  }

  const peerList = () => [...nodes.values()].map((n) => ({ id: n.id, address: n.addr, role: n.mrole, up: !n.draining && isUp(n) }));
  const isUp = (n) => n.ws.readyState === 1 && n.hs > 0 && now() / 1000 - n.hs < UP_HANDSHAKE_S;
  function broadcastPeers() { const m = JSON.stringify({ type: "peers", peers: peerList() }); for (const n of nodes.values()) try { n.ws.send(m); } catch { /* */ } }

  async function removePeer(pub) { try { await run("wg", ["set", iface, "peer", pub, "remove"]); } catch { /* already gone */ } }
  function teardown(n, reason) {
    clearInterval(n.timer); clearTimeout(n.endTimer);
    try { n.udp.close(); } catch { /* */ }
    try { n.ws.close(4000, reason); } catch { /* */ }
  }
  async function dropNode(n, reason, { keepPeer = false } = {}) {
    if (nodes.get(n.id) === n) nodes.delete(n.id);
    teardown(n, reason);
    if (!keepPeer) await removePeer(n.pub);
    log(`mesh node ${n.id} left (${reason})`);
    broadcastPeers();
  }

  /** Poll `wg show <if> dump` for handshakes/traffic. */
  async function refresh() {
    if (!ready || !nodes.size) return;
    let out; try { out = await run("wg", ["show", iface, "dump"]); } catch { return; }
    const byPub = new Map(); for (const n of nodes.values()) byPub.set(n.pub, n);
    for (const line of out.trim().split("\n").slice(1)) {
      const f = line.split("\t"); const n = byPub.get(f[0]); if (!n) continue;
      n.hs = Number(f[4]) || 0; n.rx = Number(f[5]) || 0; n.tx = Number(f[6]) || 0;
    }
  }

  function upgrade(req, socket, head) {
    const reject = (status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
    if (!enabled()) { reject(503, "BoosterLinkDisabled"); return true; }
    let claims; const a = req.headers["authorization"] || "";
    try { claims = verify(/^Bearer /i.test(a) ? a.slice(7).trim() : "", key); }
    catch (e) { reject(e instanceof SessionError ? e.status : 401, e.code || "BoosterSessionInvalid"); return true; }
    if (claims.role !== ROLE) { reject(403, "BoosterSessionWrongRole"); return true; }
    if (!/^100\.96\.\d+\.\d+$/.test(claims.mesh_addr || "") || claims.mesh_addr === HUB_ADDR || !claims.node) { reject(403, "MeshClaimsInvalid"); return true; }
    if (sessionId && sessionId !== claims.session_id) { reject(409, "MeshSessionMismatch"); return true; }   // one mesh (one session) per hub
    wss.handleUpgrade(req, socket, head, (ws) => onSocket(ws, claims));
    return true;
  }

  function onSocket(ws, claims) {
    let me = null, joined = false;
    const joinTimer = setTimeout(() => { if (!joined) ws.close(4001, "join timeout"); }, 10000);
    const queue = [];                          // datagrams that arrive while join is being processed
    ws.on("message", async (data, isBinary) => {
      if (isBinary) { if (me) me.udp.send(data, hubPort, "127.0.0.1"); else if (queue.length < 64) queue.push(data); return; }
      let m; try { m = JSON.parse(data.toString()); } catch { return; }
      if (m.type === "join" && !joined) {
        joined = true; clearTimeout(joinTimer);
        try { me = await join(ws, claims, m); } catch (e) { log("mesh join failed: " + e.message); try { ws.close(4002, "join failed"); } catch { /* */ } return; }
        for (const d of queue.splice(0)) me.udp.send(d, hubPort, "127.0.0.1");
      } else if (m.type === "leave" && me) { dropNode(me, "left"); }
      else if (m.type === "hb" && me) { me.lastSeen = now(); }
    });
    const gone = () => { clearTimeout(joinTimer); if (me && nodes.get(me.id) === me) dropNode(me, "disconnected"); else if (me) teardown(me, "replaced"); };
    ws.on("close", gone); ws.on("error", gone);
  }

  async function join(ws, claims, m) {
    if (!validPub(m.pubkey)) throw new Error("bad pubkey");
    await init();
    sessionId = sessionId || claims.session_id;
    const id = claims.node, addr = claims.mesh_addr;
    for (const o of nodes.values()) if (o.id !== id && o.addr === addr) throw new Error("address already held by another node");
    const udp = dgram.createSocket("udp4");
    await new Promise((res, rej) => { udp.once("error", rej); udp.bind(0, "127.0.0.1", res); });
    udp.on("error", () => {});
    const port = udp.address().port;
    const n = { id, addr, mrole: claims.mesh_role || "node", pub: m.pubkey, ws, udp, port, hs: 0, rx: 0, tx: 0, since: now(), lastSeen: now(), draining: false, timer: null, endTimer: null };
    udp.on("message", (d) => { if (ws.readyState === 1 && ws.bufferedAmount < MAX_QUEUED) ws.send(d, { binary: true }); });
    // Add the NEW peer first (steals the /32 from a previous key of the same node id), then remove the old one: no gap for others.
    await run("wg", ["set", iface, "peer", n.pub, "allowed-ips", `${addr}/32`, "endpoint", `127.0.0.1:${port}`, "persistent-keepalive", String(KEEPALIVE)]);
    const old = nodes.get(id);
    nodes.set(id, n);
    if (old) { teardown(old, "rekeyed"); if (old.pub !== n.pub) await removePeer(old.pub); log(`mesh node ${id} re-keyed`); }
    n.endTimer = setTimeout(() => dropNode(n, "session_end"), Math.max(0, claims.session_end * 1000 - now()));
    n.timer = setInterval(async () => { await refresh(); }, 5000);
    ws.send(JSON.stringify({ type: "joined", node: id, address: addr, cidr: CIDR, hub_pubkey: hubPub, hub_address: HUB_ADDR, mtu: MTU, keepalive: KEEPALIVE, direct: direct || null, peers: peerList() }));
    log(`mesh node ${id} joined`);
    broadcastPeers();
    return n;
  }

  /** HTTP GET /mesh/_peers (any valid mesh-node token of the session). Returns true if handled. */
  function http(req, res) {
    const url = new URL(req.url, "http://x");
    if (!url.pathname.startsWith("/mesh")) return false;
    const out = (st, obj) => { res.writeHead(st, { "content-type": "application/json", "x-vyomi-hub": "1" }); res.end(JSON.stringify(obj)); return true; };
    if (!enabled()) return out(503, { error: "BoosterLinkDisabled" });
    let claims; const a = req.headers["authorization"] || "";
    try { claims = verify(/^Bearer /i.test(a) ? a.slice(7).trim() : "", key); } catch (e) { return out(e.status || 401, { error: e.code || "BoosterSessionInvalid" }); }
    if (claims.role !== ROLE || (sessionId && claims.session_id !== sessionId)) return out(403, { error: "BoosterSessionWrongRole" });
    if (url.pathname === "/mesh/_peers") {
      refresh().then(() => out(200, { session_id: sessionId, iface, mode, hub: HUB_ADDR, peers: [...nodes.values()].map((n) => ({
        id: n.id, address: n.addr, role: n.mrole, up: !n.draining && isUp(n), pubkey: n.pub.slice(0, 8) + "...", last_handshake_s: n.hs ? Math.round(now() / 1000 - n.hs) : null,
        connected_s: Math.round((now() - n.since) / 1000), rx_bytes: n.rx, tx_bytes: n.tx })) }));
      return true;
    }
    return out(404, { error: "NotFound" });
  }

  /** Hub-initiated drain: tell the node to leave gracefully (it removes its peer when it sends {type:"leave"}). */
  function drain(id) { const n = nodes.get(id); if (!n) return false; n.draining = true; try { n.ws.send(JSON.stringify({ type: "drain" })); } catch { /* */ } return true; }
  async function close() { for (const n of [...nodes.values()]) await dropNode(n, "relay shutdown"); try { await run("ip", ["link", "del", iface]); } catch { /* */ } ready = null; }

  return { upgrade, http, enabled, drain, close, peers: () => peerList(), refresh };
}

// ---------------------------------------------------------------- NODE AGENT
/** Runs on every node (runner or booster). Needs root (or CAP_NET_ADMIN) for `ip`/`wg`. */
export function meshAgent({ relayUrl, token, WS, iface = "wgvyomi", run = sh, log = () => {}, directWaitMs = 8000,
                            statusFile = "", onDrain = () => {}, minBackoffMs = 500, maxBackoffMs = 15000 }) {
  const url = /\/mesh\/?$/.test(relayUrl) ? relayUrl : relayUrl.replace(/\/$/, "") + "/mesh";
  let ws = null, udp = null, wgPort = 0, stopped = false, backoff = minBackoffMs, retryT = null, mode = null;
  let kp = null, cfg = null, peerDump = [];
  const state = { linked: false, address: null, mode: null, path: null, connects: 0, rekeys: 0 };
  let resolveDone; const done = new Promise((r) => { resolveDone = r; });

  function writeStatus() { if (!statusFile) return; try { fs.writeFileSync(statusFile, JSON.stringify({ ...state, peers: peerDump }) + "\n", { mode: 0o644 }); } catch { /* */ } }

  async function bridgeStart() {
    if (udp) return;
    udp = dgram.createSocket("udp4");
    await new Promise((res, rej) => { udp.once("error", rej); udp.bind(0, "127.0.0.1", res); });
    udp.on("error", () => {});
    udp.on("message", (d, r) => { wgPort = r.port; if (ws && ws.readyState === 1 && ws.bufferedAmount < MAX_QUEUED) ws.send(d, { binary: true }); });
  }

  async function configure(j) {
    mode = await ensureIface(iface, run);
    await setPrivateKey(iface, kp.priv, run);
    await run("ip", ["addr", "replace", `${j.address}/16`, "dev", iface]);
    await run("ip", ["link", "set", iface, "mtu", String(j.mtu || MTU), "up"]);
    await bridgeStart();
    const bridgeEp = `127.0.0.1:${udp.address().port}`;
    const peerArgs = (ep) => ["set", iface, "peer", j.hub_pubkey, "allowed-ips", j.cidr || CIDR, "endpoint", ep, "persistent-keepalive", String(j.keepalive || KEEPALIVE)];
    state.path = "ws-bridge";
    if (j.direct) {                               // optional direct-UDP attempt; the bridge stays the fallback
      await run("wg", peerArgs(j.direct));
      const t0 = Date.now(); let ok = false;
      while (Date.now() - t0 < directWaitMs) { await new Promise((r) => setTimeout(r, 500)); if (await handshook(j)) { ok = true; break; } }
      if (ok) { state.path = "direct-udp"; return; }
      log("direct UDP failed, using the WebSocket bridge");
    }
    await run("wg", peerArgs(bridgeEp));
  }
  async function handshook(j) { try { const o = await run("wg", ["show", iface, "latest-handshakes"]); return o.split("\n").some((l) => l.startsWith(j.hub_pubkey) && Number(l.split("\t")[1]) > 0); } catch { return false; } }

  function connect() {
    if (stopped) return;
    kp = genKeypair();                            // fresh key per connection: reconnects/rotations always re-key
    const sock = new WS(url, { headers: { Authorization: "Bearer " + token }, maxPayload: 4096 });
    ws = sock;
    sock.on("open", () => { sock.send(JSON.stringify({ type: "join", pubkey: kp.pub })); });
    sock.on("message", async (data, isBinary) => {
      if (isBinary) { if (udp && wgPort) udp.send(data, wgPort, "127.0.0.1"); return; }
      let m; try { m = JSON.parse(data.toString()); } catch { return; }
      if (m.type === "joined") {
        try { cfg = m; await configure(m); } catch (e) { log("mesh configure failed: " + e.message); finish("configure_failed"); return; }
        state.linked = true; state.address = m.address; state.mode = mode; state.connects++; backoff = minBackoffMs; peerDump = m.peers || [];
        writeStatus(); log(`mesh joined as ${m.address} (${mode}, ${state.path})`);
      } else if (m.type === "peers") { peerDump = m.peers || []; writeStatus(); }
      else if (m.type === "drain") { log("drain requested"); onDrain(); leave("drained"); }
    });
    const lost = () => {
      if (ws !== sock) return; state.linked = false; writeStatus();
      if (stopped) return;
      retryT = setTimeout(connect, backoff); backoff = Math.min(backoff * 2, maxBackoffMs);
    };
    sock.on("close", lost); sock.on("error", () => {});
    sock.on("unexpected-response", (_rq, res) => { log(`mesh join refused (HTTP ${res.statusCode})`); if (res.statusCode === 401 || res.statusCode === 403 || res.statusCode === 410) finish("rejected"); });
  }

  /** Planned re-key without dropping the node: dial a second WS with a new key; the hub swaps the peer atomically. */
  async function rekey() {
    const oldWs = ws; clearTimeout(retryT);
    connect();                                    // sets ws to the new socket; the old socket's `lost` is ignored (ws !== sock)
    state.rekeys++;
    setTimeout(() => { try { oldWs && oldWs.close(1000, "rekeyed"); } catch { /* */ } }, 3000);
  }
  function leave(why) { try { ws && ws.readyState === 1 && ws.send(JSON.stringify({ type: "leave" })); } catch { /* */ } finish(why); }
  async function finish(why) {
    if (stopped) return; stopped = true; clearTimeout(retryT);
    state.linked = false; writeStatus();
    setTimeout(() => { try { ws && ws.close(1000, why); } catch { /* */ } try { udp && udp.close(); } catch { /* */ } }, 200);
    try { await run("ip", ["link", "del", iface]); } catch { /* */ }
    resolveDone(why);
  }
  connect();
  return { state, done, rekey, leave, stop: () => finish("stop"), peers: () => peerDump, config: () => cfg };
}

// ---------------------------------------------------------------- CLI:  node booster-mesh.mjs agent
//   env: VYOMI_RELAY_URL  VYOMI_MESH_TOKEN  WS_PKG  [VYOMI_MESH_IFACE=wgvyomi] [VYOMI_MESH_STATUS=/run/vyomi-mesh.json] [TTL_S]
if (process.argv[1] && process.argv[1].endsWith("booster-mesh.mjs") && process.argv[2] === "agent") {
  const { createRequire } = await import("node:module");
  const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
  const token = process.env.VYOMI_MESH_TOKEN || ""; delete process.env.VYOMI_MESH_TOKEN;
  if (!token || !process.env.VYOMI_RELAY_URL) { console.error("[mesh] VYOMI_RELAY_URL and VYOMI_MESH_TOKEN are required"); process.exit(2); }
  const agent = meshAgent({ relayUrl: process.env.VYOMI_RELAY_URL, token, WS, iface: process.env.VYOMI_MESH_IFACE || "wgvyomi",
                            statusFile: process.env.VYOMI_MESH_STATUS || "", directWaitMs: Number(process.env.VYOMI_MESH_DIRECT_WAIT_MS || 8000), log: (m) => console.log("[mesh] " + m) });
  for (const s of ["SIGTERM", "SIGINT"]) process.on(s, () => agent.leave("signal"));
  if (process.env.TTL_S) setTimeout(() => agent.leave("ttl"), Number(process.env.TTL_S) * 1000).unref();
  const why = await agent.done; console.log("[mesh] ended: " + why);
  setTimeout(() => process.exit(why === "rejected" ? 3 : 0), 400);
}
