/* Portal-Nano booster flow (NO Create Space): Start/Stop live on the vyomi.cloud dashboard; Nano shows the session and routes
 * compute/AI to it. The portal's /api/booster/status is faked (page.route) and a tiny fake relay+booster answers the session
 * token plane. Checks: off / starting / running+connected / <15 min warning / compute+AI routed while emulators stay local /
 * unreachable / ended note / failed+action / not entitled -> no chip / session token never persisted.
 *   PW=<playwright path> node consoles/tests/booster-portal-smoke.mjs      Exit 1 on any FAIL. */
import http from "node:http";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const here = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8895), FAKE = Number(process.env.FAKE_PORT || 8896);
const NANO = `http://127.0.0.1:${PORT}/nano`;
let bad = 0; const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${ok || !d ? "" : " - " + String(d).slice(0, 160)}`); };

const TOK = "sess-token-" + Date.now(), wire = [];
const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*", "access-control-allow-private-network": "true" };
const fake = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x"); const send = (st, o) => { res.writeHead(st, { ...cors, "content-type": "application/json" }); res.end(JSON.stringify(o)); };
  if (req.method === "OPTIONS") { res.writeHead(204, cors); return res.end(); }
  if (req.headers["x-vyomi-session-token"] !== TOK) return send(401, { error: "bad session token" });
  if (u.pathname === "/booster/status") return send(200, { hostname: "cs-booster", healthy: true });
  if (u.pathname.startsWith("/_wire/")) { wire.push(u.pathname); return send(200, { ok: true, from: "booster" }); }
  send(404, {});
});
await new Promise((r) => fake.listen(FAKE, "127.0.0.1", r));
const preview = spawn("node", [join(here, "..", "nano_preview.mjs"), "--port", String(PORT)], { stdio: "ignore" });
for (let i = 0; i < 40; i++) { try { if ((await fetch(`${NANO}/`, { redirect: "manual" })).status < 500) break; } catch {} await new Promise((r) => setTimeout(r, 250)); }

const base = { entitled: true, tier: "pro", clouds: "one", primary_cloud: "aws", github: { connected: true, login: "octo" }, active: false, session: null,
  allowance_hours: 40, hours_used: 1, hours_remaining: 39, relay_url: "", error: null, ended_note: "" };
const running = (left = 25000) => ({ ...base, active: true, relay_url: `ws://127.0.0.1:${FAKE}/booster`,
  session: { id: 1, state: "running", countdown_seconds: left, session_token: TOK, session_end: new Date(Date.now() + left * 1000).toISOString() } });
