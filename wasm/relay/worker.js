/* Vyomi-Nano relay — Cloudflare Worker + Durable Object (production).
 *
 * Same WS protocol as wasm/relay/local-relay.mjs; this is the deployable,
 * near-free version (no egress fees; DO holds the per-session tab WS).
 *
 *   tab  → wss://relay.vyomi.cloud/register?session=<id>   (registers, held by the DO)
 *   app  → https://relay.vyomi.cloud/<id>/<bucket>/<key>   (relayed to the tab)
 *
 * Deploy:  cd wasm/relay && npx wrangler deploy
 * Local:   npx wrangler dev   (miniflare — validate with e2e-relay.mjs against the dev URL)
 */

function b64encode(bytes) { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); }
function b64decode(str) { const s = atob(str); const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }

const MAX_BODY = 6 * 1024 * 1024;   // 6 MiB request cap (413 above this)
const MAX_PENDING = 64;             // per-session in-flight cap (429 above this)
const REQ_TIMEOUT_MS = 20000;       // tab must answer within this (504 otherwise)
const PING_MS = 25000;              // keepalive so bg-tab throttling can't silently drop the WS

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);

    // tab registration: /register?session=<id>  (WebSocket upgrade)
    if (parts[0] === "register") {
      const session = url.searchParams.get("session");
      if (!session) return new Response("missing session", { status: 400 });
      // Sandbox guardrail: only our own SPA may register a tab — the prod apex
      // AND its www host (both serve /nano/ with no redirect, so a user can be on
      // either origin).
      const origin = request.headers.get("Origin") || "";
      const allowedHost = (env.ALLOWED_ORIGIN || "").replace(/^https?:\/\//, "");
      const originOk = origin === env.ALLOWED_ORIGIN
        || (allowedHost && origin === "https://www." + allowedHost);
      if (env.ALLOWED_ORIGIN && origin && !originOk)
        return new Response("forbidden origin", { status: 403 });
      const stub = env.RELAY.get(env.RELAY.idFromName(session));
      return stub.fetch("https://do/register", { headers: forwardHeaders(request, "register") });
    }

    // external app:  /<session>/<path...>
    const session = parts[0];
    if (!session) return new Response("missing session id", { status: 404 });
    const subpath = "/" + parts.slice(1).join("/") + (url.search || "");
    const stub = env.RELAY.get(env.RELAY.idFromName(session));
    return stub.fetch("https://do/proxy", {
      method: request.method,
      headers: forwardHeaders(request, "proxy", subpath),
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    });
  },
};

function forwardHeaders(request, mode, subpath) {
  const h = new Headers(request.headers);
  h.set("X-Relay-Mode", mode);
  if (subpath) h.set("X-Relay-Path", subpath);
  return h;
}

export class RelaySession {
  constructor(state, env) {
    this.state = state; this.env = env;
    // In-flight proxy requests. Only ever populated WHILE the DO is awake handling
    // a request (so it's never lost to hibernation — the DO can't hibernate with a
    // request in flight). The held tab WebSocket itself lives in the runtime's
    // hibernatable socket set, NOT in memory — retrieved via getWebSockets().
    this.pending = new Map();
  }

  // Newest registered tab for this session (survives DO eviction/hibernation).
  _tab() {
    const socks = this.state.getWebSockets();
    return socks.length ? socks[socks.length - 1] : null;
  }

  async fetch(request) {
    const mode = request.headers.get("X-Relay-Mode");

    if (mode === "register") {
      if (request.headers.get("Upgrade") !== "websocket")
        return new Response("expected websocket", { status: 426 });
      const [client, server] = Object.values(new WebSocketPair());
      // A fresh tab supersedes any stale one for this session (reconnect/refresh).
      for (const old of this.state.getWebSockets()) { try { old.close(1012, "superseded"); } catch (_) {} }
      // HIBERNATION API: the runtime holds the socket even when the DO is evicted
      // from memory, so the connection no longer drops (1006) after ~60s.
      this.state.acceptWebSocket(server);
      // Keepalive so background-tab throttling / idle proxies can't silently drop it.
      try { await this.state.storage.setAlarm(Date.now() + PING_MS); } catch (_) {}
      return new Response(null, { status: 101, webSocket: client });
    }

    if (mode === "proxy") {
      const tab = this._tab();
      if (!tab) return new Response("no Nano tab registered", { status: 503 });
      if (this.pending.size >= MAX_PENDING)
        return new Response("session busy (too many in-flight)", { status: 429 });
      const path = request.headers.get("X-Relay-Path") || "/";
      const u = new URL("http://x" + path);
      const query = Object.fromEntries(u.searchParams.entries());
      const bodyBytes = new Uint8Array(await request.arrayBuffer());
      if (bodyBytes.byteLength > MAX_BODY)
        return new Response("payload too large", { status: 413 });
      const id = crypto.randomUUID();
      const respP = new Promise((resolve) => {
        const t = setTimeout(() => { if (this.pending.delete(id)) resolve(null); }, REQ_TIMEOUT_MS);
        this.pending.set(id, (r) => { clearTimeout(t); resolve(r); });
      });
      try {
        tab.send(JSON.stringify({
          id, method: request.method, path: u.pathname, query,
          headers: Object.fromEntries(request.headers), body: b64encode(bodyBytes),
        }));
      } catch (_) { this.pending.delete(id); return new Response("no Nano tab registered", { status: 503 }); }
      const resp = await respP;
      if (!resp) return new Response("tab timeout", { status: 504 });
      const out = new Headers();
      for (const [k, v] of Object.entries(resp.headers || {}))
        if (k.toLowerCase() !== "content-length") out.set(k, v);   // relay owns content-length
      return new Response(b64decode(resp.body || ""), { status: resp.status || 200, headers: out });
    }

    return new Response("bad relay mode", { status: 400 });
  }

  // ── Hibernation handlers (methods on the DO) — invoked by the runtime even
  //    after the DO was evicted, unlike addEventListener on an in-memory socket.
  async webSocketMessage(ws, message) {
    let msg;
    try { msg = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message)); }
    catch { return; }
    if (msg.type === "pong") return;
    const done = this.pending.get(msg.id);
    if (done) { this.pending.delete(msg.id); done(msg); }
  }
  async webSocketClose(ws, code, reason) { try { ws.close(code, reason); } catch (_) {} }
  async webSocketError(ws) { try { ws.close(1011, "error"); } catch (_) {} }

  // Keepalive tick: ping every held tab and re-arm while any is connected.
  async alarm() {
    const tabs = this.state.getWebSockets();
    for (const t of tabs) { try { t.send(JSON.stringify({ type: "ping" })); } catch (_) {} }
    if (tabs.length) { try { await this.state.storage.setAlarm(Date.now() + PING_MS); } catch (_) {} }
  }
}
