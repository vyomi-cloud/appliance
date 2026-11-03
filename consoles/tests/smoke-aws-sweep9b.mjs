/* AWS-09 sweep part B: VPC multi-subnet create + All VPC resources, SNS Integrations tab, Lambda RDS databases (RDS Proxy helper).
 *   BASE=http://127.0.0.1:9110 node consoles/tests/smoke-aws-sweep9b.mjs
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-sweep9b.mjs
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
const TOPIC = `sw9-topic-${N}`, RULE = `sw9-rule-${N}`, ALARM = `sw9-alarm-${N}`, FN = `sw9-fn-${N}`, DB = `sw9-db-${N}`, SEC = `sw9-sec-${N}`, ROLE = `sw9-role-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const Q = (svc, action, params = {}, version) => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body });
  return { status: r.status, text: await r.text() };
}, [WIRE, auth(svc), new URLSearchParams({ Action: action, Version: version, ...params }).toString()]);
const J = (svc, target, body, ct = "application/x-amz-json-1.1") => page.evaluate(async ([u, a, t, b, c]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": c }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, json: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth(svc), target, body, ct]);
const REST = (svc, method, path, body) => page.evaluate(async ([u, a, m, p, b]) => {
  const r = await fetch(u + p, { method: m, headers: { authorization: a, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  const tx = await r.text(); return { status: r.status, text: tx };
}, [WIRE, auth(svc), method, path, body]);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const body = async () => await page.locator("body").innerText();

await page.goto(UI + "#/vpc");
await page.getByText("VPC dashboard").first().waitFor({ timeout: 30000 });

// ── VPC: multiple subnets in one submit
const vpc = (await Q("ec2", "CreateVpc", { CidrBlock: "10.77.0.0/16" }, "2016-11-15")).text.match(/<vpcId>(.*?)<\/vpcId>/)[1];
await page.goto(UI + "#/vpc/create-subnet");
await page.getByRole("button", { name: /Select a VPC|vpc-/ }).first().click();
await page.getByRole("option", { name: new RegExp(vpc) }).click();
await page.getByPlaceholder("10.0.0.0/24").fill("10.77.1.0/24");
await page.getByRole("button", { name: "Add new subnet" }).click();
await page.getByLabel("Subnet 2 CIDR").fill("10.77.2.0/24");
await page.getByLabel("Subnet 2 name").fill(`sw9-b-${N}`);
check("the Add new subnet button is a real control (no Not-simulated modal)", true);
await shot("sw9-multisubnet");
await page.getByRole("button", { name: "Create 2 subnets" }).click();
await page.waitForTimeout(2500);
const subs = (await Q("ec2", "DescribeSubnets", { "Filter.1.Name": "vpc-id", "Filter.1.Value.1": vpc }, "2016-11-15")).text;
check("both subnets exist on the native EC2 wire", subs.includes("10.77.1.0/24") && subs.includes("10.77.2.0/24"), (subs.match(/<cidrBlock>[^<]*/g) || []).join(" "));
await page.goto(UI + "#/vpc/all-resources");
await page.getByText("US East (N. Virginia) us-east-1").waitFor({ timeout: 15000 });
check("All VPC resources lists real counts for the one simulated Region", (await body()).includes("Subnets") && (await body()).includes("One simulated Region"));
await page.goto(UI + "#/vpc");
check("VPC dashboard 'All VPC Resources' is a real link", await page.getByRole("link", { name: "All VPC Resources" }).count() > 0);

