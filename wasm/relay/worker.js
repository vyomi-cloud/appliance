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

import { egress } from "./egress.mjs";
import { serveGwEgress, createRateLimiter, LIMITS } from "./gw-egress.mjs";

// Hosted gateway-backend egress (Nano without a local tunnel): public https backends on an allow-list only (gw-egress.mjs hostedTargetProblem).
const gwLimiter = createRateLimiter(LIMITS.hosted.perMinute);
async function workerTransport({ method, url, headers, body, timeoutMs, maxBytes }) {
  const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url.href, { method, headers, body, redirect: "manual", signal: ctl.signal });   // redirects are returned, never followed
    const reader = res.body ? res.body.getReader() : null, parts = []; let n = 0;
    while (reader) { const { done, value } = await reader.read(); if (done) break; n += value.length; if (n > maxBytes) { try { await reader.cancel(); } catch (_) {} throw Object.assign(new Error("too large"), { code: "too-large" }); } parts.push(value); }
    const out = new Uint8Array(n); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
    return { status: res.status, headers: Object.fromEntries(res.headers), body: out };
  } catch (e) { throw e && e.code ? e : Object.assign(e, { code: e && e.name === "AbortError" ? "timeout" : "failed" }); }
  finally { clearTimeout(timer); }
}

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

    // Nano VM package egress: /egress?u=<url>. Allow-listed hosts only (egress.mjs); same Origin rule as /register;
    // per-IP rate limit when the EGRESS_LIMIT binding exists. Must precede the /<session> catch-all below.
    if (parts[0] === "egress") {
      const origin = request.headers.get("Origin") || "";
      const allowedHost = (env.ALLOWED_ORIGIN || "").replace(/^https?:\/\//, "");
      const originOk = !env.ALLOWED_ORIGIN || !origin || origin === env.ALLOWED_ORIGIN
        || (allowedHost && origin === "https://www." + allowedHost);
      const cors = { "access-control-allow-origin": origin || "*", "access-control-allow-private-network": "true",
                     "access-control-allow-headers": "*", "access-control-allow-methods": "GET, HEAD, POST, OPTIONS", "vary": "Origin" };
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
      if (!originOk) return new Response("forbidden origin", { status: 403, headers: cors });
      if (env.EGRESS_LIMIT) {
        const ip = request.headers.get("CF-Connecting-IP") || "unknown";
        const { success } = await env.EGRESS_LIMIT.limit({ key: ip });
        if (!success) return new Response("egress rate limited", { status: 429, headers: { ...cors, "retry-after": "30" } });
      }
      const r = await egress(request);
      const h = new Headers(r.headers);
      for (const [k, v] of Object.entries(cors)) h.set(k, v);
      return new Response(r.body, { status: r.status, headers: h });
    }

    // Nano API Gateway backend egress: POST /gw-egress (header x-vyomi-session). Origin rule as /register; the session must have a registered
    // Nano tab (the only way to get one is to pass the Origin rule on /register); per-session rate limit; allow-listed public https hosts only.
    if (parts[0] === "gw-egress") {
      const origin = request.headers.get("Origin") || "";
      const allowedHost = (env.ALLOWED_ORIGIN || "").replace(/^https?:\/\//, "");
      const originOk = !!origin && (!env.ALLOWED_ORIGIN || origin === env.ALLOWED_ORIGIN || (allowedHost && origin === "https://www." + allowedHost));
      const cors = { "access-control-allow-origin": origin || "null", "access-control-allow-headers": "content-type, x-vyomi-session", "access-control-allow-methods": "POST, OPTIONS", "vary": "Origin" };
      const jsonOut = (st, o, extra) => new Response(JSON.stringify(o), { status: st, headers: { "content-type": "application/json", "cache-control": "no-store", ...cors, ...(extra || {}) } });
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
      if (request.method !== "POST") return jsonOut(405, { error: "POST only", code: "method-not-allowed" });
      if (!originOk) return jsonOut(403, { error: "forbidden origin", code: "forbidden-origin" });
      const session = request.headers.get("x-vyomi-session") || "";
      if (!/^[A-Za-z0-9._-]{1,80}$/.test(session)) return jsonOut(401, { error: "missing session", code: "unauthorized" });
      const has = await env.RELAY.get(env.RELAY.idFromName(session)).fetch("https://do/has-tab", { headers: { "X-Relay-Mode": "has-tab" } });
      if (!has.ok) return jsonOut(401, { error: "no Nano tab is registered for this session", code: "unauthorized" });
      if (env.GW_LIMIT) { const { success } = await env.GW_LIMIT.limit({ key: session }); if (!success) return jsonOut(429, { error: "gateway egress rate limited", code: "rate-limited" }, { "retry-after": "30" }); }
      const raw = await request.text();
      if (raw.length > Math.ceil(LIMITS.hosted.reqBody * 4 / 3) + 4096) return jsonOut(413, { error: "request body too large", code: "too-large" });
      let payload; try { payload = JSON.parse(raw); } catch (_) { return jsonOut(400, { error: "body must be JSON", code: "bad-request" }); }
      const allow = env.GW_EGRESS_ALLOW ? String(env.GW_EGRESS_ALLOW).split(",").map((x) => x.trim()).filter(Boolean) : undefined;
      const o = await serveGwEgress({ mode: "hosted", payload, allow, transport: workerTransport, limiter: gwLimiter, who: session,
        log: (e) => console.log("gw-egress " + JSON.stringify(e)) });
      return new Response(o.body, { status: o.status, headers: { ...o.headers, "cache-control": "no-store", ...cors } });
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

    if (mode === "has-tab") return this._tab() ? new Response("yes") : new Response("no", { status: 404 });

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
