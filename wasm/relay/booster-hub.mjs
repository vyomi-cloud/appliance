/* Booster pairing hub (inside the relay). The booster dials OUT to  wss://<relay>/booster  with its signed session token
 * (Authorization: Bearer ...) - the Codespace opens no inbound port. Nano / SDK / CLI clients then talk plain HTTP to the
 * relay carrying the SAME session's token (X-Vyomi-Session-Token) and are paired to that booster by token.session_id.
 *
 *   - bad / expired / foreign-key token            -> refused (401/410)
 *   - Origin present and not on the allow-list     -> refused (403)   [browsers always send Origin; SDK/CLI don't]
 *   - at session_end the link is closed and requests are refused (410)
 *
 * Wire protocol booster<->relay is the Nano tab protocol: relay sends {id,method,path,query,headers,body(b64)},
 * booster answers {id,status,headers,body(b64)}.
 */
import crypto from "node:crypto";
import { verify, SessionError } from "./booster-session.mjs";

export const HEADER = "x-vyomi-session-token";
const DEFAULT_ORIGINS = ["https://vyomi.cloud", "https://www.vyomi.cloud"];
const LOOPBACK_ORIGIN = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/;

export function createHub({ WebSocketServer, key = process.env.VYOMI_BOOSTER_SESSION_KEY || "",
                            origins = (process.env.VYOMI_RELAY_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean),
                            allowLoopback = process.env.VYOMI_RELAY_ALLOW_LOOPBACK === "1",
                            requestTimeoutMs = 30000, log = () => {} } = {}) {
  const allow = new Set(origins.length ? origins : DEFAULT_ORIGINS);
  const boosters = new Map();          // session_id -> {ws, claims, timer, pending:Map, account}
  const wss = new WebSocketServer({ noServer: true });
  const enabled = () => !!key;

  const originOk = (o) => !o || allow.has(o) || (allowLoopback && LOOPBACK_ORIGIN.test(o));
  const nowS = () => Date.now() / 1000;

  function corsHeaders(origin) {
    return origin && originOk(origin) ? {
      "access-control-allow-origin": origin, "vary": "Origin",
      "access-control-allow-methods": "GET,PUT,POST,DELETE,HEAD,OPTIONS",
      "access-control-allow-headers": "*", "access-control-allow-private-network": "true" } : {};
  }
  function bearer(req) {
    const a = req.headers["authorization"] || "";
    return /^Bearer /i.test(a) ? a.slice(7).trim() : "";
  }
  function dropBooster(sid, reason) {
    const b = boosters.get(sid); if (!b) return;
    boosters.delete(sid); clearTimeout(b.timer);
    for (const [, p] of b.pending) p({ status: 502, headers: { "content-type": "text/plain" }, body: Buffer.from("booster link closed: " + reason).toString("base64") });
    b.pending.clear();
    try { b.ws.close(4000, reason); } catch { /* already closed */ }
    log(`booster ${sid} closed (${reason})`);
  }

  /** WebSocket upgrade for /booster. Returns true if it took the socket. */
  function upgrade(req, socket, head) {
    const reject = (status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
    if (!enabled()) { reject(503, "BoosterLinkDisabled"); return true; }
    if (!originOk(req.headers.origin)) { reject(403, "OriginNotAllowed"); return true; }
    let claims;
    try { claims = verify(bearer(req), key, nowS()); }
    catch (e) { reject(e instanceof SessionError ? e.status : 401, e.code || "BoosterSessionInvalid"); return true; }
    wss.handleUpgrade(req, socket, head, (ws) => {
      const sid = claims.session_id;
      if (boosters.has(sid)) dropBooster(sid, "replaced by a newer dial");
      const entry = { ws, claims, pending: new Map(), timer: null };
      entry.timer = setTimeout(() => dropBooster(sid, "session_end"), Math.max(0, claims.session_end * 1000 - Date.now()));
      boosters.set(sid, entry);
      log(`booster ${sid} (${claims.sub}) linked`);
      ws.on("message", (data) => {
        let m; try { m = JSON.parse(data.toString()); } catch { return; }
        const done = entry.pending.get(m.id);
        if (done) { entry.pending.delete(m.id); done(m); }
      });
      const gone = () => { if (boosters.get(sid) === entry) dropBooster(sid, "booster disconnected"); };
      ws.on("close", gone); ws.on("error", gone);
      ws.send(JSON.stringify({ type: "linked", session_id: sid, session_end: claims.session_end }));
    });
    return true;
  }

  /** HTTP: returns true if the request belongs to the booster plane (carries a session token) and was answered/forwarded. */
  function http(req, res, body) {
    const tok = req.headers[HEADER];
    const origin = req.headers.origin;
    if (tok === undefined) return false;                 // not the booster plane: existing relay behaviour
    const out = (status, code, msg) => {
      res.writeHead(status, { "content-type": "application/json", ...corsHeaders(origin) });
      res.end(JSON.stringify({ error: { ok: false, code, reason: msg } }));
      return true;
    };
    if (!enabled()) return out(503, "BoosterLinkDisabled", "relay has no session key");
    if (!originOk(origin)) return out(403, "OriginNotAllowed", `origin ${origin} is not allowed`);
    let claims;
    try { claims = verify(tok, key, nowS()); } catch (e) { return out(e.status || 401, e.code || "BoosterSessionInvalid", e.message); }
    const b = boosters.get(claims.session_id);
    if (!b || b.ws.readyState !== b.ws.OPEN) return out(502, "BoosterNotLinked", "no booster is linked for this session");
    if (b.claims.sub !== claims.sub) return out(403, "BoosterSessionMismatch", "session belongs to another account");
    const url = new URL(req.url, "http://x");
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { if (b.pending.delete(id)) out(504, "BoosterTimeout", "booster did not answer"); }, requestTimeoutMs);
    b.pending.set(id, (resp) => {
      clearTimeout(timer);
      const buf = Buffer.from(resp.body || "", "base64");
      const headers = {};
      for (const [k, v] of Object.entries(resp.headers || {})) if (!["content-length", "transfer-encoding", "connection"].includes(k.toLowerCase())) headers[k.toLowerCase()] = v;
      Object.assign(headers, corsHeaders(origin));
      headers["content-length"] = String(req.method === "HEAD" && resp.headers?.["content-length"] != null ? resp.headers["content-length"] : buf.length);
      res.writeHead(resp.status || 200, headers);
      res.end(req.method === "HEAD" ? undefined : buf);
    });
    const fwd = { ...req.headers }; delete fwd[HEADER];
    b.ws.send(JSON.stringify({ id, method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), headers: fwd, body: Buffer.from(body).toString("base64") }));
    return true;
  }

  return { upgrade, http, enabled, linked: () => [...boosters.keys()], close: () => { for (const sid of [...boosters.keys()]) dropBooster(sid, "relay shutdown"); } };
}
