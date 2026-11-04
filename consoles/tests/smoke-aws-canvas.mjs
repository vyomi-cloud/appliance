/* Visual canvas kit (AWS-10): drives the three real canvases end to end and cross-checks over the native wires.
 *   CloudFormation Template Studio: add nodes, wire a dependency, edit text -> canvas, Validate, Create stack.
 *   EventBridge Builder: event + target nodes -> PutRule/PutTargets.
 *   Lambda Infrastructure Composer: function + queue wired -> stack + function + event source mapping.
 *
 *   BASE=http://127.0.0.1:9170 node consoles/tests/smoke-aws-canvas.mjs
 *   BASE=http://127.0.0.1:8870 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-canvas.mjs
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
const page = await browser.newPage({ viewport: { width: 1600, height: 1500 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const cred = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/cloudformation");
const wire = (svc, method, path, { target, ct = "application/x-amz-json-1.1", body = "" } = {}) =>
  page.evaluate(async ([u, svc, method, path, target, ct, body, a]) => {
    const h = { authorization: a, "content-type": ct }; if (target) h["x-amz-target"] = target;
    const r = await fetch(u + path, { method, headers: h, body: method === "GET" || method === "DELETE" ? undefined : body });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* xml */ }
    return { status: r.status, text: t, json: j };
  }, [WIRE, svc, method, path, target || "", ct, body, cred(svc)]);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const body = () => page.locator("body").innerText();
const drag = async (fromId, toId) => {
  const h = await page.locator(`[data-handle-out="${fromId}"]`).boundingBox();
  const t = await page.locator(`[data-node="${toId}"]`).boundingBox();
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2); await page.mouse.down();
  await page.mouse.move(t.x + 60, t.y + 20, { steps: 8 }); await page.mouse.up();
};
const nodeId = (type, i = 0) => page.locator(`[data-node-type="${type}"]`).nth(i).getAttribute("data-node");

