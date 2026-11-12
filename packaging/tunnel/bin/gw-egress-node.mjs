/* Node half of the gateway egress (see gw-egress.mjs): the backend map file, DNS, a size/time-capped transport that connects to the
 * address the policy validated (no second DNS answer), the local route handler, and the origin + token gate for browsers.
 *
 * Map file: ~/.vyomi/gateway-backends.json  {"version":1,"backends":{"https://hello-abc-uc.a.run.app":"http://127.0.0.1:3000"}}
 * written by `vyomi-tunnel gateway-backend`; re-read on every request (mtime-cached), so no relay restart is needed.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import https from "node:https";
import dns from "node:dns";
import crypto from "node:crypto";
import { serveGwEgress, createRateLimiter, LIMITS, isMetadataAddress, originOf } from "./gw-egress.mjs";

export const mapFile = (env = process.env) => env.VYOMI_GATEWAY_BACKENDS_FILE || path.join(env.VYOMI_HOME || path.join(os.homedir(), ".vyomi"), "gateway-backends.json");

export function loadMap(env = process.env) {
  let m = {};
  try { m = (JSON.parse(fs.readFileSync(mapFile(env), "utf8")).backends) || {}; } catch (_) { /* none */ }
  for (const pair of String(env.VYOMI_GATEWAY_BACKENDS || "").split(",").map((s) => s.trim()).filter(Boolean)) {
    const i = pair.indexOf("="); if (i > 0) m[pair.slice(0, i)] = pair.slice(i + 1);
  }
  return m;
}
export function saveMap(backends, env = process.env) {
  const f = mapFile(env);
  fs.mkdirSync(path.dirname(f), { recursive: true, mode: 0o700 });
  fs.writeFileSync(f, JSON.stringify({ version: 1, backends }, null, 2), { mode: 0o600 });
}
/** Validate one `<https origin>=<local origin>` pair. -> {from, to} or {error}. */
export function parseMapping(arg) {
  const i = String(arg || "").indexOf("=");
  if (i < 1) return { error: "expected <https origin>=<local origin>, e.g. https://hello-abc-uc.a.run.app=http://127.0.0.1:3000" };
  let a, b;
  try { a = new URL(arg.slice(0, i)); b = new URL(arg.slice(i + 1)); } catch (_) { return { error: "both sides must be URLs" }; }
  if (a.protocol !== "https:") return { error: "the backend (left side) must be an https origin, as written in the API config" };
  if (!/^https?:$/.test(b.protocol)) return { error: "the local target (right side) must be http or https" };
  if ((a.pathname !== "/" && a.pathname !== "") || a.search || a.username || b.username || (b.pathname !== "/" && b.pathname !== "") || b.search) return { error: "give origins only (scheme://host[:port], no path, query or credentials)" };
  if (isMetadataAddress(b.hostname.replace(/^\[|\]$/g, "")) || /(^|\.)metadata\.google\.internal$/.test(b.hostname)) return { error: "link-local / metadata addresses cannot be mapped" };
  return { from: a.origin, to: b.origin };
}

export const resolveAll = async (host) => (await dns.promises.lookup(host, { all: true })).map((a) => a.address);

/** Capped, pinned, no-redirect transport over node http(s). */
export function nodeTransport({ method, url, headers, body, timeoutMs, maxBytes, pin }) {
  return new Promise((resolve, reject) => {
    const mod = url.protocol === "https:" ? https : http;
    const opts = { method, headers: { ...headers, host: url.host }, timeout: timeoutMs, agent: false };
    if (pin) opts.lookup = (_h, _o, cb) => (_o && _o.all ? cb(null, [{ address: pin, family: pin.includes(":") ? 6 : 4 }]) : cb(null, pin, pin.includes(":") ? 6 : 4));
    if (url.protocol === "https:") opts.servername = url.hostname;
    const req = mod.request(url, opts, (res) => {
      const parts = []; let n = 0;
      res.on("data", (c) => { n += c.length; if (n > maxBytes) { reject(Object.assign(new Error("response too large"), { code: "too-large" })); req.destroy(); res.destroy(); } else parts.push(c); });
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: new Uint8Array(Buffer.concat(parts)) }));
      res.on("error", (e) => reject(Object.assign(e, { code: "failed" })));
    });
    const timer = setTimeout(() => { reject(Object.assign(new Error("timeout"), { code: "timeout" })); req.destroy(); }, timeoutMs);
    req.on("timeout", () => { reject(Object.assign(new Error("timeout"), { code: "timeout" })); req.destroy(); });
    req.on("error", (e) => { clearTimeout(timer); reject(Object.assign(e, { code: e.code === "timeout" ? "timeout" : "failed" })); });
    req.on("close", () => clearTimeout(timer));
    req.end(body ? Buffer.from(body) : undefined);
  });
}

