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
