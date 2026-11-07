/* Remote-LLM plane of the relay (SPIKE, off unless VYOMI_BOOSTER_SESSION_KEY is set AND a runner dials in).
 *
 * A GitHub-Actions runner (user's own account) dials OUT to  wss://<relay>/llm-runner  with a runner-role session token
 * (Authorization: Bearer ..., claims.role === "llm-runner", same session_id/sub as the booster's token). The booster -
 * which also only ever dials/calls OUT - reaches the runner's llama.cpp with plain HTTP:
 *
 *     <relay>/llm/v1/chat/completions      + header  X-Vyomi-Session-Token: <booster session token>
 *
 * Neither side accepts an inbound connection from the internet. Wire (runner<->relay), JSON text frames:
 *   relay -> runner  {id, method, path, headers, body(b64)}                  (path has the /llm prefix stripped)
 *   runner -> relay  {id, type:"head", status, headers} {id, type:"chunk", body(b64)} {id, type:"end"}   (streamed)
 *                    {type:"ready"}  once llama-server is healthy     {type:"hb", busy}  every ~15 s
 * Honesty: every relay-generated error carries  x-vyomi-hub: 1  so the booster can tell "runner not there" (-> its own 503)
 * from a model error passed through from llama.cpp.
 * Tokens never appear in logs here.
 */
import crypto from "node:crypto";
import { verify, SessionError } from "./booster-session.mjs";

export const HEADER = "x-vyomi-session-token";
export const ROLE = "llm-runner";
const MAX_BODY = 8 * 1024 * 1024;

export function createRunnerLlmHub({ WebSocketServer, key = process.env.VYOMI_BOOSTER_SESSION_KEY || "",
                                     requestTimeoutMs = Number(process.env.VYOMI_LLM_REQUEST_TIMEOUT_MS || 300000),
                                     hbStaleMs = Number(process.env.VYOMI_LLM_HB_STALE_MS || 45000), log = () => {} } = {}) {
  const runners = new Map();           // session_id -> {ws, claims, timer, pending:Map, ready, lastSeen}
  const wss = new WebSocketServer({ noServer: true });
  const enabled = () => !!key;
  const nowS = () => Date.now() / 1000;

  function dropRunner(sid, reason) {
    const r = runners.get(sid); if (!r) return;
    runners.delete(sid); clearTimeout(r.timer);
    for (const [, p] of r.pending) p.fail(502, "RunnerDropped", "runner link closed: " + reason);
    r.pending.clear();
    try { r.ws.close(4000, reason); } catch { /* */ }
    log(`llm runner ${sid} closed (${reason})`);
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
      const sid = claims.session_id;
      if (runners.has(sid)) dropRunner(sid, "replaced by a newer dial");
      const entry = { ws, claims, pending: new Map(), timer: null, ready: false, lastSeen: Date.now() };
      entry.timer = setTimeout(() => dropRunner(sid, "session_end"), Math.max(0, claims.session_end * 1000 - Date.now()));
      runners.set(sid, entry);
      log(`llm runner ${sid} linked`);
      ws.on("message", (data) => {
        let m; try { m = JSON.parse(data.toString()); } catch { return; }
        entry.lastSeen = Date.now();
        if (m.type === "ready") { entry.ready = true; return; }
        if (m.type === "hb") return;
        const p = entry.pending.get(m.id); if (!p) return;
        if (m.type === "head") p.head(m);
        else if (m.type === "chunk") p.chunk(Buffer.from(m.body || "", "base64"));
        else if (m.type === "end") { entry.pending.delete(m.id); p.end(); }
      });
      const gone = () => { if (runners.get(sid) === entry) dropRunner(sid, "runner disconnected"); };
      ws.on("close", gone); ws.on("error", gone);
      ws.send(JSON.stringify({ type: "linked", session_id: sid, session_end: claims.session_end }));
    });
    return true;
  }

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
    const r = runners.get(claims.session_id);
    const stale = r && (Date.now() - r.lastSeen > hbStaleMs);
    if (path === "/_status") {
      res.writeHead(200, { "content-type": "application/json", "x-vyomi-hub": "1" });
      res.end(JSON.stringify({ runner: !r ? "absent" : stale ? "stale" : r.ready ? "ready" : "starting", last_seen_s: r ? Math.round((Date.now() - r.lastSeen) / 1000) : null }));
      return true;
    }
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
    const fwd = { ...req.headers }; delete fwd[HEADER]; delete fwd["host"]; delete fwd["connection"];
    r.ws.send(JSON.stringify({ id, method: req.method, path: path + url.search, headers: fwd, body: Buffer.from(body).toString("base64") }));
    return true;
  }

  return { upgrade, http, enabled, linked: () => [...runners.keys()], close: () => { for (const sid of [...runners.keys()]) dropRunner(sid, "relay shutdown"); } };
}
