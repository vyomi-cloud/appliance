/* UI proof: drive the REAL Nano v4 AWS console (wasm/v4/aws, the exact bundle the portal serves) in headless Chromium, pair the tab with the
 * Mesh-mode server the Terraform estate was applied to, create a mesh-homed space (so every /_wire call goes to that server), then open a
 * representative list (+ detail) page per service and assert the Terraform-created resources are rendered (names, ids, status).
 *   NODE_PATH=<dir with playwright> node run_ui.mjs <endpoint> <tfstate> <out.json>
 * Reuses wasm/ui-tests/lib.mjs (startServer). Output: {check_name: {ok, detail, pages:[...]}}; check names match checks.py.
 * Server must run in mesh mode with a licence that allows pairing: tests/endurance/proof/run_mesh_server.py. */
import { readFileSync, writeFileSync } from "node:fs";
import { startServer, chromium } from "../../../../wasm/ui-tests/lib.mjs";

const [, , MESH, STATE, OUT] = process.argv;
const tf = JSON.parse(readFileSync(STATE, "utf8"));
const R = {};
for (const r of tf.resources) if (r.mode === "managed" && r.instances.length) R[r.type + "." + r.name] = r.instances[0].attributes;
const A = (k) => R[k];
const lastSeg = (s) => String(s).split("/").pop();

