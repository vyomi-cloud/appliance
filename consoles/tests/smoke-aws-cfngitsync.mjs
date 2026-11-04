/* CloudFormation Git sync: link a vyomi repo from the stack's Git sync tab, push, watch the stack get created/updated.
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-cfngitsync.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const N = Date.now() % 100000, STACK = `gsstack${N}`, REPO = `infra${N}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const CC = (op, body) => page.evaluate(async ([u, a, t, b]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.0" }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, body: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth("codeconnections"), "com.amazonaws.codeconnections.CodeConnections_20231201." + op, body]);
const CF = (action, p) => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body });
  return await r.text();
}, [WIRE, auth("cloudformation"), new URLSearchParams({ Action: action, Version: "2010-05-15", ...p }).toString()]);
const TPL = "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  Q:\n    Type: AWS::SQS::Queue\n";
await page.goto(UI + "#/cloudformation/stacks"); await page.waitForTimeout(1500);
await CF("CreateStack", { StackName: STACK, TemplateBody: "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  T:\n    Type: AWS::SNS::Topic\n" });
await page.goto(UI + `#/cloudformation/stacks/${STACK}`); await page.waitForTimeout(2000);
await page.getByRole("tab", { name: "Git sync" }).click(); await page.waitForTimeout(800);
check("Git sync tab is a real form, not a not-simulated panel", await page.getByRole("button", { name: "Link repository" }).count() === 1);
await page.getByLabel("Repository name").fill(REPO);
await page.getByRole("button", { name: "Link repository" }).click(); await page.waitForTimeout(2500);
check("linked: configuration shown", await page.getByText(`vyomi/${REPO}`).count() >= 1);
const link = (await CC("ListRepositoryLinks", {})).body.RepositoryLinks.find((l) => l.RepositoryName === REPO);
const push = await CC("VyomiPush", { RepositoryLinkId: link.RepositoryLinkId, Files: { "deployment.json": JSON.stringify({ "template-file-path": "t.yaml" }), "t.yaml": TPL }, Message: "sync" });
check("push accepted", push.status === 200, JSON.stringify(push.body));
const d = await CF("DescribeStacks", { StackName: STACK });
check("the stack was UPDATED from the repo (Topic -> Queue template)", /UPDATE_COMPLETE/.test(d), d.slice(0, 200));
const tpl = await CF("GetTemplate", { StackName: STACK });
check("stack template is the repository's", /AWS::SQS::Queue/.test(tpl));
await page.reload(); await page.waitForTimeout(2000);
await page.getByRole("tab", { name: "Git sync" }).click(); await page.waitForTimeout(1200);
check("UI shows SUCCEEDED sync + events", await page.getByText("SUCCEEDED").count() >= 1 && await page.getByText("Updating stack").count() >= 1);
check("not a not-simulated panel", await page.locator("[data-vyomi-not-simulated]").count() === 0);
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
