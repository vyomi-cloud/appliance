/* Mesh pairing hub (inside the relay). The mesh dials OUT to  wss://<relay>/mesh  with its signed session token
 * (Authorization: Bearer ...) - the Codespace opens no inbound port. Nano / SDK / CLI clients then talk plain HTTP to the
 * relay carrying the SAME session's token (X-Vyomi-Session-Token) and are paired to that mesh by token.session_id.
 *
 *   - bad / expired / foreign-key token            -> refused (401/410)
 *   - Origin present and not on the allow-list     -> refused (403)   [browsers always send Origin; SDK/CLI don't]
 *   - at session_end the link is closed and requests are refused (410)
 *
 * Wire protocol mesh<->relay is the Nano tab protocol: relay sends {id,method,path,query,headers,body(b64)},
 * mesh answers {id,status,headers,body(b64)}.
 *
 * STREAMS (interactive shell into a Docker VM on the mesh). The tab opens  wss://<relay>/shell  and authenticates with the
 * SAME session token in its first message (browsers cannot set headers on a WebSocket, and a token in the URL would be logged):
 *     tab -> relay   text {"type":"auth","token","cloud","ref","cols","rows"}
 *     relay -> tab   text {"t":"opened","container"} | {"t":"error","code","message"} (then close); afterwards binary = terminal output
 *     tab -> relay   binary = terminal input;  text {"t":"resize","cols","rows"} | {"t":"close"}
 * The hub multiplexes streams over the mesh's existing WSS as {type:"stream",op,sid,...} frames:
 *     relay -> mesh  open{cloud,ref,cols,rows} | data{d:b64} | resize{cols,rows} | pause | resume | close
 *     mesh -> relay  opened{container} | data{d:b64} | close{reason} | error{code,message}
 * A stream is owned by (mesh entry, tab socket): a mesh can only address the sids that entry created, and a tab only
 * reaches the mesh of its own token's session_id and account. Streams die with the tab, the mesh link, the idle timer
 * or the token's session_end.
 */
import crypto from "node:crypto";
import { verify, SessionError } from "./mesh-session.mjs";

export const HEADER = "x-vyomi-session-token";
const DEFAULT_ORIGINS = ["https://vyomi.cloud", "https://www.vyomi.cloud"];
const LOOPBACK_ORIGIN = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/;

