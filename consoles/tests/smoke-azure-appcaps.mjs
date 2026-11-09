/* Smoke: App Service Overview > Capabilities tab is a real (Vyomi-simulated, "Dev Simplified") page whose tiles
 * follow the app's ARM state.   BASE=http://127.0.0.1:9171 UI_PATH=/v4/azure/ node consoles/tests/smoke-azure-appcaps.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9171";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `cap-rg-${n}`, APP = `capapp${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const arm = (m, path, body, v = "2023-12-01") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const site = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`;
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: "domcontentloaded" }); await pg.waitForTimeout(2500);
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", site, { location: "eastus", properties: { httpsOnly: true, siteConfig: {} } });
await pg.goto(`${UI}#/appservices/${RG}/${APP}`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Capabilities" }).click(); await pg.waitForTimeout(1500);
ok("no not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
ok("Dev Simplified badge shown", (await pg.getByText("Dev Simplified").count()) > 0);
const tile = (t) => pg.getByTestId(`cap-${t}`);
ok("HTTPS only enabled", (await tile("HTTPS only").innerText()).includes("Enabled"));
ok("Deployment slots not configured initially", (await tile("Deployment slots").innerText()).includes("Not configured"));
await arm("PUT", `${site}/slots/staging`, {});
await pg.reload(); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Capabilities" }).click(); await pg.waitForTimeout(1500);
ok("slot tile follows ARM state", (await tile("Deployment slots").innerText()).includes("1 slot"), await tile("Deployment slots").innerText());
await b.close();
console.log(`${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
