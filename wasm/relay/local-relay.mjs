/* Vyomi-Nano local relay — the local, zero-cloud reverse-tunnel. The
 * install-once counterpart to the Cloudflare Worker (worker.js): same WS
 * protocol, same external HTTP surface, but everything stays on your machine
 * (faster, private, offline, no cloud caps). Installed via `brew install
 * vyomi-tunnel` and run as `vyomi-tunnel`.
 *
 *   external app (aws-cli/SDK) ──HTTP──▶ this relay (:RELAY_PORT)
 *                                          │  WebSocket (tab registered)
 *                                          ▼
 *                                      Nano tab (Pyodide + conformance cores)
 *
 * The tab connects out to ws://host:PORT/register and is held here; external
 * HTTP requests are forwarded over that WS and correlated by id. MULTIPLE tabs may
 * register (shared worker + standalone endpoint + extra views); we keep them all,
 * prune dead ones via ping/pong liveness, and forward to the freshest OPEN one —
 * their stores are synced (nano_registry + IndexedDB) so any live tab answers
 * consistently. The Cloudflare version keys this per-session via a Durable Object.
 *
 * A GET /health endpoint (CORS + Private-Network-Access enabled) lets the Nano
 * bundle AUTO-DETECT this relay from an HTTPS tab and prefer it over the cloud
 * tunnel — and detect it the moment it's installed/started, with no reload.
 *
 * Since 1.1.0 it also bridges TCP to Nano's in-browser VMs (EC2 / Compute Engine /
 * Azure VMs, wasm/vm): each VM worker connects to /vm, gets a host port in
 * VM_PORT_MIN..VM_PORT_MAX (default 22000-22999), and `ssh -p <port> user@127.0.0.1`
 * from this machine reaches the VM's sshd (see "In-browser VM TCP bridge" below).
 *
 * Run:  vyomi-tunnel                          (brew) — or: node local-relay.mjs
 *   env: RELAY_PORT (default 8090), RELAY_HOST (default 127.0.0.1; set 0.0.0.0 for LAN),
 *        VM_PORT_MIN / VM_PORT_MAX (ssh ports for in-browser VMs)
 */
import { egress } from "./egress.mjs";
import { createHub } from "./mesh-hub.mjs";
import { createSshHub, createSshTransport } from "./mesh-ssh.mjs";
import { createLazySshHub } from "./mesh-lazy-hub.mjs";
import { createRunnerLlmHub } from "./runner-llm-hub.mjs";
import { createMeshHub } from "./mesh-llm.mjs";
import { Readable } from "node:stream";
import http from "node:http";
import net from "node:net";
import crypto from "node:crypto";
import { createRequire } from "node:module";
// CommonJS require honors NODE_PATH (unlike ESM import), so the `ws` package
// resolves wherever it's installed (e.g. NODE_PATH=/tmp/node_modules for tests).
const { WebSocketServer, WebSocket } = createRequire(import.meta.url)(process.env.WS_PKG || "ws");

// Mesh / SSH client subcommands (no relay is started for these): login | config | connect <vm> | status
if (["login", "config", "connect", "status", "forward", "keep", "gh-login", "list", "ls", "help", "-h", "--help", "-help", "--version", "-v", "version"].includes(process.argv[2])) {
  const { main } = await import("./mesh-cli.mjs");
  process.exit(await main(process.argv.slice(2)));
}

if (process.argv[2] && !process.argv[2].startsWith("-")) { console.error(`vyomi-tunnel: unknown command "${process.argv[2]}". Run \`vyomi-tunnel help\`.`); process.exit(2); }

// The user's CLI (packaging/tunnel) serves nothing without a valid Vyomi key (Free is enough for Nano): set VYOMI_RELAY_AUTH=1. The copy that runs
// inside the appliance image (the Codespace's own bundled relay) does not use the user's key.
if (process.env.VYOMI_RELAY_AUTH === "1") { const { requireSession } = await import("./credentials.mjs"); const a = await requireSession();
  if (a.error) { console.error("vyomi-tunnel: " + a.error); process.exit(a.code === "NoCredentials" ? 2 : 1); } }