export function createHub({ WebSocketServer, key = process.env.VYOMI_MESH_SESSION_KEY || "",
                            origins = (process.env.VYOMI_RELAY_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean),
                            allowLoopback = process.env.VYOMI_RELAY_ALLOW_LOOPBACK === "1",
                            requestTimeoutMs = 30000, log = () => {},
                            maxStreams = Number(process.env.VYOMI_SHELL_MAX_PER_SESSION || 4),
                            idleMs = Number(process.env.VYOMI_SHELL_IDLE_MS || 900000),
                            openTimeoutMs = 20000, authTimeoutMs = 10000,
                            maxTcp = Number(process.env.VYOMI_MAX_STREAMS || 20),            // raw TCP streams (SSH) per Mesh session
                            tcpIdleMs = Number(process.env.VYOMI_TCP_IDLE_MS || 3600000) } = {}) {
  const allow = new Set(origins.length ? origins : DEFAULT_ORIGINS);
  const meshes = new Map();          // session_id -> {ws, claims, timer, pending:Map, account}
  const wss = new WebSocketServer({ noServer: true });
  const shellWss = new WebSocketServer({ noServer: true, maxPayload: 70 * 1024 });   // input frames are capped (64 KiB data + control)
  const MAX_INPUT = 64 * 1024, HIGH_WATER = 1024 * 1024, LOW_WATER = 256 * 1024, LINK_HIGH = 4 * 1024 * 1024;
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
  function dropMesh(sid, reason) {
    const b = meshes.get(sid); if (!b) return;
    meshes.delete(sid); clearTimeout(b.timer);
    for (const [, p] of b.pending) p({ status: 502, headers: { "content-type": "text/plain" }, body: Buffer.from("mesh link closed: " + reason).toString("base64") });
    b.pending.clear();
    for (const st of [...b.streams.values()]) {
      if (reason === "session_end") endStream(st, 4410, "MeshSessionExpired", "the mesh session has ended");
      else endStream(st, 4000, "MeshLinkClosed", "mesh link closed: " + reason);
    }
    try { b.ws.close(4000, reason); } catch { /* already closed */ }
    log(`mesh ${sid} closed (${reason})`);
  }


  // ── streams ─────────────────────────────────────────────────────────────────────────────────────
  const sendTab = (st, obj) => { if (st.kind === "tcp") return;   // raw TCP clients (vyomi-tunnel connect) get bytes only, never JSON
    try { if (st.tab.readyState === st.tab.OPEN) st.tab.send(JSON.stringify(obj)); } catch { /* gone */ } };
  function endStream(st, code, errCode, message, tellMesh = true) {
    if (st.ended) return; st.ended = true;
    clearTimeout(st.openTimer); clearTimeout(st.expTimer); clearInterval(st.idleTimer); clearInterval(st.drainTimer);
    st.mesh.streams.delete(st.sid);
    if (tellMesh && st.mesh.ws.readyState === st.mesh.ws.OPEN) { try { st.mesh.ws.send(JSON.stringify({ type: "stream", op: "close", sid: st.sid })); } catch { /* */ } }
    if (errCode) sendTab(st, { t: "error", code: errCode, message });
    try { st.tab.close(code, String(errCode || "closed").slice(0, 100)); } catch { /* */ }
    log(`stream ${st.sid} closed (${errCode || "normal"})`);
  }
  function fromMesh(entry, m) {
    const st = entry.streams.get(m.sid);                         // only streams THIS mesh's session owns
    if (!st) return;
    st.last = Date.now();
    if (m.op === "opened") {
      clearTimeout(st.openTimer); st.open = true; sendTab(st, { t: "opened", container: String(m.container || "") });
      for (const f of st.queue || []) entry.ws.send(JSON.stringify({ type: "stream", op: "data", sid: st.sid, d: f.toString("base64") }));
      st.queue = [];
    }
    else if (m.op === "data") {
      if (!st.open) return;
      const buf = Buffer.from(String(m.d || ""), "base64");
      try { st.tab.send(buf); } catch { return; }
      if (st.tab.bufferedAmount > HIGH_WATER && !st.paused) {   // slow tab: tell the mesh to stop reading the PTY
        st.paused = true; entry.ws.send(JSON.stringify({ type: "stream", op: "pause", sid: st.sid }));
        st.drainTimer = setInterval(() => {
          if (st.tab.bufferedAmount < LOW_WATER) { clearInterval(st.drainTimer); st.paused = false; try { entry.ws.send(JSON.stringify({ type: "stream", op: "resume", sid: st.sid })); } catch { /* */ } }
        }, 50);
      }
    }
    else if (m.op === "close") endStream(st, 1000, m.reason && m.reason !== "exit" ? String(m.reason).slice(0, 40) : "", String(m.message || ""), false);
    else if (m.op === "error") endStream(st, 4403, String(m.code || "StreamError").slice(0, 60), String(m.message || "").slice(0, 300), false);
  }

  /** WebSocket upgrade for /shell (the Nano tab). Returns true if it took the socket. */
  function shellUpgrade(req, socket, head) {
    const reject = (status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
    if (!enabled()) { reject(503, "MeshLinkDisabled"); return true; }
    if (!originOk(req.headers.origin)) { reject(403, "OriginNotAllowed"); return true; }
    shellWss.handleUpgrade(req, socket, head, (tab) => {
      const fail = (code, message, wsCode = 4401) => { try { tab.send(JSON.stringify({ t: "error", code, message })); tab.close(wsCode, code.slice(0, 100)); } catch { /* */ } };
      const authTimer = setTimeout(() => fail("AuthTimeout", "no auth message"), authTimeoutMs);
      tab.once("message", (data, isBinary) => {
        clearTimeout(authTimer);
        let a; try { if (isBinary) throw 0; a = JSON.parse(data.toString()); } catch { return fail("BadRequest", "first message must be JSON auth"); }
        if (!a || a.type !== "auth") return fail("BadRequest", "first message must be auth");
        let claims;
        try { claims = verify(a.token, key, nowS()); } catch (e) { return fail(e.code || "MeshSessionInvalid", e.message, e.status === 410 ? 4410 : 4401); }
        if (claims.role) return fail("MeshSessionWrongRole", "runner-role token cannot open a shell", 4403);
        const b = meshes.get(claims.session_id);
        if (!b || b.ws.readyState !== b.ws.OPEN) return fail("MeshNotLinked", "no mesh is linked for this session", 4502);
        if (b.claims.sub !== claims.sub) return fail("MeshSessionMismatch", "session belongs to another account", 4403);
        if (b.streams.size >= maxStreams) return fail("TooManyShells", `at most ${maxStreams} shells per session`, 4429);
        const cloud = String(a.cloud || ""), ref = String(a.ref || "");
        if (!/^(aws|gcp|azure)$/.test(cloud) || !ref || ref.length > 200) return fail("BadRequest", "cloud/ref", 4400);
        const sid = crypto.randomUUID();
        const st = { sid, tab, mesh: b, open: false, ended: false, paused: false, last: Date.now() };
        b.streams.set(sid, st);
        st.openTimer = setTimeout(() => endStream(st, 4504, "MeshTimeout", "the mesh did not open the shell in time"), openTimeoutMs);
        st.expTimer = setTimeout(() => endStream(st, 4410, "MeshSessionExpired", "the mesh session has ended"), Math.max(0, claims.session_end * 1000 - Date.now()));
        st.idleTimer = setInterval(() => { if (Date.now() - st.last > idleMs) endStream(st, 4408, "IdleTimeout", "shell closed after being idle"); }, Math.min(1000, Math.max(20, idleMs / 4)));
        b.ws.send(JSON.stringify({ type: "stream", op: "open", sid, cloud, ref, cols: a.cols, rows: a.rows }));
        tab.on("message", (d, isBin) => {
          if (st.ended) return;
          st.last = Date.now();
          if (isBin) {
            if (!st.open) return;
            if (d.length > MAX_INPUT) return endStream(st, 1009, "FrameTooLarge", "input frame too large");
            if (b.ws.bufferedAmount > LINK_HIGH) return endStream(st, 4413, "BackPressure", "mesh link is saturated");
            b.ws.send(JSON.stringify({ type: "stream", op: "data", sid, d: Buffer.from(d).toString("base64") }));
            return;
          }
          let c; try { c = JSON.parse(d.toString()); } catch { return; }
          if (c.t === "resize") b.ws.send(JSON.stringify({ type: "stream", op: "resize", sid, cols: c.cols, rows: c.rows }));
          else if (c.t === "close") endStream(st, 1000, "", "");
        });
        const gone = () => endStream(st, 1000, "", "");
        tab.on("close", gone); tab.on("error", gone);
      });
      tab.on("close", () => clearTimeout(authTimer));
    });
    return true;
  }

  /** WebSocket upgrade for /connect?vm=<name>&port=<n> (`vyomi-tunnel connect`): a raw TCP stream to a VM behind the mesh of the
   *  token's own session. Auth is the Bearer session token (a CLI can set headers); same account + session rules as /shell. The stream
   *  rides the shell framework above (kind:"tcp"): binary WS messages are raw bytes both ways, no JSON reaches the client. */
  const connWss = new WebSocketServer({ noServer: true, maxPayload: 70 * 1024 });
  function connectUpgrade(req, socket, head) {
    const reject = (status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
    if (!enabled()) { reject(503, "MeshLinkDisabled"); return true; }
    if (!originOk(req.headers.origin)) { reject(403, "OriginNotAllowed"); return true; }
    let claims;
    try { claims = verify(bearer(req), key, nowS()); }
    catch (e) { reject(e instanceof SessionError ? e.status : 401, e.code || "MeshSessionInvalid"); return true; }
    if (claims.role) { reject(403, "MeshSessionWrongRole"); return true; }
    const u = new URL(req.url, "http://x");
    const vm = u.searchParams.get("vm") || "", port = Number(u.searchParams.get("port") || 22);
    if (!/^[A-Za-z0-9._-]{1,80}$/.test(vm) || !Number.isInteger(port) || port < 1 || port > 65535) { reject(400, "BadVm"); return true; }
    const b = meshes.get(claims.session_id);
    if (!b || b.ws.readyState !== b.ws.OPEN) { reject(502, "MeshNotLinked"); return true; }
    if (b.claims.sub !== claims.sub) { reject(403, "MeshSessionMismatch"); return true; }
    if ([...b.streams.values()].filter((x) => x.kind === "tcp").length >= maxTcp) { reject(429, "TooManyStreams"); return true; }
    connWss.handleUpgrade(req, socket, head, (tab) => {
      const sid = crypto.randomUUID();
      const st = { sid, kind: "tcp", tab, mesh: b, open: false, ended: false, paused: false, last: Date.now() };
      b.streams.set(sid, st);
      st.openTimer = setTimeout(() => endStream(st, 1011, "MeshTimeout", "the VM did not answer in time"), openTimeoutMs);
      st.expTimer = setTimeout(() => endStream(st, 4410, "MeshSessionExpired", "the mesh session has ended"), Math.max(0, claims.session_end * 1000 - Date.now()));
      st.idleTimer = setInterval(() => { if (Date.now() - st.last > tcpIdleMs) endStream(st, 4408, "IdleTimeout", "connection closed after being idle"); }, Math.min(1000, Math.max(20, tcpIdleMs / 4)));
      b.ws.send(JSON.stringify({ type: "stream", op: "open", kind: "tcp", sid, vm, port }));
      log(`tcp stream ${sid} -> ${claims.session_id}/${vm}:${port}`);
      tab.on("message", (d, isBin) => {
        if (st.ended || !isBin) return;
        st.last = Date.now();
        if (!st.open) { st.queue = (st.queue || []); if (st.queue.length < 64) st.queue.push(Buffer.from(d)); return; }   // early bytes wait for the VM
        if (d.length > MAX_INPUT) return endStream(st, 1009, "FrameTooLarge", "frame too large");
        if (b.ws.bufferedAmount > LINK_HIGH) return endStream(st, 4413, "BackPressure", "mesh link is saturated");
        b.ws.send(JSON.stringify({ type: "stream", op: "data", sid, d: Buffer.from(d).toString("base64") }));
      });
      const gone = () => endStream(st, 1000, "", "");
      tab.on("close", gone); tab.on("error", gone);
    });
    return true;
  }

  /** WebSocket upgrade for /mesh. Returns true if it took the socket. */
  function upgrade(req, socket, head) {
    const reject = (status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
    if (!enabled()) { reject(503, "MeshLinkDisabled"); return true; }
    if (!originOk(req.headers.origin)) { reject(403, "OriginNotAllowed"); return true; }
    let claims;
    try { claims = verify(bearer(req), key, nowS()); }
    catch (e) { reject(e instanceof SessionError ? e.status : 401, e.code || "MeshSessionInvalid"); return true; }
    if (claims.role) { reject(403, "MeshSessionWrongRole"); return true; }       // runner-role tokens only dial /llm-runner
    wss.handleUpgrade(req, socket, head, (ws) => {
      const sid = claims.session_id;
      if (meshes.has(sid)) dropMesh(sid, "replaced by a newer dial");
      const entry = { ws, claims, pending: new Map(), streams: new Map(), timer: null };
      entry.timer = setTimeout(() => dropMesh(sid, "session_end"), Math.max(0, claims.session_end * 1000 - Date.now()));
      meshes.set(sid, entry);
      log(`mesh ${sid} (${claims.sub}) linked`);
      ws.on("message", (data) => {
        let m; try { m = JSON.parse(data.toString()); } catch { return; }
        if (m && m.type === "stream") { fromMesh(entry, m); return; }
        const done = entry.pending.get(m.id);
        if (done) { entry.pending.delete(m.id); done(m); }
      });
      const gone = () => { if (meshes.get(sid) === entry) dropMesh(sid, "mesh disconnected"); };
      ws.on("close", gone); ws.on("error", gone);
      ws.send(JSON.stringify({ type: "linked", session_id: sid, session_end: claims.session_end }));
    });
    return true;
  }

  /** HTTP: returns true if the request belongs to the mesh plane (carries a session token) and was answered/forwarded. */
  function http(req, res, body) {
    const tok = req.headers[HEADER];
    const origin = req.headers.origin;
    if (tok === undefined) return false;                 // not the mesh plane: existing relay behaviour
    const out = (status, code, msg) => {
      res.writeHead(status, { "content-type": "application/json", ...corsHeaders(origin) });
      res.end(JSON.stringify({ error: { ok: false, code, reason: msg } }));
      return true;
    };
    if (!enabled()) return out(503, "MeshLinkDisabled", "relay has no session key");
    if (!originOk(origin)) return out(403, "OriginNotAllowed", `origin ${origin} is not allowed`);
    let claims;
    try { claims = verify(tok, key, nowS()); } catch (e) { return out(e.status || 401, e.code || "MeshSessionInvalid", e.message); }
    if (claims.role) return out(403, "MeshSessionWrongRole", "runner-role token cannot drive a mesh");
    const b = meshes.get(claims.session_id);
    if (!b || b.ws.readyState !== b.ws.OPEN) return out(502, "MeshNotLinked", "no mesh is linked for this session");
    if (b.claims.sub !== claims.sub) return out(403, "MeshSessionMismatch", "session belongs to another account");
    const url = new URL(req.url, "http://x");
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { if (b.pending.delete(id)) out(504, "MeshTimeout", "mesh did not answer"); }, requestTimeoutMs);
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

  return { upgrade, shellUpgrade, connectUpgrade, http, enabled, linked: () => [...meshes.keys()], streams: () => [...meshes.values()].reduce((n, b) => n + b.streams.size, 0), close: () => { for (const sid of [...meshes.keys()]) dropMesh(sid, "relay shutdown"); } };
}
