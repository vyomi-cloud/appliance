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
 * Run:  vyomi-tunnel                          (brew) — or: node local-relay.mjs
 *   env: RELAY_PORT (default 8090), RELAY_HOST (default 127.0.0.1; set 0.0.0.0 for LAN)
 */
import http from "node:http";
import crypto from "node:crypto";
import { createRequire } from "node:module";
// CommonJS require honors NODE_PATH (unlike ESM import), so the `ws` package
// resolves wherever it's installed (e.g. NODE_PATH=/tmp/node_modules for tests).
const { WebSocketServer } = createRequire(import.meta.url)(process.env.WS_PKG || "ws");

const VERSION = "1.0.0";
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
      for (const [k, v] of Object.entries(resp.headers || {})) {
        if (k.toLowerCase() === "content-length") continue;
        headers[k.toLowerCase()] = v;
      }
      headers["content-length"] = String(buf.length);
      res.writeHead(resp.status || 200, headers);
      res.end(buf);
    });
    tab.send(JSON.stringify({
      id, method: req.method, path: url.pathname, query,
      headers: req.headers, body: body.toString("base64"),
    }));
  });
});

const wss = new WebSocketServer({ server, path: "/register" });
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

// Liveness: ping every tab on an interval and drop any that didn't pong since the
// last tick (dead/zombie sockets). The tab side already answers {type:"ping"} with
// a pong, so this is protocol-compatible with existing endpoints. This is what
// clears the orphaned sockets that used to linger and misroute requests.
const PING_MS = 10000;
const liveness = setInterval(() => {
  for (const ws of tabs) {
    if (ws.readyState !== ws.OPEN) { tabs.delete(ws); continue; }
    if (ws.isAlive === false) { try { ws.terminate(); } catch (_) {} tabs.delete(ws); continue; }
    ws.isAlive = false;
    try { ws.send(JSON.stringify({ type: "ping" })); } catch (_) {}
  }
}, PING_MS);
wss.on("close", () => clearInterval(liveness));

server.listen(PORT, HOST, () => {
  const shown = HOST === "0.0.0.0" ? "<this-machine-ip>" : HOST;
  console.log(`Vyomi-Nano local tunnel v${VERSION}`);
  console.log(`  health   http://${shown}:${PORT}/health`);
  console.log(`  tab regs ws://${shown}:${PORT}/register   (the Nano tab auto-detects this)`);
  console.log(`  apps  →  point --endpoint-url / SDK endpoint at http://${shown}:${PORT}`);
});
