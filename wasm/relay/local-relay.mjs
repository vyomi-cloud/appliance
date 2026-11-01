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
import http from "node:http";
import net from "node:net";
import crypto from "node:crypto";
import { createRequire } from "node:module";
// CommonJS require honors NODE_PATH (unlike ESM import), so the `ws` package
// resolves wherever it's installed (e.g. NODE_PATH=/tmp/node_modules for tests).
const { WebSocketServer } = createRequire(import.meta.url)(process.env.WS_PKG || "ws");

const VERSION = "1.1.0";
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
      features: ["http", "vm-tcp"],
      vms: [...vmHosts.values()].map((v) => ({ vm: v.vm, port: v.port, host_port: v.hostPort })),
    }));
  }
  // Collect the external request body, forward to the tab, await the response.
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
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
  const target = p === "/register" ? wss : p === "/vm" ? vmWss : null;
  if (!target) { socket.destroy(); return; }
  target.handleUpgrade(req, socket, head, (ws) => target.emit("connection", ws, req));
});
wss.on("connection", (ws) => {
  ws.isAlive = true;
  tabs.add(ws);
  console.log(`[relay] tab registered (${tabs.size} active)`);
  ws.on("message", (data) => {
    let msg; try { msg = JSON.parse(data.toString()); } catch { return; }
    if (msg.type === "pong") { ws.isAlive = true; return; }
    const done = pending.get(msg.id);
    if (done) { pending.delete(msg.id); done(msg); }
  });
  ws.on("close", () => { tabs.delete(ws); console.log(`[relay] tab gone (${tabs.size} active)`); });
  ws.on("error", () => { try { ws.terminate(); } catch (_) {} tabs.delete(ws); });
});

const PING_MS = 10000;
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
function listenFree(start) {
  return new Promise((resolve, reject) => {
    const span = VM_PORT_MAX - VM_PORT_MIN + 1;
    const first = start >= VM_PORT_MIN && start <= VM_PORT_MAX ? start : VM_PORT_MIN;
    let tries = 0;
    const attempt = (p) => {
      const srv = net.createServer();
      srv.once("error", () => {
        if (++tries >= span) return reject(new Error("no free VM port"));
        attempt(VM_PORT_MIN + ((p - VM_PORT_MIN + 1) % span));
      });
      srv.listen(p, HOST, () => resolve(srv));
    };
    attempt(first);
  });
}
vmWss.on("connection", async (ws, req) => {
  const q = new URL(req.url, "http://x").searchParams;
  const vm = q.get("vm") || "", guestPort = Number(q.get("port") || 22);
  if (!/^[A-Za-z0-9._-]{1,80}$/.test(vm)) { ws.close(1008, "bad vm id"); return; }
  const old = vmHosts.get(vm);
  // A VM that reconnects (worker restart, tab reload) keeps its host port.
  const prefer = old ? old.hostPort : Number(q.get("prefer") || 0);
  if (old) { try { old.server.close(); } catch (_) {} try { old.ws.terminate(); } catch (_) {} vmHosts.delete(vm); }
  let srv;
  try { srv = await listenFree(prefer); } catch (e) { ws.close(1013, String(e.message)); return; }
  const hostPort = srv.address().port;
  const entry = { vm, port: guestPort, hostPort, ws, server: srv, streams: new Map() };
  vmHosts.set(vm, entry);
  ws.isAlive = true;
  console.log(`[relay] vm ${vm} :${guestPort} ⇄ ${HOST}:${hostPort}`);
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
