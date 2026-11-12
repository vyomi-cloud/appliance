/* IAM Role manager: UI <-> native IAM wire.  BASE=http://127.0.0.1:9101 node consoles/tests/smoke-aws-iam-rolemanager.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9101";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const N = Date.now() % 100000, ROLE = `rm-idle-${N}`, KEEP = `rm-keep-${N}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=0`;
const Q = (params) => page.evaluate(async ([u, a, p]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Version: "2010-05-08", ...p }).toString() });
  return { status: r.status, text: await r.text() };
}, [WIRE, auth, params]);
const trust = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: "lambda.amazonaws.com" }, Action: "sts:AssumeRole" }] });
await page.goto(UI + "#/iam");
await page.getByText("IAM").first().waitFor({ timeout: 30000 });
// UnusedDays=1 window + roles older than a day cannot be created through the wire, so an idle role is "New"; the UI must protect it.
for (const n of [ROLE, KEEP]) check(`create ${n}`, (await Q({ Action: "CreateRole", RoleName: n, AssumeRolePolicyDocument: trust })).status === 200);
await page.goto(UI + "#/iam/account-settings");
await page.getByText("Role manager").first().waitFor({ timeout: 15000 });
await page.getByText(ROLE).first().waitFor({ timeout: 15000 });
check("role listed with status", (await page.locator("body").innerText()).includes("New (not yet evaluated)"));
check("no Not-simulated badge on page", !/Not simulated/i.test(await page.locator("body").innerText()));
// delete through the UI: new role must be refused (server-side dependency/window check)
await page.getByRole("row").filter({ hasText: ROLE }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Delete selected unused roles" }).click();
await page.getByLabel("Delete selected roles").getByRole("button", { name: "Delete" }).click();
await page.getByText(/newer than the unused-days window/).first().waitFor({ timeout: 10000 });
check("new role refused by server", true);
const still = await Q({ Action: "GetRole", RoleName: ROLE });
check("role still exists", still.status === 200);
for (const n of [ROLE, KEEP]) await Q({ Action: "DeleteRole", RoleName: n });
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
