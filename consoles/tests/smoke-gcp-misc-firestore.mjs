/* GCP leftovers smoke: Firestore security rules — publish through the page, client-SDK style request enforced on the wire.
 *   PW=... BASE=http://127.0.0.1:9072 node consoles/tests/smoke-gcp-misc-firestore.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9072";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const wj = (path, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); const t = await r.text(); return { status: r.status, text: t }; }, [WIRE + path, init]);
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project";
const D = `/v1/projects/${P}/databases/(default)/documents`;
const jwt = (uid) => { const b = (o) => Buffer.from(JSON.stringify(o)).toString("base64url"); return `${b({ alg: "none" })}.${b({ iss: "https://securetoken.google.com/" + P, sub: uid, user_id: uid })}.`; };
const RULES = `rules_version = '2';\nservice cloud.firestore {\n  match /databases/{database}/documents {\n    match /notes/{id} {\n      allow read, write: if request.auth != null && request.auth.uid == id;\n    }\n  }\n}`;
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.goto(UI + "#/firestore/create-database");
  await page.getByText("Security rules").first().waitFor();
  check("create-database has no rules-enforcement Not-simulated panel", (await page.locator("[data-vyomi-not-simulated='Security rules enforcement']").count()) === 0);
  await wj(`${D}/notes/alice`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ fields: { t: { stringValue: "x" } } }) });
  await page.goto(UI + "#/firestore/databases/(default)/rules");
  const ed = page.getByLabel("Rules editor");
  await ed.waitFor();
  await ed.fill(RULES);
  await page.getByRole("button", { name: "Publish" }).click();
  await page.getByText(/Rules published/).first().waitFor({ timeout: 15000 });
  await page.getByTestId("rules-history").first().waitFor({ timeout: 15000 }).catch(() => {});
  check("rules history lists the new ruleset", (await page.getByTestId("rules-history").count()) === 1);
  const ok = await wj(`${D}/notes/alice`, { headers: { authorization: "Bearer " + jwt("alice") } });
  const bad = await wj(`${D}/notes/alice`, { headers: { authorization: "Bearer " + jwt("mallory") } });
  const admin = await wj(`${D}/notes/alice`, { headers: { authorization: "Bearer owner" } });
  check("owner client allowed", ok.status === 200);
  check("other client denied PERMISSION_DENIED", bad.status === 403 && /PERMISSION_DENIED/.test(bad.text));
  check("admin bypasses", admin.status === 200);
  const bogus = await wj(`/v1/projects/${P}/databases/(default):updateSecurityRules`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ rules: "service cloud.firestore {" }) });
  check("broken rules refused", bogus.status === 400);
} catch (e) { check("smoke ran", false, e.message); }
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
