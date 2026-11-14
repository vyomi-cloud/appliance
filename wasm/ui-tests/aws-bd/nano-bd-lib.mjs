/* Shared harness for the GENUINE-NANO AWS v4 console <-> native-wire bi-directional suites.
 * Nano = the in-browser engine (service worker + Pyodide cores). "API" side = the native wire the SDK/CLI speak, sent to /_wire/ from the page
 * (the SW routes it to the same AwsWireRouter the console uses). PRIMARY direction is UI action -> API verification.
 * Env: NODE_PATH, PLAYWRIGHT_BROWSERS_PATH, NANO_DIR=<repo>/wasm */
import { chromium, startServer, sleep } from "../lib.mjs";
import { mkdirSync, writeFileSync } from "node:fs";

export { sleep };
export const RUN = Math.random().toString(36).slice(2, 8);
export const N = (s) => `bd${RUN}${s}`;
const rows = []; let fails = 0;
export const rec = (check, status, detail = "") => { rows.push({ check, status, detail }); if (status === "FAIL") fails++; console.log(`[${status}] ${check}${detail ? " :: " + String(detail).slice(0, 200) : ""}`); };
export const ck = (check, ok, detail = "") => rec(check, ok ? "PASS" : "FAIL", detail);

export async function boot(name) {
  const { server, base } = await startServer();
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1500, height: 1000 } });
  const page = await ctx.newPage();
  page.on("dialog", (d) => d.accept("delete").catch(() => {}));
  const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));
  const H = { page, base, browser, server, pageErrors };
  const date = "20261111";
  const auth = (svc) => `AWS4-HMAC-SHA256 Credential=test/${date}/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=x`;
  // raw native wire call: path starts with "/" (S3/Lambda REST) ; headers/body as an SDK would send
  H.raw = async (svc, method, path, { headers = {}, body = "", query = "" } = {}) => {
    for (let i = 0; i < 3; i++) {
      try {
        return await page.evaluate(async ([m, p, h, b]) => { const r = await fetch(p, { method: m, headers: h, body: b === "" || m === "GET" || m === "HEAD" ? undefined : b }); return { status: r.status, text: await r.text() }; },
          [method, "/_wire" + path + (query ? "?" + query : ""), { authorization: auth(svc), ...headers }, body]);
      } catch (e) { await sleep(1500); }
    }
    return { status: 0, text: "" };
  };
  H.query = (svc, Action, params = {}, version = "2016-11-15") => H.raw(svc, "POST", "/", { headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action, Version: version, ...params }).toString() });
  H.json = async (svc, target, body = {}, ver = "1.1") => { const r = await H.raw(svc, "POST", "/", { headers: { "content-type": `application/x-amz-json-${ver}`, "x-amz-target": target }, body: JSON.stringify(body) }); try { r.json = JSON.parse(r.text); } catch { r.json = {}; } return r; };
  H.go = async (hashRoute) => {
    const first = page.waitForResponse((r) => r.url().includes("/_wire/") && r.status() < 500, { timeout: 90000 }).catch(() => null);
    await page.goto("about:blank");
    await page.goto(`${base}/v4/aws/index.html#/${hashRoute}`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 90000, polling: 300 });
    await first; await sleep(1500);
  };
  H.nav = async (hashRoute) => { await page.evaluate((h) => { location.hash = "#/" + h; }, hashRoute); await sleep(1800); };   // SPA nav, keeps the in-page store
  H.body = async () => (await page.locator("body").innerText()).replace(/\s+/g, " ");
  H.listHas = async (route, text, tries = 3) => { for (let i = 0; i < tries; i++) { await H.go(route); for (let j = 0; j < 8; j++) { if ((await H.body()).includes(text)) return true; await sleep(1500); } } return false; };
  H.waitUntilGone = async (text, ms = 12000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (!(await H.body()).includes(text)) return true; await sleep(1000); } return false; };
  H.row = (text) => page.locator("tr", { hasText: text }).first();
  H.selectRow = async (route, text) => { await H.go(route); await H.row(text).waitFor({ timeout: 30000 }); await H.row(text).locator("input[type=checkbox],input[type=radio]").first().check({ force: true }); };
  H.menu = async (btn, item) => { await page.getByRole("button", { name: btn }).first().click(); await sleep(400); await page.getByRole("menuitem", { name: item }).first().click(); await sleep(800); };
  H.pick = async (label, optText, placeholder) => {   // Cloudscape Select: trigger is a button labelled by the field label or showing the placeholder
    const cands = [page.locator(`[aria-label="${label}"]`).first(), placeholder ? page.locator("button", { hasText: placeholder }).last() : null, page.getByRole("button", { name: new RegExp(label, "i") }).first()].filter(Boolean);
    let ok = false; for (const c of cands) { try { await c.click({ timeout: 4000 }); ok = true; break; } catch (_) {} }
    if (!ok) throw new Error("Select trigger not found: " + label);
    await sleep(500);
    await page.getByRole("option", { name: optText }).first().click();
  };
  H.confirmDelete = async () => {   // some actions delete immediately, others open a typed-confirmation modal
    await sleep(600);
    const cd = page.getByLabel("Confirm deletion");
    if (await cd.count()) { const ph = await cd.first().getAttribute("placeholder").catch(() => null); await cd.first().fill(ph || "delete").catch(() => {}); }   // the modal asks for "delete" or the resource name (its placeholder)
    const b = page.getByRole("dialog").getByRole("button", { name: /^(Delete|Terminate|Remove|Confirm|Deregister)\b/ }).last();
    if (await b.count()) await b.dispatchEvent("click", {}, { timeout: 5000 }).catch(() => {});
    await sleep(2500);
  };
  H.click = async (name) => { await page.getByRole("button", { name }).last().dispatchEvent("click", {}, { timeout: 10000 }); await sleep(2500); };
  H.finish = async (title, outFile) => {
    ck("no uncaught page errors", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));
    const outDir = new URL("../../../tests/conformance/hourly/out/", import.meta.url).pathname; mkdirSync(outDir, { recursive: true });
    let md = `# ${title} (run ${RUN})\n\n| Check | Result | Detail |\n|---|---|---|\n`;
    for (const r of rows) md += `| ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 140)} |\n`;
    md += `\n**${rows.filter((r) => r.status === "PASS").length} pass, ${fails} fail, ${rows.filter((r) => r.status === "NOT-AUTOMATED").length} not automated.**\n`;
    writeFileSync(outDir + outFile, md);
    await browser.close(); server.close();
    console.log(`DONE ${rows.filter((r) => r.status === "PASS").length} pass ${fails} fail`);
    process.exit(fails ? 1 : 0);
  };
  return H;
}
export const xf = (x, t) => (x.match(new RegExp(`<${t}>([^<]*)</${t}>`)) || [])[1];
export const xall = (x, t) => [...x.matchAll(new RegExp(`<${t}>([^<]*)</${t}>`, "g"))].map((m) => m[1]);
