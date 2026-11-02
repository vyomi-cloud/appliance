/* GCP detail tabs: Properties is an editable grid (the resource's own fields read-only + custom properties you
 * add / edit / save), and Labels + Properties both show when they were last modified.
 * Nano by default; VYOMI_CONSOLE_URL drives the offline console instead. */
import { startServer, bootConsole, chromium, RAIL_SEL, sleep } from "./lib.mjs";

const offline = process.env.VYOMI_CONSOLE_URL;
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
const tag = Date.now().toString(36), fn = "fp" + tag;
try {
  if (offline) {
    await page.goto(offline, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else {
    const s = await startServer(); server = s.server;
    await bootConsole(page, s.base, "/gcp-console.html");
  }
  await page.evaluate(async (fn) => {
    await fetch(`/api/gcp/cloudfunctions/v2/projects/${PROJECT}/locations/us-central1/functions`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: fn, runtime: "python312", entryPoint: "hello_world" }) });
  }, fn);
  await page.locator(RAIL_SEL).filter({ hasText: "Cloud Functions" }).first().click({ timeout: 8000 });
  await page.waitForSelector("#main table.gc tr td", { timeout: 15000 });
  await page.locator("#main table.gc a.id", { hasText: fn }).first().click({ timeout: 8000 });
  const tab = async (label) => { await page.locator(".sub-nav a.nav-item", { hasText: label }).first().click({ timeout: 8000 }); await sleep(1200); };
  const modified = () => page.locator(".vy-modified b").first().innerText().catch(() => "(none)");

  // ── Labels: last modified, never → a time after a save
  await tab("Labels");
  check("Labels shows a Last modified line", (await page.locator(".vy-modified").count()) === 1);
  check("Labels: 'Never' before any edit", (await modified()) === "Never", await modified());
  await page.locator("#main button.btn", { hasText: "Add label" }).first().click(); await sleep(400);
  const lin = page.locator("#main table.gc input"); await lin.nth(0).fill("team"); await lin.nth(1).fill("platform");
  await page.locator("#main button.primary", { hasText: "Save" }).first().click(); await sleep(1500);
  check("Labels: saved label listed", (await page.locator("#main table.gc").innerText()).includes("platform"));
  check("Labels: Last modified is a time after the save", !/never|none/i.test(await modified()), await modified());

  // ── Properties: read-only resource fields + editable custom properties
  await tab("Properties");
  const txt0 = await page.locator("#main").innerText();
  check("Properties is a grid (Property / Value / Source)", /Property/.test(txt0) && /Source/.test(txt0));
  check("Properties lists the resource's own fields (Resource)", (await page.locator("#main table.gc td", { hasText: /^Resource$/ }).count()) > 3);
  check("Properties: 'Never' modified before any edit", (await modified()) === "Never", await modified());
  await page.locator("#main button.btn", { hasText: "Add property" }).first().click(); await sleep(400);
  const pin = page.locator("#main table.gc input"); await pin.nth(0).fill("cost-center"); await pin.nth(1).fill("cc-1234");
  await page.locator("#main button.primary", { hasText: "Save" }).first().click(); await sleep(1500);
  check("Properties: saved property listed as Custom", /cost-center/.test(await page.locator("#main table.gc").innerText()) && /Custom/.test(await page.locator("#main table.gc").innerText()));
  check("Properties: Last modified is a time after the save", !/never|none/i.test(await modified()), await modified());
  // survives leaving and reopening the tab
  await tab("Overview"); await tab("Properties");
  check("Properties: the saved property is still there after reopening", /cc-1234/.test(await page.locator("#main table.gc").innerText()));
  // edit + remove
  await page.locator("#main button.btn", { hasText: "Edit" }).first().click(); await sleep(400);
  const e = page.locator("#main table.gc input"); await e.nth(1).fill("cc-9999");
  await page.locator("#main button.primary", { hasText: "Save" }).first().click(); await sleep(1500);
  check("Properties: an edited value is saved", /cc-9999/.test(await page.locator("#main table.gc").innerText()));
  check("Properties: the read-only resource fields survive a save", (await page.locator("#main table.gc td", { hasText: /^Resource$/ }).count()) > 3);
} catch (e) { check("run", false, String(e).split("\n").slice(0, 3).join(" / ")); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
