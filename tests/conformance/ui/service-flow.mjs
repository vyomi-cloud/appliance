/* Shared console flow for a catalog service (offline + Nano): open it from the
 * rail, create with the form's default values, check every grid cell is filled,
 * open the detail view and render each tab, then delete. One [PASS]/[FAIL] line
 * per check via `check(ok, what, detail)`. */
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";

const CREATE_BTN = /create|launch|assume|add/i;
const SUBMIT_BTN = /create|launch|submit|confirm|assume/i;
const NOT_SUBMIT = /cancel|close|back|previous/i;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runServiceFlow(page, { service, label, listLabel, check }) {
  const listRail = () => page.locator(RAIL_SEL).filter({ hasText: listLabel || label }).first();
  const rail = page.locator(RAIL_SEL).filter({ hasText: label }).first();
  await rail.click({ timeout: 15000 });
  await sleep(1800);
  check(true, `${service}: service opens from the rail`);

  const rowSel = "#main table tr:has(td)";
  // The grid is paginated: count from the "N items" header, not visible rows.
  const countRows = async () => page.evaluate(() => {
    const m = (document.querySelector("#main") || {}).innerText?.match(/(\d+)\s+items?\b/);
    return m ? Number(m[1]) : document.querySelectorAll("#main table tr td").length ? document.querySelectorAll("#main table tbody tr").length : 0;
  });
  const before = await countRows();
  await page.locator("#main button, #main [role=button]").filter({ hasText: CREATE_BTN }).first().click({ timeout: 8000 });
  await sleep(1200);
  const dialog = page.locator("[role=dialog]:visible, .modal:visible, .drawer:visible").last();
  const scope = (await dialog.count()) ? dialog : page.locator("#main");
  await scope.locator("button, [type=submit]").filter({ hasText: SUBMIT_BTN }).filter({ hasNotText: NOT_SUBMIT }).last().click({ timeout: 8000 });
  await sleep(1500);
  await listRail().click({ timeout: 8000 }).catch(() => {});
  let after = before;
  for (let i = 0; i < 12 && after <= before; i++) { await sleep(800); after = await countRows(); }
  check(after > before, `${service}: create with defaults adds a row`, `rows ${before} → ${after}`);

  // Every grid column filled for the new row.
  const grid = await page.evaluate(() => {
    const t = document.querySelector("#main table");
    if (!t) return { heads: [], cells: [] };
    const heads = [...t.querySelectorAll("th")].map((h) => (h.innerText || "").trim());
    const row = t.querySelector("tr:has(td)");
    const cells = row ? [...row.querySelectorAll("td")].map((c) => (c.innerText || "").trim()) : [];
    return { heads, cells };
  });
  const blank = grid.cells.map((c, i) => ({ c, h: grid.heads[i] || "" }))
    .filter((x) => x.h && !/^(select|actions?)$/i.test(x.h) && (x.c === "" || x.c === "-" || x.c === "—"));
  check(grid.cells.length > 0 && !blank.length, `${service}: every grid column is filled`,
    blank.map((b) => b.h).join(", ") || "no row");

  // Detail view: open the first link in the row, click each tab.
  const opened = await page.evaluate(() => {
    const a = document.querySelector("#main table tr:has(td) a");
    if (a) { a.click(); return true; }
    return false;
  });
  await sleep(1500);
  check(opened, `${service}: detail view opens`);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((e) => (e.innerText || "").trim()).filter(Boolean));
  check(tabs.length > 0, `${service}: detail tabs render`, tabs.join(", "));
  for (let i = 0; i < tabs.length; i++) {
    await page.evaluate((i) => { const b = [...document.querySelectorAll("#main .top-tabs button")]; b[i] && b[i].click(); }, i);
    await sleep(500);
    const len = await page.evaluate(() => {
      const s = document.querySelector("#main .top-tabs");
      const n = s && s.nextElementSibling;
      return ((n && n.innerText) || "").trim().length;
    });
    check(len >= 25, `${service}: tab "${tabs[i]}" has content`, `len ${len}`);
  }

  // Delete: back to the list, delete the row.
  await listRail().click({ timeout: 8000 }).catch(() => {});
  await sleep(1500);
  const n0 = await countRows();
  page.on("dialog", (d) => d.accept().catch(() => {}));
  await page.locator("#main tr:has(td) input[type=checkbox]").first().check({ timeout: 5000 });
  await page.locator("#main button, #main [role=button]").filter({ hasText: /^\s*(more_horiz\s*)?Actions/ }).first().click({ timeout: 5000 });
  await sleep(400);
  await page.getByText(/^\s*Delete( selected)?\s*$/i).first().click({ timeout: 5000 });
  await sleep(800);
  await page.locator("[role=dialog]:visible button, .modal:visible button, .modal-back:visible button").filter({ hasText: /^\s*(delete|confirm|yes|ok|remove)/i }).last().click({ timeout: 2500 }).catch(() => {});
  let n1 = n0;
  for (let i = 0; i < 12 && n1 >= n0; i++) { await sleep(800); n1 = await countRows(); }
  check(n1 < n0, `${service}: delete removes the row`, `rows ${n0} → ${n1}`);
}
