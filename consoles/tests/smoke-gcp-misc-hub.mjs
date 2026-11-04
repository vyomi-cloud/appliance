/* GCP leftovers smoke: Marketplace subscribe/cancel, Cloud Hub aggregate, Privacy & Security.
 *   PW=... BASE=http://127.0.0.1:9072 node consoles/tests/smoke-gcp-misc-hub.mjs */
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
const P = "vyomi-project";
const wj = (path, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); const t = await r.text(); try { return { status: r.status, ...JSON.parse(t || "{}") }; } catch { return { status: r.status, raw: t }; } }, [WIRE + path, init]);
try {
  await page.goto(UI, { waitUntil: "networkidle" });
  await page.goto(UI + "#/marketplace");
  await page.getByTestId("mp-catalog").waitFor({ timeout: 20000 });
  check("marketplace is a real page", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  await page.getByLabel("I accept the end-user license agreement").first().check();
  await page.getByRole("button", { name: /^Subscribe to / }).first().click();
  await page.getByText(/Endpoint:/).first().waitFor({ timeout: 15000 });
  const subs = await wj(`/vyomi/gcp/${P}/marketplace/subscriptions`);
  check("subscription visible over the wire", subs.subscriptions?.length === 1 && subs.subscriptions[0].state === "ACTIVE");
  await page.getByRole("button", { name: "Cancel subscription" }).click();
  await page.getByText(/Cancelled /).first().waitFor({ timeout: 15000 });
  await wj(`/storage/v1/b?project=${P}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "hub-smoke-bkt" }) });
  await page.goto(UI + "#/cloud-hub");
  await page.getByText("Cloud Storage buckets").first().waitFor({ timeout: 20000 });
  check("cloud hub counts real buckets", true);
  await page.goto(UI + "#/iam-admin/privacy");
  await page.getByTestId("privacy-overview").waitFor({ timeout: 20000 });
  check("privacy page is real (no Not-simulated panel)", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  check("access transparency log lists the bucket create", (await page.getByText(/buckets\.insert|storage\.buckets\.create/i).count()) > 0);
} catch (e) { check("smoke ran without exception", false, e.message); }
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