// check name -> [{route, expect:[strings]}]   (all pages of a check must pass)
const P = {
  vpc: [{ route: "#/vpc/vpcs", expect: [A("aws_vpc.main").id, A("aws_vpc.main").cidr_block] }],
  subnets: [{ route: "#/vpc/subnets", expect: [A("aws_subnet.public").id, A("aws_subnet.private").id, A("aws_subnet.public").cidr_block] }],
  igw: [{ route: "#/vpc/internet-gateways", expect: [A("aws_internet_gateway.main").id] }],
  eip: [{ route: "#/vpc/elastic-ips", expect: [A("aws_eip.nat").id, A("aws_eip.nat").public_ip] }],
  nat: [{ route: "#/vpc/nat-gateways", expect: [A("aws_nat_gateway.main").id] }],
  route_tables: [{ route: "#/vpc/route-tables", expect: [A("aws_route_table.public").id, A("aws_route_table.private").id] }],
  nacl: [{ route: "#/vpc/network-acls", expect: [A("aws_network_acl.private").id] }],
  sgs: [{ route: "#/vpc/security-groups", expect: [A("aws_security_group.web").id, A("aws_security_group.db").id] },
        { route: "#/ec2/security-groups", expect: [A("aws_security_group.web").id] }],
  prefix_list: [{ route: "#/vpc/managed-prefix-lists", expect: [A("aws_ec2_managed_prefix_list.office").id, "endurance-office"] }],
  dhcp: [{ route: "#/vpc/dhcp-option-sets", expect: [A("aws_vpc_dhcp_options.main").id] }],
  kms: [{ route: "#/kms/customer-managed-keys", expect: ["endurance-data", A("aws_kms_key.data").key_id] },
        { route: "#/kms/customer-managed-keys/" + A("aws_kms_key.data").key_id, expect: [A("aws_kms_key.data").key_id, "Enabled"] }],
  iam_role: [{ route: "#/iam/roles", expect: ["endurance-app", "AmazonBedrockExecutionRoleForAgents_endurance"] },
             { route: "#/iam/roles/endurance-app", expect: ["endurance-app", "endurance-app-access"] }],
  iam_policy: [{ route: "#/iam/policies", expect: ["endurance-app-access"] }],
  iam_user: [{ route: "#/iam/users", expect: ["endurance-ops"] }, { route: "#/iam/groups", expect: ["endurance-ops"] }],
  instance_profile: null,   // IAM instance profiles have no page in the v4 AWS console (IAM nav: users/groups/roles/policies/...): honest n/a
  secret: [{ route: "#/secretsmanager/listsecrets", expect: ["endurance/db-password"] },
           { route: "#/secretsmanager/secret/endurance%2Fdb-password", expect: ["endurance/db-password"] }],
  s3: [{ route: "#/s3/buckets", expect: ["endurance-assets"] }, { route: "#/s3/buckets/endurance-assets", expect: ["endurance-assets"] }],
  rds: [{ route: "#/rds/databases", expect: ["endurance-db", "postgres"] }, { route: "#/rds/subnet-groups", expect: ["endurance-db"] },
        { route: "#/rds/parameter-groups", expect: ["endurance-pg16"] }, { route: "#/rds/snapshots", expect: ["endurance-db-snap"] }],
  ddb: [{ route: "#/dynamodb/tables", expect: ["endurance-orders"] }, { route: "#/dynamodb/tables/endurance-orders", tab: "Indexes", expect: ["endurance-orders", "by-customer"] }],
  ecr: [{ route: "#/ecr/repositories", expect: ["endurance/app"] }],
  ec2_misc: [{ route: "#/ec2/key-pairs", expect: ["endurance-ops"] }, { route: "#/ec2/launch-templates", expect: ["endurance-app"] },
             { route: "#/ec2/volumes", expect: [A("aws_ebs_volume.data").id] }],
  sqs: [{ route: "#/sqs/queues", expect: ["endurance-orders", "endurance-orders-dlq", "endurance-ledger.fifo"] }, { route: "#/sqs/queues/endurance-orders", expect: ["endurance-orders"] }],
  sns: [{ route: "#/sns/topics", expect: ["endurance-events"] }, { route: "#/sns/subscriptions", expect: ["endurance-orders"] }],
  events: [{ route: "#/eventbridge/event-buses", expect: ["endurance-bus"] }, { route: "#/eventbridge/rules", expect: ["endurance-nightly"] }],
  bedrock: [{ route: "#/bedrock/guardrails", expect: ["endurance-guardrail"] }, { route: "#/bedrock/agents", expect: ["endurance-agent"] }],
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { server, base } = await startServer(new URL("../../../../wasm", import.meta.url).pathname);
const browser = await chromium.launch();
const ctx = await browser.newContext();
// default 5 s health poll: the mesh rate-limits /mesh/* to 30 req/min, a faster poll flips the tab to "unreachable" mid-run
const page = await ctx.newPage();
const out = {};
let fatal = null;
try {
  await page.goto(base + "/v4/aws/index.html", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.VyomiMesh && navigator.serviceWorker.controller, null, { timeout: 120000, polling: 500 });
  const code = (await (await fetch(MESH + "/mesh/pair/start", { method: "POST" })).json()).code;
  const paired = await page.evaluate(([b, c]) => VyomiMesh.pair(b, c).then(() => "ok", (e) => "ERR " + e.message), [MESH, code]);
  if (paired !== "ok") throw new Error("pairing failed: " + paired);
  await page.waitForFunction(() => VyomiMesh.list().some((b) => VyomiMesh.state(b.id) === "connected"), null, { timeout: 40000 });
  const id = await page.evaluate(() => VyomiMesh.list()[0].id);
  const st = await page.evaluate(async (id) => (await fetch("/api/spaces", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ provider: "aws", name: "endurance-proof", region: "us-east-1", home: { type: "mesh", mesh_id: id, mesh_name: "endurance-proof-mesh" } }) })).status, id);
  if (st !== 201) throw new Error("mesh-homed space create -> " + st);
  await page.goto(base + "/v4/aws/index.html#/kms/home", { waitUntil: "domcontentloaded" });
  await page.reload();
  await page.waitForFunction(() => document.body && document.body.innerText.length > 200, null, { timeout: 60000 });
  for (const [name, pages] of Object.entries(P)) {
    if (!pages) { out[name] = { ok: null, detail: "n/a: no console page" }; continue; }
    const res = [];
    for (const p of pages) {
      let miss = p.expect, err = null;
      // one retry when the page shows a transport error ("Failed to load ... HTTP 503" is the mesh link's own refusal while a 2.5 s health probe
      // of the busy single-process server flickered): wait for the link to be connected again, then re-open the page. A page that renders but
      // lacks the resource is never retried-away: it still fails.
      for (let attempt = 0; attempt < 2; attempt++) {
        await page.waitForFunction(() => VyomiMesh.list().some((b) => VyomiMesh.state(b.id) === "connected"), null, { timeout: 30000 }).catch(() => {});
        if (attempt) { await page.evaluate(() => { location.hash = "/kms/home"; }); await sleep(800); }
        await page.evaluate((h) => { location.hash = h; }, p.route.slice(1));
        let text = "";
        if (p.tab) { await sleep(2500); await page.getByRole("tab", { name: p.tab }).first().click({ timeout: 8000 }).catch(() => page.getByText(p.tab, { exact: true }).first().click({ timeout: 4000 }).catch(() => {})); }
        for (let i = 0; i < 40; i++) {   // up to ~20 s per page
          await sleep(500);
          text = await page.evaluate(() => document.body.innerText);
          miss = p.expect.filter((s) => !text.includes(s));
          if (!miss.length) break;
        }
        const m = /Failed to load|HTTP [45]\d\d|Something went wrong/.exec(text);
        err = m ? m[0] : null;
        if (!miss.length || !err) break;
      }
      res.push({ route: p.route, ok: !miss.length, missing: miss, error: miss.length && err ? err : undefined });
      console.log(`${miss.length ? "FAIL" : "PASS"} ui ${name} ${p.route}${miss.length ? " missing " + JSON.stringify(miss) + (err ? " [" + err + "]" : "") : ""}`);
    }
    out[name] = { ok: res.every((r) => r.ok), detail: res.filter((r) => !r.ok).map((r) => r.route + " missing " + r.missing.join("|")).join("; "), pages: res };
  }
} catch (e) { fatal = String(e && e.stack || e); console.log("FATAL " + fatal); }
writeFileSync(OUT, JSON.stringify({ fatal, checks: out }, null, 1));
await browser.close(); server.close();
process.exit(fatal ? 2 : 0);
