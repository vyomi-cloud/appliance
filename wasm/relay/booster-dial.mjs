/* Booster-side connector: dials OUT over WSS to the relay with the signed session token (no inbound port on the Codespace)
 * and serves the relay's forwarded requests from the local simulator.
 *
 *   env: VYOMI_RELAY_URL              wss://relay.example/booster   (required; /booster appended if missing)
 *        VYOMI_BOOSTER_SESSION_TOKEN  the portal-signed session token (required)
 *        VYOMI_BOOSTER_LOCAL_URL      the local simulator (default http://127.0.0.1:9000)
 *        WS_PKG                       path to the `ws` package (default "ws")
 * Streams: the relay multiplexes interactive shells over this same link ({type:"stream",op,sid}, see booster-hub.mjs). Each
 * stream is bridged to the LOCAL simulator's  ws://.../booster/shell?cloud=&ref=  (which does the container check and owns the PTY),
 * presenting the same session token. This agent never names a container and holds no Docker access.
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

const MAX_STREAMS = Number(process.env.VYOMI_SHELL_MAX_PER_SESSION || 4);
const HIGH = 1024 * 1024, CHUNK = 48 * 1024, MAX_IN = 64 * 1024;

function wsBase(base) { const u = new URL(base); u.protocol = u.protocol === "https:" ? "wss:" : "ws:"; u.pathname = ""; u.search = ""; return u.toString().replace(/\/+$/, ""); }

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
    state.linked = false; closeStreams(); resolveDone(why);
  };
  if (Number.isFinite(end)) endTimer = setTimeout(() => finish("session_end"), Math.max(0, end * 1000 - Date.now()));
  const streams = new Map();                       // sid -> local WebSocket to the simulator's PTY endpoint
  const closeStreams = () => { for (const [sid, lw] of [...streams]) { streams.delete(sid); try { lw.close(1001, "link closed"); } catch { /* */ } } };
  const connect = () => {
    if (stopped) return;
    if (Number.isFinite(end) && Date.now() >= end * 1000) return finish("session_end");
    state.connects++;
    ws = new WS(url, { headers: { authorization: `Bearer ${token}` } });
    ws.on("open", () => { backoff = minBackoffMs; });
    const out = (o) => { try { if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(o)); } catch { /* */ } };
    const onStream = (m) => {
      const sid = String(m.sid || ""); if (!sid) return;
      const lw = streams.get(sid);
      if (m.op === "open") {
        if (lw) return;
        if (streams.size >= MAX_STREAMS) return out({ type: "stream", op: "error", sid, code: "TooManyShells", message: "too many shells" });
        const cloud = String(m.cloud || ""), ref = String(m.ref || "");
        if (!/^(aws|gcp|azure)$/.test(cloud) || !ref || ref.length > 200) return out({ type: "stream", op: "error", sid, code: "BadRequest", message: "cloud/ref" });
        const q = new URLSearchParams({ cloud, ref, cols: String(m.cols ?? ""), rows: String(m.rows ?? "") });
        const l = new WS(`${wsBase(localUrl)}/booster/shell?${q}`, { headers: { "x-vyomi-session-token": token }, maxPayload: 1024 * 1024 });
        streams.set(sid, l);
        let drain = null;
        l.on("message", (d, isBin) => {
          if (isBin) {
            for (let i = 0; i < d.length; i += CHUNK) out({ type: "stream", op: "data", sid, d: Buffer.from(d.subarray(i, i + CHUNK)).toString("base64") });
            if (ws.bufferedAmount > HIGH && !drain) {          // the relay link is slow: stop reading the PTY until it drains
              l.pause(); drain = setInterval(() => { if (ws.bufferedAmount < HIGH / 4 || ws.readyState !== ws.OPEN) { clearInterval(drain); drain = null; l.resume(); } }, 50);
            }
            return;
          }
          let c; try { c = JSON.parse(d.toString()); } catch { return; }
          if (c.t === "opened") out({ type: "stream", op: "opened", sid, container: c.container });
          else if (c.t === "error") { streams.delete(sid); out({ type: "stream", op: "error", sid, code: c.code, message: c.message }); try { l.close(); } catch { /* */ } }
        });
        l.on("close", (code) => { clearInterval(drain); if (streams.get(sid) === l) { streams.delete(sid); out({ type: "stream", op: "close", sid, reason: code === 1000 ? "exit" : "closed" }); } });
        l.on("unexpected-response", (_q, res) => { if (streams.get(sid) === l) { streams.delete(sid); out({ type: "stream", op: "error", sid, code: "LocalRefused", message: "simulator refused the shell: HTTP " + res.statusCode }); } });
        l.on("error", () => { /* 'close' follows */ });
      } else if (!lw) return;
      else if (m.op === "data") { const b = Buffer.from(String(m.d || ""), "base64"); if (b.length <= MAX_IN && lw.readyState === lw.OPEN) lw.send(b); }
      else if (m.op === "resize") { if (lw.readyState === lw.OPEN) lw.send(JSON.stringify({ t: "resize", cols: m.cols, rows: m.rows })); }
      else if (m.op === "pause") lw.pause();
      else if (m.op === "resume") lw.resume();
      else if (m.op === "close") { streams.delete(sid); try { lw.close(1000, "closed by tab"); } catch { /* */ } }
    };
    ws.on("message", async (data) => {
      let m; try { m = JSON.parse(data.toString()); } catch { return; }
      if (m.type === "stream") { onStream(m); return; }
      if (m.type === "linked") { state.linked = true; log("linked to relay"); return; }
      if (m.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
      if (m.id && m.method) ws.send(JSON.stringify(await localRequest(localUrl, token, m)));
    });
    const retry = () => {
      state.linked = false; closeStreams();
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
