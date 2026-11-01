/* Shared GCP console flow for a catalog service (offline + Nano): open it from the
 * rail, create with the wizard's default values, check every grid cell is filled,
 * open the detail view and render each sub-nav tab, then delete from the detail
 * page. One [PASS]/[FAIL] line per check via `check(ok, what, detail)`. */
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runGcpServiceFlow(page, { service, label, check, pushAction }) {
  const open = async () => {
    await page.locator(RAIL_SEL).filter({ hasText: label }).first().click({ timeout: 15000 });
    await sleep(1500);
  };
  const countRows = () => page.evaluate(() => document.querySelectorAll("#main table.gc tr[data-row-name]").length);
  await open();
  check(true, `${service}: service opens from the rail`);

  // the grid reloads right after the service opens: take the baseline once the count is stable
  let before = await countRows();
  for (let i = 0, same = 0; i < 10 && same < 2; i++) {
    await sleep(600);
    const n = await countRows();
    same = n === before ? same + 1 : 0;
    before = n;
  }
  const existing = await page.evaluate(() => [...document.querySelectorAll("#main table.gc tr[data-row-name]")].map((r) => r.getAttribute("data-row-name")));
  await page.locator("#main button").filter({ hasText: /^\s*(add\s*)?Create/i }).first().click({ timeout: 8000 });
  await sleep(1000);
  // Earlier suites (the UI crawl creates with defaults and keeps what it made) can leave a
  // resource under the wizard's default name; the real cloud rejects the duplicate with 409.
  // Keep every other default, and only make the name unique when it is already taken.
  await page.evaluate((existing) => {
    const input = document.querySelector("#main input[type=text]");
    if (!input) return;
    if (existing.includes(input.value)) { input.value = `${input.value}-${Date.now().toString(36)}`.slice(0, 62); input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); }
  }, existing);
  // the wizard's primary "Create" (top of the summary card or the bottom of the form)
  await page.locator("#main button.primary").filter({ hasText: /Create/ }).first().click({ timeout: 8000 });
  await sleep(1500);
  let after = await countRows();
  for (let i = 0; i < 12 && after <= before; i++) { await sleep(800); after = await countRows(); }
  check(after > before, `${service}: create with defaults adds a row`, `rows ${before} → ${after}`);

  const grid = await page.evaluate(() => {
    const t = document.querySelector("#main table.gc");
    if (!t) return { heads: [], cells: [] };
    const heads = [...t.querySelectorAll("th")].map((h) => (h.innerText || "").replace(/[▲▼]/g, "").trim());
    const row = t.querySelector("tr[data-row-name]:last-of-type") || t.querySelector("tr[data-row-name]");
    const cells = row ? [...row.querySelectorAll("td")].map((c) => (c.innerText || "").trim()) : [];
    return { heads, cells };
  });
  const blank = grid.cells.map((c, i) => ({ c, h: grid.heads[i] || "" }))
    .filter((x) => x.h && (x.c === "" || x.c === "-" || x.c === "—"));
  check(grid.cells.length > 0 && !blank.length, `${service}: every grid column is filled`,
    blank.map((b) => b.h).join(", ") || "no row");

  const name = await page.evaluate(() => { const a = document.querySelector("#main table.gc tr[data-row-name] a.id"); if (a) { a.click(); return a.innerText; } return ""; });
  await sleep(1500);
  check(!!name, `${service}: detail view opens`, name);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .sub-nav a.nav-item")].map((e) => (e.innerText || "").replace(/^\S+\s/, "").trim()));
  check(tabs.length > 0, `${service}: detail tabs render`, tabs.join(", "));
  const n = tabs.length;
  for (let i = 0; i < n; i++) {
    await page.evaluate((i) => { const b = [...document.querySelectorAll("#main .sub-nav a.nav-item")]; b[i] && b[i].click(); }, i);
    await sleep(600);
    if (pushAction && tabs[i] === pushAction.tab) {
      await page.locator("#main button").filter({ hasText: pushAction.button }).first().click({ timeout: 5000 }).catch(() => {});
      await sleep(1200);
    }
    const len = await page.evaluate(() => ((document.querySelector("#main .sub-content") || {}).innerText || "").trim().length);
    check(len >= 25, `${service}: tab "${tabs[i]}" has content`, `len ${len}`);
  }

  if (pushAction) {
    await page.evaluate((t) => { const b = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => (e.innerText || "").includes(t)); b && b.click(); }, pushAction.tab);
    await sleep(800);
    const filled = await page.evaluate(() => {
      const rows = [...document.querySelectorAll("#main .sub-content table tr")].slice(1);
      return { rows: rows.length, blank: rows.flatMap((r) => [...r.querySelectorAll("td")].filter((c) => ["", "-", "—"].includes((c.innerText || "").trim()))).length };
    });
    check(filled.rows > 0 && filled.blank === 0, `${service}: ${pushAction.tab} rows are filled after the push`, JSON.stringify(filled));
  }

  page.on("dialog", (d) => d.accept().catch(() => {}));
  await page.locator("#main button.danger").filter({ hasText: /Delete/ }).first().click({ timeout: 5000 });
  await sleep(1500);
  await open();
  const gone = await page.evaluate((nm) => ![...document.querySelectorAll("#main table.gc tr[data-row-name]")].some((r) => r.getAttribute("data-row-name") === nm), name);
  check(gone, `${service}: delete removes the row`, name);
}
