/* GCP Pub/Sub topics grid: a topic created with default values must show a
 * real value in every column (Retention, Encryption, Subscriptions) — never
 * "-", blank, undefined or null. Nano by default; set VYOMI_CONSOLE_URL
 * (e.g. $VYOMI_BASE_URL/console/gcp) to drive the offline console instead. */
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
  const topic = "gridchk" + Date.now().toString(36);
  await page.evaluate(async (t) => {
    const j = { method: "POST", headers: { "content-type": "application/json" } };
    const proj = PROJECT;
    await fetch(`/api/gcp/pubsub/v1/projects/${proj}/topics`, { ...j, body: JSON.stringify({ name: t }) });
  }, topic);
  await page.evaluate((sel) => [...document.querySelectorAll(sel)].find((e) => /pub\/sub/i.test(e.innerText))?.click(), RAIL_SEL);
  await sleep(2500);
  const row = await page.evaluate((t) => {
    const tr = [...document.querySelectorAll("#main tr")].find((r) => r.innerText.includes(t));
    return tr ? [...tr.querySelectorAll("td")].slice(1).map((td) => td.innerText.trim()) : null;
  }, topic);
  check("topic row listed", !!row, JSON.stringify(row) + " " + (await page.evaluate(() => document.querySelector("#main").innerText.slice(0, 300))).replace(/\n/g, "|"));
  const bad = (row || []).filter((c) => !c || /^[-—]$|undefined|null/i.test(c));
  check("no placeholder cells in the topic row", !!row && bad.length === 0, JSON.stringify(row));
  check("subscriptions column is a number", !!row && /^\d+$/.test(row[row.length - 1]), JSON.stringify(row));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
