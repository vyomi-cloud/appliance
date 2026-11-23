/* Nano IAM hook: end-to-end + per-request overhead in the real browser build (Chrome, Pyodide).
 *
 *   NODE_PATH=/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules \
 *   NANO_DIR=<worktree>/wasm node wasm/ui-tests/iam/iam-hook-e2e.mjs
 *
 * The real map/evaluator (map_aws, aws_eval) and host adapters (iam_state_adapters) are on other WP branches, and modes/audit/gate/api on
 * origin/v4/iam-enforce-mesh. For every module the vendored manifest lacks, this script serves it through a Playwright route (the bundle on
 * disk is untouched): modes/audit/gate/api from that git ref (the REAL ones), map_aws/aws_eval/iam_state_adapters from ui-tests/iam/standin/
 * (STAND-INS, reported as such). Needs network for Pyodide (CDN) unless wasm/vendor/pyodide exists.
 */
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startServer, bootConsole, chromium, NANO_DIR } from "../lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url)), REPO = join(NANO_DIR, "..");
const { server, base } = await startServer(NANO_DIR);
const browser = await chromium.launch({ channel: process.env.CHROME_CHANNEL || "chrome" });
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) console.log("[console.error]", m.text().slice(0, 200)); });

const manifest = JSON.parse(readFileSync(join(NANO_DIR, "core/iam_engine/manifest.json"), "utf8"));
const served = {}, standins = [];
for (const f of ["modes.py", "audit.py", "gate.py", "api.py"]) if (!manifest.engine.includes(f)) {
  try { served[f] = execFileSync("git", ["show", "origin/v4/iam-enforce-mesh:core/iam_engine/" + f], { cwd: REPO, encoding: "utf8" }); }
  catch (_) { console.log("FAIL  cannot read " + f + " from origin/v4/iam-enforce-mesh"); process.exit(2); }
}
for (const f of ["map_aws.py", "aws_eval.py"]) if (!manifest.engine.includes(f)) { served[f] = readFileSync(join(HERE, "standin", f), "utf8"); standins.push(f); }
const coreExtra = {};
if (!(manifest.core || []).includes("iam_state_adapters.py")) { coreExtra["iam_state_adapters.py"] = readFileSync(join(HERE, "standin", "iam_state_adapters.py"), "utf8"); standins.push("iam_state_adapters.py"); }
console.log(standins.length ? "STAND-INS (not on this branch): " + standins.join(", ") : "real engine modules");
await page.route("**/core/iam_engine/manifest.json", (r) => r.fulfill({ contentType: "application/json",
  body: JSON.stringify({ ...manifest, engine: [...manifest.engine, ...Object.keys(served)], core: [...(manifest.core || []), ...Object.keys(coreExtra)] }) }));
for (const [f, t] of Object.entries(served)) await page.route("**/core/iam_engine/" + f, (r) => r.fulfill({ contentType: "text/plain", body: t }));
for (const [f, t] of Object.entries(coreExtra)) await page.route("**/core/" + f, (r) => r.fulfill({ contentType: "text/plain", body: t }));