// ── SNS Integrations tab
const topicArn = (await Q("sns", "CreateTopic", { Name: TOPIC }, "2010-03-31")).text.match(/<TopicArn>(.*?)</)[1];
await J("events", "AWSEvents.PutRule", { Name: RULE, EventPattern: JSON.stringify({ source: ["x"] }) });
await J("events", "AWSEvents.PutTargets", { Rule: RULE, Targets: [{ Id: "t1", Arn: topicArn }] });
await J("monitoring", "GraniteServiceVersion20100801.PutMetricAlarm", { AlarmName: ALARM, Namespace: "N", MetricName: "M", Statistic: "Average", Period: 60, EvaluationPeriods: 1, Threshold: 1, ComparisonOperator: "GreaterThanThreshold", AlarmActions: [topicArn] }, "application/x-amz-json-1.0");
await page.goto(UI + `#/sns/topics/${TOPIC}`);
await page.getByRole("tab", { name: "Integrations" }).click();
await page.getByRole("link", { name: RULE }).waitFor({ timeout: 15000 }).catch(async (e) => { await shot("sw9-fail"); console.log((await body()).slice(0, 1200)); throw e; });
check("Integrations tab lists the EventBridge rule targeting the topic", true);
check("Integrations tab lists the CloudWatch alarm notifying the topic", (await body()).includes(ALARM));
await shot("sw9-sns");

// ── Lambda: RDS databases / RDS Proxy helper
const subnetIds = [...subs.matchAll(/<subnetId>(.*?)<\/subnetId>/g)].map((m) => m[1]);
const sg = (await Q("ec2", "CreateSecurityGroup", { GroupName: `sw9-sg-${N}`, GroupDescription: "x", VpcId: vpc }, "2016-11-15")).text.match(/<groupId>(.*?)<\/groupId>/)[1];
const mkfn = await REST("lambda", "POST", "/2015-03-31/functions", { FunctionName: FN, Runtime: "python3.12", Handler: "lambda_function.lambda_handler", Role: "arn:aws:iam::123456789012:role/x",
  Code: { Source: "def lambda_handler(e, c):\n    return 1\n" }, VpcConfig: { SubnetIds: subnetIds.slice(0, 2), SecurityGroupIds: [sg] } });
check("fixture VPC-attached Lambda", mkfn.status === 200 || mkfn.status === 201, mkfn.text.slice(0, 120));
await Q("rds", "CreateDBInstance", { DBInstanceIdentifier: DB, Engine: "postgres", DBInstanceClass: "db.t3.micro", MasterUsername: "u", MasterUserPassword: "pw12345678", AllocatedStorage: "20" }, "2014-10-31");
await J("secretsmanager", `secretsmanager.CreateSecret`, { Name: SEC, SecretString: JSON.stringify({ username: "u", password: "pw12345678" }) });
await Q("iam", "CreateRole", { RoleName: ROLE, AssumeRolePolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: "rds.amazonaws.com" }, Action: "sts:AssumeRole" }] }) }, "2010-05-08");
await page.goto(UI + `#/lambda/functions/${FN}`);
await page.getByRole("tab", { name: "Configuration" }).click();
await page.getByRole("button", { name: "Connect to RDS database" }).click();
const dlg = page.getByRole("dialog");
await dlg.getByRole("button", { name: /RDS database/ }).first().click();
await page.getByRole("option", { name: new RegExp(DB) }).click();
await dlg.getByRole("button", { name: /Secrets Manager secret/ }).first().click();
await page.getByRole("option", { name: new RegExp(SEC) }).click();
await dlg.getByRole("button", { name: /IAM role/ }).first().click();
await page.getByRole("option", { name: new RegExp(ROLE) }).click();
await shot("sw9-lambda-modal");
await page.getByRole("button", { name: "Create proxy" }).click();
await page.getByRole("cell", { name: `${FN}-proxy`, exact: true }).waitFor({ timeout: 15000 }).catch(async (e) => { await shot("sw9-fail"); console.log((await body()).slice(0, 800)); throw e; });
const tg = await Q("rds", "DescribeDBProxyTargets", { DBProxyName: `${FN}-proxy` }, "2014-10-31");
check("the helper created a real RDS Proxy targeting the database in the function's VPC", tg.text.includes(`<RdsResourceId>${DB}</RdsResourceId>`));
const px = await Q("rds", "DescribeDBProxies", { DBProxyName: `${FN}-proxy` }, "2014-10-31");
check("proxy carries the function's subnets + the secret auth", subnetIds.slice(0, 2).every((s) => px.text.includes(s)) && px.text.includes(SEC));
await shot("sw9-lambda");
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
