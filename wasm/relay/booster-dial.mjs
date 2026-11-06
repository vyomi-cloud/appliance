/* Booster-side connector: dials OUT over WSS to the relay with the signed session token (no inbound port on the Codespace)
 * and serves the relay's forwarded requests from the local simulator.
 *
 *   env: VYOMI_RELAY_URL              wss://relay.example/booster   (required; /booster appended if missing)
 *        VYOMI_BOOSTER_SESSION_TOKEN  the portal-signed session token (required)
 *        VYOMI_BOOSTER_LOCAL_URL      the local simulator (default http://127.0.0.1:9000)
 *        WS_PKG                       path to the `ws` package (default "ws")
 * The process exits 0 at the token's session_end (the relay closes its side at the same moment). It reconnects with
 * backoff until then, and never after.
 */
import http from "node:http";
import https from "node:https";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { peekSessionEnd } from "./booster-session.mjs";

const HOP = new Set(["host", "connection", "content-length", "transfer-encoding", "upgrade", "keep-alive"]);

function localRequest(base, token, m) {
  return new Promise((resolve) => {
    const u = new URL(m.path + (m.query && Object.keys(m.query).length ? "?" + new URLSearchParams(m.query) : ""), base);
    const headers = {};
    for (const [k, v] of Object.entries(m.headers || {})) if (!HOP.has(k.toLowerCase())) headers[k] = v;
    headers["x-vyomi-session-token"] = token;           // the simulator re-verifies the SAME token (core/booster_session.py)
    const body = Buffer.from(m.body || "", "base64");
    const lib = u.protocol === "https:" ? https : http;
    const rq = lib.request(u, { method: m.method, headers: { ...headers, "content-length": body.length, host: u.host } }, (r) => {
      const chunks = []; r.on("data", (c) => chunks.push(c));
      r.on("end", () => resolve({ id: m.id, status: r.statusCode, headers: r.headers, body: Buffer.concat(chunks).toString("base64") }));
    });
    rq.on("error", (e) => resolve({ id: m.id, status: 502, headers: { "content-type": "text/plain" }, body: Buffer.from("local simulator unreachable: " + e.message).toString("base64") }));
    rq.end(body);
  });
}

/** Start the link. Returns {stop(), done: Promise<"session_end"|"stopped">, state}. */
export function dial({ relayUrl, token, localUrl = "http://127.0.0.1:9000", WS, log = () => {}, minBackoffMs = 500, maxBackoffMs = 15000 }) {
  const end = peekSessionEnd(token);
  let ws = null, stopped = false, resolveDone, timer = null, endTimer = null, backoff = minBackoffMs;
  const state = { linked: false, connects: 0 };
  const done = new Promise((r) => { resolveDone = r; });
  const url = /\/booster\/?$/.test(relayUrl) ? relayUrl : relayUrl.replace(/\/$/, "") + "/booster";
  const finish = (why) => {
    if (stopped) return; stopped = true; clearTimeout(timer); clearTimeout(endTimer);
    try { ws && ws.close(1000, why); } catch { /* */ }
    state.linked = false; resolveDone(why);
  };
  if (Number.isFinite(end)) endTimer = setTimeout(() => finish("session_end"), Math.max(0, end * 1000 - Date.now()));
  const connect = () => {
    if (stopped) return;
    if (Number.isFinite(end) && Date.now() >= end * 1000) return finish("session_end");
    state.connects++;
    ws = new WS(url, { headers: { authorization: `Bearer ${token}` } });
    ws.on("open", () => { backoff = minBackoffMs; });
    ws.on("message", async (data) => {
      let m; try { m = JSON.parse(data.toString()); } catch { return; }
      if (m.type === "linked") { state.linked = true; log("linked to relay"); return; }
      if (m.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
      if (m.id && m.method) ws.send(JSON.stringify(await localRequest(localUrl, token, m)));
    });
    const retry = () => {
      state.linked = false;
      if (stopped) return;
      timer = setTimeout(connect, backoff); backoff = Math.min(maxBackoffMs, backoff * 2);
    };
    ws.on("close", retry);
    ws.on("error", () => { /* 'close' follows */ });
    ws.on("unexpected-response", (_req, res) => {            // relay refused the token / origin: do not hammer it forever
      log(`relay refused the dial: HTTP ${res.statusCode}`);
      if ([401, 403, 410].includes(res.statusCode)) finish(`refused-${res.statusCode}`);
    });
  };
  connect();
  return { stop: () => finish("stopped"), done, state };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const relayUrl = process.env.VYOMI_RELAY_URL, token = process.env.VYOMI_BOOSTER_SESSION_TOKEN;
  if (!relayUrl || !token) { console.error("booster-dial: VYOMI_RELAY_URL and VYOMI_BOOSTER_SESSION_TOKEN are required"); process.exit(2); }
  const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
  const link = dial({ relayUrl, token, localUrl: process.env.VYOMI_BOOSTER_LOCAL_URL || "http://127.0.0.1:9000", WS,
                      log: (m) => console.log("[booster-dial] " + m) });
  link.done.then((why) => { console.log("[booster-dial] ended: " + why); process.exit(why === "session_end" || why === "stopped" ? 0 : 1); });
}
