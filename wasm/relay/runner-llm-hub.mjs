/* Remote-LLM plane of the relay (SPIKE, off unless VYOMI_BOOSTER_SESSION_KEY is set AND a runner dials in).
 *
 * GitHub-Actions runners (user's own account, one per RUNNER id of the catalogue, each serving one or more models through
 * Ollama) dial OUT to  wss://<relay>/llm-runner  with a runner-role session token (Authorization: Bearer ...,
 * claims.role === "llm-runner", claims.model === <runner id>, same session_id/sub as the booster's token). The booster -
 * which also only makes outbound calls - reaches them with plain HTTP:
 *
 *     <relay>/llm/v1/chat/completions     + X-Vyomi-Session-Token: <booster token>  + X-Vyomi-Llm-Model: <runner id>
 *     <relay>/llm/_status                 -> {runners: {<id>: ready|starting|stale}, rotating: {<id>: true}}
 *
 * ROTATION (hosted-runner jobs die at 6 h): a SECOND runner dialling for the same (session, runner id) is held as `next`;
 * the old one keeps serving. When `next` reports ready the hub swaps (new requests -> next), tells the old runner
 * {type:"drain"}, and closes it once its in-flight requests finish (force-close after 60 s). So rotation has no gap at all
 * when the new runner is ready before the old one ends; if the old one dies first, requests get 503 until `next` is ready.
 *
 * Wire (runner<->relay), JSON text frames:
 *   relay -> runner  {id, method, path, headers, body(b64)}  {type:"cancel", id}  {type:"drain"}
 *   runner -> relay  {id, type:"head", status, headers} {id, type:"chunk", body(b64)} {id, type:"end"}  (streamed)
 *                    {type:"ready"} once Ollama/llama-server is healthy      {type:"hb", busy} every ~15 s
 * Every relay-generated error carries  x-vyomi-hub: 1  so the booster can tell "runner not there" from a model error.
 * Tokens never appear in logs here.
 */
import crypto from "node:crypto";
import { verify, SessionError } from "./booster-session.mjs";

export const HEADER = "x-vyomi-session-token";
export const ROLE = "llm-runner";
const MAX_BODY = 8 * 1024 * 1024;
const DRAIN_FORCE_MS = 60000;

