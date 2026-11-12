/* Gateway-backend egress for Nano (docs/architecture/v4.0/GATEWAY-NANO-FORWARDING.md).
 *
 * The Nano tab runs the API Gateway engine in Pyodide, which has no sockets. When a request matches a route, the engine hands the
 * backend call (method, url, headers, body) to the browser bridge (wasm/gw-bridge.js), which POSTs it HERE:
 *
 *   mode "local"  (wasm/relay/local-relay.mjs, `vyomi-tunnel`): ONLY origins the user mapped with
 *                 `vyomi-tunnel gateway-backend <https origin>=<local origin>`; anything else -> 502 not-mapped. Never an open proxy.
 *   mode "hosted" (wasm/relay/worker.js, relay.vyomi.cloud): PUBLIC https backends on an allow-list, 443 only, no IP literals,
 *                 no redirects, tight limits, and a registered Nano session is required.
 *
 * This module is runtime-neutral (no node imports): the policy lives here, the socket work is a pluggable `transport`
 * (wasm/relay/gw-egress-node.mjs for node, fetch for the Worker).
 *
 * Wire: POST {method,url,headers,body(base64),timeout} -> 200 {status,headers,body(base64)} (the BACKEND's answer, whatever its status)
 *       or a refusal  {error, code} with 400/401/403/405/413/429/502/504.
 * Redirects are NEVER followed: a 3xx from the backend is returned to the gateway verbatim (ESPv2 does the same), so a backend cannot
 * bounce the relay onto a private address.
 */

export const METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"];   // no CONNECT, no TRACE
export const LIMITS = {
  local: { reqBody: 6 * 1024 * 1024, respBody: 16 * 1024 * 1024, timeoutMs: 30000, perMinute: 240 },
  hosted: { reqBody: 1 * 1024 * 1024, respBody: 4 * 1024 * 1024, timeoutMs: 15000, perMinute: 60 },
};
const HOP_REQ = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te", "trailer", "trailers",
  "transfer-encoding", "upgrade", "host", "content-length", "cookie", "expect", "x-vyomi-gw-token", "x-vyomi-session"]);
const HOP_RESP = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te", "trailer", "trailers",
  "transfer-encoding", "upgrade", "content-length", "set-cookie", "set-cookie2"]);
export const stripRequestHeaders = (h) => {
  const out = {};
  for (const [k, v] of Object.entries(h || {})) { const lk = k.toLowerCase(); if (!HOP_REQ.has(lk) && !lk.startsWith("x-vyomi-") && typeof v === "string") out[lk] = v; }
  return out;
};
export const stripResponseHeaders = (h) => {
  const out = {};
  for (const [k, v] of Object.entries(h || {})) { const lk = k.toLowerCase(); if (!HOP_RESP.has(lk)) out[lk] = Array.isArray(v) ? v.join(", ") : String(v); }
  return out;
};

// ── address classification ───────────────────────────────────────────────────
const v4 = (ip) => { const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(ip); return m ? m.slice(1).map(Number) : null; };
/** true when `ip` (v4 or v6 literal) is loopback / private / link-local / metadata / unspecified / CGNAT / multicast / reserved. */
export function isPrivateAddress(ip) {
  ip = String(ip || "").toLowerCase().replace(/^\[|\]$/g, "").split("%")[0];
  const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(ip); if (mapped) ip = mapped[1];
  const mappedHex = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(ip);
  if (mappedHex) { const a = parseInt(mappedHex[1], 16), b = parseInt(mappedHex[2], 16); ip = `${a >> 8}.${a & 255}.${b >> 8}.${b & 255}`; }
  const q = v4(ip);
  if (q) {
    const [a, b, c] = q;
    return a === 0 || a === 10 || a === 127 || a >= 224 || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 192 && b === 0 && c === 0) || (a === 198 && (b === 18 || b === 19));
  }
  if (ip.includes(":")) {
    if (ip === "::" || ip === "::1") return true;
    const first = ip.split(":")[0] || "0";
    const w = parseInt(first || "0", 16);
    return (w & 0xfe00) === 0xfc00 || (w & 0xffc0) === 0xfe80 || (w & 0xff00) === 0xff00 || ip.startsWith("64:ff9b:") || ip.startsWith("2001:db8");
  }
  return false;
}
/** link-local + cloud-metadata: refused even for a MAPPED (user-approved) local target. */
export function isMetadataAddress(ip) {
  ip = String(ip || "").toLowerCase().replace(/^\[|\]$/g, "").split("%")[0];
  const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(ip); if (mapped) ip = mapped[1];
  const q = v4(ip);
  if (q) return (q[0] === 169 && q[1] === 254) || q[0] === 0;
  return ip === "::" || /^fe[89ab][0-9a-f]:/.test(ip) || ip === "fd00:ec2::254";
}
const isIpLiteral = (h) => /^[\d.]+$/.test(h) || h.includes(":") || /^0x[0-9a-f]+$/i.test(h);
const INTERNAL_NAME = /(^|\.)(localhost|local|internal|localdomain|lan|home|corp|intranet|metadata\.google\.internal)$/;

