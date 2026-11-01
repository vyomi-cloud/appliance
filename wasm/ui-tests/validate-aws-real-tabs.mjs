/* AWS console resource-detail tabs render THIS resource's backend data, and tab
 * actions persist across reopening the tab — in Nano and offline.
 *   Nano:    NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-aws-real-tabs.mjs [section…]
 *   Offline: VYOMI_CONSOLE_URL=http://localhost:9000/console/aws node …
 * Each section creates a resource through the console's API, reads the values the
 * tab must show from the same API, opens the tab in the UI and checks them. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(!!ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + String(extra).slice(0, 300)}`); };
const call = (method, path, body) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b === undefined ? undefined : JSON.stringify(b) });
  let j = null; try { j = await r.json(); } catch (_) {}
  return { status: r.status, json: j };
}, [method, path, body]);
const openService = async (re) => {
  await page.evaluate(([sel, r]) => [...document.querySelectorAll(sel)].find((e) => new RegExp(r, "i").test(e.innerText.trim().split("\n").pop()))?.click(), [RAIL_SEL, re]);
  await sleep(2000);
};
const openRow = async (text) => {
  await page.locator("#main tr", { hasText: text }).first().locator("a.id, td a").first().click({ timeout: 15000 });
  await sleep(2000);
};
const tab = async (label) => {
  await page.locator(".top-tabs button", { hasText: label }).first().click();
  await sleep(1200);
  return page.evaluate(() => document.querySelector("#main")?.innerText || "");
};

const SECTIONS = {
  async ec2() {
    const name = "rt" + Date.now().toString(36);
    const c = await call("POST", "/api/ec2/instances?auto_start=false", { name, instance_type: "t3.micro", key_name: "kp-" + name,
      user_data: "#!/bin/bash\necho " + name, storage_gb: 14, create_security_group: { requested: true, ssh_cidr: "0.0.0.0/0" } });
    const iid = c.json.instance_id;
    check("ec2: launched", c.status < 300 && iid, JSON.stringify(c));
    const eni = (await call("GET", `/api/ec2/instances/${iid}/network-interfaces`)).json.network_interfaces[0];
    const vol = (await call("GET", `/api/ec2/instances/${iid}/storage`)).json.block_devices[0];
    const sec = (await call("GET", `/api/ec2/instances/${iid}/security`)).json;
    await openService("^ec2$");
    await openRow(name);
    const net = await tab("Networking");
    check("ec2 Networking: this instance's ENI, subnet and VPC", net.includes(eni.network_interface_id) && net.includes(eni.subnet_id) && net.includes(eni.vpc_id), net);
    const st = await tab("Storage");
    check("ec2 Storage: its root volume (14 GiB)", st.includes(vol.volume_id) && /\b14\b/.test(st), st);
    const s = await tab("Security");
    check("ec2 Security: its launch-wizard group + SSH rule", s.includes(sec.security_groups[0].group_id) && /launch-wizard-\d+/.test(s) && /\b22\b/.test(s), s);
    const ud = await page.evaluate(async () => {
      document.querySelectorAll(".top-tabs button").forEach((b) => { if (b.innerText.trim() === "User data") b.click(); });
      await new Promise((r) => setTimeout(r, 1200));
      return document.querySelector("[data-testid=ec2-user-data]")?.value || "";
    });
    check("ec2 User data: the launch script", ud.includes("echo " + name), ud);
    const conn = await tab("Connect");
    check("ec2 Connect: SSH command with its key pair", conn.includes(`kp-${name}.pem`), conn);
    await tab("Details");
    await page.locator("#main input[data-attr=disable_api_stop]").check();
    await page.locator("#main button", { hasText: "Save" }).first().click();
    await sleep(1500);
    await tab("Networking");
    await tab("Details");
    check("ec2 Details: stop protection persists after reopening the tab",
      await page.locator("#main input[data-attr=disable_api_stop]").isChecked());
    check("ec2 Details: backend has stop protection on", (await call("GET", `/api/ec2/instances/${iid}/details`)).json.stop_protection === true);
    await call("PUT", `/api/ec2/instances/${iid}/attributes`, { disable_api_stop: false });
    const perm = await tab("Permissions");
    check("ec2 Permissions: evaluated for this instance's ARN", perm.includes(`instance/${iid}`), perm);
  },
  async s3() {
    const name = "rt-" + Date.now().toString(36);
    await call("POST", `/api/s3/buckets/${name}`, {});
    await call("PUT", `/api/s3/buckets/${name}/config/cors`, { value: [{ id: "cors-" + name, allowed_methods: ["GET"], allowed_origins: ["https://x.example"] }] });
    await openService("^s3$");
    await openRow(name);
    const enc = await tab("Default encryption");
    check("s3 Default encryption: SSE-S3 from the backend", /SSE-S3/.test(enc), enc);
    await tab("Lifecycle rules");
    const inputs = page.locator("#main .kv-card").last().locator("input");
    await inputs.nth(0).fill("expire-" + name);
    await inputs.nth(2).fill("45");
    await page.locator("#main button", { hasText: "Create rule" }).click();
    await sleep(1500);
    await tab("Versions");
    const lc = await tab("Lifecycle rules");
    check("s3 Lifecycle: rule created in the tab persists after reopening it", lc.includes("expire-" + name) && /45 days/.test(lc), lc);
    check("s3 Lifecycle: backend has the rule", (await call("GET", `/api/s3/buckets/${name}/config/lifecycle`)).json.value[0]?.id === "expire-" + name);
    const cors = await tab("Cross-origin resource sharing (CORS)");
    check("s3 CORS: the bucket's rule", cors.includes("cors-" + name) && cors.includes("https://x.example"), cors);
    await tab("Block Public Access");
    await page.locator("#main input[data-pab=block_public_policy]").uncheck();
    await page.locator("#main button", { hasText: "Save changes" }).click();
    await sleep(1500);
    await tab("Versions");
    await tab("Block Public Access");
    check("s3 Block Public Access: change persists after reopening the tab",
      !(await page.locator("#main input[data-pab=block_public_policy]").isChecked()) && await page.locator("#main input[data-pab=block_public_acls]").isChecked());
    const pol = await tab("Bucket Policy");
    check("s3 Bucket Policy: names this bucket's ARN", pol.includes("arn:aws:s3:::" + name), pol);
  },
  async rds() {
    const name = "rt-db-" + Date.now().toString(36);
    const c = await call("POST", "/api/rds/databases", { db_instance_identifier: name, name, engine: "postgres",
      master_username: "postgres", master_user_password: "Password123!" });
    check("rds: created", c.status < 300, JSON.stringify(c).slice(0, 200));
    const conn = (await call("GET", `/api/rds/databases/${name}/connectivity`)).json;
    await openService("^rds$");
    await openRow(name);
    const net = await tab("Networking");
    check("rds Networking: its VPC, subnets and security group", net.includes(conn.vpc_id) && net.includes(conn.subnets[0].subnet_id)
      && net.includes(conn.security_groups[0].group_id), net);
    await tab("Automated backups");
    await page.locator("#main input[data-cfg=backup_retention_period]").fill("9");
    await page.locator("#main button", { hasText: "Apply immediately" }).click();
    await sleep(1500);
    await tab("Maintenance");
    const bk = await tab("Automated backups");
    check("rds Automated backups: retention change persists after reopening the tab", /Enabled \(9 Days\)/.test(bk), bk);
    const logs = await tab("Logs & events");
    check("rds Logs & events: this instance's modification event", /Finished applying modification to backup_retention_period/.test(logs), logs);
    await call("DELETE", `/api/rds/databases/${name}`);
  },
  async dynamodb() {
    const name = "rt-t-" + Date.now().toString(36);
    await call("POST", "/api/dynamodb/tables", { name, table_name: name, partition_key_name: "user_id" });
    await call("POST", `/api/dynamodb/tables/${name}/items`, { item: { user_id: "u-" + name, plan: "pro" } });
    await openService("^dynamodb$");
    await openRow(name);
    const ov = await tab("Overview");
    check("dynamodb Overview: its partition key + ARN", ov.includes("user_id (S)") && ov.includes(":table/" + name), ov);
    const q = await tab("Query/Scan");
    check("dynamodb Query/Scan: scan returns the table's item", q.includes("u-" + name) && /Scan: items returned \(1\)/.test(q), q);
    await tab("Time to live");
    await page.locator("#main [data-testid=ddb-ttl-attr]").fill("expiresAt");
    await page.locator("#main button", { hasText: "Turn on TTL" }).click();
    await sleep(1500);
    await tab("Indexes");
    const ttl = await tab("Time to live");
    check("dynamodb TTL: turned on in the tab, persists after reopening", /TTL status\s*\nOn/i.test(ttl) && ttl.includes("expiresAt"), ttl);
    await tab("Read/write capacity");
    await page.locator("#main [data-testid=ddb-billing]").selectOption("PROVISIONED");
    await page.locator("#main button", { hasText: "Save changes" }).click();
    await sleep(1500);
    await tab("Indexes");
    const cap = await tab("Read/write capacity");
    check("dynamodb Capacity: provisioned mode persists", /Capacity mode\s*\nProvisioned/i.test(cap), cap);
    check("dynamodb Capacity: backend agrees", (await call("GET", `/api/dynamodb/tables/${name}/detail/capacity`)).json.billing_mode === "PROVISIONED");
  },
  async lambda() {
    const name = "rt-fn-" + Date.now().toString(36);
    await call("POST", "/api/lambda/functions", { name, function_name: name });
    await call("PUT", `/api/lambda/functions/${name}/detail/env`, { variables: { RT_KEY: "rt-" + name } });
    await openService("^lambda$");
    await openRow(name);
    const env = await tab("Environment variables");
    check("lambda Environment variables: this function's variables", env.includes("RT_KEY") && env.includes("rt-" + name), env);
    await tab("Code");
    const code = await page.locator("#main [data-testid=lambda-code]").inputValue();
    check("lambda Code: the function's source", /def \w+\(event, context\)/.test(code), code);
    await tab("Test");
    await page.locator("#main [data-testid=lambda-test-json]").fill('{"who": "rt"}');
    await page.locator("#main input[placeholder=MyEventName]").fill("rt-event");
    await page.locator("#main [data-testid=lambda-test-save]").click();
    await sleep(1500);
    await tab("Code");
    await tab("Test");
    const saved = await page.locator("#main [data-testid=lambda-test-event]").inputValue();
    check("lambda Test: saved test event persists after reopening the tab", saved === "rt-event", saved);
    await page.locator("#main [data-testid=lambda-test-run]").click();
    await sleep(2000);
    const res = await page.locator("#main [data-testid=lambda-test-result]").innerText().catch(() => "");
    check("lambda Test: the invocation result is shown", res.length > 2, res);
    await tab("Aliases");
    await page.locator("#main [data-testid=lambda-alias-name]").fill("live");
    await page.locator("#main [data-testid=lambda-alias-save]").click();
    await sleep(1500);
    await tab("Versions");
    const al = await tab("Aliases");
    check("lambda Aliases: alias created in the tab is listed after reopening", al.includes(":" + name + ":live"), al);
  },
  async iam() {
    const user = "rt-user-" + Date.now().toString(36);
    await call("POST", "/api/iam/users", { user_name: user, name: user, UserName: user });
    await openService("^iam$");
    await openRow(user);
    await tab("Password policy");
    await page.locator("#main [data-testid=pwd-min]").fill("17");
    await page.locator("#main [data-testid=pwd-save]").click();
    await sleep(1500);
    await tab("Identity providers");
    const pp = await tab("Password policy");
    check("iam Password policy: saved in the tab, persists after reopening", /17 characters/.test(pp), pp);
    await tab("Identity providers");
    const host = "rt-" + Date.now().toString(36) + ".example.com";
    await page.locator("#main [data-testid=idp-url]").fill("https://" + host);
    await page.locator("#main [data-testid=idp-aud]").fill("sts.amazonaws.com");
    await page.locator("#main [data-testid=idp-add]").click();
    await sleep(1500);
    await tab("Password policy");
    let idp = await tab("Identity providers");
    for (let i = 0; i < 4 && !idp.includes(":oidc-provider/" + host); i++) { await sleep(1500); await tab("Password policy"); idp = await tab("Identity providers"); }
    check("iam Identity providers: provider added in the tab is listed with its ARN", idp.includes(":oidc-provider/" + host), idp);
    const aa = await tab("Access Analyzer");
    if (await page.locator("#main [data-testid=analyzer-create]").count()) {
      await page.locator("#main [data-testid=analyzer-create]").click();
      await sleep(1500);
    }
    const aa2 = await tab("Access Analyzer");
    check("iam Access Analyzer: an account analyzer with findings section", /Active findings/.test(aa2) && /ACCOUNT/.test(aa2), aa + aa2);
  },
  async vpc() {
    const name = "rt-vpc-" + Date.now().toString(36);
    const v = await call("POST", "/api/vpc/vpcs", { name, cidr_block: "10.77.0.0/16" });
    const vid = v.json.vpc_id || v.json.id;
    await call("POST", "/api/vpc/subnets", { vpc_id: vid, vpcId: vid, cidr_block: "10.77.3.0/24", cidr: "10.77.3.0/24", availability_zone: "us-east-1a" });
    await openService("^vpc$");
    await openRow(vid);
    const det = await tab("VPC details");
    check("vpc details: this VPC's CIDR + main network ACL", det.includes("10.77.0.0/16") && /acl-/.test(det), det);
    await tab("Endpoints");
    await page.locator("#main [data-testid=vpce-create]").click();
    await sleep(1500);
    await tab("NAT gateways");
    const ep = await tab("Endpoints");
    check("vpc Endpoints: S3 gateway endpoint created in the tab persists", /com\.amazonaws\.us-east-1\.s3/.test(ep) && /vpce-/.test(ep), ep);
    await tab("Flow logs");
    await page.locator("#main [data-testid=flowlog-dest]").fill("/vpc/" + name);
    await page.locator("#main [data-testid=flowlog-create]").click();
    await sleep(1500);
    await tab("Network ACLs");
    const fl = await tab("Flow logs");
    check("vpc Flow logs: flow log created in the tab persists", fl.includes("/vpc/" + name), fl);
    const nacl = await tab("Network ACLs");
    check("vpc Network ACLs: the default NACL with its allow rules", /\(default\)/.test(nacl) && /Allow/.test(nacl), nacl);
  },
  async sqs() {
    const name = "rt-q-" + Date.now().toString(36), dlq = name + "-dlq";
    for (const n of [name, dlq]) await call("POST", "/api/sqs/queues", { name: n, queue_name: n });
    await openService("^sqs$");
    await openRow(name);
    await tab("Send and receive messages");
    await page.locator("#main [data-testid=sqs-body]").fill("hello " + name);
    await page.locator("#main [data-testid=sqs-send]").click();
    await sleep(1500);
    const sr = await tab("Send and receive messages");
    check("sqs Send and receive: the sent message is counted as available", /Messages available\s*\n\s*1\b/i.test(sr), sr);
    await page.locator("#main [data-testid=sqs-poll]").click();
    await sleep(1500);
    const polled = await page.evaluate(() => document.querySelector("#main")?.innerText || "");
    check("sqs Poll: receives the message body", polled.includes("hello " + name), polled);
    await tab("Dead-letter queue");
    const opt = await page.locator("#main [data-testid=sqs-dlq-target] option", { hasText: dlq }).first().getAttribute("value");
    await page.locator("#main [data-testid=sqs-dlq-target]").selectOption(opt);
    await page.locator("#main [data-testid=sqs-dlq-save]").click();
    await sleep(1500);
    await tab("Encryption");
    const dl = await tab("Dead-letter queue");
    check("sqs Dead-letter queue: set in the tab, persists after reopening", dl.includes(":" + dlq), dl);
    await tab("Configuration");
    await page.locator("#main input[data-cfg=visibility_timeout]").fill("75");
    await page.locator("#main [data-testid=sqs-config-save]").click();
    await sleep(1500);
    await tab("Encryption");
    const cfg = await tab("Configuration");
    check("sqs Configuration: visibility timeout change persists", /75 seconds/.test(cfg), cfg);
  },
  async sns() {
    const name = "rt-topic-" + Date.now().toString(36), q = "rt-sub-q-" + Date.now().toString(36);
    await call("POST", "/api/aws/sns/topics", { name });
    await call("POST", "/api/sqs/queues", { name: q, queue_name: q });
    const qarn = (await call("GET", `/api/sqs/queues/${q}`)).json.queue_arn;
    await openService("^amazon sns$");
    await openRow(name);
    await tab("Subscriptions");
    await page.locator("#main [data-testid=sns-endpoint]").fill(qarn);
    await page.locator("#main [data-testid=sns-subscribe]").click();
    await sleep(1500);
    await tab("Publish message");
    const subs = await tab("Subscriptions");
    check("sns Subscriptions: SQS subscription created in the tab is listed after reopening", subs.includes(qarn), subs);
    await tab("Publish message");
    await page.locator("#main [data-testid=sns-message]").fill("ping " + name);
    await page.locator("#main [data-testid=sns-publish]").click();
    await sleep(2000);
    await call("POST", `/api/aws/sns/topics/${name}/subscriptions`, { protocol: "email", endpoint: "ops@" + name + ".example.com" });
    const pub = await tab("Publish message");
    // SQS deliveries land in the queue; the log records the other protocols (here the email confirmation).
    check("sns Publish: the message log shows this topic's email delivery", pub.includes("ops@" + name + ".example.com"), pub);
    const qv = (await call("GET", `/api/sqs/queues/${q}/detail/configuration`)).json;
    check("sns Publish: the subscribed queue received it", qv.messages_available >= 1, JSON.stringify(qv).slice(0, 200));
  },
  async secretsmanager() {
    const name = "rt-sec-" + Date.now().toString(36);
    await call("POST", "/api/aws/secrets", { name, value: '{"db":"' + name + '"}' });
    await openService("^secrets manager$");
    await openRow(name);
    await tab("Secret value");
    await page.locator("#main [data-testid=secret-retrieve]").click();
    await sleep(1500);
    const v = await page.evaluate(() => document.querySelector("#main")?.innerText || "");
    check("secretsmanager Secret value: retrieves this secret's value", v.includes(name), v);
    await page.locator("#main [data-testid=secret-edit]").click();
    await page.locator("#main [data-testid=secret-edit-text]").fill('{"db":"changed-' + name + '"}');
    await page.locator("#main [data-testid=secret-save]").click();
    await sleep(1500);
    const vers = await tab("Versions");
    check("secretsmanager Versions: the edit created a new AWSCURRENT version", /AWSCURRENT/.test(vers) && /AWSPREVIOUS/.test(vers), vers);
    await tab("Replication");
    await page.locator("#main [data-testid=sec-rep-add]").click();
    await sleep(1500);
    await tab("Versions");
    const rep = await tab("Replication");
    check("secretsmanager Replication: replica added in the tab persists", /us-east-2/.test(rep) && /InSync/.test(rep), rep);
  },
  async kms() {
    const alias = "rt-key-" + Date.now().toString(36);
    const c = await call("POST", "/api/aws/kms/keys", { name: alias, alias: "alias/" + alias, description: "rt" });
    const kid = c.json.key_id || c.json.KeyId;
    await openService("^kms$");
    await openRow(kid);
    const g = await tab("General configuration");
    check("kms General configuration: this key's ID and alias", g.includes(kid) && g.includes("alias/" + alias), g);
    await tab("Key rotation");
    await page.locator("#main [data-testid=kms-rot-on]").check();
    await page.locator("#main [data-testid=kms-rot-save]").click();
    await sleep(1500);
    await tab("Aliases");
    const rot = await tab("Key rotation");
    check("kms Key rotation: enabled in the tab, persists after reopening", /Automatic key rotation\s*\nEnabled/i.test(rot), rot);
    check("kms Key rotation: backend agrees", (await call("GET", `/api/aws/kms/keys/${kid}/detail/rotation`)).json.key_rotation_enabled === true);
  },
  async eventbridge() {
    const name = "rt-rule-" + Date.now().toString(36);
    await call("POST", "/api/aws/extras/eventbridge/rules", { name, rule_type: "EventPattern", event_pattern: '{"source":["rt.app"]}' });
    await openService("^eventbridge$");
    await openRow(name);
    await tab("Targets");
    await page.locator("#main [data-testid=eb-target-arn]").fill("arn:aws:sqs:us-east-1:" + "123456789012:" + name);
    await page.locator("#main [data-testid=eb-target-add]").click();
    await sleep(1500);
    await tab("Event pattern");
    const tg = await tab("Targets");
    check("eventbridge Targets: target added in the tab persists", tg.includes(":" + name), tg);
    await tab("Event pattern");
    await page.locator("#main [data-testid=eb-test]").click();
    let res = "";
    for (let i = 0; i < 20 && !/matched/.test(res); i++) {
      await sleep(500);
      res = await page.locator("#main [data-testid=eb-test-result]").innerText().catch(() => "");
    }
    check("eventbridge Event pattern: TestEventPattern result for the rule's own pattern", /matched the event pattern/.test(res), res);
    const det = await tab("Rule details");
    check("eventbridge Rule details: this rule's ARN", det.includes(":rule/" + name), det);
  },
  async apigateway() {
    const name = "rt-api-" + Date.now().toString(36);
    const c = await call("POST", "/api/apigateway/apis", { name, mockBody: "ok" });
    const aid = c.json.rest_api_id || c.json.id || (c.json.api || {}).rest_api_id;
    await openService("^api gateway$");
    await openRow(name);
    const m = await tab("Models");
    check("apigateway Models: the API's Empty/Error models", /Empty/.test(m) && /Error/.test(m), m);
    await tab("Deployments");
    await page.locator("#main [data-testid=apigw-dep-stage]").fill("rtstage");
    await page.locator("#main [data-testid=apigw-deploy]").click();
    await sleep(1500);
    let dep = "";
    for (let i = 0; i < 6 && !/rtstage/.test(dep); i++) {   // the deploy is async on a loaded host: poll, don't guess
      await tab("Models");
      dep = await tab("Deployments");
      if (!/rtstage/.test(dep)) await sleep(1500);
    }
    check("apigateway Deployments: deployment made in the tab is listed", /rtstage/.test(dep), dep);
    await tab("Settings");
    await page.locator("#main [data-testid=apigw-settings-save]").click();
    await sleep(1200);
    const st = (await call("GET", `/api/apigateway/apis/${aid}/detail/settings`)).json;
    check("apigateway Settings: API ID from the backend", st.rest_api_id === aid, JSON.stringify(st).slice(0, 200));
  },
  async stepfunctions() {
    const name = "rt-sm-" + Date.now().toString(36);
    await call("POST", "/api/stepfunctions/machines", { name });
    await openService("^step functions$");
    await openRow(name);
    const def = await tab("Definition");
    check("stepfunctions Definition: the machine's states from its ASL", /States \(\d+\)/.test(def) && /Start state/.test(def), def);
    const asl = JSON.stringify({ StartAt: "RtOnly", States: { RtOnly: { Type: "Pass", End: true } } });
    await page.locator("#main [data-testid=sfn-definition]").fill(asl);
    await page.locator("#main [data-testid=sfn-definition-save]").click();
    await sleep(1500);
    await tab("Executions");
    const def2 = await tab("Definition");
    check("stepfunctions Definition: an edited definition persists (UpdateStateMachine)", /RtOnly/.test(def2), def2);
  },
  async ssm() {
    const name = "/rt/" + Date.now().toString(36);
    await call("POST", "/api/ssm/parameters", { name, value: "rt-value-" + name.slice(4), type: "String" });
    await openService("^systems manager$");
    await openRow(name);
    const v = await tab("Value");
    check("ssm Value: GetParameter value + version of this parameter", v.includes("rt-value-" + name.slice(4)) && /VERSION\s*\n\s*1/i.test(v), v);
    const props = (await call("GET", "/api/ssm/parameters/" + encodeURIComponent(name) + "/metadata")).json;
    check("ssm Properties: DescribeParameters metadata without the value", props.name === name && props.value === undefined, JSON.stringify(props).slice(0, 200));
  },
};

let server;
try {
  if (url) {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else {
    const s = await startServer(); server = s.server;
    await bootConsole(page, s.base, "/aws-console.html");
  }
  const base = page.url();
  for (const k of (process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SECTIONS))) {
    try { await SECTIONS[k](); } catch (e) { check(`${k}: section ran`, false, String(e).split("\n")[0]); }
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 120000 });
  }
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
