/* GCP consoles: a resource created through the Create form with its default values must
 * succeed (the form may not demand a value it has no default for) and come out with a real
 * value in every grid column — never "-", blank, undefined or null.
 * Nano by default; set VYOMI_CONSOLE_URL (e.g. $VYOMI_BASE_URL/console/gcp) for offline. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const offline = process.env.VYOMI_CONSOLE_URL;
const SERVICES = ["Cloud SQL", "API Gateway", "Secret Manager", "Cloud Functions", "Firestore", "VPC Network", "Cloud KMS", "Eventarc", "Pub/Sub"];
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
const open = (name) => page.evaluate(([sel, n]) => {
  const el = [...document.querySelectorAll(sel)].find((e) => e.innerText.replace(/^[a-z_]+\n/, "").trim().startsWith(n));
  el?.click(); return !!el;
}, [RAIL_SEL, name]);
try {
  if (offline) {
    await page.goto(offline, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else {
    const s = await startServer(); server = s.server;
    await bootConsole(page, s.base, "/gcp-console.html");
  }
  for (const svc of SERVICES) {
    const posts = [];
    const onResp = (r) => { if (r.request().method() === "POST" && r.url().includes("/api/")) posts.push(r.status()); };
    page.on("response", onResp);
    check(`${svc}: service is on the rail`, await open(svc));
    await sleep(1500);
    await page.locator("#main button").filter({ hasText: /create|new [a-z]/i }).first().click();
    await sleep(1200);
    await page.locator("button").filter({ hasText: /create|save|submit/i }).filter({ hasNotText: /cancel/i }).last().click();
    await sleep(2500);
    page.off("response", onResp);
    check(`${svc}: create with defaults is accepted`, posts.some((c) => c < 300), JSON.stringify(posts));
    await page.keyboard.press("Escape");
    await open(svc);
    await sleep(2000);
    const rows = await page.evaluate(() => [...document.querySelectorAll("#main tr")].filter((r) => r.querySelector("td"))
      .map((r) => [...r.querySelectorAll("td")].slice(1).map((td) => td.innerText.trim())));
    check(`${svc}: the new resource is listed`, rows.length > 0);
    const bad = rows.flat().filter((c) => !c || /^[-—]$|undefined|null|\[object/i.test(c));
    check(`${svc}: no placeholder cells`, rows.length > 0 && bad.length === 0, JSON.stringify(rows.slice(0, 2)));
  }
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