// ── CloudFormation Template Studio ──────────────────────────────────────────
await page.goto(UI + "#/cloudformation/template-studio");
await page.getByRole("button", { name: "Add S3 Bucket" }).waitFor();
check("studio canvas is not the Not-simulated panel", !/Canvas isn't backed|Not simulated in Vyomi/i.test(await body()));
await page.getByRole("button", { name: "Add S3 Bucket" }).click();
await page.getByRole("button", { name: "Add SQS Queue" }).click();
const ta = page.getByLabel("Template editor");
let tpl = JSON.parse(await ta.inputValue());
check("canvas nodes serialise into the template", Object.values(tpl.Resources).map((r) => r.Type).sort().join() === "AWS::S3::Bucket,AWS::SQS::Queue");
const b = await nodeId("AWS::S3::Bucket"), q = await nodeId("AWS::SQS::Queue");
await drag(b, q);
tpl = JSON.parse(await ta.inputValue());
check("dragging a connector writes DependsOn", tpl.Resources[q]?.DependsOn === b);
// inspector: set queue properties through the canvas
await page.locator(`[data-node="${q}"]`).click();
await page.getByLabel("Properties (JSON)").fill(JSON.stringify({ QueueName: `cvq-${N}` }));
tpl = JSON.parse(await ta.inputValue());
check("inspector edits flow into template", tpl.Resources[q].Properties.QueueName === `cvq-${N}`);
// text -> canvas
tpl.Resources.Topic = { Type: "AWS::SNS::Topic", Properties: { TopicName: `cvt-${N}` }, DependsOn: q };
await ta.fill(JSON.stringify(tpl, null, 2));
await page.waitForTimeout(300);
check("text edits redraw the canvas (3 nodes + 2 edges)", (await page.locator("[data-node]").count()) === 3 && (await page.locator("[data-edge]").count()) === 2);
await page.getByRole("button", { name: "Validate", exact: true }).click();
await page.getByText(/Template is valid/i).first().waitFor({ timeout: 8000 }).catch(() => {});
check("Validate returns the real ValidateTemplate result", /Parameters|Description|Capabilities|\{\s*\}/.test(await body()));
await shot("canvas-cfn");
await page.getByRole("button", { name: "Create stack from template" }).click();
await page.getByLabel("Stack name").fill(`cvs-${N}`);
await page.getByRole("dialog").getByRole("button", { name: "Create stack" }).click();
await page.waitForFunction(() => location.hash.includes("/stacks"), null, { timeout: 15000 }).catch(() => {});
const ds = await wire("cloudformation", "POST", "/", { ct: "application/x-www-form-urlencoded", body: `Action=DescribeStacks&Version=2010-05-15&StackName=cvs-${N}` });
check("canvas template really created the stack", /CREATE_COMPLETE/.test(ds.text), ds.text.slice(0, 120));
const sq = await wire("sqs", "POST", "/", { target: "AmazonSQS.ListQueues", ct: "application/x-amz-json-1.0", body: JSON.stringify({ QueueNamePrefix: `cvq-${N}` }) });
check("stack's queue really exists on the SQS wire", JSON.stringify(sq.json || sq.text).includes(`cvq-${N}`));

// ── EventBridge Builder ──────────────────────────────────────────────────────
await wire("sqs", "POST", "/", { target: "AmazonSQS.CreateQueue", ct: "application/x-amz-json-1.0", body: JSON.stringify({ QueueName: `cvbuilder-${N}` }) });
await page.goto(UI + "#/eventbridge/create-rule");
await page.getByRole("button", { name: "Add Builder target node" }).waitFor();
check("builder is not the Not-simulated note", !(await page.locator("[data-vyomi-not-simulated='Builder mode']").count()));
check("builder starts with the Triggering event node", (await page.locator('[data-node-type="event"]').count()) === 1);
await page.getByRole("button", { name: "Add Builder target node" }).click();
const tn = await nodeId("target"), en = await nodeId("event");
await page.locator(`[data-node="${tn}"]`).click();
await page.locator("[data-vyomi-canvas-inspector]").getByRole("button", { name: /Select/ }).click();
await page.getByRole("option", { name: new RegExp(`cvbuilder-${N}`) }).first().click();
await drag(en, tn);
await page.locator(`[data-node="${en}"]`).click();
await page.getByLabel("Event source").fill(`cv.app${N}`);
await page.getByLabel("Event detail type").fill("order");
const pat = JSON.parse(await page.getByLabel("Event pattern", { exact: true }).inputValue());
check("builder drives the Event pattern editor", pat.source?.[0] === `cv.app${N}` && pat["detail-type"]?.[0] === "order");
await shot("canvas-eventbridge");
await page.getByRole("tab", { name: "Configure" }).click();
await page.getByLabel("Rule name").fill(`cvrule-${N}`);
await page.getByRole("button", { name: "Create rule" }).click();
await page.waitForFunction(() => !location.hash.includes("create-rule"), null, { timeout: 10000 }).catch(() => {});
const lt = await wire("events", "POST", "/", { target: "AWSEvents.ListTargetsByRule", body: JSON.stringify({ Rule: `cvrule-${N}` }) });
check("builder rule has its wired target on the wire", (lt.json?.Targets || []).some((t) => t.Arn.includes(`cvbuilder-${N}`)));
const dr = await wire("events", "POST", "/", { target: "AWSEvents.DescribeRule", body: JSON.stringify({ Name: `cvrule-${N}` }) });
check("rule pattern matches the canvas event node", (dr.json?.EventPattern || "").includes(`cv.app${N}`));

// ── Lambda Infrastructure Composer ───────────────────────────────────────────
await page.goto(UI + "#/lambda/create/application");
await page.getByRole("tab", { name: "Build with Infrastructure Composer" }).click();
await page.getByRole("button", { name: "Add Lambda function" }).waitFor();
check("composer is not the Not-simulated panel", !(await page.locator("[data-vyomi-gap-box]").count()));
await page.getByRole("button", { name: "Add Lambda function" }).click();
await page.locator('[data-node-type="function"]').first().click();
await page.getByLabel("Node name").fill("worker");
await page.getByRole("button", { name: "Add SQS queue" }).click();
await page.locator('[data-node-type="queue"]').first().click();
await page.getByLabel("Node name").fill("jobs");
const fnN = await nodeId("function"), qN = await nodeId("queue");
await drag(qN, fnN);
check("queue -> function connector drawn", (await page.locator("[data-edge]").count()) === 1);
await drag(fnN, qN);
check("function -> queue refused with a reason", /Wire an SQS queue/.test(await page.locator("[data-canvas-notice]").innerText()));
await page.getByLabel("Application name").fill(`cvapp${N}`);
await shot("canvas-lambda");
await page.getByRole("button", { name: "Deploy application" }).click();
await page.waitForFunction(() => location.hash.includes("applications"), null, { timeout: 20000 }).catch(() => {});
const fn = await wire("lambda", "GET", `/2015-03-31/functions/cvapp${N}-worker`, { ct: "application/json" });
check("composer created the Lambda function", fn.status === 200, fn.text.slice(0, 100));
const esm = await wire("lambda", "GET", `/2015-03-31/event-source-mappings?FunctionName=cvapp${N}-worker`, { ct: "application/json" });
check("composer created the SQS event source mapping", (esm.json?.EventSourceMappings || []).some((m) => m.EventSourceArn.endsWith(`cvapp${N}-jobs`)), esm.text.slice(0, 120));
const cs = await wire("cloudformation", "POST", "/", { ct: "application/x-www-form-urlencoded", body: `Action=DescribeStacks&Version=2010-05-15&StackName=cvapp${N}` });
check("composer created its stack", /CREATE_COMPLETE/.test(cs.text));
const sq2 = await wire("sqs", "POST", "/", { target: "AmazonSQS.ListQueues", ct: "application/x-amz-json-1.0", body: JSON.stringify({ QueueNamePrefix: `cvapp${N}` }) });
check("composer's queue really exists", JSON.stringify(sq2.json || "").includes(`cvapp${N}-jobs`));
check("application listed", (await body()).includes(`cvapp${N}`));

check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
