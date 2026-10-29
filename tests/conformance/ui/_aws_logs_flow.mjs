/* Shared console flow for CloudWatch Logs — used by the offline test
 * (tests/conformance/ui/aws-logs.mjs) and the Nano test
 * (wasm/ui-tests/validate-aws-logs.mjs) so both consoles are held to the SAME checks:
 * open the service, create with the form defaults, every grid column filled,
 * every detail tab renders (and its table cells are filled), delete.
 */
const RAIL_SEL = "#rail a, #rail button, #rail li, #rail [data-service], #rail .svc, #rail .service, #rail .navitem, #rail [data-key]";
const DEFAULT_GROUP = "/aws/vyomi/my-app";   // the create form's default name
const BLANK = /^\s*(|-|—|–|undefined|null|NaN)\s*$/;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runLogsFlow(page, check) {
  const api = (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    let j = null; try { j = await r.json(); } catch (_) {}
    return { status: r.status, json: j };
  }, [method, path, body || null]);
  page.on("dialog", (d) => d.accept().catch(() => {}));
  const main = () => page.locator("#main");

  // clean slate (a previous run in the same space may have left the default group)
  await api("DELETE", "/api/logs/log-groups/" + encodeURIComponent(DEFAULT_GROUP));

  // 1. open the service from the rail
  const rail = page.locator(RAIL_SEL).filter({ hasText: /CloudWatch Logs/i }).first();
  check(await rail.count() > 0, "CloudWatch Logs is on the service rail");
  await rail.click({ timeout: 8000 });
  await sleep(1500);
  check(/CloudWatch Logs/.test(await main().innerText()), "service page opens");

  // 2. create with defaults
  await main().locator(".actions-bar button, button.primary").filter({ hasText: /create/i }).first().click({ timeout: 8000 });
  await sleep(1000);
  const nameVal = await main().locator("input").first().inputValue();
  check(nameVal === DEFAULT_GROUP, "create form has a realistic default name", nameVal);
  const created = page.waitForResponse((r) => r.request().method() === "POST" && /\/api\/logs\/log-groups/.test(r.url()), { timeout: 15000 }).catch(() => null);
  await main().locator(".wizard-footer button.primary").last().click({ timeout: 8000 });
  const resp = await created;
  check(resp && resp.status() < 300, "create with defaults returns 2xx", resp ? String(resp.status()) : "no response");
  await sleep(1500);

  // seed real data through the console API so the detail tabs have rows to fill
  await api("POST", "/api/logs/log-groups/" + encodeURIComponent(DEFAULT_GROUP) + "/events", { stream: "web-1", message: "GET /health 200" });
  await api("POST", "/api/logs/log-groups/" + encodeURIComponent(DEFAULT_GROUP) + "/events", { stream: "web-1", message: "GET /boom 500 ERROR" });
  await page.locator(RAIL_SEL).filter({ hasText: /CloudWatch Logs/i }).first().click().catch(() => {});
  await sleep(1500);

  // 3. grid: the new row is listed and every column is filled
  const grid = await page.evaluate(() => {
    const t = document.querySelector("#main table.aws") || document.querySelector("#main table");
    if (!t) return { heads: [], rows: [] };
    const heads = [...t.querySelectorAll("tr:first-child th")].map((h) => h.innerText.replace(/[▲▼]/g, "").trim()).filter(Boolean);
    const rows = [...t.querySelectorAll("tr")].filter((r) => r.querySelector("td")).map((r) => [...r.querySelectorAll("td")].slice(1).map((c) => c.innerText.trim()));
    return { heads, rows };
  });
  const row = grid.rows.find((r) => r.some((c) => c.includes(DEFAULT_GROUP)));
  check(!!row, "created log group is listed", JSON.stringify(grid.rows.slice(0, 2)));
  check(grid.heads.join("|") === "Log group|Log class|Retention|Log streams|Metric filters|Stored bytes|Creation time", "grid columns", grid.heads.join("|"));
  check(!!row && row.length >= 7 && row.every((c) => !BLANK.test(c)), "every grid column is filled", JSON.stringify(row));

  // 4. detail: every tab renders and its table cells are filled
  await main().locator("a.id, td a").filter({ hasText: DEFAULT_GROUP }).first().click({ timeout: 8000 });
  await sleep(1500);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((b) => b.innerText.trim()).filter(Boolean));
  for (const want of ["Overview", "Tags", "Log streams", "Log events", "Metric filters", "Subscription filters", "Properties"]) {
    check(tabs.includes(want), `detail tab "${want}" exists`, tabs.join(", "));
  }
  for (let i = 0; i < tabs.length; i++) {
    await page.evaluate((i) => { const b = [...document.querySelectorAll("#main .top-tabs button")]; b[i] && b[i].click(); }, i);
    await sleep(900);
    const tab = await page.evaluate(() => {
      const strip = document.querySelector("#main .top-tabs");
      const pane = strip && strip.nextElementSibling;
      const cells = pane ? [...pane.querySelectorAll("td")].map((c) => c.innerText.trim()) : [];
      return { text: pane ? pane.innerText.trim() : "", cells };
    });
    check(tab.text.length > 15, `tab "${tabs[i]}" renders content`, tab.text.slice(0, 60));
    check(tab.cells.every((c) => !BLANK.test(c)), `tab "${tabs[i]}" has no blank cells`, JSON.stringify(tab.cells.filter((c) => BLANK.test(c))));
    if (tabs[i] === "Log streams") check(tab.cells.some((c) => c === "web-1"), "Log streams tab lists the stream", tab.text.slice(0, 80));
    if (tabs[i] === "Log events") check(tab.text.includes("500 ERROR"), "Log events tab shows the events", tab.text.slice(0, 80));
  }

  // 5. delete from the detail page
  await main().locator("button.danger").filter({ hasText: /delete/i }).first().click({ timeout: 8000 });
  await sleep(2000);
  const gone = await api("GET", "/api/logs/log-groups");
  check(!(gone.json.items || []).some((g) => g.name === DEFAULT_GROUP), "delete removes the log group", JSON.stringify((gone.json.items || []).map((g) => g.name)));
}
