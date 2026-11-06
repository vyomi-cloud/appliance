/* Shared Cognito console flow (offline + Nano): open the service, create a user pool
 * with the form defaults, check every grid cell is filled, open the detail view, render
 * every tab, exercise Users / Groups / App clients / Domain (create + list + delete),
 * then delete the pool. `check(ok, what, detail)` prints one [PASS]/[FAIL] per check. */
const BLANK = /^(|-|—|–|undefined|null|n\/a)$/i;

export async function runCognitoFlow(page, check, { apiBase = "" } = {}) {
  page.on("dialog", (d) => d.accept().catch(() => {}));
  const RAIL = "#rail a, #rail button, #rail li, #rail [data-service], #rail .svc, #rail .service, #rail .navitem, #rail [data-key]";
  const sleep = (ms) => page.waitForTimeout(ms);
  const openService = async () => {
    const home = page.locator(RAIL).filter({ hasText: /Cognito/i }).first();
    if (await home.count()) await home.click({ timeout: 10000 });
    else await page.locator(RAIL).filter({ hasText: /User pools/i }).first().click({ timeout: 10000 });
    await sleep(1500);
  };
  const cells = () => page.evaluate(() => [...document.querySelectorAll("#main table tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => (td.innerText || "").trim())).filter((r) => r.length));
  const headers = () => page.evaluate(() => [...document.querySelectorAll("#main table tr th")].map((th) => (th.innerText || "").trim()));

  // ── service page + create with defaults ──
  await openService();
  check(await page.locator("#main").innerText().then((t) => /cognito/i.test(t) && /create/i.test(t)), "Cognito service opens with a Create action");
  let created = null;
  page.on("response", async (r) => {
    if (r.request().method() === "POST" && /\/api\/cognito-idp\/user-pools$/.test(r.url())) {
      created = { status: r.status(), body: await r.json().catch(() => ({})) };
    }
  });
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 10000 });
  await sleep(1000);
  await page.locator("#main button").filter({ hasText: /create/i }).filter({ hasNotText: /cancel|back/i }).last().click({ timeout: 10000 });
  for (let i = 0; i < 30 && !created; i++) await sleep(500);
  check(created && created.status === 201, "create user pool with form defaults returns 201", JSON.stringify(created));
  const pid = created && created.body && created.body.id;
  check(!!pid && /^us-east-1_/.test(pid), "created pool has an AWS-shaped id", String(pid));
  await sleep(800);
  await openService();

  // ── every column filled ──
  const hdr = await headers();
  const rows = await cells();
  const row = rows.find((r) => r.some((c) => c.includes(pid)));
  check(!!row, "new pool appears in the list", `rows=${rows.length}`);
  if (row) {
    const off = row.length - hdr.length;   // leading checkbox cell(s)
    const blanks = row.map((c, i) => [c, hdr[i - off] || ""]).filter(([c, h]) => h && BLANK.test(c)).map(([, h]) => h);
    check(blanks.length === 0, `every grid column is filled (${hdr.filter(Boolean).join(", ")})`, `blank: ${blanks.join(", ")}`);
  }

  // ── detail view + tabs ──
  await page.locator("#main table tr").filter({ hasText: pid }).locator("a.id, a").first().click({ timeout: 10000 });
  await sleep(1500);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((e) => (e.innerText || "").trim()).filter(Boolean));
  for (const want of ["Overview", "Users", "Groups", "App clients", "Domain", "Properties"]) {
    check(tabs.includes(want), `detail tab "${want}" present`, tabs.join(", "));
  }
  const tabContent = () => page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText.trim() : ""; });
  const clickTab = async (name) => {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp(`^\\s*${name}\\s*$`) }).first().click({ timeout: 10000 });
    await sleep(900);
  };
  for (const t of tabs) {
    await clickTab(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const c = await tabContent();
    check(c.length > 25 && !/Renderer error|Not yet wired/i.test(c), `tab "${t}" renders content`, c.slice(0, 80));
  }

  // ── sub-resources: create with defaults, columns filled, delete ──
  const subCols = async (what) => {
    const h = await headers(), r = await cells();
    const last = r[r.length - 1] || [];
    const body = h.map((x, i) => [x, last[i]]).filter(([x]) => x && x !== "Actions");   // sub-grids have no checkbox column
    const bad = body.filter(([, v]) => v === undefined || BLANK.test(v)).map(([x]) => x);
    check(r.length > 0 && bad.length === 0, `${what}: every column filled`, `blank: ${bad.join(", ")} rows=${r.length}`);
  };
  for (const [tab, label] of [["Users", "user"], ["Groups", "group"], ["App clients", "app client"], ["Domain", "domain"]]) {
    await clickTab(tab);
    await page.locator('#main [data-testid="subgrid-create"]').click({ timeout: 10000 });
    await sleep(400);
    await page.locator('#main [data-testid="subgrid-submit"]').click({ timeout: 10000 });
    await sleep(1500);
    await subCols(`${tab} tab after creating a ${label} with defaults`);
  }
  // delete the user and the group through the row actions
  for (const tab of ["Users", "Groups"]) {
    await clickTab(tab);
    const before = (await cells()).length;
    await page.locator("#main table button").filter({ hasText: /^Delete$/ }).first().click({ timeout: 10000 });
    await sleep(1500);
    const after = (await cells()).length;
    check(after < before || (await tabContent()).includes("No "), `${tab}: row Delete removes the entry`, `${before} → ${after}`);
  }

  // ── delete the pool from the detail view ──
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll("#main button")].find((x) => !x.closest("table") && /delete/i.test(x.innerText || ""));
    if (b) b.click();
    return !!b;
  });
  check(clicked, "detail view has a Delete action");
  await sleep(2000);
  await openService();
  const rows2 = await cells();
  check(!rows2.some((r) => r.some((c) => c.includes(pid))), "deleted pool is gone from the list");
}
