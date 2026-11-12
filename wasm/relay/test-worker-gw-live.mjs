/* Hosted-relay policy against the REAL worker.js running under `wrangler dev` (workerd, local, NOT deployed).
 *   wrangler dev -c <toml: ALLOWED_ORIGIN=https://vyomi.cloud, GW_EGRESS_ALLOW=example.com> --port 8787 --local
 *   WS_PKG=<ws dir> BASE=http://127.0.0.1:8787 node wasm/relay/test-worker-gw-live.mjs
 * Needs outbound internet for the one allowed public host (example.com). */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const BASE = process.env.BASE || "http://127.0.0.1:8787", OK = "https://vyomi.cloud";
let fails = 0; const check = (n, ok, x) => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " :: " + String(x).slice(0, 300)}`); if (!ok) fails++; };
const post = async (body, h = {}) => { const r = await fetch(BASE + "/gw-egress", { method: "POST", headers: { "content-type": "application/json", origin: OK, ...h }, body: typeof body === "string" ? body : JSON.stringify(body) }); const t = await r.text(); let j; try { j = JSON.parse(t); } catch { j = t; } return { s: r.status, j }; };
const sid = "live" + Date.now();
const call = (url, extra) => post({ method: "GET", url, headers: {}, ...(extra || {}) }, { "x-vyomi-session": sid });
let r = await fetch(BASE + "/gw-egress"); check("GET refused (405)", r.status === 405);
r = await post({ method: "GET", url: "https://example.com/" }, { origin: "https://evil.example" }); check("foreign Origin refused (403)", r.s === 403, JSON.stringify(r));
r = await fetch(BASE + "/gw-egress", { method: "POST", body: "{}" }); check("no Origin refused (403)", r.status === 403);
r = await post({ method: "GET", url: "https://example.com/" }); check("no session header -> 401", r.s === 401, JSON.stringify(r));
r = await call("https://example.com/"); check("session with NO registered Nano tab -> 401", r.s === 401, JSON.stringify(r));
// register a tab for the session exactly as the Nano page does (Origin = the prod apex)
const ws = new WS(`${BASE.replace("http", "ws")}/register?session=${sid}`, { headers: { Origin: OK } });
await new Promise((res, rej) => { ws.on("open", res); ws.on("error", rej); setTimeout(() => rej(new Error("register timeout")), 8000); }).catch((e) => check("tab registered on the worker", false, e));
const wsr = new WS(`${BASE.replace("http", "ws")}/register?session=x${sid}`, { headers: { Origin: "https://evil.example" } });
const bad = await new Promise((res) => { wsr.on("open", () => res("open")); wsr.on("unexpected-response", (_q, p) => res(p.statusCode)); wsr.on("error", () => res("err")); setTimeout(() => res("timeout"), 5000); });
check("/register from a foreign Origin refused (403)", bad === 403, bad);
await new Promise((r) => setTimeout(r, 500));
r = await call("https://example.com/"); check("allow-listed public host via a registered session -> 200 with a real body", r.s === 200 && r.j.status === 200 && Buffer.from(r.j.body, "base64").toString().includes("Example Domain"), JSON.stringify(r).slice(0, 300));
r = await call("https://not-allowed.test/"); check("host not on the allow-list -> 403", r.s === 403 && r.j.code === "blocked", JSON.stringify(r));
r = await call("http://example.com/"); check("http (not https) -> 403", r.s === 403, JSON.stringify(r));
r = await call("https://example.com:8443/"); check("non-443 port -> 403", r.s === 403, JSON.stringify(r));
r = await call("https://127.0.0.1/"); check("IP literal / loopback -> 403", r.s === 403, JSON.stringify(r));
r = await call("https://169.254.169.254/latest/meta-data/"); check("cloud metadata IP -> 403", r.s === 403, JSON.stringify(r));
r = await call("https://localhost/"); check("internal name -> 403", r.s === 403, JSON.stringify(r));
r = await call("https://user:pw@example.com/"); check("credentials in URL refused (400 bad-url)", r.s === 400 && r.j.code === "bad-url", JSON.stringify(r));
r = await post({ method: "CONNECT", url: "https://example.com/" }, { "x-vyomi-session": sid }); check("CONNECT method refused", r.s >= 400 && r.s < 500, JSON.stringify(r));
r = await post("not json", { "x-vyomi-session": sid }); check("non-JSON body -> 400", r.s === 400, JSON.stringify(r));
r = await post({ method: "POST", url: "https://example.com/", body: Buffer.alloc(2 * 1024 * 1024).toString("base64") }, { "x-vyomi-session": sid }); check("oversize request body refused (413)", r.s === 413, JSON.stringify(r).slice(0, 200));
r = await call("https://example.com/", { headers: { "x-forwarded-for": "1.2.3.4", cookie: "a=b", authorization: "Bearer t" } }); check("request with hop/cookie headers still works (stripped)", r.s === 200, JSON.stringify(r).slice(0, 200));
let limited = false; for (let i = 0; i < 70 && !limited; i++) { const x = await call("https://example.com/"); if (x.s === 429) limited = true; }
check("per-session rate limit kicks in (429)", limited);
ws.close(); console.log(fails ? "\nFAIL" : "\nPASS - hosted relay policy under wrangler dev"); process.exit(fails ? 1 : 0);
