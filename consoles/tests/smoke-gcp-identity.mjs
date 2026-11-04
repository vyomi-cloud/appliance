/* GCP-03 smoke: Cloud SQL (custom shape / SSL mode / CMEK), GCS (turbo / Autoclass / CMEK), Workload Identity provider dialog and
 * org-policy simulation are real controls - none is a "Not simulated" panel - and the SQL create + org simulate round-trips work.
 *   BASE=http://127.0.0.1:9130 node consoles/tests/smoke-gcp-identity.mjs
 *   BASE=http://127.0.0.1:8830 UI_PATH=/nano/v4/gcp/ WIRE_PATH=/nano/_wire NANO=1 node consoles/tests/smoke-gcp-identity.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9130";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-identity";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1500 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (40[034]|412)/.test(m.text()) && errors.push(m.text()));
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const wj = async (path, init) => { const r = await wire(path, init); try { return JSON.parse(r.text || "{}"); } catch { return { raw: r.text }; } };
const J = { "content-type": "application/json" };
const P = "vyomi-project";
const ns = () => page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated")));
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });

  // Cloud SQL create form
  await page.goto(UI + "#/sql/create/instance");
  await page.getByText("Customize your instance").waitFor();
  await page.getByLabel("Custom", { exact: true }).check();
  await page.getByLabel("vCPUs").waitFor();
  await page.getByLabel("SSL mode").click();
  await page.getByRole("option", { name: "Allow only SSL connections" }).click();
  await page.getByLabel("Use a customer-managed encryption key (CMEK)").check();
  await page.getByLabel("Cloud KMS key").waitFor();
  check("sql: custom shape, SSL mode and CMEK controls render, no Not-simulated for them", !(await ns()).some((t) => /Custom machine|SSL|KMS/.test(t)), (await ns()).join("|"));
  const iname = `sql-${N}`;
  await page.getByLabel("Instance ID").fill(iname).catch(() => page.getByLabel(/Instance (ID|name)/).fill(iname));
  await page.getByLabel(/^Password|Root password/).first().fill("Passw0rd!x");
  await page.getByLabel("vCPUs").fill("2"); await page.getByLabel("Memory (MB)").fill("7680");
  await page.getByRole("button", { name: "Create instance" }).click();
  await page.waitForURL(/#\/sql\/instances\//, { timeout: 20000 });
  const inst = await wj(`/sql/v1beta4/projects/${P}/instances/${iname}`);
  check("sql: instance created with custom tier + ENCRYPTED_ONLY", inst.settings?.tier === "db-custom-2-7680" && inst.settings?.ipConfiguration?.sslMode === "ENCRYPTED_ONLY", JSON.stringify(inst.settings?.tier));
  const bad = await wire(`/sql/v1beta4/projects/${P}/instances`, { method: "POST", headers: J, body: JSON.stringify({ name: `bad-${N}`, settings: { tier: "db-custom-3-7680" } }) });
  check("sql: an invalid custom shape is rejected by the API (400)", bad.status === 400, bad.status);

  // GCS create form
  await page.goto(UI + "#/storage/create-bucket");
  await page.getByLabel("Automatically transition objects to colder classes based on access").waitFor();
  check("gcs: Autoclass control present, no Not-simulated for turbo/Autoclass/CMEK", !(await ns()).some((t) => /Autoclass|turbo|CMEK|key/i.test(t)), (await ns()).join("|"));

  // Workload Identity provider dialog
  await wire(`/v1/projects/${P}/locations/global/workloadIdentityPools?workloadIdentityPoolId=pool-${N}`, { method: "POST", headers: J, body: "{}" });
  await page.goto(UI + "#/iam-admin/workload-identity-pools");
  await page.getByRole("button", { name: "Add provider" }).first().click();
  await page.getByLabel("Provider ID").waitFor();
  check("wif: Add provider dialog opens with OIDC/SAML/AWS types", (await page.getByLabel("Amazon Web Services (AWS)").count()) === 1);
  await page.keyboard.press("Escape");

  // Org policy simulation
  await page.goto(UI + "#/iam-admin/orgpolicies");
  await page.getByRole("button", { name: "Simulate constraint" }).click();
  check("org policy: simulation panel renders, not a Not-simulated stub", !(await ns()).some((t) => /simulat/i.test(t)), (await ns()).join("|"));
  const sim = await wire(`/v2/projects/${P}/policies:simulate`, { method: "POST", headers: J, body: JSON.stringify({ constraint: "constraints/iam.disableServiceAccountKeyCreation", enforce: true }) });
  check("org policy: policies:simulate returns 200", sim.status === 200, sim.text);
  await page.screenshot({ path: `${OUT}/orgpolicy.png` });
} catch (e) { check("smoke ran to completion", false, e.message); }
check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
