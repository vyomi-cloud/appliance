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
  const tiles = await page.evaluate(async () => {
    const out = [];
    for (const s of ((typeof CATALOG !== "undefined" && CATALOG?.services) || []).filter((x) => x.dataPlane)) {
      const card = [...document.querySelectorAll("#main .card")].find((c) => (c.querySelector(".t")?.innerText || "").trim().endsWith(s.label));
      let api = null;
      try { api = ((await (await fetch("/api/azure/" + s.key)).json()).items || []).length; } catch (_) {}
      out.push({ label: s.label, shown: card ? card.querySelector(".n")?.innerText.trim() : null, api });
    }
    return out;
  });
  check(undefinedCalls.length === 0, "home makes no requests to .../undefined", undefinedCalls.slice(0, 2).join(", "));
  check(tiles.length > 0, "data-plane services present on the home dashboard", `${tiles.length} found`);
  for (const t of tiles) check(t.api !== null && t.shown === String(t.api), `tile "${t.label}" shows its real count`, `shown=${t.shown} api=${t.api}`);
} catch (e) { check(false, "(boot)", String(e).split("\n")[0]); }
await browser.close(); server.close();

for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.what}${!r.ok && r.note ? ` :: ${r.note}` : ""}`);
const bad = results.filter((r) => !r.ok).length;
console.log(`${results.length - bad}/${results.length} Azure home checks passed`);
process.exit(bad ? 1 : 0);