// Public serverless / PaaS hosts a Nano user's backend is likely to live on. The hosted relay reaches ONLY these (+ env GW_EGRESS_ALLOW).
export const DEFAULT_HOSTED_ALLOW = [
  ".run.app", ".cloudfunctions.net", ".appspot.com",                       // GCP: Cloud Run, Functions, App Engine
  ".azurewebsites.net", ".azurecontainerapps.io", ".azure-api.net",        // Azure: App Service / Functions, Container Apps, APIM
  ".execute-api.amazonaws.com", ".lambda-url.on.aws", ".elasticbeanstalk.com",   // AWS (regional hosts end in .amazonaws.com; checked as suffix below)
  ".vercel.app", ".netlify.app", ".onrender.com", ".fly.dev", ".railway.app", ".herokuapp.com", ".workers.dev", ".pages.dev", ".deno.dev", ".glitch.me",
];
export const hostAllowed = (host, allow) => {
  host = String(host || "").toLowerCase().replace(/\.$/, "");
  return (allow || DEFAULT_HOSTED_ALLOW).some((d) => { d = d.toLowerCase(); return d.startsWith(".") ? host.endsWith(d) && host.length > d.length : host === d; })
    || /\.execute-api\.[a-z0-9-]+\.amazonaws\.com$/.test(host) || /\.lambda-url\.[a-z0-9-]+\.on\.aws$/.test(host);
};
/** Hosted-relay target rule. -> null if allowed, else the refusal reason. */
export function hostedTargetProblem(u, allow) {
  if (u.protocol !== "https:") return "https only";
  if (u.username || u.password) return "credentials in the URL are not allowed";
  if (u.port && u.port !== "443") return "port 443 only";
  const h = u.hostname.toLowerCase().replace(/\.$/, "");
  if (isIpLiteral(h) || INTERNAL_NAME.test(h) || isPrivateAddress(h)) return "private, loopback and IP-literal targets are blocked";
  if (!hostAllowed(h, allow)) return `${h} is not on the hosted relay's backend allow-list`;
  return null;
}
export const originOf = (u) => `${u.protocol}//${u.host}`;

// ── rate limit ───────────────────────────────────────────────────────────────
export function createRateLimiter(perMinute, now = () => Date.now()) {
  const hits = new Map();
  return { take(key) {
    const t = now(), arr = (hits.get(key) || []).filter((x) => t - x < 60000);
    if (arr.length >= perMinute) { hits.set(key, arr); return false; }
    arr.push(t); hits.set(key, arr);
    if (hits.size > 5000) for (const [k, v] of hits) if (!v.length || t - v[v.length - 1] > 60000) hits.delete(k);
    return true;
  } };
}

const json = (status, obj, extra) => ({ status, headers: { "content-type": "application/json", ...(extra || {}) }, body: JSON.stringify(obj) });
const refuse = (status, code, error, extra) => json(status, { error, code }, extra);
const b64 = {
  dec: (s) => { const bin = atob(String(s || "")); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; },
  enc: (bytes) => { let s = ""; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)); return btoa(s); },
};

/**
 * The policy core. `authorized` has already been decided by the caller (token + Origin / session); `who` is the rate-limit + log key.
 * @param {object} o
 *   mode          "local" | "hosted"
 *   payload       parsed JSON {method,url,headers,body,timeout}
 *   map           (local) {httpsOrigin: targetOrigin}
 *   allow         (hosted) host allow-list override
 *   transport     async ({method, url:URL, headers, body:Uint8Array|undefined, timeoutMs, maxBytes, pin}) -> {status, headers, body:Uint8Array}
 *                 throws {code:"timeout"|"too-large"|"blocked"|"failed", message}
 *   resolve       (local) async (hostname) -> [ip...]  (DNS), used to re-check a mapped target against metadata/link-local
 *   limiter, who, log
 * @returns {status, headers, body(string)}  an HTTP-ish answer for the relay to send
 */
