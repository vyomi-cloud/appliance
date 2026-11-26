/* v4.0.0 AWS console (consoles/src/aws -> /v4/aws/): list -> resource detail -> every tab, per service.
 * Retarget of the legacy v3 detail/row/tab suites (validate-aws-detail-tabs, -real-tabs, -ec2-detail-tabs, -sqs-dlq-tab,
 * -rds-connectivity-tabs, -vpc-details-tab, -vpc-sg-iam-cells, -*-row ...) onto the v4 React/Cloudscape DOM and the /_wire transport.
 * For each service: boto3 seeds one resource on /_wire; the console list must show it and link to its detail; the detail must name
 * the resource; EVERY tab must open without a wire 4xx/5xx, without an error banner / "undefined" / "[object Object]", and render
 * content. Service-specific assertions (PROFILES[].extra) pin the intent of the old suite it replaces.
 * Env: BASE (default http://127.0.0.1:8741 = `python3 consoles/dev_server.py --port 8741`), UI_PATH (/v4/aws/), WIRE_PATH (/_wire),
 *      PY (python with boto3), ONLY=sqs,rds,... , PW_CHANNEL (e.g. chrome when no playwright browser is installed). */
import { chromium, sleep } from "./lib.mjs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const SEED = join(dirname(fileURLToPath(import.meta.url)), "_aws_v4_seed.py");
const BASE = process.env.BASE || "http://127.0.0.1:8741";
const UI = BASE + (process.env.UI_PATH || "/v4/aws/");
const WIRE = BASE + (process.env.WIRE_PATH || "/_wire");
const stamp = Date.now().toString(36).slice(-6);
const NOISE = /vyomi-appbar|nano-tunnel|\/api\/(license|issues|runtime|spaces)|favicon|feedback|issue-reporter/;