const VERSION = "1.2.0";
const PORT = Number(process.env.RELAY_PORT || 8090);
const HOST = process.env.RELAY_HOST || "127.0.0.1";   // loopback-only by default; 0.0.0.0 to expose on LAN
const pending = new Map();     // id -> {resolve}
// All registered tab sockets (shared worker, standalone endpoint, extra views).
// Previously a single `tab` var was OVERWRITTEN on each /register, so N contexts
// fought — requests routed to whoever registered last (often a mid-boot/empty or
// orphaned socket) and the losers churned with code-1006. Now we keep every tab,
// prune dead ones via ping/pong liveness, and forward to the freshest OPEN one.
// Store state is synced across contexts (nano_registry + IndexedDB), so ANY live
// tab answers consistently — no need to force-close others (which would war with
// their auto-reconnect).
const tabs = new Set();        // live registrant sockets, insertion-ordered
// Mesh link (outbound-dialed mesh <-> token-paired clients). Inert unless VYOMI_MESH_SESSION_KEY is set.
// VYOMI_MESH_CODESPACE=<name>: the link runs on THIS machine over the user's own `gh codespace ssh` session (mesh-ssh.mjs); the Codespace dials nothing.
const hub = process.env.VYOMI_MESH_CODESPACE
  ? createSshHub({ WebSocketServer, WebSocket, transport: createSshTransport({ codespace: process.env.VYOMI_MESH_CODESPACE, log: (m) => console.log("[relay] " + m) }), log: (m) => console.log("[relay] " + m) })
  : process.env.VYOMI_RELAY_AUTH === "1"
    // the user's own `vyomi-tunnel`: open the ssh link to their Mesh Codespace on first use (no hosted relay, no MESH_RELAY_URL)
    ? createLazySshHub({ WebSocketServer, WebSocket, openMesh: async (o) => (await import("./mesh-cli.mjs")).openMesh(o), log: (m) => console.log("[relay] " + m) })
    : createHub({ WebSocketServer, log: (m) => console.log("[relay] " + m) });
// Remote-LLM plane (spike, inert unless VYOMI_MESH_SESSION_KEY is set): a GitHub-Actions runner dials OUT to /llm-runner;
// the mesh reaches it with plain HTTP under /llm/*.
const llmHub = createRunnerLlmHub({ WebSocketServer, log: (m) => console.log("[relay] " + m) });
// LLM mesh (WireGuard star over WebSocket): only active when VYOMI_MESH=1 (the hub needs NET_ADMIN + wireguard-tools).
const meshHub = process.env.VYOMI_MESH === "1" ? createMeshHub({ WebSocketServer, log: (m) => console.log("[relay] " + m) }) : null;
function pickTab() {           // most-recently-registered OPEN socket, or null
  let chosen = null;
  for (const ws of tabs) if (ws.readyState === ws.OPEN) chosen = ws;
  return chosen;
}