export async function serveGwEgress(o) {
  const { mode, payload, map, allow, transport, resolve, limiter, who = "?", log = () => {} } = o;
  const lim = LIMITS[mode], t0 = Date.now();
  const note = (st, why, u) => { try { log({ mode, who, method: payload && payload.method, origin: u ? originOf(u) : "", path: u ? u.pathname : "", status: st, why: why || "", ms: Date.now() - t0 }); } catch (_) {} };
  if (limiter && !limiter.take(who)) { note(429, "rate"); return refuse(429, "rate-limited", "gateway egress rate limit reached; retry in a minute", { "retry-after": "30" }); }
  const method = String((payload && payload.method) || "GET").toUpperCase();
  if (!METHODS.includes(method)) { note(405, "method"); return refuse(405, "method-not-allowed", `${method} is not allowed`); }
  let u;
  try { u = new URL(String(payload.url || "")); } catch (_) { note(400, "bad-url"); return refuse(400, "bad-url", "invalid backend url"); }
  if (u.username || u.password) { note(400, "userinfo", u); return refuse(400, "bad-url", "credentials in the backend URL are not allowed"); }
  let body;
  if (payload.body) {
    if (String(payload.body).length > Math.ceil(lim.reqBody * 4 / 3) + 4) { note(413, "req-size", u); return refuse(413, "too-large", "request body too large"); }
    try { body = b64.dec(payload.body); } catch (_) { return refuse(400, "bad-body", "body is not base64"); }
    if (body.length > lim.reqBody) { note(413, "req-size", u); return refuse(413, "too-large", "request body too large"); }
    if (!body.length) body = undefined;
  }
  let target = u, pin = null;
  if (mode === "local") {
    const dst = map && Object.prototype.hasOwnProperty.call(map, originOf(u)) ? map[originOf(u)] : null;
    if (!dst) { note(502, "not-mapped", u); return refuse(502, "not-mapped", `backend ${originOf(u)} is not mapped. Run: vyomi-tunnel gateway-backend ${originOf(u)}=<local origin, e.g. http://127.0.0.1:3000>`); }
    let d; try { d = new URL(dst); } catch (_) { return refuse(502, "bad-map", "the mapping target is invalid"); }
    target = new URL(d.origin + u.pathname + u.search);
    const host = target.hostname.replace(/^\[|\]$/g, "");
    let ips = isIpLiteral(host) ? [host] : [];
    if (!ips.length && resolve) { try { ips = await resolve(host); } catch (_) { note(502, "dns", u); return refuse(502, "dns", `cannot resolve ${host}`); } }
    if (ips.some(isMetadataAddress)) { note(403, "metadata", u); return refuse(403, "blocked", "the mapped target resolves to a link-local / metadata address"); }
    pin = ips[0] || null;           // connect to the address we validated, not a second DNS answer (rebinding)
  } else {
    const why = hostedTargetProblem(u, allow);
    if (why) { note(403, why, u); return refuse(403, "blocked", why); }
  }
  const headers = stripRequestHeaders(payload.headers);
  const timeoutMs = Math.min(lim.timeoutMs, Math.max(1000, Math.round(Number(payload.timeout || 15) * 1000)));
  let r;
  try { r = await transport({ method, url: target, headers, body, timeoutMs, maxBytes: lim.respBody, pin, redirect: "manual" }); }
  catch (e) {
    const code = (e && e.code) || "failed";
    const st = code === "timeout" ? 504 : code === "too-large" ? 413 : code === "blocked" ? 403 : 502;
    note(st, code, u);
    return refuse(st, code === "failed" ? "unreachable" : code, code === "timeout" ? "backend timed out" : code === "too-large" ? "backend response too large" : `backend unreachable: ${String((e && e.message) || e).slice(0, 120)}`);
  }
  note(r.status, "ok", u);
  return json(200, { status: r.status, headers: stripResponseHeaders(r.headers), body: b64.enc(r.body || new Uint8Array(0)) });
}
