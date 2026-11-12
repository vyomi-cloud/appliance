/* IAM service access report (AWS-07): SCP detail page -> choose a target -> Generate report, driven against real
 * recorded activity (a user's access key makes a signed S3 call) and the native IAM/Organizations wire.
 *   BASE=http://127.0.0.1:9170 node consoles/tests/smoke-aws-accessreport.mjs
 *   BASE=http://127.0.0.1:8870 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-accessreport.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9170";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || ""}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 1300 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/iam");
const cred = (svc, akid = "VYOMICONSOLE") => `AWS4-HMAC-SHA256 Credential=${akid}/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wire = (svc, path, { method = "POST", target, ct, body = "", akid } = {}) => page.evaluate(async ([u, p, m, t, c, b, a]) => {
  const h = { authorization: a, "content-type": c }; if (t) h["x-amz-target"] = t;
  const r = await fetch(u + p, { method: m, headers: h, body: m === "GET" ? undefined : b }); return { status: r.status, text: await r.text() };
}, [WIRE, path, method, target || "", ct || "application/x-www-form-urlencoded", body, cred(svc, akid)]);
const org = (a, p) => wire("organizations", "/", { target: `AWSOrganizationsV20161128.${a}`, ct: "application/x-amz-json-1.1", body: JSON.stringify(p) }).then((r) => ({ ...r, json: JSON.parse(r.text || "{}") }));
const iam = (a, q) => wire("iam", "/", { body: `Action=${a}&Version=2010-05-08&${q}` });

let d = await org("DescribeOrganization", {});
if (d.status !== 200) await org("CreateOrganization", { FeatureSet: "ALL" });
const root = (await org("ListRoots", {})).json.Roots[0].Id;
const pol = (await org("CreatePolicy", { Name: `ar-scp-${N}`, Description: "d", Type: "SERVICE_CONTROL_POLICY",
  Content: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: ["s3:*", "sqs:*"], Resource: "*" }] }) })).json.Policy.PolicySummary.Id;
await org("AttachPolicy", { PolicyId: pol, TargetId: root });
await iam("CreateUser", `UserName=arUser${N}`);
const akid = /<AccessKeyId>(.*?)<\/AccessKeyId>/.exec((await iam("CreateAccessKey", `UserName=arUser${N}`)).text)?.[1];
check("user + access key created", !!akid);
const s3 = await wire("sqs", "/", { target: "AmazonSQS.ListQueues", ct: "application/x-amz-json-1.0", body: "{}", akid });
check("signed SQS call by the user succeeds (records activity)", s3.status === 200, s3.status);

await page.goto(UI + `#/iam/service-control-policies/ar-scp-${N}`);
await page.getByRole("button", { name: "Generate report" }).waitFor();
check("not the Not-simulated panel", !(await page.locator("[data-vyomi-gap-box]").count()));
await page.getByRole("button", { name: /Choose a target/ }).last().click();
await page.getByRole("option").first().click();
await page.getByRole("button", { name: "Generate report" }).click();
await page.getByText("COMPLETED").waitFor({ timeout: 10000 });
const t = await page.locator("body").innerText();
check("report lists the accessed service (SQS)", /Simple Queue Service/.test(t));
check("report is scoped to the SCP (EC2/DynamoDB absent)", !/Amazon DynamoDB|Amazon EC2/.test(t.split("Service access report")[1] || ""));
await page.screenshot({ path: `${OUT}/access-report.png`, fullPage: true });
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
