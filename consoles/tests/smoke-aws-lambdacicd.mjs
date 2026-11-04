/* Lambda CI/CD pipeline application: create from the wizard tab, see the pipeline deploy a real function, push, redeploy.
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-lambdacicd.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const N = Date.now() % 100000, APP = `cicd${N}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/lambda/aws4_request, SignedHeaders=host, Signature=0`;
const REST = (m, path, body) => page.evaluate(async ([u, a, m, p, b]) => {
  const r = await fetch(u + p, { method: m, headers: { authorization: a, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  const t = await r.text(); return { status: r.status, text: t };
}, [WIRE, auth, m, path, body]);
await page.goto(UI + "#/lambda/create/application"); await page.waitForTimeout(2000);
check("CI/CD tab is a real form, not a not-simulated panel", await page.getByLabel("Pipeline application name").count() === 1 && await page.locator("[data-vyomi-not-simulated]").count() === 0);
await page.getByLabel("Pipeline application name").fill(APP);
await page.getByRole("button", { name: "Create application" }).first().click(); await page.waitForTimeout(2500);
await page.goto(UI + "#/lambda/applications"); await page.waitForTimeout(2000);
check("applications table shows the pipeline Succeeded (v1)", await page.getByText(/Succeeded \(v1\)/).count() >= 1);
let inv = await REST("POST", `/2015-03-31/functions/${APP}/invocations`, {});
check("the deployed function runs the starter code", /version 1/.test(inv.text), inv.text);
const push = await REST("POST", `/2015-03-31/applications/${APP}/pipeline/push`, { Files: { "app.py": 'def handler(e, c):\n    return {"body": "ui-shipped v2"}\n' }, Message: "v2" });
check("push accepted", push.status === 200, push.text);
inv = await REST("POST", `/2015-03-31/functions/${APP}/invocations`, {});
check("push redeployed the function (v2)", /ui-shipped v2/.test(inv.text), inv.text);
await page.reload(); await page.waitForTimeout(2000);
check("UI shows version 2", await page.getByText(/Succeeded \(v2\)/).count() >= 1);
await page.getByRole("checkbox").nth(1).check().catch(() => {}); await page.waitForTimeout(300);
const rel = page.getByRole("button", { name: "Release change" });
check("Release change enabled for a pipeline app", await rel.isEnabled().catch(() => false));
await rel.click(); await page.waitForTimeout(1500);
const ex = JSON.parse((await REST("GET", `/2015-03-31/applications/${APP}/pipeline/executions`)).text).Executions;
check("manual release recorded a third execution", ex.length >= 3 && ex[0].Trigger === "manual", ex.length);
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
