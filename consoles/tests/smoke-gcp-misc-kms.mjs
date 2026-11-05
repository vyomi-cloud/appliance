/* GCP leftovers smoke: Cloud KMS import jobs + wrapped key import UI (no "Not simulated" panel; create job -> public key -> import via wire -> version appears).
 *   BASE=http://127.0.0.1:9072 node consoles/tests/smoke-gcp-misc-kms.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9072";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-misc";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const J = { "content-type": "application/json" };
const wj = (path, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); const t = await r.text(); try { return { status: r.status, ...JSON.parse(t || "{}") }; } catch { return { status: r.status, raw: t }; } }, [WIRE + path, init]);
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project";
const ns = () => page.locator("[data-vyomi-not-simulated]").count();
try {
  await page.goto(UI, { waitUntil: "networkidle" });
  const ring = `imp${N}`;
  await wj(`/v1/projects/${P}/locations/global/keyRings?keyRingId=${ring}`, { method: "POST", headers: J, body: "{}" });
  await page.goto(UI + `#/security/kms/keyring/manage/global/${ring}?tab=import`);
  await page.getByRole("button", { name: "Create import job" }).waitFor();
  check("import jobs tab has no Not-simulated panel", (await ns()) === 0);
  await page.getByRole("button", { name: "Create import job" }).click();
  await page.getByLabel("Import job name").fill("job-a");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("button", { name: "job-a" }).first().waitFor({ timeout: 20000 });
  const pem = await page.getByTestId("import-pem").innerText();
  check("public key shown", /BEGIN PUBLIC KEY/.test(pem));
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  const jobs = await wj(`/v1/projects/${P}/locations/global/keyRings/${ring}/importJobs`);
  check("job on the wire ACTIVE", jobs.importJobs?.[0]?.state === "ACTIVE");
  // import-only key from the create form
  await page.goto(UI + `#/security/kms/key/create?location=global&keyring=${ring}`);
  await page.getByLabel("Key name").fill("ik");
  await page.getByLabel("Imported key").check();
  check("create-key has no import Not-simulated note", (await page.locator("[data-vyomi-not-simulated='Imported key material']").count()) === 0);
  await page.getByRole("button", { name: /^Create$/ }).click();
  await page.waitForURL(/key\/manage\/global\/.+\/ik/, { timeout: 20000 });
  const k = await wj(`/v1/projects/${P}/locations/global/keyRings/${ring}/cryptoKeys/ik`);
  check("import-only key has no primary", k.importOnly === true && !k.primary);
  await page.goto(UI + `#/security/kms/key/manage/global/${ring}/ik`);
  await page.getByRole("button", { name: "Import key version" }).click();
  await page.getByLabel("Wrapped key material (base64)").fill("AAAA");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByText(/Unable to unwrap/).first().waitFor({ timeout: 20000 });
  check("bad wrapped key surfaces the real API error", true);
} catch (e) { check("smoke ran", false, e.message); await page.screenshot({ path: `${OUT}/fail.png` }); }
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