let cur = { ...base };
const browser = await pw.chromium.launch(); const ctx = await browser.newContext(); const page = await ctx.newPage();
await ctx.addInitScript(() => { try { localStorage.setItem("vyomi.booster_poll_ms", "250"); } catch {} });
await page.route("**/api/booster/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(cur) }));
await page.route("**/api/account/booster**", (route) => route.fulfill({ status: 404, body: "no" }));
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const chip = () => page.evaluate(() => { const c = document.getElementById("vyb-chip"); return c ? { text: c.textContent, state: c.dataset.state, link: c.dataset.link, cls: c.className, href: (c.querySelector("a") || {}).getAttribute?.("href") } : null; });
const until = (fn, arg, t = 15000) => page.waitForFunction(fn, arg, { timeout: t }).then(() => true, () => false);
// local (non-routed) calls may be slow or hang in the preview SW: cap at 4 s and report {s:0,local:true}
const wireCall = (auth, path) => page.evaluate(async ([a, p]) => { const ac = new AbortController(), t = setTimeout(() => ac.abort(), 4000); try { const r = await fetch(p, { method: "POST", headers: { authorization: a }, signal: ac.signal }); let j = {}; try { j = await r.json(); } catch {} return { s: r.status, from: j.from, code: j.error && j.error.code }; } catch { return { s: 0, local: true }; } finally { clearTimeout(t); } }, [auth, path]);
const EC2 = "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=x";
const S3 = "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=x";

try {
  await page.goto(`${NANO}/clouds.html`);
  await until(() => !!window.VyomiBooster && !!navigator.serviceWorker.controller, null, 30000);
  await page.waitForTimeout(1500);
  await until(() => !!window.VyomiBooster && !!document.getElementById("vyb-chip"), null, 30000);
  let c = await chip();
  check("off: chip says Booster off + hours left, no Create Space needed", c && /Booster off/.test(c.text) && /39 h left/.test(c.text) && c.state === "off", JSON.stringify(c));

  cur = { ...base, active: true, session: { id: 1, state: "starting", countdown_seconds: 28000 } };
  check("starting: chip says starting", await until(() => /starting/.test((document.getElementById("vyb-chip") || {}).textContent || "")));

  cur = running(); 
  check("running: link connects through the relay (session token plane)", await until(() => VyomiBooster.state("vyomi-session") === "connected"));
  c = await chip();
  check("running: chip connected with countdown", c && c.state === "running" && /connected/.test(c.text) && /ends in 6h/.test(c.text), JSON.stringify(c));
  check("session token is NOT persisted to localStorage", await page.evaluate((t) => !JSON.stringify(Object.entries(localStorage)).includes(t), TOK));
  check("session booster is not exposed with its token", await page.evaluate(() => { const b = VyomiBooster.sessionBooster(); return !!b && b.token === undefined; }));

  wire.length = 0;
  const ec2 = await wireCall(EC2, `${NANO}/_wire/`);
  check("EC2 (compute) call is routed to the booster with the session token", ec2.s === 200 && ec2.from === "booster" && wire.length === 1, JSON.stringify([ec2, wire]));
  const lam = await wireCall("x", `${NANO}/_wire/compute/v1/projects/p/zones/z/instances`);
  check("GCP compute path routed", lam.from === "booster", JSON.stringify(lam));
  const ai = await wireCall("x", `${NANO}/_wire/subscriptions/s/resourceGroups/r/providers/Microsoft.CognitiveServices/accounts/a`);
  check("Azure AI path routed", ai.from === "booster", JSON.stringify(ai));
  const before = wire.length; const s3 = await wireCall(S3, `${NANO}/_wire/bucket/key`);
  check("S3 (emulator) call stays in the browser", wire.length === before && s3.from !== "booster", JSON.stringify([s3, wire.length]));

  cur = { ...running(600), session: { ...running(600).session, warning: "This session ends in under 15 minutes. A session cannot be extended; start a fresh one afterwards." } };
  check("warning shown under 15 minutes (no extend offered)", await until(() => /under 15 minutes/.test((document.getElementById("vyb-chip") || {}).textContent || "")));

  cur = { ...base, error: { code: "token_revoked", message: "GitHub access was revoked. Reconnect GitHub.", action: "reconnect" } };
  check("error state: message + action link to dashboard", await until(() => /revoked/.test((document.getElementById("vyb-chip") || {}).textContent || "")));
  c = await chip();
  check("error chip links to the dashboard booster section", c && /Reconnect GitHub/.test(c.text) && c.href === "/dashboard#booster-session", JSON.stringify(c));
  check("ended/failed: session booster dropped", await page.evaluate(() => VyomiBooster.sessionBooster() === null));
  wire.length = 0; const after = await wireCall(EC2, `${NANO}/_wire/`);
  check("after the session: compute is no longer sent to the booster", wire.length === 0 && after.from !== "booster", JSON.stringify(after));

  cur = { ...base, session: { id: 1, state: "ended", countdown_seconds: 0, reason: "ttl" }, ended_note: "Your 8-hour booster session ended. Start a new one to keep going." };
  check("ended by TTL: clear note", await until(() => /8-hour booster session ended/.test((document.getElementById("vyb-chip") || {}).textContent || "")));

  cur = running();
  await until(() => VyomiBooster.state("vyomi-session") === "connected");
  await new Promise((r) => fake.closeAllConnections?.() || r()); await new Promise((r) => fake.close(r));
  check("relay down: state unreachable", await until(() => VyomiBooster.state("vyomi-session") === "unreachable", null, 20000));
  const down = await wireCall(EC2, `${NANO}/_wire/`);
  check("relay down: compute call refused with DatacenterUnreachable (no silent local fallback)", down.s === 503 && down.code === "DatacenterUnreachable", JSON.stringify(down));

  cur = { ...base, entitled: false };
  check("not entitled (Free): no chip at all", await until(() => !document.getElementById("vyb-chip")));
  check("no page errors", errors.length === 0, errors.join(" | "));
} catch (e) { bad++; console.log("FAIL harness - " + (e && e.stack || e)); }
finally { await browser.close(); preview.kill(); try { fake.close(); } catch {} }
console.log(bad ? `${bad} FAILED` : "ALL PASS"); process.exit(bad ? 1 : 0);
