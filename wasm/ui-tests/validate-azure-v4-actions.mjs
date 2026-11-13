/* Azure v4 console, GENUINE NANO: every UI action beyond create/delete, bi-directional against ARM.
 *
 *   NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-azure-v4-actions.mjs          (ONLY=vms,storage,... to select)
 *
 * Serves the real Nano bundle (nano boot + service worker + in-browser cores; NOT dev_server, NO "offline" rewrite).
 * The "API side" is a same-origin fetch to /subscriptions/... through the service worker (the /_wire path `az`/SDKs hit over the relay; it also
 * bypasses the console-only fetch overlay in nano-vm-host.js that shows a VM as 'stopped' while in-browser VM compute is off). UI->API: do the action in the console, verify through ARM (primary). API->UI: do it over ARM,
 * reload the console, see it. `az` cannot reach an in-browser engine, so CLI->UI is NOT-AUTOMATED here (it runs in the
 * offline/dev-server wrapper tests/conformance/nightly/azure-v4-bidirectional.mjs). Writes out/azure-v4-actions.{json,md}.
 */
import { startServer, chromium, sleep, NANO_DIR } from "./lib.mjs";
import { mkdirSync, writeFileSync } from "node:fs";

export const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = `act-rg-${Date.now() % 100000}`;
const P = `/subscriptions/${SUB}/resourceGroups/${RG}/providers`;
const only = (process.env.ONLY || "").split(",").filter(Boolean);
const rows = []; let fails = 0, cur = "";
const rec = (check, status, detail = "") => {
  rows.push({ svc: cur, check, status, detail }); if (status === "FAIL") fails++;
  console.log(`[${status === "PASS" ? "PASS" : status === "FAIL" ? "FAIL" : "NOTE"}] ${cur} :: ${check}${detail ? ` :: ${String(detail).slice(0, 160)}` : ""}`);
};
const { server, base } = await startServer(NANO_DIR);
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await (await browser.newContext()).newPage();
const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));
// raw: send `body` as-is with that content-type; hdrs: extra headers (data-plane auth / x-vyomi-vault)
const arm = (method, path, body, raw, hdrs) => page.evaluate(async ([m, p, b, r, h]) => {
  const x = await fetch("/_wire" + p, { method: m, headers: { ...(r ? { "content-type": r } : { "content-type": "application/json" }), ...(h || {}) }, body: b == null ? undefined : (r ? b : JSON.stringify(b)) });
  const t = await x.text(); let j = null; try { j = JSON.parse(t); } catch { /* */ } return { status: x.status, json: j, text: t };
}, [method, path, body ?? null, raw || null, hdrs || null]);
const v = (x) => `?api-version=${x}`;
const go = async (hash) => { await page.goto(`${base}/v4/azure/index.html#${hash}`, { waitUntil: "domcontentloaded" }); await page.reload({ waitUntil: "domcontentloaded" }); await sleep(3500); };
const body = async () => (await page.locator("body").innerText()).replace(/\s+/g, " ");
const click = async (name, opts = {}) => { const l = (opts.scope || page).getByRole(opts.role || "button", { name, exact: opts.exact ?? true }).first(); await l.waitFor({ timeout: opts.timeout || 20000 }); await l.dispatchEvent("click"); };
const tab = async (name) => { const l = page.locator("nav, [role=navigation], [role=tablist], .vy-nav, aside").getByText(name, { exact: true }).first(); await l.waitFor({ timeout: 15000 }); await l.click(); await sleep(1500); };
const poll = async (fn, ms = 40000, step = 1500) => { const t = Date.now(); let r; while (Date.now() - t < ms) { try { r = await fn(); if (r) return r; } catch { /* retry */ } await sleep(step); } return r; };
const seenInUi = async (text, hash) => { if (hash) await go(hash); return !!(await poll(async () => (await body()).includes(text), 12000, 1500)); };
const uiDelete = async (name, openHash, btn = /^Delete$/) => {
  if (openHash) await go(openHash);
  await click(btn); const dlg = page.getByRole("dialog").last();
  await dlg.getByLabel("Confirm deletion").fill(name); await dlg.getByRole("button", { name: /^Delete$/ }).dispatchEvent("click");
};
const shows = async (re, ms = 15000) => !!(await poll(async () => (re.test(await body()) ? true : null), ms, 1000));
const uiRowDelete = async (name) => {
  const row = page.getByRole("row", { name: new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).first();
  await row.waitFor({ timeout: 15000 }); await row.getByRole("checkbox").check({ force: true });
  await click(/^Delete$/); const dlg = page.getByRole("dialog").last();
  await dlg.getByLabel("Confirm deletion").fill(name); await dlg.getByRole("button", { name: /^Delete$/ }).dispatchEvent("click");
};
const ctx = { shows, uiRowDelete, arm, v, go, body, click, tab, poll, seenInUi, uiDelete, page, base, RG, P, SUB, sleep, rec };
const SECTIONS = {};
export const section = (id, title, fn) => { SECTIONS[id] = { title, fn }; };
const mods = (await Promise.all(["vms", "storage", "keyvaults", "nsgs", "dns", "servicebus", "appconfiguration", "sql", "cosmos", "appservices", "functionapp", "aks", "acr", "eventgrid", "loganalytics", "containerapps", "vnets", "generic"].map((m) => import(new URL(`./azure-actions/${m}.mjs`, import.meta.url).href).catch((e) => { console.log("no driver", m, e.message.slice(0, 60)); return null; }))));
for (const m of mods) if (m && m.default) for (const d of [].concat(m.default)) SECTIONS[d.id] = { title: d.title, fn: d.fn };

try {
  await page.goto(`${base}/v4/azure/index.html`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 120000 });
  await sleep(4000);
  cur = "(setup)";
  const hz = await arm("GET", `/subscriptions/${SUB}/resourcegroups${v("2021-04-01")}`);
  rec("Nano engine answers ARM through the service worker (not a dev server)", hz.status === 200 ? "PASS" : "FAIL", `HTTP ${hz.status}`);
  const rg = await arm("PUT", `/subscriptions/${SUB}/resourcegroups/${RG}${v("2021-04-01")}`, { location: "eastus" });
  rec("create the test resource group", rg.status < 300 ? "PASS" : "FAIL", rg.status);
  for (const [id, s] of Object.entries(SECTIONS)) {
    if (only.length && !only.includes(id)) continue;
    cur = s.title;
    try { await s.fn(ctx); } catch (e) { rec("section ran to completion", "FAIL", String(e.message).split("\n")[0]); }
  }
  await arm("DELETE", `/subscriptions/${SUB}/resourcegroups/${RG}${v("2021-04-01")}`);
} catch (e) { cur = "(run)"; rec("harness ran to completion", "FAIL", String(e.message).split("\n")[0]); }
cur = "(run)"; rec("no uncaught page errors", pageErrors.length ? "NOTE" : "PASS", pageErrors.slice(0, 3).join(" | "));
rec("CLI->UI via az against an in-browser engine", "NOT-AUTOMATED", "az cannot reach the in-browser engine without the tunnel relay; covered by the offline wrapper");

const outDir = new URL("../../tests/conformance/hourly/out/", import.meta.url).pathname; mkdirSync(outDir, { recursive: true });
writeFileSync(outDir + "azure-v4-actions.json", JSON.stringify({ at: new Date().toISOString(), mode: "nano", rows }, null, 1));
const by = {}; for (const r of rows) (by[r.svc] ||= []).push(r);
let md = "# Azure v4 console actions (genuine Nano)\n\n| Service | Check | Result | Detail |\n|---|---|---|---|\n";
for (const [svc, rs] of Object.entries(by)) for (const r of rs) md += `| ${svc} | ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 120)} |\n`;
const n = (st) => rows.filter((r) => r.status === st).length;
md += `\n**${n("PASS")} pass, ${n("FAIL")} fail, ${n("NOT-AUTOMATED")} not automated.**\n`;
writeFileSync(outDir + "azure-v4-actions.md", md);
await browser.close(); server.close(); process.exit(fails ? 1 : 0);