const results = [];
const check = (name, ok, detail = "") => { results.push(!!ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + detail : ""}`); };
const SFX = Date.now().toString(36), BUCKET = "iam-" + SFX;

const inPage = async ({ BUCKET, phase, N }) => {
  const BASE = new URL(".", document.querySelector('script[src*="nano-boot"]')?.src || location.href).pathname.replace(/\/$/, "");
  const W = BASE + "/_wire";
  const AUTH = (k) => `AWS4-HMAC-SHA256 Credential=${k}/20261030/us-east-1/s3/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);
  const call = (k, m, p, body) => fetch(W + p, { method: m, body, headers: { authorization: AUTH(k) } });
  const iamApi = async (m, p, body) => { const x = await fetch(BASE + "/api/iam/aws" + p, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); return { s: x.status, b: await x.json().catch(() => null) }; };
  const pct = (a, q) => { const s = [...a].sort((x, y) => x - y); return +s[Math.min(s.length - 1, Math.floor(q * s.length))].toFixed(3); };
  const hook = globalThis.NanoIamHook, r = { hookInstalled: !!hook };
  if (phase === "off") {
    let x = await call("AKIAVYOMIDUMMY", "PUT", "/" + BUCKET); r.create = x.status;
    x = await call("AKIAVYOMIDUMMY", "PUT", "/" + BUCKET + "/k", "hello"); r.put = x.status;
    const t = []; for (let i = 0; i < N; i++) { const a = performance.now(); await call("AKIAREADONLY", "GET", "/" + BUCKET + "/k"); t.push(performance.now() - a); }
    r.getOff = { p50: pct(t, .5), p95: pct(t, .95) }; r.statsOff = { ...hook.stats };
    const q = { method: "GET", path: "/" + BUCKET + "/k", query: {}, headers: { authorization: AUTH("AKIAREADONLY") }, body_b64: "" };
    const a = performance.now(); for (let i = 0; i < 20000; i++) await hook.guard("aws", q); r.guardOffUs = +((performance.now() - a) / 20000 * 1000).toFixed(2);
    r.statsAfterGuardLoop = { ...hook.stats };
  }
  if (phase === "enforce") {
    r.getDefault = await iamApi("GET", "/enforcement");
    r.putSettings = await iamApi("PUT", "/enforcement", { services: { s3: "enforce" } });
    r.putBad = (await iamApi("PUT", "/enforcement", { space: "nope" })).s;
    const q = (k, m, p) => ({ method: m, path: p, query: {}, headers: { authorization: AUTH(k) }, body_b64: "" });
    const first = performance.now(); const d = await hook.guard("aws", q("AKIAREADONLY", "GET", "/" + BUCKET + "/k")); r.firstGuardMs = +(performance.now() - first).toFixed(1);
    r.firstAllowNull = d === null; r.statsFirst = { ...hook.stats };
    let x = await call("AKIAREADONLY", "GET", "/" + BUCKET + "/k"); r.roGet = x.status;
    x = await call("AKIAREADONLY", "PUT", "/" + BUCKET + "/k2", "x"); r.roPut = x.status; const body = await x.text(); r.roPutXml = body.includes("<Code>AccessDenied</Code>") && body.includes("s3:PutObject"); r.roPutCT = x.headers.get("content-type");
    x = await call("AKIANOTHING", "GET", "/" + BUCKET + "/k"); r.nothing = x.status;
    x = await call("AKIAVYOMIDUMMY", "PUT", "/" + BUCKET + "/k3", "y"); r.adminPut = x.status;
    x = await call("AKIAVYOMIDUMMY", "DELETE", "/locked-" + BUCKET); r.explicitDeny = x.status;
    x = await fetch(W + "/" + BUCKET + "/k"); r.unsignedConsole = x.status;
    x = await call("AKIAVYOMIDUMMY", "GET", "/" + BUCKET + "/k2"); r.k2Exists = x.status;
    const au = await iamApi("GET", "/audit?limit=50"); r.audit = (au.b.records || []).map((z) => z.decision + ":" + z.action); r.auditShape = au.b.records && au.b.records[0] && ["id", "ts", "cloud", "principal", "action", "resource", "mode", "decision"].every((k) => k in au.b.records[0]);
    r.catalog = await iamApi("GET", "/catalog/s3").then((z) => ({ s: z.s, err: z.b && z.b.error, simulated: z.b && z.b.vyomi && z.b.vyomi.simulated, has: !!(z.b && z.b.actions && z.b.actions.GetObject) }));
    r.evaluate = (await iamApi("POST", "/evaluate", { principal: { arn: "arn:aws:iam::000000000000:user/AKIAREADONLY" }, action: "s3:PutObject", resource: "arn:aws:s3:::b/k" })).b;
    const allowQ = q("AKIAREADONLY", "GET", "/" + BUCKET + "/k"), denyQ = q("AKIAREADONLY", "PUT", "/" + BUCKET + "/k");
    for (let i = 0; i < 50; i++) await hook.guard("aws", allowQ);
    // Chrome clamps performance.now() to ~0.1 ms: time batches of 20 calls and divide (p50/p95 over 30 batches)
    const batch = async (qq) => { const out = []; for (let b = 0; b < 30; b++) { const a = performance.now(); for (let i = 0; i < 20; i++) await hook.guard("aws", qq); out.push((performance.now() - a) / 20); } return out; };
    const ta = await batch(allowQ), td = await batch(denyQ); const c0 = hook.stats.calls;
    r.decisionAllow = { p50: pct(ta, .5), p95: pct(ta, .95) }; r.decisionDeny = { p50: pct(td, .5), p95: pct(td, .95) }; r.gateCallsPerGuard = (hook.stats.calls - c0) / 1;
    const t = []; for (let i = 0; i < N; i++) { const a = performance.now(); await call("AKIAREADONLY", "GET", "/" + BUCKET + "/k"); t.push(performance.now() - a); }
    r.getEnforce = { p50: pct(t, .5), p95: pct(t, .95) };
    const e2e = async () => { const t = []; for (let i = 0; i < 100; i++) { const a = performance.now(); await call("AKIAREADONLY", "GET", "/" + BUCKET + "/k"); t.push(performance.now() - a); } return { p50: pct(t, .5), p95: pct(t, .95) }; };
    r.e2eRounds = [];
    for (const mode of ["off", "enforce", "off", "enforce"]) { await iamApi("PUT", "/enforcement", mode === "off" ? {} : { services: { s3: "enforce" } }); r.e2eRounds.push([mode, await e2e()]); }
    await iamApi("PUT", "/enforcement", { services: { s3: "audit" } });
    x = await call("AKIAREADONLY", "PUT", "/" + BUCKET + "/k4", "z"); r.auditPut = x.status;
    await iamApi("PUT", "/enforcement", { services: { s3: "enforce" }, resources: { ["arn:aws:s3:::" + BUCKET + "/k5"]: "off" } });
    x = await call("AKIAREADONLY", "PUT", "/" + BUCKET + "/k5", "z"); r.resOffPut = x.status;
    r.cleared = (await iamApi("DELETE", "/audit")).b;
    r.afterClear = ((await iamApi("GET", "/audit")).b.records || []).length;
    await iamApi("PUT", "/enforcement", {});
    x = await call("AKIAREADONLY", "PUT", "/" + BUCKET + "/k6", "z"); r.backOffPut = x.status;
    await iamApi("PUT", "/enforcement", { services: { s3: "enforce" } });
  }
  if (phase === "reload") {
    await hook.ready; r.docAfterReload = hook.settings("aws");
    r.apiAfterReload = (await iamApi("GET", "/enforcement")).b;
    r.putAfterReload = (await call("AKIAREADONLY", "PUT", "/" + BUCKET + "/k7", "z")).status;
    await iamApi("PUT", "/enforcement", {});
  }
  return r;
};

