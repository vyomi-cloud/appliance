/* EventBridge Schemas (AWS-08): discovery from PutEvents + registry/schema UI. UI <-> native wire.
 *   BASE=http://127.0.0.1:9110 node consoles/tests/smoke-aws-ebschemas.mjs
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-ebschemas.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9110";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const BUS = `ebsc-${N}`, REG = `ebreg-${N}`, SCH = `ebsch-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const J = (svc, target, body) => page.evaluate(async ([u, a, t, b]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, json: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth(svc), target, body]);
const REST = (method, path) => page.evaluate(async ([u, a, m, p]) => {
  const r = await fetch(u + p, { method: m, headers: { authorization: a } }); const tx = await r.text(); return { status: r.status, json: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth("schemas"), method, path]);
const body = async () => await page.locator("body").innerText();

await page.goto(UI + "#/eventbridge");
await page.getByText("EventBridge").first().waitFor({ timeout: 30000 });

// create bus via UI with schema discovery on
await page.goto(UI + "#/eventbridge/create-event-bus");
await page.getByLabel("Name", { exact: true }).first().fill(BUS);
await page.getByText("Enable schema discovery on this event bus").click();
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(BUS).first().waitFor({ timeout: 15000 });
const d = await REST("GET", "/v1/discoverers");
check("discoverer created from create-bus form (wire)", (d.json.Discoverers || []).some((x) => x.SourceArn.endsWith("/" + BUS) && x.State === "STARTED"), JSON.stringify(d.json).slice(0, 120));

// events flow in -> schema discovered
await J("events", "AWSEvents.PutEvents", { Entries: [{ EventBusName: BUS, Source: "sc.test", DetailType: "Order Placed", Detail: JSON.stringify({ id: "1", total: 4.5, paid: true }) }] });
await page.goto(UI + "#/eventbridge/schemas");
await page.getByRole("heading", { name: "Schemas" }).first().waitFor({ timeout: 15000 });
await page.getByText("sc.test@OrderPlaced").first().waitFor({ timeout: 15000 }).catch(() => {});
check("discovered schema listed in UI", (await body()).includes("sc.test@OrderPlaced"));
await page.getByRole("button", { name: "sc.test@OrderPlaced" }).first().click();
await page.locator("pre[aria-label=\"Schema content\"]").waitFor({ timeout: 10000 });
const content = await page.locator("pre[aria-label=\"Schema content\"]").innerText();
check("schema viewer shows inferred properties", /total/.test(content) && /paid/.test(content), content.slice(0, 80));
await page.getByRole("button", { name: "Close" }).click();

// create registry + schema through the UI
await page.getByRole("button", { name: "Create a schema registry" }).click();
await page.getByLabel("Registry name").fill(REG);
await page.getByRole("button", { name: "Create registry" }).click();
await page.waitForTimeout(800);
const regs = await REST("GET", "/v1/registries");
check("registry created via UI (wire)", (regs.json.Registries || []).some((r) => r.RegistryName === REG));
await page.getByRole("button", { name: "Create schema", exact: true }).first().click();
const dlg = page.getByRole("dialog");
await dlg.getByRole("button", { name: /Registry/ }).first().click();
await page.getByRole("option", { name: REG }).click();
await dlg.getByLabel("Schema name").fill(SCH);
await dlg.getByRole("button", { name: "Create schema" }).click();
await page.waitForTimeout(800);
const sl = await REST("GET", `/v1/registries/name/${REG}/schemas`);
check("schema created via UI (wire)", (sl.json.Schemas || []).some((s) => s.SchemaName === SCH));
check("new schema shown in table", (await body()).includes(SCH));

// stop discoverer from UI
await page.getByRole("tab", { name: "Discovery" }).click();
await page.getByRole("row").filter({ hasText: BUS }).getByRole("button", { name: "Stop" }).click();
await page.waitForTimeout(800);
const d2 = await REST("GET", "/v1/discoverers");
check("discoverer stopped via UI (wire)", (d2.json.Discoverers || []).some((x) => x.SourceArn.endsWith("/" + BUS) && x.State === "STOPPED"));
check("no page errors", errors.length === 0, errors[0]);
await page.screenshot({ path: `${OUT}/ebschemas.png` });
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
