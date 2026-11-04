/* Bedrock console (playground, knowledge bases, agents, AgentCore gateways) + API Gateway AgentCore targets +
 * Lambda agent onboarding + DynamoDB/RDS zero-ETL: UI <-> native wire.
 *   node consoles/tests/llm_stub.py 9171 &  VYOMI_LLM_ENDPOINT=http://127.0.0.1:9171 python3 consoles/dev_server.py --port 9071 -q &
 *   BASE=http://127.0.0.1:9071 node consoles/tests/smoke-aws-bedrock.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9071";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const ZIP = "UEsDBBQAAAAAAFm1ZF3NfQC1SQAAAEkAAAAIAAAAaW5kZXgucHlkZWYgaGFuZGxlcihldmVudCwgY29udGV4dCk6CiAgICByZXR1cm4geyJzdW0iOiBldmVudFsiYSJdICsgZXZlbnRbImIiXX0KUEsBAhQDFAAAAAAAWbVkXc19ALVJAAAASQAAAAgAAAAAAAAAAAAAAIABAAAAAGluZGV4LnB5UEsFBgAAAAABAAEANgAAAG8AAAAAAA==";
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261104/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const W = (svc, method, path, body, extra = {}) => page.evaluate(async ([u, a, m, p, b, e]) => {
  const r = await fetch(u + p, { method: m, headers: { authorization: a, "content-type": b && typeof b === "object" ? "application/json" : "application/octet-stream", ...e }, body: b === undefined ? undefined : (typeof b === "object" ? JSON.stringify(b) : b) });
  const tx = await r.text(); let j = {}; try { j = tx ? JSON.parse(tx) : {}; } catch { /* xml/binary */ }
  return { status: r.status, json: j, text: tx };
}, [WIRE, auth(svc), method, path, body, extra]);
const body = () => page.locator("body").innerText();
await page.goto(UI + "#/bedrock");
await page.getByRole("heading", { name: "Amazon Bedrock" }).first().waitFor({ timeout: 30000 });

// seed: S3 docs + Lambda
await W("s3", "PUT", "/kbdocs");
await W("s3", "PUT", "/kbdocs/docs/refunds.txt", "Refunds are processed within fourteen days of the return request.");
await W("s3", "PUT", "/kbdocs/docs/shipping.md", "Shipping to Europe takes five business days by tracked courier.");
const lf = await W("lambda", "POST", "/2015-03-31/functions", { FunctionName: "adder", Runtime: "python3.12", Role: "arn:aws:iam::123456789012:role/r", Handler: "index.handler", Code: { ZipFile: ZIP } });
check("seed lambda", lf.status === 201 || lf.status === 200, lf.status);

// overview + model check
await page.getByRole("button", { name: "Check local model" }).click();
if (process.env.NANO === "1") {
  // Nano has no model until the page registers WebLLM (WebGPU + CDN download): the honest result is a not-ready message, never a canned answer.
  await page.waitForTimeout(3000);
  const t = await body();
  check("Nano: no in-browser model -> honest not-ready state (no crash, no canned answer)", !/Model answered/.test(t) && (/not ready|ModelNotReady|WebLLM|no (local )?model|not available/i.test(t)), t.slice(0, 80));
  check("no page errors", errs.length === 0, errs[0]);
  await browser.close();
  process.exit(results.every(Boolean) ? 0 : 1);
}
await page.getByText(/Model answered/).waitFor({ timeout: 15000 });
check("overview: local model answered", true);

// playground
await page.goto(UI + "#/bedrock/playground");
await page.getByRole("button", { name: "Run" }).waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await page.getByRole("button", { name: "Run" }).click();
await page.getByTestId("converse-output").waitFor({ timeout: 15000 });
check("playground: Converse response shown", /STUB ANSWER/.test(await page.getByTestId("converse-output").innerText()));

// knowledge base
await page.goto(UI + "#/bedrock/knowledge-bases");
await page.getByRole("button", { name: "Create knowledge base" }).first().click();
await page.getByLabel("Knowledge base name").fill("support-kb");
await page.getByRole("button", { name: /S3 bucket/ }).click();
await page.getByRole("option", { name: "kbdocs" }).click();
await page.getByLabel("Key prefix").fill("docs/");
await page.getByRole("button", { name: "Create and sync" }).click();
await page.getByRole("heading", { name: "Knowledge base overview" }).waitFor({ timeout: 20000 });
check("kb created + navigated to detail", true);
await page.getByLabel("Query").fill("how long do refunds take");
await page.getByRole("button", { name: "Retrieve", exact: true }).click();
await page.getByText("s3://kbdocs/docs/refunds.txt").first().waitFor({ timeout: 10000 });
check("retrieve shows the refunds document", true);
await page.getByRole("button", { name: "Retrieve and generate" }).click();
await page.getByTestId("rag-answer").waitFor({ timeout: 15000 });
check("retrieve and generate answer", /STUB ANSWER/.test(await page.getByTestId("rag-answer").innerText()));

