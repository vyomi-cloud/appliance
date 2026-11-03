/* CloudFormation sweep (AWS-08): stack policy enforcement, alarm rollback triggers, SNS notifications. UI <-> native wire.
 *   BASE=http://127.0.0.1:9110 node consoles/tests/smoke-aws-cfnsweep.mjs
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-cfnsweep.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9110";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const ST = `cfnsw-${N}`, TOPIC = `cfnsw-t-${N}`, ALARM = `cfnsw-guard-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const Q = (svc, action, params = {}, version = "2010-05-15") => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body });
  return { status: r.status, text: await r.text() };
}, [WIRE, auth(svc), new URLSearchParams({ Action: action, Version: version, ...params }).toString()]);
const cfn = (a, p) => Q("cloudformation", a, p);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const tmpl = (d) => JSON.stringify({ Resources: { Topic: { Type: "AWS::SNS::Topic", Properties: { TopicName: TOPIC } }, Queue: { Type: "AWS::SQS::Queue", Properties: { QueueName: `q-${TOPIC}`, DelaySeconds: d } } } });
const status = async () => (await cfn("DescribeStacks", { StackName: ST })).text.match(/<StackStatus>(.*?)<\/StackStatus>/)?.[1];

await page.goto(UI + "#/cloudformation");
await page.getByText("CloudFormation").first().waitFor({ timeout: 30000 });
const notifyTopic = (await Q("sns", "CreateTopic", { Name: `cfnsw-n-${N}` }, "2010-03-31")).text.match(/<TopicArn>(.*?)</)[1];
await Q("monitoring", "PutMetricAlarm", { AlarmName: ALARM, MetricName: "M", Namespace: "N", Statistic: "Average", Period: "60", EvaluationPeriods: "1", Threshold: "1", ComparisonOperator: "GreaterThanThreshold" }, "2010-08-01");
const created = await cfn("CreateStack", { StackName: ST, TemplateBody: tmpl("0") });
check("fixture stack created", created.status === 200, created.text.slice(0, 100));

await page.goto(UI + `#/cloudformation/stacks/${ST}`);
await page.getByRole("heading", { name: "Stack policy" }).first().waitFor({ timeout: 20000 });
check("stack info shows Stack policy/Rollback/Notification panels, not Not simulated", !/Not simulated in Vyomi/.test(await page.locator("body").innerText()));

// stack policy: deny any modify of Queue
await page.getByLabel("Stack policy document").fill(JSON.stringify({ Statement: [{ Effect: "Allow", Action: "Update:*", Principal: "*", Resource: "*" }, { Effect: "Deny", Action: "Update:Modify", Principal: "*", Resource: "LogicalResourceId/Queue" }] }));
await page.getByRole("button", { name: "Save stack policy" }).click();
await page.waitForTimeout(800);
const gp = await cfn("GetStackPolicy", { StackName: ST });
check("UI-saved stack policy readable via GetStackPolicy", gp.text.includes("LogicalResourceId/Queue"));
await cfn("UpdateStack", { StackName: ST, TemplateBody: tmpl("3") });
check("update touching the protected resource is denied (rolled back)", (await status()) === "UPDATE_ROLLBACK_COMPLETE");
await page.getByRole("tab", { name: "Events" }).click();
await page.getByText(/Action denied by stack policy/).first().waitFor({ timeout: 15000 });
check("Events tab shows the policy denial", true);
await shot("cfnsw-policy");

// notifications through the UI
await page.getByRole("tab", { name: "Stack info" }).click();
await page.getByLabel("Notification topic ARNs").fill(notifyTopic);
await page.getByRole("button", { name: "Save notification options" }).click();
await page.waitForTimeout(1000);
check("notification topic saved from the UI", (await cfn("DescribeStacks", { StackName: ST })).text.includes(notifyTopic));
const sinkUrl = (await Q("sqs", "CreateQueue", { QueueName: `cfnsw-sink-${N}` }, "2012-11-05")).text.match(/<QueueUrl>(.*?)</)[1];
await Q("sns", "Subscribe", { TopicArn: notifyTopic, Protocol: "sqs", Endpoint: `arn:aws:sqs:us-east-1:123456789012:cfnsw-sink-${N}` }, "2010-03-31");
await cfn("SetStackPolicy", { StackName: ST, StackPolicyBody: JSON.stringify({ Statement: [{ Effect: "Allow", Action: "Update:*", Principal: "*", Resource: "*" }] }) });
const t2 = JSON.parse(tmpl("0")); t2.Resources.Topic.Properties.DisplayName = "d";
await cfn("UpdateStack", { StackName: ST, TemplateBody: JSON.stringify(t2) });
const rcv = await Q("sqs", "ReceiveMessage", { QueueUrl: sinkUrl, MaxNumberOfMessages: "10" }, "2012-11-05");
check("stack events published to the SNS topic", /UPDATE_COMPLETE/.test(rcv.text) && /StackName=/.test(rcv.text), rcv.text.slice(0, 120));

// rollback trigger set from the UI
await page.reload();
await page.getByRole("heading", { name: "Rollback configuration" }).first().waitFor({ timeout: 20000 });
await page.getByRole("button", { name: /Choose CloudWatch alarms|Rollback alarms/ }).first().click();
await page.getByRole("option", { name: new RegExp(ALARM) }).click();
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Save rollback configuration" }).click();
await page.waitForTimeout(1000);
const desc = await cfn("DescribeStacks", { StackName: ST });
check("rollback alarm saved from the UI", desc.text.includes(`alarm:${ALARM}`));
await Q("monitoring", "SetAlarmState", { AlarmName: ALARM, StateValue: "ALARM", StateReason: "t" }, "2010-08-01");
await cfn("UpdateStack", { StackName: ST, TemplateBody: tmpl("0") });
const st = await status();
check("alarm in ALARM -> update rolled back", st === "UPDATE_ROLLBACK_COMPLETE", st);
await shot("cfnsw-rollback");
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
