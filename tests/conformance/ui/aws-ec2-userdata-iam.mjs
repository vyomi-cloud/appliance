/* Offline console conformance — AWS EC2 User data / IAM role / EC2 serial console tabs
 * (against $VYOMI_BASE_URL/console/aws). Each shows this instance's own data; a saved change
 * is still there after reopening the tab and over the API.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-ec2-userdata-iam.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const J = { "content-type": "application/json" };
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
let iid = "";
try {
  const cr = await fetch(`${BASE}/api/ec2/instances`, { method: "POST", headers: J,
    body: JSON.stringify({ name: "ui-ud-iam", user_data: "#!/bin/bash\necho from-user-data", iam_instance_profile: "web-role" }) });
  const inst = await cr.json();
  iid = inst.instance_id || "";
  check(cr.ok && iid && inst.iam_instance_profile === "web-role", "instance created with user data + IAM profile", JSON.stringify(inst).slice(0, 120));
  await fetch(`${BASE}/api/ec2/instances/${iid}/stop`, { method: "POST" });
  for (let i = 0; i < 20; i++) {
    const g = await (await fetch(`${BASE}/api/ec2/instances/${iid}`)).json();
    if (g.state === "stopped") break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.locator(RAIL_SEL).filter({ hasText: /EC2/ }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  await page.locator("#main table a.id, #main table td a").filter({ hasText: iid }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const openTab = async (name) => {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp("^\\s*" + name + "\\s*$") }).first().click({ timeout: 5000 });
    await page.waitForTimeout(900);
    return page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText + " " + [...n.querySelectorAll("textarea,input")].map((e) => e.value).join(" ") : ""; });
  };
  const real = (t) => !/This pane mirrors|Not yet wired|Coming soon/.test(t);

  let t = await openTab("User data");
  check(real(t) && /from-user-data/.test(t), "User data tab shows the instance's user data", t.slice(0, 160));
  t = await openTab("IAM role");
  check(real(t) && /web-role/.test(t), "IAM role tab shows the attached profile", t.slice(0, 160));
  t = await openTab("EC2 serial console");
  check(real(t) && new RegExp(iid).test(t), "Serial console tab shows this instance", t.slice(0, 160));

  await openTab("User data");
  await page.fill("#ec2-user-data", "#!/bin/bash\necho edited-data");
  await page.click("#ec2-user-data-save");
  await page.waitForTimeout(1200);
  await openTab("IAM role");
  t = await openTab("User data");
  check(/edited-data/.test(t), "saved user data survives re-opening the tab", t.slice(0, 160));
  await openTab("IAM role");
  await page.fill("#ec2-iam-profile", "db-role");
  await page.click("#ec2-iam-save");
  await page.waitForTimeout(1200);
  await openTab("User data");
  t = await openTab("IAM role");
  check(/db-role/.test(t), "saved IAM role survives re-opening the tab", t.slice(0, 160));
  const g = await (await fetch(`${BASE}/api/ec2/instances/${iid}`)).json();
  check(g.iam_instance_profile === "db-role" && /edited-data/.test(g.user_data), "the API returns the saved attributes", JSON.stringify([g.iam_instance_profile, g.user_data]));
} catch (e) {
  check(false, "console flow", String(e).slice(0, 200));
} finally {
  if (iid) await fetch(`${BASE}/api/ec2/instances/${iid}`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