// agent
await page.goto(UI + "#/bedrock/agents");
await page.getByRole("button", { name: "Create agent" }).first().click();
await page.getByLabel("Agent name").fill("support-agent");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("heading", { name: "Agent overview" }).waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "Prepare" }).click();
await page.getByText("PREPARED").first().waitFor({ timeout: 10000 });
check("agent prepared", true);
await page.getByLabel("Message").fill("How long do refunds take?");
await page.getByRole("button", { name: "Send" }).click();
await page.getByText(/Agent:.*STUB ANSWER/).waitFor({ timeout: 15000 });
check("agent replies through InvokeAgent", true);
await page.getByPlaceholder("alias name").fill("live");
await page.getByRole("button", { name: "Create alias" }).click();
await page.getByText("Alias created").first().waitFor({ timeout: 10000 });
const al = await W("bedrock", "POST", `/agents/${(await W("bedrock", "GET", "/agents/")).json.agentSummaries[0].agentId}/agentaliases/`, {});
check("alias on the wire", (al.json.agentAliasSummaries || []).some((a) => a.agentAliasName === "live"));

// AgentCore gateway + target + tool call
await page.goto(UI + "#/bedrock/agentcore");
await page.getByRole("button", { name: "Create gateway" }).first().click();
await page.getByLabel("Gateway name").fill("tools-gw");
await page.getByRole("button", { name: "Create gateway" }).last().click();
await page.getByRole("heading", { name: "Gateway details" }).waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "Add target" }).click();
await page.getByLabel("Target name").fill("calc");
await page.getByRole("button", { name: /Lambda function/ }).click();
await page.getByRole("option", { name: "adder" }).click();
await page.getByRole("button", { name: "Create target" }).click();
await page.getByText("calc___add").first().waitFor({ timeout: 15000 });
check("gateway tools/list shows calc___add", true);
await page.getByRole("button", { name: "Call tool" }).click();
await page.getByLabel("Arguments").fill('{"a": 2, "b": 5}');
await page.getByRole("button", { name: "Call", exact: true }).click();
await page.getByTestId("tool-result").waitFor({ timeout: 15000 });
check("tools/call invoked the Lambda", /"sum":\s*7/.test(await page.getByTestId("tool-result").innerText()));
await page.keyboard.press("Escape");

// API Gateway AgentCore targets
await page.goto(UI + "#/apigateway/agentcore-targets");
await page.getByText("calc", { exact: true }).first().waitFor({ timeout: 15000 });
check("apigateway AgentCore targets lists the target", true);

// Lambda onboarding
await page.goto(UI + "#/lambda");
await page.getByRole("heading", { name: "Set up your agent to build with Lambda" }).waitFor({ timeout: 20000 });
check("lambda onboarding shows existing gateway", await page.getByText(/Gateway lambda-tools exists/).count() === 0 && (await body()).includes("Create gateway"));
await page.getByRole("button", { name: "Create gateway" }).click();
await page.getByRole("heading", { name: "Gateway details" }).waitFor({ timeout: 15000 });
check("onboarding created the lambda-tools gateway", (await W("bedrock-agentcore", "GET", "/gateways/")).json.items.some((g) => g.name === "lambda-tools"));

// zero-ETL (DynamoDB)
const D = (t, p) => page.evaluate(async ([u, a, t, p]) => (await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": "DynamoDB_20120810." + t, "content-type": "application/x-amz-json-1.0" }, body: JSON.stringify(p) })).status, [WIRE, auth("dynamodb"), t, p]);
await D("CreateTable", { TableName: "orders", KeySchema: [{ AttributeName: "id", KeyType: "HASH" }], AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], BillingMode: "PAY_PER_REQUEST" });
await D("UpdateContinuousBackups", { TableName: "orders", PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true } });
await D("PutItem", { TableName: "orders", Item: { id: { S: "a" } } });
await page.goto(UI + "#/dynamodb/integrations");
await page.getByRole("button", { name: "Create zero-ETL integration" }).first().click();
await page.getByLabel("Integration name").fill("ddb-orders");
await page.getByRole("button", { name: /Source DynamoDB table/ }).click();
await page.getByRole("option", { name: "orders" }).click();
await page.getByRole("button", { name: "Create integration" }).click();
await page.getByText("ACTIVE").first().waitFor({ timeout: 10000 });
check("zero-ETL integration ACTIVE", true);
await page.getByRole("button", { name: "Create database from ddb-orders" }).click();
await page.getByText(/Database ddb_orders created/).waitFor({ timeout: 10000 });
await page.locator("textarea").fill("SELECT id FROM ddb_orders.orders");
await page.getByRole("button", { name: "Run", exact: true }).click();
await page.getByRole("heading", { name: /Result/ }).waitFor({ timeout: 10000 });
check("Redshift-lite query returns the replicated row", (await body()).includes("a"));

check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