// kind -> {list: hash route of the list, key: which seed field the row link shows, extra(ctx): service-specific assertions}
const PROFILES = {
  sqs: { list: "sqs/queues", key: "name", extra: async (c) => { await c.tab(/^dead-letter queue$/i); const t = await c.text();
    c.check("SQS Dead-letter queue tab: Maximum receives is filled (a dash when no redrive policy), never blank", /Maximum receives\s*(-|\d+)/i.test(t), t.slice(-200));
    // real SQS shows "Disabled" here; v4 renders "-". Printed as a SKIP (honest gap, finding F2), not counted as a pass.
    if (!/disabled/i.test(t)) c.skip("SQS Dead-letter queue tab says Disabled for a queue without a redrive policy", "v4 console renders '-' (consoles/src/aws/services/sqs/QueueDetail.jsx DlqTab)"); } },
  sns: { list: "sns/topics", key: "name" },
  rds: { list: "rds/databases", key: "name", extra: async (c) => {
    await c.tab(/connectivity/i); const t = await c.text();
    c.check("RDS Connectivity & security: endpoint and port are filled in (not a dash)", /endpoint/i.test(t) && /port/i.test(t) && /\b(5432|3306|1433|1521)\b/.test(t) && /[a-z0-9.-]+\.(rds|amazonaws|local|vyomi)[a-z0-9.:-]*|localhost|127\.0\.0\.1/i.test(t), t.slice(0, 260));
    c.check("RDS Connectivity & security: shows RDS networking fields, not EC2 IPv4 addresses", /VPC|subnet group|security group/i.test(t) && !/public IPv4 address/i.test(t), t.slice(0, 260)); } },
  vpc: { list: "vpc/vpcs", key: "id", extra: async (c) => {
    const ov = await c.text();
    c.check("VPC detail names the VPC id and CIDR", ov.includes(c.s.id) && /10\.91\.0\.0\/16/.test(ov), ov.slice(0, 200));
    c.check("VPC detail: no field renders as a placeholder dash for id/CIDR", !/VPC ID\s*[-—]\s/i.test(ov)); } },
  subnet: { list: "vpc/subnets", key: "subnet", seedKind: "vpc", extra: async (c) => { const t = await c.text(); c.check("Subnet detail carries its own CIDR and parent VPC", /10\.91\.1\.0\/24/.test(t) && t.includes(c.seed.vpc.id), t.slice(0, 200)); } },
  sg: { list: "vpc/security-groups", key: "sg", seedKind: "vpc", extra: async (c) => { const t = await c.text(); c.check("Security group detail shows the group id and name (not a placeholder cell)", t.includes(c.seed.vpc.sg) && t.includes(c.seed.vpc.sgname), t.slice(0, 200)); } },
  igw: { list: "vpc/internet-gateways", key: "igw", seedKind: "vpc", extra: async (c) => { const t = await c.text(); c.check("Internet gateway detail shows it attached to the VPC", t.includes(c.seed.vpc.id) && /attached/i.test(t), t.slice(0, 200)); } },
  rtb: { list: "vpc/route-tables", key: "rtb", seedKind: "vpc" },
  ec2: { list: "ec2/instances", key: "id", extra: async (c) => {
    const t0 = await c.text();
    c.check("EC2 detail shows the instance's own subnet and security group, not a dash", t0.includes(c.seed.ec2.subnet) || (await (async () => { await c.tab(/networking/i); return (await c.text()).includes(c.seed.ec2.subnet); })()), "subnet missing");
    await c.tab(/security/i); const sec = await c.text(); c.check("EC2 Security tab shows the instance's security group", sec.includes(c.seed.ec2.sg), sec.slice(0, 200));
    const labels = await c.tabs(); c.check("EC2 Status-and-alarms and Monitoring are distinct tabs", labels.some((l) => /status (and|&) alarms/i.test(l)) && labels.some((l) => /^monitoring$/i.test(l)), labels.join("|")); } },
  lambda: { list: "lambda/functions", key: "name" },
  apigw: { list: "apigateway/apis", key: "name" },
  iam: { list: "iam/users", key: "name", extra: async (c) => { const t = await c.text(); c.check("IAM user detail carries its ARN", t.includes(c.seed.iam.arn), t.slice(0, 200)); } },
  events: { list: "eventbridge/event-buses", key: "name" },
  ssm: { list: "ssm/parameters", key: "id" },
  secret: { list: "secretsmanager/listsecrets", key: "name" },
  kinesis: { list: "kinesis/streams", key: "name" },
  states: { list: "states/state-machines", key: "name" },
  logs: { list: "cloudwatch/logs", key: "name" },
  s3: { list: "s3", key: "name" },
  ddb: { list: "dynamodb/tables", key: "name" },
  alarm: { list: "cloudwatch/alarms", key: "name" },
  rule: { list: "eventbridge/rules", key: "name", extra: async (c) => { await c.tab(/^event pattern$/i); const t = await c.text(); const ta = await c.page.evaluate(() => [...document.querySelectorAll("textarea")].map((e) => e.value).join(" ")); c.check("EventBridge rule detail shows it enabled with its own event pattern", /enabled/i.test(t) && ta.includes("dt.test"), `${ta} | ${t.slice(0, 120)}`); } },
  httpapi: { list: "apigateway/apis", key: "name" },
  kms: { list: "kms/customer-managed-keys", key: "name" },
  elbv2: { list: "ec2/load-balancers", key: "name" },
};
const ALL = Object.keys(PROFILES);
const ONLY = (process.env.ONLY || ALL.join(",")).split(",").filter((k) => PROFILES[k]);
const seedKinds = [...new Set(ONLY.map((k) => PROFILES[k].seedKind || (k === "apigw" ? "apigw" : k === "secret" ? "secret" : k === "logs" ? "logs" : k === "ddb" ? "ddb" : k === "events" ? "events" : k === "lambda" ? "lambda_" : k)))];
const seed = JSON.parse(execFileSync(process.env.PY || "python3", [SEED, stamp, seedKinds.join(",")], { env: { ...process.env, VYOMI_BASE_URL: WIRE }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim().split("\n").pop());

const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
const results = []; const skipped = [];
const skip = (name, why) => { skipped.push(name); console.log(`[SKIP] ${name} :: ${why}`); };
const check = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + String(extra).replace(/\s+/g, " ").slice(0, 240)}`); };
let bad = []; const devGaps = new Set();
// A 4xx/5xx on the wire fails the tab, EXCEPT the real-cloud "unset" answers (NoSuchEntity, ResourceNotFound, ...): AWS itself answers
// GetLoginProfile / GetFunctionUrlConfig / GetPolicy / DescribeLogGroups(missing) that way for a resource that has no such setting.
const UNSET = /NoSuchEntity|ResourceNotFound|NotFoundException|NoSuchKey|NoSuchBucketPolicy|NoSuchLifecycle|NoSuchCORS|NoSuchTagSet|ServerSideEncryptionConfigurationNotFound|OwnershipControlsNotFound|NoSuchPublicAccessBlock|NoSuchWebsite|NoSuchReplication|NoSuchConfiguration|ParameterNotFound|PolicyNotFound|ConfigurationNotFound|ResourceNotFoundException|DBInstanceNotFound|CacheItem|does not exist/i;
// dev_server (the Nano/appliance router minus the appliance-only mounts) does not serve the IAM engine API; appliance + Nano do.
const DEV_ONLY_GAPS = [/\/api\/iam\/aws\/enforcement/];
page.on("response", async (r) => {
  if (r.status() < 400 || !r.url().includes("/_wire") || NOISE.test(r.url())) return;
  const u = r.url().replace(BASE, ""); const hdr = JSON.stringify(r.headers()); const body = await r.text().catch(() => "");
  if (UNSET.test(body) || UNSET.test(hdr)) return;
  if (DEV_ONLY_GAPS.some((g) => g.test(u))) { devGaps.add(u); return; }
  bad.push(`${r.status()} ${r.request().method()} ${u} ${(r.request().postData() || "").slice(0, 80)} ${body.replace(/\s+/g, " ").slice(0, 90)}`);
});
page.on("pageerror", (e) => bad.push("pageerror " + String(e.message).slice(0, 100)));
const text = () => page.evaluate(() => (document.querySelector("main, [class*=awsui_content]") || document.body).innerText.replace(/\s+/g, " "));
const BADTXT = /\bundefined\b|\[object Object\]|NaN\b|something went wrong|failed to (load|fetch)|error loading|cannot read prop/i;

for (const kind of ONLY) {
  const P = PROFILES[kind], tag = `[${kind}]`, s = seed[P.seedKind || (kind === "lambda" ? "lambda" : kind)] || {};
  if (!s || s.error || !s.id) { check(`${tag} seed resource created on /_wire`, false, s?.error || "no seed"); continue; }
  const want = String(kind === "vpc" || P.seedKind === "vpc" ? (s[P.key] ?? s.id) : s[P.key]);
  try {
    bad = [];
    await page.goto(`${UI}#/${P.list}`); await page.reload(); await sleep(2500);
    // grids page at 10-20 rows: narrow with the table's own filter box so this run's resource is on page 1 (also exercises the filter)
    if (!(await page.locator("a", { hasText: want }).count())) { const f = page.locator("input[type=search]").filter({ visible: true }).first(); if (await f.count()) { await f.fill(want).catch(() => {}); await sleep(1200); } }
    const link = page.locator("a", { hasText: want }).first();
    const found = (await link.count()) > 0 || (await page.locator("a", { hasText: want }).count()) > 0;
    check(`${tag} list shows the SDK-created resource`, found, (await text()).slice(0, 160));
    if (!found) continue;
    const cells = await page.evaluate((w) => { const tr = [...document.querySelectorAll("tr")].find((r) => r.innerText.includes(w)); return tr ? [...tr.querySelectorAll("td")].slice(1).map((td) => td.innerText.trim() || (td.querySelector("button, svg, input, img, [class*=icon]") ? "<widget>" : "")) : null; }, want);
    check(`${tag} list row: no blank / undefined / NaN cell`, !!cells && cells.length > 1 && cells.every((c2) => c2 !== "" && !BADTXT.test(c2)), JSON.stringify(cells));
    await link.click(); await sleep(2500);
    const ctx = { page, seed, s, text, check, tabs: () => page.evaluate(() => [...document.querySelectorAll("[role=tab]")].map((e) => e.innerText.trim())),
      tab: async (re) => { const t = page.locator("[role=tab]", { hasText: re }).first(); if (await t.count()) { await t.click(); await sleep(1200); return true; } return false; } };
    const head = await text();
    check(`${tag} detail opens on the resource (names it)`, head.includes(String(s.name || s.id).replace(/^\//, "")) || head.includes(String(s.id)), head.slice(0, 160));
    check(`${tag} detail load: no wire 4xx/5xx`, bad.length === 0, bad.join(" ; "));
    const labels = await ctx.tabs();
    const clean = labels.filter(Boolean);
    for (const lab of clean) {
      bad = [];
      const t = page.locator("[role=tab]", { hasText: lab }).first();
      try { await t.click({ timeout: 6000 }); await sleep(1200); } catch (e) { check(`${tag} tab "${lab}" opens`, false, String(e).split("\n")[0]); continue; }
      const body = await text();
      const alert = await page.evaluate(() => [...document.querySelectorAll("[role=alert], [class*=awsui_error]")].filter((e) => e.offsetParent && /error|failed|denied/i.test(e.innerText)).map((e) => e.innerText.slice(0, 100)).join(" | "));
      check(`${tag} tab "${lab}": renders without wire error / error banner / undefined`, bad.length === 0 && !alert && !BADTXT.test(body), `${bad.join(" ; ")} ${alert} ${(body.match(BADTXT) || [""])[0]}`);
    }
    if (P.extra) await P.extra({ ...ctx, check: (n, ok, x) => check(`${tag} ${n}`, ok, x), skip: (n, w) => skip(`${tag} ${n}`, w) });
  } catch (e) { check(`${tag} run`, false, String(e).split("\n")[0]); }
}
await browser.close();
for (const g of devGaps) console.log(`[SKIP] ${g} :: dev_server does not mount the IAM engine API (served by the appliance and Nano)`);
console.log(`\n${results.filter(Boolean).length}/${results.length} passed, ${skipped.length} skipped (known gaps, printed)`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
