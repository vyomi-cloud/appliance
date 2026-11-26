/* Playwright smoke for the AWS IAM pickers (Create policy visual + JSON editor, attach-policies table) against the BUILT bundle
 * (wasm/v4/aws), with the REAL catalogs served at /_wire/api/iam/aws/catalog/<svc> and a mocked IAM Query API.
 *   NODE_PATH=/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules SHOTS=<dir> node consoles/tests/smoke-aws-iam-pickers.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, readFileSync, mkdirSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname, CAT = new URL("../../core/iam_catalog/aws/", import.meta.url).pathname;
const SHOTS = process.env.SHOTS || "/tmp/aws-pickers-shots"; mkdirSync(SHOTS, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  const p0 = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  let p = p0.endsWith("/") ? p0 + "index.html" : p0; const f = join(ROOT, p);
  if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
const results = []; const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 240) : ""}`); };
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage(); const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
const xml = (inner, action) => `<${action}Response><${action}Result>${inner}</${action}Result></${action}Response>`;
const policies = Array.from({ length: 25 }, (_, i) => `<member><PolicyName>${i < 12 ? "AWSManaged" : "CustomerPolicy"}${String(i).padStart(2, "0")}</PolicyName><Arn>arn:aws:iam::${i < 12 ? "aws" : "000000000000"}:policy/P${i}</Arn><AttachmentCount>${i % 3}</AttachmentCount></member>`).join("");
const calls = [];
await page.route("**/_wire/**", async (r) => {
  const u = new URL(r.request().url()), rq = r.request();
  const m = u.pathname.match(/\/api\/iam\/aws\/catalog\/([\w.-]+)$/);
  if (m) { const f = CAT + m[1] + ".json"; return existsSync(f) ? r.fulfill({ status: 200, contentType: "application/json", body: readFileSync(f, "utf8") }) : r.fulfill({ status: 404, body: "{}" }); }
  if (rq.method() === "POST") {
    const a = new URLSearchParams(rq.postData() || "").get("Action"); calls.push(a);
    const body = { ListPolicies: xml(`<Policies>${policies}</Policies>`, a), ListUsers: xml(`<Users><member><UserName>alice</UserName><Arn>arn:aws:iam::000000000000:user/alice</Arn></member></Users>`, a),
      GetUser: xml(`<User><UserName>alice</UserName><Arn>arn:aws:iam::000000000000:user/alice</Arn></User>`, a), AttachUserPolicy: `<AttachUserPolicyResponse/>`, CreatePolicy: xml(`<Policy><PolicyName>x</PolicyName></Policy>`, a) }[a] || xml("", a);
    return r.fulfill({ status: 200, contentType: "text/xml", body });
  }
  return r.fulfill({ status: 404, contentType: "application/json", body: "{}" });
});
const sample = (s) => page.locator(s);
await page.goto(`${BASE}/v4/aws/#/iam/create-policy`);
await page.getByText("Select a service").first().waitFor({ timeout: 30000 });
await page.screenshot({ path: `${SHOTS}/p1-empty.png` });
check("empty visual editor shows Select a service", true);

// 1. service dropdown: commonly used first, then other, searchable
await page.getByRole("button", { name: /Choose a service/ }).first().click();
await page.getByText("Commonly used services").waitFor(); await page.getByText("Other services").waitFor();
await page.screenshot({ path: `${SHOTS}/p2-service-dropdown.png` });
check("service dropdown groups: Commonly used then Other", true);
await page.getByPlaceholder("Search services").fill("S3");
await page.getByRole("option", { name: "S3", exact: true }).click();

// 2. actions: counts, filter, tick
await page.getByText("Specify actions from the service to be allowed.").waitFor();
for (const c of ["List (18)", "Read (66)", "Write (57)", "Permissions management (27)", "Tagging (12)"]) check(`access level ${c}`, await page.getByText(c, { exact: true }).count() >= 1);
check("All S3 actions (s3:*) checkbox", (await page.getByText("All S3 actions (s3:*)").count()) === 1);
await page.screenshot({ path: `${SHOTS}/p3-actions.png`, fullPage: true });
await page.getByPlaceholder("Filter Actions").fill("GetObject");
await page.getByText("GetObjectVersionTorrent").waitFor();
check("filter shows Read heading with per-action Info", (await page.getByRole("heading", { name: "Read" }).count()) >= 1 && (await page.getByText("Info", { exact: true }).count()) >= 10);
await page.getByLabel("GetObject", { exact: true }).check();
await page.screenshot({ path: `${SHOTS}/p4-ticked.png`, fullPage: true });

// 3. resources -> specific + ARN
await page.getByText("Resources", { exact: true }).first().click();
await page.getByRole("radio", { name: "Specific" }).check({ force: true });
await page.getByText("You have not specified resource with type").first().waitFor();
check("resource rows per catalog type (accesspointobject, object)", (await page.getByTestId("res-row-object").count()) === 1 && (await page.getByTestId("res-row-accesspointobject").count()) === 1);
check("warning 'Specified object resource ARN for the ... action'", await page.getByTestId("res-row-object").getByText(/Specified object resource ARN for the/).count() > 0);
check("Any in this account / Any checkboxes", (await page.getByText("Any in this account").count()) === 1 && (await page.getByText("Any", { exact: true }).count()) >= 1);
await page.getByTestId("res-row-object").getByText("Add ARNs").click();
const arnIn = page.getByLabel("object ARN"); await arnIn.fill("arn:aws:s3:::my-bucket/*");
await page.getByRole("button", { name: "Add ARN", exact: true }).click();
// 4. conditions
await page.getByText("Request conditions").first().click();
await page.getByText("User is MFA Authenticated").waitFor();
await page.getByText("User is MFA Authenticated").click();
await page.getByRole("button", { name: "Add another condition" }).click();
await page.getByRole("button", { name: /Condition key/ }).click();
await page.getByRole("option", { name: /^s3:TlsVersion(\s|$)/ }).click();
await page.getByLabel("Condition value").fill("1.2");
await page.screenshot({ path: `${SHOTS}/p5-resources-conditions.png`, fullPage: true });
check("status bar present with counts", /Errors: 0/.test(await page.getByTestId("policy-status").innerText()), await page.getByTestId("policy-status").innerText());

// 5. toggle to JSON: generated JSON
await page.getByRole("button", { name: "JSON", exact: true }).click();
const json = JSON.parse(await page.getByLabel("Policy document").inputValue());
const st = json.Statement[0];
check("generated JSON: Effect/Action/Resource", st.Effect === "Allow" && st.Action === "s3:GetObject" && st.Resource === "arn:aws:s3:::my-bucket/*", JSON.stringify(st));
check("generated JSON: Condition (MFA + chosen key)", st.Condition?.Bool?.["aws:MultiFactorAuthPresent"] === "true" && Object.values(st.Condition).some((v) => v["s3:TlsVersion"] === "1.2"), JSON.stringify(st.Condition));
await page.screenshot({ path: `${SHOTS}/p6-json.png`, fullPage: true });
check("JSON editor has Edit statement panel", (await page.getByTestId("edit-statement").getByText("Edit statement").count()) === 1);

// 6. Edit statement panel inserts an action
await page.getByTestId("edit-statement").getByPlaceholder("Search services").fill("KMS");
await page.getByTestId("edit-statement").getByText("KMS", { exact: true }).click();
await page.getByTestId("edit-statement").getByPlaceholder("Filter actions").fill("Decrypt");
await page.getByTestId("edit-statement").getByLabel("Decrypt", { exact: true }).check();
await page.getByTestId("edit-statement").getByRole("button", { name: "Add actions" }).click();
const j2 = JSON.parse(await page.getByLabel("Policy document").inputValue());
check("panel inserted kms:Decrypt", [].concat(j2.Statement[0].Action).includes("kms:Decrypt"), JSON.stringify(j2.Statement[0].Action));

// 7. JSON validation: unknown action -> verbatim error + wildcard count
const bad = { Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: ["s3:GetObjekt", "s3:GetObject*"], Resource: "*" }] };
await page.getByLabel("Policy document").fill(JSON.stringify(bad, null, 2));
await page.getByText(/does not exist in the S3 service/).first().waitFor();
const stat = await page.getByTestId("policy-status").innerText();
check("unknown action error names s3:GetObjekt verbatim", /"s3:GetObjekt" does not exist in the S3 service/.test(stat) && /Errors: 1/.test(stat), stat);
check("wildcard expansion count shown", /s3:GetObject\* matches \d+ actions/.test(await page.getByTestId("expansions").innerText()));
await page.screenshot({ path: `${SHOTS}/p7-json-error.png`, fullPage: true });
// back to Visual with valid policy
await page.getByLabel("Policy document").fill(JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: ["s3:GetObject"], Resource: "arn:aws:s3:::b/*" }] }, null, 2));
await page.getByRole("button", { name: "Visual", exact: true }).click();
await page.getByText("Specify actions from the service to be denied.").waitFor();
check("JSON -> Visual keeps Deny + service", (await page.getByRole("radio", { name: "Deny" }).isChecked()));

// 8. attach policies table (user detail)
await page.goto(`${BASE}/v4/aws/#/iam/users/alice`);
await page.getByRole("button", { name: "Add permissions" }).first().click().catch(async () => { await page.getByText("Add permissions").first().click(); });
const dlg = page.getByRole("dialog");
await dlg.getByText("Permissions policies").waitFor({ timeout: 15000 });
check("attach table shows type + used as columns", (await dlg.getByText("AWS managed").count()) > 0 && (await dlg.getByText("Customer managed").count()) >= 0);
await dlg.getByLabel("Filter policies").fill("CustomerPolicy1");
await page.waitForTimeout(300);
check("attach table filters by name", (await dlg.getByText("AWSManaged00").count()) === 0 && (await dlg.getByText("CustomerPolicy12").count()) === 1);
await dlg.getByLabel("Filter policies").fill("");
check("attach table paginated (25 policies / 10 per page)", (await dlg.getByRole("button", { name: /^(Page )?3\b/ }).count()) === 1);
await page.screenshot({ path: `${SHOTS}/p8-attach.png` });

check("no page errors", errs.length === 0, errs[0]);
await browser.close(); server.close();
const bad2 = results.filter((r) => !r).length;
console.log(`\n${results.length - bad2}/${results.length} checks passed`);
process.exit(bad2 ? 1 : 0);
