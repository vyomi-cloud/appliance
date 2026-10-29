/* GCP Activity tab: every recorded event must carry a non-empty Detail.
 * Nano by default; VYOMI_CONSOLE_URL drives the offline console instead. */
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
  const topic = "actchk" + Date.now().toString(36);
  const events = await page.evaluate(async (t) => {
    const j = { method: "POST", headers: { "content-type": "application/json" } };
    await fetch(`/api/gcp/pubsub/v1/projects/${PROJECT}/topics`, { ...j, body: JSON.stringify({ name: t }) });
    const r = await fetch(`/api/cloudsim/events?resource=${t}&provider=gcp&limit=50`);
    return (await r.json()).events || [];
  }, topic);
  check("create event recorded", events.length > 0, JSON.stringify(events));
  const bad = events.filter((e) => !String(e.detail || "").trim() || /undefined|null/.test(e.detail));
  check("every event has a Detail", events.length > 0 && bad.length === 0, JSON.stringify(bad));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
