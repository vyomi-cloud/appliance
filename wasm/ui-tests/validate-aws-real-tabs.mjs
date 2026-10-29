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
