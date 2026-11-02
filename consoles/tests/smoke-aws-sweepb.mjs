/* AWS sweep B2: drives the real UI and cross-checks each step over the native wire.
 *   EventBridge: Pipes (create/stop/start/delete + SQS->SQS delivery), Connections, API destinations,
 *   Global endpoints, Sandbox (TestEventPattern), account/rule/pipe metric graphs; Kinesis stream metrics.
 *
 *   BASE=http://127.0.0.1:9101 node consoles/tests/smoke-aws-sweepb.mjs                                  (offline)
 *   BASE=http://127.0.0.1:9103 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-sweepb.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9101";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "/tmp/smoke-out-sweepb";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const sign = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wireJson = (svc, target, p = {}, ver = "1.1") => page.evaluate(async ([u, svc, target, p, au, ver]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": `application/x-amz-json-${ver}`, "x-amz-target": target }, body: JSON.stringify(p) });
  const t = await r.text(); return { status: r.status, json: t ? JSON.parse(t) : {} };
}, [WIRE, svc, target, p, sign(svc), ver]);
const ev = (op, p) => wireJson("events", `AWSEvents.${op}`, p);
const sqs = (op, p) => wireJson("sqs", `AmazonSQS.${op}`, p);
const pipes = (method, path, body) => page.evaluate(async ([u, m, path, body, au]) => {
  const r = await fetch(u + path, { method: m, headers: { authorization: au, "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, json: t ? JSON.parse(t) : {} };
}, [WIRE, method, path, body, sign("pipes")]);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const body = () => page.locator("body").innerText();
const badges = () => page.locator('[data-vyomi-not-simulated]').count();
const go = async (hash, heading) => { await page.goto(UI + hash); await page.reload(); await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 40000 }); await page.waitForTimeout(800); };

await page.goto(UI + "#/eventbridge/dashboard");
await page.getByRole("heading", { name: "Amazon EventBridge" }).first().waitFor({ timeout: 60000 }).catch(() => {});

// ── EventBridge: Pipes ──────────────────────────────────────────────────────
const SRC = `pipe-src-${N}`, DST = `pipe-dst-${N}`, PIPE = `pipe-${N}`;
const su = (await sqs("CreateQueue", { QueueName: SRC })).json.QueueUrl, du = (await sqs("CreateQueue", { QueueName: DST })).json.QueueUrl;
await go("#/eventbridge/create-pipe", "Create pipe");
check("Create pipe page has no Not-simulated badge", (await badges()) === 0);
await page.getByRole("textbox", { name: "Pipe name" }).fill(PIPE);
await page.getByRole("button", { name: /Select a source/ }).click();
await page.getByRole("option", { name: `SQS queue: ${SRC}` }).click();
await page.getByRole("button", { name: /Select a target/ }).click();
await page.getByRole("option", { name: `SQS queue: ${DST}` }).click();
await page.getByRole("button", { name: "Create pipe" }).last().click();
await page.getByRole("heading", { name: "Pipes" }).first().waitFor({ timeout: 20000 });
check("Pipes list shows the pipe RUNNING", (await page.getByText(PIPE).first().isVisible()) && (await pipes("GET", `/v1/pipes/${PIPE}`)).json.CurrentState === "RUNNING");
check("Pipes page has no Not-simulated badge", (await badges()) === 0);
await sqs("SendMessage", { QueueUrl: su, MessageBody: "via-pipe" });
const got = await sqs("ReceiveMessage", { QueueUrl: du });
check("a message sent to the source really arrives at the target through the pipe", got.json.Messages?.[0]?.Body === "via-pipe");
await shot("sweepb-pipes");
await page.locator("tr", { hasText: PIPE }).locator("input[type=radio]").check({ force: true });
await page.getByRole("button", { name: "Stop", exact: true }).click();
await page.waitForTimeout(800);
check("Stop pipe -> STOPPED over the wire", (await pipes("GET", `/v1/pipes/${PIPE}`)).json.CurrentState === "STOPPED");
await go(`#/eventbridge/pipes/${PIPE}`, PIPE);
await page.getByText("Pipe details").first().waitFor({ timeout: 20000 });
await page.waitForTimeout(1500);
check("Pipe detail renders Monitoring with metric graphs, no badge", (await body()).includes("Execution") && (await badges()) === 0);
await pipes("DELETE", `/v1/pipes/${PIPE}`);

// ── EventBridge: Connections + API destinations ──────────────────────────────
const CN = `conn-${N}`, AD = `dest-${N}`;
await ev("DeleteApiDestination", { Name: AD }); await ev("DeleteConnection", { Name: CN });
await go("#/eventbridge/create-connection", "Create connection");
check("Create connection page has no badge", (await badges()) === 0);
await page.getByRole("textbox", { name: "Connection name" }).fill(CN);
await page.getByRole("textbox", { name: "API key name" }).fill("x-api-key");
await page.getByRole("textbox", { name: "API key value" }).fill("s3cret");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("heading", { name: "Connections" }).first().waitFor({ timeout: 20000 });
const dc = (await ev("DescribeConnection", { Name: CN })).json;
check("Connection created via UI is AUTHORIZED over the wire and hides the secret", dc.ConnectionState === "AUTHORIZED" && !JSON.stringify(dc).includes("s3cret"));
await go("#/eventbridge/create-api-destination", "Create API destination");
await page.getByRole("textbox", { name: "Name" }).first().fill(AD);
await page.getByRole("textbox", { name: "API destination endpoint" }).fill("https://example.com/hook");
await page.getByRole("button", { name: /Choose a connection/ }).click();
await page.getByRole("option", { name: CN }).click();
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("heading", { name: "API destinations" }).first().waitFor({ timeout: 20000 });
const dd = (await ev("DescribeApiDestination", { Name: AD })).json;
check("API destination created via UI (ACTIVE, rate 300, bound to the connection)", dd.ApiDestinationState === "ACTIVE" && dd.InvocationRateLimitPerSecond === 300 && dd.ConnectionArn === dc.ConnectionArn);
check("API destinations page has no badge", (await badges()) === 0 && (await body()).includes(AD));
await shot("sweepb-apidest");
check("Deleting an in-use connection is refused", (await ev("DeleteConnection", { Name: CN })).json.__type === "ResourceInUseException");
await ev("DeleteApiDestination", { Name: AD }); await ev("DeleteConnection", { Name: CN });

// ── EventBridge: Global endpoints ────────────────────────────────────────────
const GE = `ge-${N}`;
await ev("DeleteEndpoint", { Name: GE });
await go("#/eventbridge/create-global-endpoint", "Create global endpoint");
await page.getByRole("textbox", { name: "Name" }).first().fill(GE);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("heading", { name: "Global endpoints" }).first().waitFor({ timeout: 20000 });
check("Global endpoint created via UI is ACTIVE with a .veo endpoint id", (await ev("DescribeEndpoint", { Name: GE })).json.EndpointId?.endsWith(".veo"));
check("Global endpoints page has no badge", (await badges()) === 0 && (await body()).includes(GE));
await ev("DeleteEndpoint", { Name: GE });

// ── EventBridge: Sandbox ─────────────────────────────────────────────────────
await go("#/eventbridge/sandbox", "Sandbox");
check("Sandbox has no badge", (await badges()) === 0);
await page.getByRole("button", { name: "Test pattern" }).click();
await page.getByText("Matched", { exact: true }).waitFor({ timeout: 10000 });
check("Sandbox: sample pattern matches the sample event (real TestEventPattern)", true);
await page.getByRole("textbox", { name: "Event pattern" }).fill('{"source":["not.ec2"]}');
await page.getByRole("button", { name: "Test pattern" }).click();
await page.getByText("Did not match").waitFor({ timeout: 10000 });
check("Sandbox: a non-matching pattern reports Did not match", true);

// ── EventBridge: metrics graphs fed by real traffic ───────────────────────────
const BUS = `mbus-${N}`, RULE = `mrule-${N}`;
await ev("CreateEventBus", { Name: BUS });
await ev("PutRule", { Name: RULE, EventBusName: BUS, EventPattern: JSON.stringify({ source: ["sweepb.app"] }) });
await ev("PutTargets", { Rule: RULE, EventBusName: BUS, Targets: [{ Id: "t", Arn: `arn:aws:sqs:us-east-1:000000000000:${DST}` }] });
await ev("PutEvents", { Entries: [1, 2, 3].map((i) => ({ EventBusName: BUS, Source: "sweepb.app", DetailType: "x", Detail: JSON.stringify({ i }) })) });
await go(`#/eventbridge/rules/${RULE}?bus=${BUS}`, RULE);
await page.getByRole("tab", { name: "Monitoring" }).click();
await page.waitForTimeout(2500);
check("Rule Monitoring tab shows graphs and no Not-simulated badge", (await badges()) === 0 && (await page.locator('[data-testid="metric-TriggeredRules"]').count()) === 1);
await shot("sweepb-rule-metrics");
await ev("DeleteEventBus", { Name: BUS }).catch(() => {});

// ── Kinesis: stream metrics ──────────────────────────────────────────────────
const KS = `ks-${N}`;
await wireJson("kinesis", "Kinesis_20131202.CreateStream", { StreamName: KS, ShardCount: 1 });
await wireJson("kinesis", "Kinesis_20131202.PutRecord", { StreamName: KS, PartitionKey: "k", Data: Buffer.from("hello").toString("base64") });
await go(`#/kinesis/streams/${KS}`, KS);
await page.getByRole("tab", { name: "Monitoring" }).click();
await page.waitForTimeout(2500);
check("Kinesis Monitoring tab renders metric graphs, no Not-simulated badge", (await badges()) === 0 && (await page.locator('[data-testid="metric-IncomingRecords"]').count()) === 1);
await shot("sweepb-kinesis-metrics");
await wireJson("kinesis", "Kinesis_20131202.DeleteStream", { StreamName: KS, EnforceConsumerDeletion: true });

console.log("page errors:", errors.length ? errors.slice(0, 3).join(" | ") : "none");
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
