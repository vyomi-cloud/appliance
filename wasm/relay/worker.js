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
      // Sandbox guardrail: only our own SPA may register a tab.
      const origin = request.headers.get("Origin") || "";
      if (env.ALLOWED_ORIGIN && origin && origin !== env.ALLOWED_ORIGIN)
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
  constructor(state, env) { this.state = state; this.env = env; this.tab = null; this.pending = new Map(); }

  async fetch(request) {
    const mode = request.headers.get("X-Relay-Mode");

    if (mode === "register") {
      if (request.headers.get("Upgrade") !== "websocket")
        return new Response("expected websocket", { status: 426 });
      const [client, server] = Object.values(new WebSocketPair());
      server.accept();
      // A fresh tab supersedes any stale one for this session (reconnect/refresh).
      if (this.tab && this.tab !== server) { try { this.tab.close(1012, "superseded"); } catch (_) {} }
      this.tab = server;
      server.addEventListener("message", (ev) => {
        let msg; try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "pong") return;
        const done = this.pending.get(msg.id);
        if (done) { this.pending.delete(msg.id); done(msg); }
      });
      server.addEventListener("close", () => { if (this.tab === server) this.tab = null; });
      // Keepalive: ping the tab on a hibernation-safe alarm so background-tab
      // throttling (or an idle proxy) can't silently drop the held WebSocket.
      try { await this.state.storage.setAlarm(Date.now() + PING_MS); } catch (_) {}
      return new Response(null, { status: 101, webSocket: client });
    }

    if (mode === "proxy") {
      if (!this.tab) return new Response("no Nano tab registered", { status: 503 });
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
      this.tab.send(JSON.stringify({
        id, method: request.method, path: u.pathname, query,
        headers: Object.fromEntries(request.headers), body: b64encode(bodyBytes),
      }));
      const resp = await respP;
      if (!resp) return new Response("tab timeout", { status: 504 });
      const out = new Headers();
      for (const [k, v] of Object.entries(resp.headers || {}))
        if (k.toLowerCase() !== "content-length") out.set(k, v);   // relay owns content-length
      return new Response(b64decode(resp.body || ""), { status: resp.status || 200, headers: out });
    }

    return new Response("bad relay mode", { status: 400 });
  }

  // Keepalive tick: ping the held tab and re-arm while one is connected.
  async alarm() {
    if (this.tab) {
      try { this.tab.send(JSON.stringify({ type: "ping" })); } catch (_) {}
      try { await this.state.storage.setAlarm(Date.now() + PING_MS); } catch (_) {}
    }
  }
}
