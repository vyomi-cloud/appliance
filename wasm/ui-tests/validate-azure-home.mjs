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
  // The Home page is the portal's design now: an "Azure services" icon row (More services
  // expands it) and a "Resources" table, not per-service count tiles. Every data-plane
  // service must still be reachable from the row, and its items listed under Resources.
  await page.evaluate(() => { const m = [...document.querySelectorAll(".az-svc")].find((a) => /More services/.test(a.innerText)); if (m) m.click(); });
  const tiles = await page.evaluate(async () => {
    const out = [];
    const labels = [...document.querySelectorAll(".az-svc .az-svc-l")].map((e) => e.innerText.trim());
    const resText = (document.querySelector(".az-res")?.innerText || "");
    for (const s of ((typeof CATALOG !== "undefined" && CATALOG?.services) || []).filter((x) => x.dataPlane)) {
      let items = null;
      try { items = ((await (await fetch("/api/azure/" + s.key)).json()).items || []); } catch (_) {}
      out.push({ label: s.label, tile: labels.includes(s.label), items: items && items.length,
                 listed: items ? items.slice(0, 10).every((it) => resText.includes(it.name || it.id || "")) : false });
    }
    return out;
  });
  check(undefinedCalls.length === 0, "home makes no requests to .../undefined", undefinedCalls.slice(0, 2).join(", "));
  check(tiles.length > 0, "data-plane services present on the home dashboard", `${tiles.length} found`);
  for (const t of tiles) {
    check(t.tile, `service "${t.label}" is in the Azure services row`);
    check(t.items !== null && t.listed, `"${t.label}" items are listed under Resources`, `items=${t.items}`);
  }
} catch (e) { check(false, "(boot)", String(e).split("\n")[0]); }
await browser.close(); server.close();

for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.what}${!r.ok && r.note ? ` :: ${r.note}` : ""}`);
const bad = results.filter((r) => !r.ok).length;
console.log(`${results.length - bad}/${results.length} Azure home checks passed`);
process.exit(bad ? 1 : 0);
