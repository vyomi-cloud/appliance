/* Step Functions active tracing -> X-Ray traces, and SNS mobile push gateway inbox, over the native wire (Nano or offline).
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-xraytrace-pushinbox.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/states/state-machines"); await page.waitForTimeout(2500);
const J = (svc, target, body) => page.evaluate(async ([u, a, t, b]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.0" }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, body: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth(svc), target, body]);
const REST = (svc, path, body) => page.evaluate(async ([u, a, p, b]) => {
  const r = await fetch(u + p, { method: "POST", headers: { authorization: a, "content-type": "application/json" }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, body: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth(svc), path, body]);
const Q = (svc, action, p) => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body });
  return await r.text();
}, [WIRE, auth(svc), new URLSearchParams({ Action: action, Version: "2010-03-31", ...p }).toString()]);

// Step Functions tracing -> X-Ray
const def = JSON.stringify({ StartAt: "A", States: { A: { Type: "Pass", Next: "B" }, B: { Type: "Succeed" } } });
const role = "arn:aws:iam::000000000000:role/sfn";
const sm = (await J("states", "AWSStepFunctions.CreateStateMachine", { name: `traced${N}`, definition: def, roleArn: role, tracingConfiguration: { enabled: true } })).body.stateMachineArn;
const ex = (await J("states", "AWSStepFunctions.StartExecution", { stateMachineArn: sm, name: "e1" })).body.executionArn;
const d = (await J("states", "AWSStepFunctions.DescribeExecution", { executionArn: ex })).body;
const tid = (d.traceHeader || "").match(/Root=([^;]+)/)?.[1];
check("DescribeExecution returns an X-Ray traceHeader", !!tid, d.traceHeader);
const tr = await REST("xray", "/Traces", { TraceIds: [tid] });
const doc = tr.body.Traces?.[0] && JSON.parse(tr.body.Traces[0].Segments[0].Document);
check("BatchGetTraces returns the execution's trace (segment + one subsegment per state)", doc?.name === `traced${N}` && doc.subsegments?.map((s) => s.name).join() === "A,B", JSON.stringify(tr.body).slice(0, 160));
const sum = await REST("xray", "/TraceSummaries", { StartTime: Date.now() / 1000 - 600, EndTime: Date.now() / 1000 + 60 });
check("GetTraceSummaries lists it", (sum.body.TraceSummaries || []).some((t) => t.Id === tid));
await page.goto(UI + `#/states/state-machines/traced${N}/executions/e1`); await page.waitForTimeout(2500);
check("execution page shows the X-Ray trace panel", await page.getByText("X-Ray trace").count() >= 1);

// SNS push gateway inbox
const app = (await Q("sns", "CreatePlatformApplication", { Name: `app${N}`, Platform: "GCM", "Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": "k" })).match(/<PlatformApplicationArn>(.*?)</)[1];
const ep = (await Q("sns", "CreatePlatformEndpoint", { PlatformApplicationArn: app, Token: "device-token-" + N })).match(/<EndpointArn>(.*?)</)[1];
await Q("sns", "Publish", { TargetArn: ep, Message: "hello phone" });
const inbox = await Q("sns", "VyomiListPushInbox", { EndpointArn: ep });
check("push gateway delivered the FCM payload to the endpoint inbox", inbox.includes("hello phone") && inbox.includes("&quot;data&quot;") || inbox.includes('"data"'), inbox.slice(0, 200));
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