// CORS + Private-Network-Access headers so an HTTPS Nano tab (a "public" origin)
// may probe/reach this loopback ("private") server. Chrome ≥104 gates public→
// private requests behind a PNA preflight; the Allow-Private-Network header +
// the OPTIONS short-circuit below satisfy it. Loopback is exempt from mixed
// content, so ws://127.0.0.1 + http://127.0.0.1 work from an https page.
function cors(res, status, extra) {
  res.writeHead(status, {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,PUT,POST,DELETE,HEAD,OPTIONS",
    "access-control-allow-headers": "*",
    "access-control-allow-private-network": "true",
    "access-control-max-age": "600",
    ...(extra || {}),
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  // Browser auto-detector: CORS/PNA preflight + the /health beacon. Kept ahead
  // of the proxy path so a real SDK request (which never sends these) is unaffected.
  if (req.method === "OPTIONS" && req.headers["access-control-request-method"]) {
    cors(res, 204); return res.end();
  }
  if (url.pathname === "/health") {
    let open = 0; for (const ws of tabs) if (ws.readyState === ws.OPEN) open++;
    cors(res, 200, { "content-type": "application/json" });
    return res.end(JSON.stringify({
      ok: true, relay: "vyomi-local", version: VERSION,
      tab: open > 0, tabs: open,
      // vm-tcp: this tunnel bridges host TCP ports to in-browser VMs (ssh to Nano EC2/GCE/Azure VMs).
      features: ["http", "vm-tcp", "vm-egress", "db-tcp", "amqp", ...(hub.enabled() ? ["mesh-link", "mesh-shell"] : [])],
      mesh_sessions: hub.enabled() ? hub.linked().length : undefined,
      mesh_streams: hub.enabled() ? hub.streams() : undefined,
      vms: [...vmHosts.values()].filter((v) => !v.db).map((v) => ({ vm: v.vm, port: v.port, host_port: v.hostPort })),
      dbs: [...vmHosts.values()].filter((v) => v.db).map((v) => ({ db: v.vm, engine: v.engine, host_port: v.hostPort })),
    }));
  }
  // Nano VM egress: allow-listed package-manager / toolchain fetches for the in-browser VMs (wasm/relay/egress.mjs).
  if (url.pathname === "/egress") {
    const body = [];
    req.on("data", (c) => body.push(c));
    req.on("end", async () => {
      try {
        const headers = new Headers(); for (const [k, v] of Object.entries(req.headers)) if (typeof v === "string") headers.set(k, v);
        const r = await egress(new Request("http://relay" + req.url, { method: req.method, headers,
          body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(body) }));
        res.writeHead(r.status, Object.fromEntries(r.headers));
        if (!r.body) return res.end();
        Readable.fromWeb(r.body).on("error", () => res.destroy()).pipe(res);
      } catch (e) { cors(res, 500, { "content-type": "text/plain" }); res.end("egress error: " + (e && e.message)); }
    });
    return;
  }
  // Collect the external request body, forward to the tab, await the response.
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    if (meshHub && meshHub.http(req, res)) return;               // LLM mesh peer table (/mesh-llm/_peers)
    if (llmHub.http(req, res, Buffer.concat(chunks))) return;   // remote-LLM plane (/llm/*)
    if (hub.http(req, res, Buffer.concat(chunks))) return;     // mesh plane (carries X-Vyomi-Session-Token)
    const tab = pickTab();
    if (!tab) {
      cors(res, 503, { "content-type": "text/plain" });
      return res.end("no Nano tab registered");
    }
    const query = Object.fromEntries(url.searchParams.entries());
    const id = crypto.randomUUID();
    const body = Buffer.concat(chunks);
    const timer = setTimeout(() => {
      if (pending.delete(id)) { cors(res, 504); res.end("tab timeout"); }
    }, 15000);
    pending.set(id, (resp) => {
      clearTimeout(timer);
      const buf = Buffer.from(resp.body || "", "base64");
      // Normalize to lowercase keys and drop any content-length from the handler —
      // the relay is authoritative for the actual byte count (a duplicate
      // Content-Length makes undici/fetch reject the response).
      const headers = { "access-control-allow-origin": "*" };
      let declared = null;
      for (const [k, v] of Object.entries(resp.headers || {})) {
        if (k.toLowerCase() === "content-length") { declared = v; continue; }
        headers[k.toLowerCase()] = v;
      }
      // A HEAD answer has no body but declares the size of what GET would return (S3's
      // object size): keep the handler's value there. Clients size downloads from it —
      // aws-cli 2.3x writes nothing for an object a HEAD says is 0 bytes.
      const head = req.method === "HEAD";
      headers["content-length"] = head && declared != null ? String(declared) : String(buf.length);
      res.writeHead(resp.status || 200, headers);
      res.end(head ? undefined : buf);
    });
    tab.send(JSON.stringify({
      id, method: req.method, path: url.pathname, query,
      headers: req.headers, body: body.toString("base64"),
    }));
  });
});

