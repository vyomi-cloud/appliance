/* CloudFormation registry (AWS-13): public extensions -> activate a module -> Modules tab; publisher registration. UI <-> native wire.
 *   BASE=http://127.0.0.1:9043 node consoles/tests/smoke-aws-cfnregistry.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9043";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const MOD = "Vyomi::Messaging::QueuePair::MODULE";
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/cloudformation/aws4_request, SignedHeaders=host, Signature=0`;
const CF = (action, p) => page.evaluate(async ([u, a, body]) => (await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body })).text(),
  [WIRE, auth, new URLSearchParams({ Action: action, Version: "2010-05-15", ...p }).toString()]);
// Poll the wire (not the DOM) for the effect of a click: "Activated" is also a static label on the page, so a text wait can pass before the call lands.
const until = async (fn, ms = 15000) => { const t0 = Date.now(); let v = await fn(); while (!v && Date.now() - t0 < ms) { await page.waitForTimeout(300); v = await fn(); } return v; };
await page.goto(UI + "#/cloudformation/registry/public-extensions");
await page.getByRole("heading", { name: "Registry: Public extensions" }).waitFor({ timeout: 30000 });
await page.getByRole("button", { name: /Extension type/ }).waitFor({ timeout: 60000 });
await page.getByRole("button", { name: /Extension type/ }).click();
await page.getByRole("option", { name: "Modules" }).click();
await page.getByText(MOD).first().waitFor({ timeout: 60000 });
check("public module catalog lists the Vyomi module", true);
await page.locator("tr", { hasText: MOD }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Activate", exact: true }).click();
await page.getByRole("button", { name: "Activate extension" }).click();
check("module activated on the wire", await until(async () => /Vyomi-Messaging-QueuePair-MODULE/.test(await CF("ListTypes", { Visibility: "PRIVATE", Type: "MODULE" }))));
await page.goto(UI + "#/cloudformation/registry/activated-extensions");
await page.getByRole("tab", { name: "Modules" }).waitFor({ timeout: 60000 });
await page.getByRole("tab", { name: "Modules" }).click();
await page.getByText(MOD).first().waitFor({ timeout: 60000 });
check("Modules tab shows the activated module", true);
await page.goto(UI + "#/cloudformation/registry/publisher");
await page.getByText("This account is not registered as a publisher.").waitFor({ timeout: 60000 });
await page.getByRole("button", { name: "Register publisher" }).click();
await page.getByText("I accept the publisher terms and conditions").click();
await page.getByRole("button", { name: "Register", exact: true }).click();
await page.getByText(/^[0-9a-f]{32}$/).first().waitFor({ timeout: 60000 });
check("publisher registered (ID shown)", /[0-9a-f]{32}/.test(await page.locator("body").innerText()));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
