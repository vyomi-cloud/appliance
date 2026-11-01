/* Azure home dashboard: every service tile must be counted from a real API.
 * Data-plane services (Blob containers, Cosmos databases, Key Vault secrets/keys,
 * Storage queues) have no ARM namespace/type — the dashboard used to request
 * .../providers/undefined/undefined for them (404) and show 0. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const undefinedCalls = [];
page.on("request", (r) => { if (/\/undefined(\/|\?|$)/.test(r.url())) undefinedCalls.push(r.url().replace(base, "")); });
const results = [];
const check = (ok, what, note = "") => results.push({ ok, what, note });
try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(3000);
  // The portal-style Home lists every service in the "Azure services" row (More services
  // expands it) and every resource, counted from each service's own list API, under Resources.
  await page.evaluate(() => { const m = [...document.querySelectorAll("#main .az-svc")].find((a) => /More services/.test(a.innerText)); if (m) m.click(); });
  await sleep(300);
  const info = await page.evaluate(async () => {
    const dps = ((typeof CATALOG !== "undefined" && CATALOG?.services) || []).filter((x) => x.dataPlane);
    const names = [...document.querySelectorAll("#main .az-svc")].map((a) => (a.getAttribute("title") || a.innerText || "").trim());
    let dpTotal = 0;
    const tiles = [];
    for (const s of dps) {
      let api = null;
      try { api = ((await (await fetch("/api/azure/" + s.key)).json()).items || []).length; } catch (_) {}
      dpTotal += api || 0;
      tiles.push({ label: s.label, present: names.includes(s.label), api });
    }
    const more = document.querySelector("#main .az-more")?.innerText || "";
    const m = /\((\d+)\)/.exec(more);
    const empty = !!document.querySelector("#main .az-res .az-empty:not(:empty)") && /No resources yet/.test(document.querySelector("#main .az-res")?.innerText || "");
    return { tiles, dpTotal, seeAll: m ? Number(m[1]) : (empty ? 0 : null) };
  });
  check(undefinedCalls.length === 0, "home makes no requests to .../undefined", undefinedCalls.slice(0, 2).join(", "));
  check(info.tiles.length > 0, "data-plane services present on the home dashboard", `${info.tiles.length} found`);
  for (const t of info.tiles) check(t.present && t.api !== null, `service "${t.label}" is on the Azure services row and its list API answers`, `present=${t.present} api=${t.api}`);
  check(info.seeAll !== null && info.seeAll >= info.dpTotal, "Resources count includes every data-plane resource", `seeAll=${info.seeAll} dataPlane=${info.dpTotal}`);
} catch (e) { check(false, "(boot)", String(e).split("\n")[0]); }
await browser.close(); server.close();

for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.what}${!r.ok && r.note ? ` :: ${r.note}` : ""}`);
const bad = results.filter((r) => !r.ok).length;
console.log(`${results.length - bad}/${results.length} Azure home checks passed`);
process.exit(bad ? 1 : 0);