// Two WebSocket endpoints share the HTTP server, routed by path on upgrade:
//   /register  the Nano tab's HTTP-relay socket (above)
//   /vm        one socket per in-browser VM: the tunnel opens a host TCP port
//              for it and bridges each accepted connection to the guest port
const wss = new WebSocketServer({ noServer: true });
const vmWss = new WebSocketServer({ noServer: true });
server.on("upgrade", (req, socket, head) => {
  const p = new URL(req.url, "http://x").pathname;
  if (p === "/mesh") { hub.upgrade(req, socket, head); return; }
  if (p === "/shell") { hub.shellUpgrade(req, socket, head); return; }
  if (p === "/connect") { hub.connectUpgrade(req, socket, head); return; }
  if (p === "/mesh-llm" && meshHub) { meshHub.upgrade(req, socket, head); return; }
  if (p === "/llm-runner") { llmHub.upgrade(req, socket, head); return; }
  if (p.endsWith("/$servicebus/websocket")) { amqpWss.handleUpgrade(req, socket, head, (ws) => amqpAccept(ws, "ws")); return; }
  const target = p === "/register" ? wss : (p === "/vm" || p === "/db") ? vmWss : null;
  if (!target) { socket.destroy(); return; }
  target.handleUpgrade(req, socket, head, (ws) => target.emit("connection", ws, req));
});
wss.on("connection", (ws) => {
  ws.isAlive = true;
  tabs.add(ws);
  console.log(`[relay] tab registered (${tabs.size} active)`);
  ws.on("message", (data, isBinary) => {
    if (isBinary) {                       // [u32 sid][AMQP bytes] from the tab's engine -> the AMQP client
      const st = amqpStreams.get(data.readUInt32BE(0));
      if (st && st.tab === ws) st.write(data.subarray(4));
      return;
    }
    let msg; try { msg = JSON.parse(data.toString()); } catch { return; }
    if (msg.type === "pong") { ws.isAlive = true; return; }
    if (msg.type === "amqp-close") { const st = amqpStreams.get(msg.sid); if (st && st.tab === ws) st.end(); return; }
    const done = pending.get(msg.id);
    if (done) { pending.delete(msg.id); done(msg); }
  });
  ws.on("close", () => { tabs.delete(ws); for (const st of [...amqpStreams.values()]) if (st.tab === ws) st.end(); console.log(`[relay] tab gone (${tabs.size} active)`); });
  ws.on("error", () => { try { ws.terminate(); } catch (_) {} tabs.delete(ws); });
});

