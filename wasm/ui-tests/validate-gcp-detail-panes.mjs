/* GCP detail tabs show this resource's real data: Activity lists the resource's own
 * events, Permissions lists the project's IAM bindings, no tab says "This pane mirrors".
 * Nano by default; VYOMI_CONSOLE_URL (e.g. $VYOMI_BASE_URL/console/gcp) drives offline. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const offline = process.env.VYOMI_CONSOLE_URL;
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  if (offline) {
    await page.goto(offline, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else {
    const s = await startServer(); server = s.server;
    await bootConsole(page, s.base, "/gcp-console.html");
  }
  const topic = "panechk" + Date.now().toString(36);
  const member = "user:pane-check@example.com";
  await page.evaluate(async ({ t, member, offline }) => {
    const j = { method: "POST", headers: { "content-type": "application/json" } };
    await fetch(`/api/gcp/pubsub/v1/projects/${PROJECT}/topics`, { ...j, body: JSON.stringify({ name: t }) });
    const bindings = [{ role: "roles/pubsub.viewer", members: [member] }];
    if (offline) await fetch(`/api/gcp/iam/v1/projects/${PROJECT}:setIamPolicy`, { ...j, body: JSON.stringify({ policy: { bindings } }) });
    else await fetch(`/api/gcp/sub/iam/setProjectPolicy/${PROJECT}`, { ...j, body: JSON.stringify({ bindings }) });
  }, { t: topic, member, offline: !!offline });
  await page.evaluate((sel) => [...document.querySelectorAll(sel)].find((e) => /pub\/sub/i.test(e.innerText))?.click(), RAIL_SEL);
  await sleep(2500);
  const opened = await page.evaluate((t) => { const a = [...document.querySelectorAll("#main a.id")].find((e) => e.innerText.includes(t)); if (a) { a.click(); return true; } return false; }, topic);
  check("topic detail opens", opened);
  await sleep(1200);
  const tabText = async (label) => {
    await page.evaluate((l) => { const b = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => e.innerText.trim().endsWith(l)); b && b.click(); }, label);
    await sleep(1500);
    return page.evaluate(() => (document.querySelector("#main .sub-content") || {}).innerText || "");
  };
  const act = await tabText("Activity");
  check("Activity lists this topic's events", act.includes(topic) && /create/i.test(act), act.slice(0, 200));
  const perm = await tabText("Permissions");
  check("Permissions shows the project's IAM bindings", perm.includes("roles/pubsub.viewer") && perm.includes(member), perm.slice(0, 200));
  const names = await page.evaluate(() => [...document.querySelectorAll("#main .sub-nav a.nav-item")].map((e) => e.innerText.trim()));
  let mirrors = [];
  for (let i = 0; i < names.length; i++) {
    const t = await tabText(names[i].replace(/^\S+\s+/, ""));
    if (/This pane mirrors|Wiring lands/.test(t)) mirrors.push(names[i]);
  }
  check("no placeholder panes", names.length > 0 && !mirrors.length, mirrors.join(", "));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