export function createRunnerLlmHub({ WebSocketServer, key = process.env.VYOMI_BOOSTER_SESSION_KEY || "",
                                     requestTimeoutMs = Number(process.env.VYOMI_LLM_REQUEST_TIMEOUT_MS || 300000),
                                     hbStaleMs = Number(process.env.VYOMI_LLM_HB_STALE_MS || 45000), log = () => {} } = {}) {
  const active = new Map();            // key -> entry serving requests
  const next = new Map();              // key -> entry that dialled while `active` exists (rotation successor)
  const wss = new WebSocketServer({ noServer: true });
  const enabled = () => !!key;
  const nowS = () => Date.now() / 1000;
  const rkey = (sid, rid) => `${sid}|${rid || ""}`;

  function closeEntry(e, reason) {
    clearTimeout(e.timer);
    for (const [, p] of e.pending) p.fail(502, "RunnerDropped", "runner link closed: " + reason);
    e.pending.clear();
    try { e.ws.close(4000, reason); } catch { /* */ }
  }
  function dropActive(k, e, reason) {
    if (active.get(k) !== e) return;
    active.delete(k); closeEntry(e, reason);
    log(`llm runner ${k.split("|")[1] || "-"} closed (${reason})`);
    const n = next.get(k);                                   // successor already dialled: promote it (serves once ready)
    if (n) { next.delete(k); active.set(k, n); }
  }
  function promote(k, n) {
    const old = active.get(k);
    next.delete(k); active.set(k, n);
    if (!old) return;
    old.draining = true;
    try { old.ws.send(JSON.stringify({ type: "drain" })); } catch { /* */ }
    const t0 = Date.now();
    const poll = setInterval(() => { if (old.pending.size === 0 || Date.now() - t0 > DRAIN_FORCE_MS) { clearInterval(poll); closeEntry(old, "drained"); } }, 200);
    log(`llm runner ${k.split("|")[1] || "-"} rotated`);
  }

  /** WebSocket upgrade for /llm-runner. */
  function upgrade(req, socket, head) {
    const reject = (status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
    if (!enabled()) { reject(503, "BoosterLinkDisabled"); return true; }
    let claims;
    const a = req.headers["authorization"] || "";
    try { claims = verify(/^Bearer /i.test(a) ? a.slice(7).trim() : "", key, nowS()); }
    catch (e) { reject(e instanceof SessionError ? e.status : 401, e.code || "BoosterSessionInvalid"); return true; }
    if (claims.role !== ROLE) { reject(403, "BoosterSessionWrongRole"); return true; }   // a booster token cannot pose as a runner
    wss.handleUpgrade(req, socket, head, (ws) => {
      const k = rkey(claims.session_id, claims.model);
      const entry = { ws, claims, pending: new Map(), timer: null, ready: false, lastSeen: Date.now(), draining: false };
      entry.timer = setTimeout(() => { if (active.get(k) === entry) dropActive(k, entry, "session_end"); else { next.delete(k); closeEntry(entry, "session_end"); } },
                               Math.max(0, claims.session_end * 1000 - Date.now()));
      if (active.has(k)) { const prev = next.get(k); if (prev) closeEntry(prev, "replaced by a newer dial"); next.set(k, entry); }
      else active.set(k, entry);
      log(`llm runner ${claims.model || "-"} linked`);
      ws.on("message", (data) => {
        let m; try { m = JSON.parse(data.toString()); } catch { return; }
        entry.lastSeen = Date.now();
        if (m.type === "ready") { entry.ready = true; if (next.get(k) === entry) promote(k, entry); return; }
        if (m.type === "hb") return;
        const p = entry.pending.get(m.id); if (!p) return;
        if (m.type === "head") p.head(m);
        else if (m.type === "chunk") p.chunk(Buffer.from(m.body || "", "base64"));
        else if (m.type === "end") { entry.pending.delete(m.id); p.end(); }
      });
      const gone = () => {
        if (entry.draining) return;
        if (active.get(k) === entry) dropActive(k, entry, "runner disconnected");
        else if (next.get(k) === entry) { next.delete(k); clearTimeout(entry.timer); }
      };
      ws.on("close", gone); ws.on("error", gone);
      ws.send(JSON.stringify({ type: "linked", session_id: claims.session_id, session_end: claims.session_end }));
    });
    return true;
  }

  const stateOf = (x) => (!x ? "absent" : Date.now() - x.lastSeen > hbStaleMs ? "stale" : x.ready ? "ready" : "starting");

  /** HTTP: /llm/* (booster -> runner) and /llm/_status. Returns true if it answered/forwarded. */
  function http(req, res, body) {
    const url = new URL(req.url, "http://x");
    if (!(url.pathname === "/llm" || url.pathname.startsWith("/llm/"))) return false;
    const out = (status, code, msg) => {
      if (res.headersSent) { res.destroy(); return true; }
      res.writeHead(status, { "content-type": "application/json", "x-vyomi-hub": "1" });
      res.end(JSON.stringify({ error: { ok: false, code, reason: msg, message: msg, type: "unavailable" } }));
      return true;
    };
    if (!enabled()) return out(503, "BoosterLinkDisabled", "relay has no session key");
    let claims;
    try { claims = verify(req.headers[HEADER] || "", key, nowS()); } catch (e) { return out(e.status || 401, e.code || "BoosterSessionInvalid", e.message); }
    if (claims.role) return out(403, "BoosterSessionWrongRole", "runner-role token cannot call the LLM plane");
    const path = url.pathname.slice(4) || "/";
    const rid = String(req.headers["x-vyomi-llm-model"] || "");
    const r = active.get(rkey(claims.session_id, rid));
    if (path === "/_status") {
      const all = {}, rotating = {}, pre = claims.session_id + "|";
      for (const [k, x] of active) if (k.startsWith(pre) && x.claims.sub === claims.sub) { all[k.slice(pre.length)] = stateOf(x); if (next.has(k)) rotating[k.slice(pre.length)] = true; }
      for (const [k, x] of next) if (k.startsWith(pre) && !active.has(k) && x.claims.sub === claims.sub) all[k.slice(pre.length)] = stateOf(x);
      res.writeHead(200, { "content-type": "application/json", "x-vyomi-hub": "1" });
      res.end(JSON.stringify({ runner: stateOf(r), last_seen_s: r ? Math.round((Date.now() - r.lastSeen) / 1000) : null, runners: all, rotating }));
      return true;
    }
    const stale = r && (Date.now() - r.lastSeen > hbStaleMs);
    if (!r || r.ws.readyState !== r.ws.OPEN) return out(502, "RunnerNotLinked", "no LLM runner is linked for this session");
    if (r.claims.sub !== claims.sub) return out(403, "BoosterSessionMismatch", "session belongs to another account");
    if (stale) return out(503, "RunnerStale", "LLM runner missed its heartbeat");
    if (!r.ready) return out(503, "RunnerNotReady", "LLM runner is still loading the model");
    if (body.length > MAX_BODY) return out(413, "BodyTooLarge", "request too large");
    const id = crypto.randomUUID();
    let timer = null;
    timer = setTimeout(() => { if (r.pending.delete(id)) out(504, "RunnerTimeout", "runner did not answer"); }, requestTimeoutMs);
    r.pending.set(id, {
      head: (m) => { clearTimeout(timer); const h = {}; for (const [k, v] of Object.entries(m.headers || {})) if (!["content-length", "transfer-encoding", "connection"].includes(k.toLowerCase())) h[k.toLowerCase()] = v; res.writeHead(m.status || 200, h); },
      chunk: (b) => { if (!res.destroyed) res.write(b); },
      end: () => { clearTimeout(timer); if (!res.destroyed) res.end(); },
      fail: (st, code, msg) => { clearTimeout(timer); out(st, code, msg); },
    });
    res.on("close", () => { clearTimeout(timer); if (r.pending.delete(id) && !res.writableEnded) { try { r.ws.send(JSON.stringify({ type: "cancel", id })); } catch { /* */ } } });
    const fwd = { ...req.headers }; delete fwd[HEADER]; delete fwd["x-vyomi-llm-model"]; delete fwd["host"]; delete fwd["connection"];
    r.ws.send(JSON.stringify({ id, method: req.method, path: path + url.search, headers: fwd, body: Buffer.from(body).toString("base64") }));
    return true;
  }

  const all = () => [...active.values(), ...next.values()];
  return { upgrade, http, enabled, linked: () => [...active.keys()], close: () => { for (const e of all()) closeEntry(e, "relay shutdown"); active.clear(); next.clear(); } };
}