const PING_MS = 10000;
// ── AMQP 1.0 bridge (Azure Service Bus): native SDK -> relay -> in-browser engine ─────────────────────────────
// Clients speak AMQP either over raw TCP (AMQP_PORT, default 5672: `UseDevelopmentEmulator=true` / use_tls=False) or
// AMQP-over-WebSocket (ws://<relay>/$servicebus/websocket, subprotocol AMQPWSB10). Each connection becomes a numbered
// stream carried over the registered tab's socket (wasm/relay/amqp-bridge.js is the tab end):
//   relay -> tab : {type:"amqp-open", sid} | {type:"amqp-close", sid} | binary [u32 BE sid][AMQP bytes]
//   tab -> relay : binary [u32 BE sid][AMQP bytes] | {type:"amqp-close", sid}
const AMQP_PORT = Number(process.env.RELAY_AMQP_PORT ?? 5672);     // 0 = raw-TCP listener off
const amqpStreams = new Map();                                      // sid -> {tab, write(buf), end()}
const amqpWss = new WebSocketServer({ noServer: true, handleProtocols: (protos) => (protos.has("AMQPWSB10") ? "AMQPWSB10" : [...protos][0] || false) });
function amqpAttach(write, end, kind) {
  const tab = pickTab();
  if (!tab) { end(); return null; }
  const sid = sidSeq++;
  const st = { tab, write, end: () => { if (amqpStreams.delete(sid)) end(); } };
  amqpStreams.set(sid, st);
  tab.send(JSON.stringify({ type: "amqp-open", sid }));
  console.log(`[relay] amqp stream ${sid} (${kind})`);
  return { sid, toTab: (buf) => { const f = Buffer.allocUnsafe(4 + buf.length); f.writeUInt32BE(sid, 0); buf.copy(f, 4); try { tab.send(f); } catch (_) {} },
           closed: () => { if (amqpStreams.delete(sid)) { try { tab.send(JSON.stringify({ type: "amqp-close", sid })); } catch (_) {} } } };
}
function amqpAccept(ws, kind) {
  const h = amqpAttach((b) => { try { ws.send(b); } catch (_) {} }, () => { try { ws.close(); } catch (_) {} }, kind);
  if (!h) return;
  ws.on("message", (d) => h.toTab(Buffer.isBuffer(d) ? d : Buffer.from(d)));
  ws.on("close", h.closed); ws.on("error", h.closed);
}
if (AMQP_PORT) {
  net.createServer((sock) => {
    sock.setNoDelay(true);
    const h = amqpAttach((b) => { try { sock.write(b); } catch (_) {} }, () => sock.end(), "tcp");
    if (!h) return;
    sock.on("data", (d) => h.toTab(d));
    sock.on("close", h.closed); sock.on("error", h.closed);
  }).on("error", (e) => console.log(`[relay] AMQP :${AMQP_PORT} listener off (${e.code || e.message})`))
    .listen(AMQP_PORT, HOST, () => console.log(`  AMQP  ->  Service Bus (azure-servicebus / @azure/service-bus) on ${HOST}:${AMQP_PORT}  (+ ws://${HOST}:${PORT}/$servicebus/websocket)`));
}
// ── In-browser VM TCP bridge (ssh to Nano EC2 / Compute Engine / Azure VMs) ──
// A VM worker connects to /vm?vm=<id>&port=22&prefer=<host port>. We listen on
// HOST:<host port> (the preferred one if free, else the next free in VM_PORT_MIN..MAX)
// and tell it {type:"vm-listening", host_port}. Each accepted TCP connection becomes a
// stream: {type:"tcp-open", sid, port} → the VM dials its guest port and answers
// {type:"tcp-opened", sid}; bytes flow as binary frames [u32 sid][payload] both ways;
// either side ends it with {type:"tcp-close", sid}.
const VM_PORT_MIN = Number(process.env.VM_PORT_MIN || 22000);
const VM_PORT_MAX = Number(process.env.VM_PORT_MAX || 22999);
const vmHosts = new Map();     // vm id -> {vm, port, hostPort, ws, server, streams}
let sidSeq = 1;
// Databases (Nano RDS / Cloud SQL / Azure SQL ... instances) bridge the same way on /db: the standard engine port
// (5432 / 3306 / 1433) is tried first so `psql -h 127.0.0.1` and unmodified apps work with defaults, then DB_PORT_MIN..MAX.
const DB_PORT_MIN = Number(process.env.DB_PORT_MIN || 25000);
const DB_PORT_MAX = Number(process.env.DB_PORT_MAX || 25999);
function listenFree(start, min = VM_PORT_MIN, max = VM_PORT_MAX) {
  return new Promise((resolve, reject) => {
    const span = max - min + 1;
    const first = start > 0 ? start : min;
    let tries = 0;
    const attempt = (p) => {
      const srv = net.createServer();
      srv.once("error", () => {
        if (++tries > span) return reject(new Error("no free port"));
        const nxt = p >= min && p < max ? p + 1 : min;
        attempt(nxt);
      });
      srv.listen(p, HOST, () => resolve(srv));
    };
    attempt(first);
  });
}
vmWss.on("connection", async (ws, req) => {
  const u0 = new URL(req.url, "http://x"), q = u0.searchParams;
  const isDb = u0.pathname === "/db", engine = isDb ? String(q.get("engine") || "postgres").slice(0, 20) : "";
  const vm = (isDb ? "db:" : "") + (q.get(isDb ? "db" : "vm") || ""), guestPort = Number(q.get("port") || 22);
  if (!/^(db:)?[A-Za-z0-9._-]{1,80}$/.test(vm)) { ws.close(1008, "bad id"); return; }
  const old = vmHosts.get(vm);
  // A VM that reconnects (worker restart, tab reload) keeps its host port.
  const prefer = old ? old.hostPort : Number(q.get("prefer") || 0);
  if (old) { try { old.server.close(); } catch (_) {} try { old.ws.terminate(); } catch (_) {} vmHosts.delete(vm); }
  let srv;
  try { srv = isDb ? await listenFree(prefer, DB_PORT_MIN, DB_PORT_MAX) : await listenFree(prefer); } catch (e) { ws.close(1013, String(e.message)); return; }
  const hostPort = srv.address().port;
  const entry = { vm, port: guestPort, hostPort, ws, server: srv, streams: new Map(), db: isDb, engine };
  vmHosts.set(vm, entry);
  ws.isAlive = true;
  console.log(`[relay] ${isDb ? "db" : "vm"} ${vm} :${guestPort} ⇄ ${HOST}:${hostPort}`);
  ws.send(JSON.stringify({ type: "vm-listening", vm, port: guestPort, host_port: hostPort }));
  srv.on("connection", (sock) => {
    const sid = sidSeq++;
    const st = { sock, open: false, queue: [] };
    entry.streams.set(sid, st);
    sock.setNoDelay(true);
    sock.on("data", (d) => {
      const frame = Buffer.allocUnsafe(4 + d.length); frame.writeUInt32BE(sid, 0); d.copy(frame, 4);
      if (st.open) ws.send(frame); else st.queue.push(frame);
    });
    const end = () => {
      if (!entry.streams.delete(sid)) return;
      try { ws.send(JSON.stringify({ type: "tcp-close", sid })); } catch (_) {}
    };
    sock.on("close", end); sock.on("error", end);
    ws.send(JSON.stringify({ type: "tcp-open", sid, port: guestPort }));
    // A VM that never answers (not running / port closed) must not hang the client.
    st.timer = setTimeout(() => { if (!st.open) { entry.streams.delete(sid); sock.destroy(); } }, 20000);
  });
  ws.on("message", (data, isBinary) => {
    if (isBinary) {
      const sid = data.readUInt32BE(0); const st = entry.streams.get(sid);
      if (st) st.sock.write(data.subarray(4));
      return;
    }
    let m; try { m = JSON.parse(data.toString()); } catch { return; }
    if (m.type === "pong") { ws.isAlive = true; return; }
    const st = entry.streams.get(m.sid);
    if (!st) return;
    if (m.type === "tcp-opened") {
      st.open = true; clearTimeout(st.timer);
      for (const f of st.queue) ws.send(f); st.queue = [];
    } else if (m.type === "tcp-close") {
      entry.streams.delete(m.sid); clearTimeout(st.timer); st.sock.end();
    }
  });
  const gone = () => {
    for (const st of entry.streams.values()) { try { st.sock.destroy(); } catch (_) {} }
    entry.streams.clear();
    if (vmHosts.get(vm) === entry) {
      vmHosts.delete(vm);
      // keep the port briefly reserved? no: close it so a stopped VM refuses ssh
      try { srv.close(); } catch (_) {}
      console.log(`[relay] vm ${vm} gone (port ${hostPort} closed)`);
    }
  };
  ws.on("close", gone); ws.on("error", () => { try { ws.terminate(); } catch (_) {} gone(); });
});
const vmLiveness = setInterval(() => {
  for (const e of vmHosts.values()) {
    const ws = e.ws;
    if (ws.isAlive === false) { try { ws.terminate(); } catch (_) {} continue; }
    ws.isAlive = false;
    try { ws.send(JSON.stringify({ type: "ping" })); } catch (_) {}
  }
}, PING_MS);