const BASE_ORIGINS = [/^https:\/\/(www\.)?vyomi\.cloud$/, /^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/];
/** The local gateway-egress surface: a per-process token handed (via CORS-gated GET /gw-token) only to the Nano page's origin. */
export function createLocalGw({ env = process.env, resolve = resolveAll, transport = nodeTransport, log = (m) => console.log("[relay] " + m), token = crypto.randomBytes(24).toString("hex") } = {}) {
  const extra = String(env.VYOMI_GW_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const originOk = (o) => !!o && (BASE_ORIGINS.some((r) => r.test(o)) || extra.includes(o));
  const limiter = createRateLimiter(LIMITS.local.perMinute);
  const packaged = /^vyomi-tunnel/.test(path.basename(process.argv[1] || ""));   // the published CLI always runs signed in (packaging/tunnel/bin/vyomi-tunnel.mjs)
  const enabled = env.VYOMI_RELAY_AUTH === "1" || env.VYOMI_GW_EGRESS === "1" || packaged;   // the user's own CLI (signed in), or an explicit opt-in; never the appliance-bundled copy
  const send = (res, o, origin) => {
    res.writeHead(o.status, { ...o.headers, "access-control-allow-origin": origin || "*", "vary": "Origin", "access-control-allow-private-network": "true", "cache-control": "no-store" });
    res.end(o.body);
  };
  /** returns true when the request was handled */
  function http_(req, res, bodyBuf) {
    const p = new URL(req.url, "http://x").pathname;
    if (p !== "/gw-token" && p !== "/gw-egress") return false;
    const origin = req.headers.origin || "";
    const fail = (st, code, msg) => send(res, { status: st, headers: { "content-type": "application/json" }, body: JSON.stringify({ error: msg, code }) }, originOk(origin) ? origin : null);
    if (!enabled) { fail(501, "disabled", "gateway egress is off in this relay (start the signed-in `vyomi-tunnel`)"); return true; }
    if (!originOk(origin)) { fail(403, "forbidden-origin", "this page's origin may not use the gateway egress"); return true; }
    if (p === "/gw-token") { if (req.method !== "GET") fail(405, "method-not-allowed", "GET only"); else send(res, { status: 200, headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) }, origin); return true; }
    if (req.method !== "POST") { fail(405, "method-not-allowed", "POST only"); return true; }
    const given = String(req.headers["x-vyomi-gw-token"] || "");
    const ok = given.length === token.length && crypto.timingSafeEqual(Buffer.from(given), Buffer.from(token));
    if (!ok) { fail(401, "unauthorized", "missing or wrong gateway token (GET /gw-token first)"); return true; }
    if (bodyBuf.length > Math.ceil(LIMITS.local.reqBody * 4 / 3) + 4096) { fail(413, "too-large", "request body too large"); return true; }
    let payload; try { payload = JSON.parse(bodyBuf.toString("utf8")); } catch (_) { fail(400, "bad-request", "body must be JSON"); return true; }
    serveGwEgress({ mode: "local", payload, map: loadMap(env), transport, resolve, limiter, who: token.slice(0, 8), log: (e) => log("gw-egress " + JSON.stringify(e)) })
      .then((o) => send(res, o, origin), (e) => fail(500, "error", String(e && e.message || e)));
    return true;
  }
  return { http: http_, token, enabled };
}
