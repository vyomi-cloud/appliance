/* Runner-side connector (runs ON the GitHub-Actions runner). Dials OUT to the relay's /llm-runner with the runner-role
 * session token, serves forwarded requests from the local llama-server(s), streams responses back, heartbeats, and exits
 * at min(token session_end, now + TTL_S) or on SIGTERM/SIGINT (workflow cancel). Prints NOTHING derived from the token
 * or from request bodies. The token is read from the environment (never argv).
 *
 *   env: VYOMI_RELAY_URL (wss://relay/llm-runner)  VYOMI_RUNNER_TOKEN  CHAT_URL (default http://127.0.0.1:8080)
 *        EMBED_URL (default http://127.0.0.1:8081)  TTL_S (default 21000 = 5h50m, hard max)  WS_PKG
 */
import http from "node:http";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const HOP = new Set(["host", "connection", "content-length", "transfer-encoding", "upgrade", "keep-alive"]);
const MAX_TTL_S = 21000;      // 5h50m: rotation re-dispatches at 5h30m, the old runner overlaps ~20 min and drains; job cap is 6 h
const peekEnd = (t) => { try { return Number(JSON.parse(Buffer.from(String(t).split(".")[1], "base64url").toString()).session_end); } catch { return NaN; } };

export function runnerDial({ relayUrl, token, chatUrl = "http://127.0.0.1:8080", embedUrl = "http://127.0.0.1:8081", ttlS = MAX_TTL_S,
                             WS, log = () => {}, hbMs = 15000, minBackoffMs = 500, maxBackoffMs = 15000, healthMs = 1000 }) {
  const ttl = Math.min(Number(ttlS) || MAX_TTL_S, MAX_TTL_S);
  const sessEnd = peekEnd(token);
  const deadline = Math.min(Date.now() + ttl * 1000, Number.isFinite(sessEnd) ? sessEnd * 1000 : Infinity);
  let ws = null, draining = false, stopped = false, resolveDone, backoff = minBackoffMs, retryT = null, hbT = null, readyT = null, endT = null;
  const state = { linked: false, ready: false, connects: 0, served: 0 };
  const inflight = new Map();     // id -> http.ClientRequest
  const done = new Promise((r) => { resolveDone = r; });
  const url = /\/llm-runner\/?$/.test(relayUrl) ? relayUrl : relayUrl.replace(/\/$/, "") + "/llm-runner";
  const finish = (why) => {
    if (stopped) return; stopped = true;
    clearTimeout(retryT); clearTimeout(endT); clearInterval(hbT); clearInterval(readyT);
    for (const rq of inflight.values()) { try { rq.destroy(); } catch { /* */ } }
    try { ws && ws.close(1000, why); } catch { /* */ }
    state.linked = state.ready = false; resolveDone(why);
  };
  endT = setTimeout(() => finish("ttl"), Math.max(0, deadline - Date.now()));
  const send = (o) => { try { if (ws && ws.readyState === ws.OPEN) ws.send(JSON.stringify(o)); } catch { /* */ } };
  const healthy = () => new Promise((resolve) => {
    const rq = http.get(chatUrl + "/health", { timeout: 2000 }, (r) => { r.resume(); resolve(r.statusCode === 200); });
    rq.on("error", () => resolve(false)); rq.on("timeout", () => { rq.destroy(); resolve(false); });
  });

  function serve(m) {
    const isEmbed = m.path.split("?")[0].replace(/\/$/, "") === "/v1/embeddings";
    const base = new URL(m.path, isEmbed ? embedUrl : chatUrl);
    let body = Buffer.from(m.body || "", "base64");
    if (isEmbed && body.length && embedUrl !== chatUrl) { try { const j = JSON.parse(body); j.model = "embed"; body = Buffer.from(JSON.stringify(j)); } catch { /* */ } }
    const headers = {}; for (const [k, v] of Object.entries(m.headers || {})) if (!HOP.has(k.toLowerCase())) headers[k] = v;
    const rq = http.request(base, { method: m.method, headers: { ...headers, "content-length": body.length } }, (r) => {
      const h = {}; for (const [k, v] of Object.entries(r.headers)) if (!HOP.has(k)) h[k] = v;
      send({ id: m.id, type: "head", status: r.statusCode, headers: h });
      r.on("data", (c) => send({ id: m.id, type: "chunk", body: c.toString("base64") }));
      r.on("end", () => { inflight.delete(m.id); state.served++; send({ id: m.id, type: "end" }); });
      r.on("error", () => { inflight.delete(m.id); send({ id: m.id, type: "end" }); });
    });
    rq.on("error", () => {
      inflight.delete(m.id);
      send({ id: m.id, type: "head", status: 502, headers: { "content-type": "application/json" } });
      send({ id: m.id, type: "chunk", body: Buffer.from('{"error":{"message":"local llama-server unreachable","type":"unavailable"}}').toString("base64") });
      send({ id: m.id, type: "end" });
    });
    inflight.set(m.id, rq);
    rq.end(body);
  }

  const connect = () => {
    if (stopped) return;
    if (Date.now() >= deadline) return finish("ttl");
    state.connects++;
    ws = new WS(url, { headers: { authorization: `Bearer ${token}` } });
    ws.on("open", () => { backoff = minBackoffMs; });
    ws.on("message", (data) => {
      let m; try { m = JSON.parse(data.toString()); } catch { return; }
      if (m.type === "linked") {
        state.linked = true; log("linked to relay");
        clearInterval(hbT); hbT = setInterval(() => send({ type: "hb", busy: inflight.size }), hbMs);
        clearInterval(readyT);
        readyT = setInterval(async () => { if (await healthy()) { clearInterval(readyT); state.ready = true; send({ type: "ready" }); log("model ready"); } }, healthMs);
        return;
      }
      if (m.type === "drain") {           // rotation: the relay moved new requests to my successor; finish in-flight ones, then leave
        draining = true; clearInterval(readyT);
        const t = setInterval(() => { if (inflight.size === 0) { clearInterval(t); finish("drained"); } }, 200);
        return;
      }
      if (m.type === "cancel") { const rq = inflight.get(m.id); if (rq) { rq.destroy(); inflight.delete(m.id); } return; }
      if (m.id && m.method) serve(m);
    });
    const retry = () => { state.linked = state.ready = false; clearInterval(hbT); clearInterval(readyT); if (stopped || draining) return; retryT = setTimeout(connect, backoff); backoff = Math.min(maxBackoffMs, backoff * 2); };
    ws.on("close", retry);
    ws.on("error", () => { /* close follows */ });
    ws.on("unexpected-response", (_q, res) => { log(`relay refused the dial: HTTP ${res.statusCode}`); if ([401, 403, 410].includes(res.statusCode)) finish(`refused-${res.statusCode}`); });
  };
  connect();
  return { stop: (why = "stopped") => finish(why), done, state };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const relayUrl = process.env.VYOMI_RELAY_URL, token = process.env.VYOMI_RUNNER_TOKEN;
  if (!relayUrl || !token) { console.error("runner-llm-dial: VYOMI_RELAY_URL and VYOMI_RUNNER_TOKEN are required"); process.exit(2); }
  const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
  const link = runnerDial({ relayUrl, token, chatUrl: process.env.CHAT_URL, embedUrl: process.env.EMBED_URL, ttlS: process.env.TTL_S, WS, log: (m) => console.log("[runner-dial] " + m) });
  for (const sig of ["SIGTERM", "SIGINT"]) process.on(sig, () => link.stop("cancelled"));
  link.done.then((why) => { console.log("[runner-dial] ended: " + why); process.exit(["ttl", "cancelled", "stopped", "drained"].includes(why) ? 0 : 1); });
}
