/* SNS SMS sandbox: the verification code appears in the simulated handset and verifies the number (AWS-13).
 *   BASE=http://127.0.0.1:9043 node consoles/tests/smoke-aws-snssmsinbox.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9043";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const PH = "+1555" + String(Date.now()).slice(-7);
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto(UI + "#/sns/mobile/text-messaging");
await page.getByRole("button", { name: "Add phone number" }).first().waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Add phone number" }).first().click();
await page.getByRole("textbox", { name: "Phone number" }).fill(PH);
await page.getByRole("button", { name: "Send code" }).click();
await page.getByText(PH).first().waitFor({ timeout: 10000 });
await page.locator("tr", { hasText: PH }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Verify phone number" }).click();
await page.getByText(/Use code \d{6}/).first().waitFor({ timeout: 10000 });
check("code shown in simulated handset", true);
await page.getByText(/Use code \d{6}/).first().click();
await page.getByRole("button", { name: "Verify", exact: true }).click();
await page.waitForTimeout(1000);
const st = await page.locator("tr", { hasText: PH }).first().innerText();
check("number is Verified after using the inbox code", /Verified/.test(st), st);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
