/* GCP leftovers smoke: Datastore mode page (create DB, create entity, GQL query, composite index, wire round-trip).
 *   PW=... BASE=http://127.0.0.1:9072 node consoles/tests/smoke-gcp-misc-datastore.mjs */
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
const wj = (path, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); const t = await r.text(); try { return { status: r.status, ...JSON.parse(t || "{}") }; } catch { return { status: r.status, raw: t }; } }, [WIRE + path, init]);
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project";
try {
  await page.goto(UI, { waitUntil: "networkidle" });
  await page.goto(UI + "#/datastore");
  await page.getByTestId("ds-empty").waitFor({ timeout: 20000 });
  check("datastore page is a real page (no Not-simulated panel)", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  await page.getByRole("button", { name: "Create a Datastore mode database" }).click();
  await page.getByRole("button", { name: "Create entity" }).first().waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "Create entity" }).first().click();
  await page.getByLabel("Kind").last().fill("Task");
  await page.getByLabel(/Key name or numeric id/).fill("t1");
  await page.getByLabel("Properties (JSON)").fill('{"title":"ship it","prio":2}');
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByText("Entity created").first().waitFor({ timeout: 15000 });
  await page.getByText("ship it").first().waitFor({ timeout: 15000 });
  const r = await wj(`/v1/projects/${P}:lookup`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ keys: [{ path: [{ kind: "Task", name: "t1" }] }] }) });
  check("entity visible over the Datastore wire", r.found?.[0]?.entity?.properties?.prio?.integerValue === "2");
  const bad = await wj(`/v1/projects/${P}:runQuery`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ gqlQuery: { queryString: "SELECT * FROM Task WHERE prio > 0 ORDER BY title", allowLiterals: true } }) });
  check("query needing a composite index fails like Datastore", bad.status === 400 && /no matching index/.test(bad.error?.message || ""));
  await page.getByRole("tab", { name: "Indexes" }).click();
  await page.getByRole("button", { name: "Create index" }).first().click();
  await page.getByLabel("Kind").last().fill("Task");
  await page.getByLabel(/Properties \(comma/).fill("prio, title");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText("READY").first().waitFor({ timeout: 15000 });
  const ok = await wj(`/v1/projects/${P}:runQuery`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ gqlQuery: { queryString: "SELECT * FROM Task WHERE prio > 0 ORDER BY title", allowLiterals: true } }) });
  check("same query succeeds once the index is READY", ok.status === 200);
  const dsAgainstNative = await wj(`/v1/projects/${P}/databases/(default)`, { method: "GET" });
  check("database is DATASTORE_MODE", dsAgainstNative.type === "DATASTORE_MODE");
} catch (e) { check("smoke ran", false, e.message); }
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