async function boot() {
  await page.goto(base + "/clouds.html", { waitUntil: "domcontentloaded" });       // SW + fixtures first, so aws-console finds its AWS space
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 60000 });
  await bootConsole(page, base, "/aws-console.html");
  await page.waitForFunction(() => !!globalThis.NanoIamHook, null, { timeout: 90000 });
}
try {
  await boot();
  const N = 300;
  const o = await page.evaluate(inPage, { BUCKET, phase: "off", N }); console.log("off:", JSON.stringify(o));
  check("hook installed", o.hookInstalled);
  check("setup: bucket + object created while off", o.create === 200 && o.put === 200);
  check("OFF: zero gate calls, engine mounts and catalog fetches over the whole off phase (incl. 20k guard() calls)",
    o.statsOff.calls === 0 && o.statsAfterGuardLoop.calls === 0 && o.statsAfterGuardLoop.engine_mounts === 0 && o.statsAfterGuardLoop.catalog_fetches === 0, JSON.stringify(o.statsAfterGuardLoop));
  const e = await page.evaluate(inPage, { BUCKET, phase: "enforce", N }); console.log("enforce:", JSON.stringify(e));
  check("/api/iam/aws/enforcement: GET default off, PUT valid -> 200, PUT invalid -> 400", e.getDefault.s === 200 && e.getDefault.b.space === "off" && e.putSettings.s === 200 && e.putBad === 400);
  check("enforce: first call mounts engine + prefetches the s3 catalog lazily, allows", e.firstAllowNull && e.statsFirst.engine_mounts === 1 && e.statsFirst.catalog_fetches >= 1, `first call ${e.firstGuardMs} ms`);
  check("enforce: read-only key may GET (200)", e.roGet === 200);
  check("enforce: read-only key PUT -> 403 AccessDenied XML naming s3:PutObject (gate.denial_spec)", e.roPut === 403 && e.roPutXml, e.roPutCT);
  check("enforce: no-policy key GET -> 403", e.nothing === 403);
  check("enforce: admin PUT -> 200; explicit Deny on locked-* DeleteBucket -> 403", e.adminPut === 200 && e.explicitDeny === 403);
  check("enforce: credential-less (console) traffic not gated", e.unsignedConsole === 200);
  check("enforce: denied PUT never reached the core (k2 missing)", e.k2Exists === 404, String(e.k2Exists));
  check("audit: /api/iam/aws/audit lists allow/deny records in the Mesh record shape", e.auditShape && e.audit.some((z) => z.startsWith("deny:s3:PutObject")) && e.audit.some((z) => z.startsWith("allow:s3:GetObject")), JSON.stringify(e.audit.slice(0, 4)));
  check("/api/iam/aws/catalog/s3: catalog slice + vyomi block (simulated unknown without wasm/service-inventory.json)", e.catalog.s === 200 && e.catalog.has && (e.catalog.simulated === null || e.catalog.simulated === true), JSON.stringify(e.catalog));
  check("/api/iam/aws/evaluate: engine decision", e.evaluate && e.evaluate.allowed === false && e.evaluate.reason === "implicit_deny", JSON.stringify(e.evaluate));
  check("audit: would-deny PUT is allowed in audit mode", e.auditPut === 200);
  check("resource-level off beats service-level enforce", e.resOffPut === 200);
  check("DELETE /audit clears; PUT {} returns to off path (PUT allowed)", e.cleared.cleared === true && e.afterClear === 0 && e.backOffPut === 200);
  await page.reload({ waitUntil: "domcontentloaded" });
  await boot();
  const rl = await page.evaluate(inPage, { BUCKET, phase: "reload", N });
  check("settings persist across reload (IndexedDB) and still enforce", rl.docAfterReload && rl.docAfterReload.services.s3 === "enforce" && rl.apiAfterReload.services.s3 === "enforce" && rl.putAfterReload === 403, JSON.stringify(rl));
  console.log("\nOVERHEAD (ms, Chrome, Pyodide 0.26.2, N=" + N + "; " + (standins.length ? "STAND-IN map/evaluator/adapters + REAL gate/modes/audit" : "real engine") + ")");
  console.log(`  off path guard():             ${o.guardOffUs} us/request, 0 Python calls`);
  console.log(`  SDK GET end-to-end, hook OFF: p50 ${o.getOff.p50}  p95 ${o.getOff.p95}`);
  console.log(`  SDK GET end-to-end, ENFORCE:  p50 ${e.getEnforce.p50}  p95 ${e.getEnforce.p95}`);
  for (const [m, v] of e.e2eRounds) console.log(`  e2e GET (100 calls) mode=${m}: p50 ${v.p50}  p95 ${v.p95}`);
  console.log(`  decision only, allow:         p50 ${e.decisionAllow.p50}  p95 ${e.decisionAllow.p95}`);
  console.log(`  decision only, deny:          p50 ${e.decisionDeny.p50}  p95 ${e.decisionDeny.p95}`);
} catch (err) { console.log("FAIL  harness:", err.message); results.push(false); }
await browser.close(); server.close();
const ok = results.length > 0 && results.every(Boolean);
console.log(`\nRESULT: ${ok ? "PASS" : "FAIL"} (${results.filter(Boolean).length}/${results.length})`);
process.exit(ok ? 0 : 1);
