/* Cosmos account Browse blade (containers + real ARM throughput) and the list-page Restore dialog.
 *   PW=... BASE=http://127.0.0.1:9082 node consoles/tests/smoke-azure-azcosmosbrowse.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9082";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `cb-rg${n}`, AC = `cb${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2024-05-15") => wire(`/subscriptions/${SUB}${path}?api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
const acc = `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${AC}`;
const r = await arm("PUT", acc, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }], backupPolicy: { type: "Continuous", continuousModeProperties: { tier: "Continuous7Days" } } } });
check("account created", r.status < 300, r.text);
await arm("PUT", `${acc}/sqlDatabases/db1`, { properties: { resource: { id: "db1" } } });
const c = await arm("PUT", `${acc}/sqlDatabases/db1/containers/c1`, { properties: { resource: { id: "c1", partitionKey: { paths: ["/pk"], kind: "Hash" } }, options: { throughput: 700 } } });
check("container created", c.status < 300, c.text);

await page.goto(UI + `#/cosmos/${RG}/${AC}/browse`);
await page.getByRole("cell", { name: "c1", exact: true }).waitFor({ timeout: 15000 });
check("browse lists the container with its partition key", await page.getByRole("cell", { name: "/pk", exact: true }).count() > 0);
check("browse shows real throughput (700 RU/s)", await page.getByText("700 RU/s").count() > 0);
check("browse is no longer a not-simulated gap", await page.getByText(/not simulated/i).count() === 0);

await page.goto(UI + "#/cosmos");
await page.getByRole("button", { name: "Restore", exact: true }).click();
await page.getByRole("dialog").getByRole("radio", { name: `Select ${AC}` }).waitFor({ timeout: 15000 });
check("restore dialog lists the continuous-backup account", true);
await page.waitForTimeout(2000);
await page.getByRole("dialog").getByRole("radio", { name: `Select ${AC}` }).check();
await page.getByRole("dialog").getByLabel("Resource group", { exact: true }).fill(RG);
await page.getByRole("dialog").getByRole("button", { name: "Restore", exact: true }).click();
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 8000 }).catch(async () => { console.log("DIALOG:", (await page.getByRole("dialog").innerText()).slice(0, 400)); });
const g = await arm("GET", `${acc}-restored`);
check("restored account exists", g.status === 200, g.text);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
