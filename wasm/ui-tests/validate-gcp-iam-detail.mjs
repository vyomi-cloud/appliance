/* GCP IAM & Admin service-account detail (Nano): Members lists the roles the project
 * policy grants to the account, Permissions lists the project bindings, and a removed
 * binding disappears on reopen. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  const s = await startServer(); server = s.server;
  await bootConsole(page, s.base, "/gcp-console.html");
  const acct = "iamval" + Date.now().toString(36);
  const email = await page.evaluate(async (a) => {
    const j = { method: "POST", headers: { "content-type": "application/json" } };
    const r = await (await fetch(`/api/gcp/iam/v1/projects/${PROJECT}/serviceAccounts`, { ...j, body: JSON.stringify({ accountId: a, serviceAccount: { displayName: a } }) })).json();
    await fetch(`/api/gcp/sub/iam/setProjectPolicy/${PROJECT}`, { ...j, body: JSON.stringify({ bindings: [{ role: "roles/viewer", members: ["serviceAccount:" + r.email] }] }) });
    return r.email;
  }, acct);
  await page.evaluate((sel) => [...document.querySelectorAll(sel)].find((e) => /IAM & Admin/i.test(e.innerText))?.click(), RAIL_SEL);
  await sleep(2500);
  const opened = await page.evaluate((e) => { const a = [...document.querySelectorAll("#main a.id")].find((x) => x.innerText.trim() === e); if (a) { a.click(); return true; } return false; }, email);
  check("service account detail opens", opened, email);
  await sleep(1200);
  const tab = async (label) => {
    await page.evaluate((l) => { const b = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => e.innerText.includes(l)); b && b.click(); }, label);
    await sleep(1500);
    return page.evaluate(() => (document.querySelector("#main .sub-content") || {}).innerText || "");
  };
  let t = await tab("Members");
  check("Members lists the role granted to this account", t.includes(email) && t.includes("roles/viewer"), t.slice(0, 150));
  t = await tab("Permissions");
  check("Permissions lists the project policy bindings", t.includes("roles/viewer") && t.includes(email), t.slice(0, 150));
  await page.evaluate(async () => { await fetch(`/api/gcp/sub/iam/setProjectPolicy/${PROJECT}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ bindings: [] }) }); });
  await tab("Overview");
  t = await tab("Members");
  check("Members reflects a removed binding after reopening", !t.includes("roles/viewer") && t.includes("no roles"), t.slice(0, 150));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
if (server) server.close?.();
process.exit(checks.every(Boolean) && checks.length ? 0 : 1);
