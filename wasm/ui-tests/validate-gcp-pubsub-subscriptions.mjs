/* GCP Pub/Sub: the project-level subscriptions collection the topics grid reads must
 * answer (GET 200, not 501) and list a subscription created on a topic.
 * Nano by default; VYOMI_CONSOLE_URL drives the offline console instead. */
import { startServer, bootConsole, chromium, RAIL_SEL } from "./lib.mjs";

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
  const tag = Date.now().toString(36);
  const r = await page.evaluate(async (tag) => {
    const base = `/api/gcp/pubsub/v1/projects/${PROJECT}`;
    const j = (b) => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    await fetch(`${base}/topics`, j({ name: "t" + tag }));
    const empty = await fetch(`${base}/subscriptions`);
    const mk = await fetch(`${base}/subscriptions/s${tag}`, { ...j({ topic: `projects/${PROJECT}/topics/t${tag}` }), method: "PUT" });
    const l = await fetch(`${base}/subscriptions`);
    const body = l.ok ? await l.json() : {};
    return { listStatus: empty.status, createStatus: mk.status, subs: (body.subscriptions || body.items || []).map((x) => String(x.name).split("/").pop()) };
  }, tag);
  check("GET subscriptions answers 200", r.listStatus === 200, JSON.stringify(r));
  check("PUT subscription succeeds", r.createStatus < 300, JSON.stringify(r));
  check("created subscription is listed", r.subs.includes("s" + tag), JSON.stringify(r));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