// Liveness: ping every tab on an interval and drop any that didn't pong since the
// last tick (dead/zombie sockets). The tab side already answers {type:"ping"} with
// a pong, so this is protocol-compatible with existing endpoints. This is what
// clears the orphaned sockets that used to linger and misroute requests.
const liveness = setInterval(() => {
  for (const ws of tabs) {
    if (ws.readyState !== ws.OPEN) { tabs.delete(ws); continue; }
    if (ws.isAlive === false) { try { ws.terminate(); } catch (_) {} tabs.delete(ws); continue; }
    ws.isAlive = false;
    try { ws.send(JSON.stringify({ type: "ping" })); } catch (_) {}
  }
}, PING_MS);
wss.on("close", () => { clearInterval(liveness); clearInterval(vmLiveness); });

server.listen(PORT, HOST, () => {
  const shown = HOST === "0.0.0.0" ? "<this-machine-ip>" : HOST;
  console.log(`Vyomi-Nano local tunnel v${VERSION}`);
  console.log(`  health   http://${shown}:${PORT}/health`);
  console.log(`  tab regs ws://${shown}:${PORT}/register   (the Nano tab auto-detects this)`);
  console.log(`  apps  →  point --endpoint-url / SDK endpoint at http://${shown}:${PORT}`);
  console.log(`  VMs   →  ssh to in-browser instances on ${shown}:${VM_PORT_MIN}-${VM_PORT_MAX} (shown in each Connect tab)`);
});
