/* Vyomi-Nano local relay — the dev/validation stand-in for the Cloudflare
 * reverse-tunnel (worker.js). Same WS protocol; same external HTTP surface.
 *
 *   external app (aws-cli/SDK) ──HTTP──▶ this relay (:RELAY_PORT)
 *                                          │  WebSocket (tab registered)
 *                                          ▼
 *                                      Nano tab (Pyodide + s3_object_core)
 *
 * The tab connects out to ws://host:PORT/register and is held here; external
 * HTTP requests are forwarded over that WS and correlated by id. Single active
 * tab (MVP) — the Cloudflare version keys this per-session via a Durable Object.
 *
 * Run:  node wasm/relay/local-relay.mjs        (needs the `ws` package)
 *   env: RELAY_PORT (default 8090)
 */
import http from "node:http";
import crypto from "node:crypto";
import { createRequire } from "node:module";
// CommonJS require honors NODE_PATH (unlike ESM import), so the `ws` package
// resolves wherever it's installed (e.g. NODE_PATH=/tmp/node_modules for tests).
const { WebSocketServer } = createRequire(import.meta.url)(process.env.WS_PKG || "ws");

const PORT = Number(process.env.RELAY_PORT || 8090);
const pending = new Map();     // id -> {resolve}
let tab = null;                // the single registered tab socket (MVP)

const server = http.createServer((req, res) => {
  // Collect the external request body, forward to the tab, await the response.
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    if (!tab || tab.readyState !== tab.OPEN) {
      res.writeHead(503, { "content-type": "text/plain" });
      return res.end("no Nano tab registered");
    }
    const url = new URL(req.url, "http://x");
    const query = Object.fromEntries(url.searchParams.entries());
    const id = crypto.randomUUID();
    const body = Buffer.concat(chunks);
    const timer = setTimeout(() => {
      if (pending.delete(id)) { res.writeHead(504); res.end("tab timeout"); }
    }, 15000);
    pending.set(id, (resp) => {
      clearTimeout(timer);
      const buf = Buffer.from(resp.body || "", "base64");
      // Normalize to lowercase keys and drop any content-length from the handler —
      // the relay is authoritative for the actual byte count (a duplicate
      // Content-Length makes undici/fetch reject the response).
      const headers = {};
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
  tab = ws;
  console.log("[relay] tab registered");
  ws.on("message", (data) => {
    let msg; try { msg = JSON.parse(data.toString()); } catch { return; }
    if (msg.type === "pong") return;
    const done = pending.get(msg.id);
    if (done) { pending.delete(msg.id); done(msg); }
  });
  ws.on("close", () => { if (tab === ws) tab = null; console.log("[relay] tab gone"); });
});

server.listen(PORT, () => console.log(`[relay] http+ws on :${PORT}  (tab → ws://localhost:${PORT}/register)`));
