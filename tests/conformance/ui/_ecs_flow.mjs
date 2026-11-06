/* Shared Amazon ECS console flow — driven by the offline test (aws-ecs.mjs) and the
 * Nano test (wasm/ui-tests/validate-aws-ecs.mjs) so both consoles are held to the
 * same checks: open the service, create a cluster with the form defaults, every grid
 * column filled, detail tabs render, create a service + run a task, delete.
 *   runEcsFlow(page, check)   page already booted on the AWS console. */
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";

const COLUMNS = ["Cluster", "Status", "Services", "Running tasks", "Container instances",
                 "Container Insights", "Capacity providers", "Created time"];
const TABS = ["Overview", "Activity", "Tags", "Services", "Tasks", "Task definitions", "Infrastructure",
              "Capacity providers", "Properties", "Permissions"];
const BLANK = new Set(["", "-", "—"]);

export async function runEcsFlow(page, check) {
  page.on("dialog", (d) => d.accept().catch(() => {}));
  const main = page.locator("#main");
  await page.locator(RAIL_SEL).filter({ hasText: /ECS\s*$/ }).first().click({ timeout: 10000 });
  await page.waitForTimeout(1500);
  check(await main.locator("button").filter({ hasText: /create/i }).first().isVisible().catch(() => false), "ECS clusters page opens with a Create button");

  const toList = () => page.locator("#rail a").filter({ hasText: /Clusters/ }).first().click().catch(() => {});
  const headers = async () => (await main.locator("table th").allInnerTexts()).map((s) => s.trim());
  const rowFor = (name) => main.locator("table tr:has(td)").filter({ hasText: name }).first();

  // create with the form defaults
  let created = null;
  page.on("response", (r) => { if (r.request().method() === "POST" && /\/api\/ecs\/clusters$/.test(r.url())) created = r.status(); });
  await main.locator("button, [role=button]").filter({ hasText: /create/i }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1000);
  const dlg = page.locator("[role=dialog]:visible, .modal:visible, .drawer:visible").last();
  const scope = (await dlg.count()) ? dlg : main;
  const name = await scope.locator("input").first().inputValue().catch(() => "");
  check(name === "my-cluster", "create form defaults to cluster name my-cluster", name);
  await scope.locator("button, [type=submit]").filter({ hasText: /create|submit|confirm/i })
    .filter({ hasNotText: /cancel|close|back|previous/i }).last().click({ timeout: 8000 });
  for (let i = 0; i < 20 && created === null; i++) await page.waitForTimeout(400);
  check(created !== null && created < 300, "create cluster with defaults returns 2xx", `HTTP ${created}`);
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(1200);

  // grid: columns present, row filled
  const row = rowFor(name || "my-cluster");
  for (let i = 0; i < 10 && !(await row.count()); i++) {
    await toList();
    await page.waitForTimeout(800);
  }
  check((await row.count()) > 0, "new cluster appears in the grid");
  const hs = await headers();
  for (const c of COLUMNS) check(hs.some((h) => h.toLowerCase().startsWith(c.toLowerCase())), `grid column "${c}"`, hs.join("|"));
  const cells = (await row.locator("td").allInnerTexts()).map((s) => s.trim());
  const blanks = cells.map((v, i) => [v, hs[i]]).filter(([v, h]) => BLANK.has(v) && h && !/action/i.test(h));
  check(blanks.length === 0, "every grid column is filled", blanks.map((b) => b[1]).join(", "));

  // detail tabs
  await row.locator("a.id").click({ timeout: 8000 });
  await page.waitForTimeout(1500);
  for (const t of TABS) {
    const tab = page.locator(".top-tabs button").filter({ hasText: new RegExp("^\\s*" + t + "\\s*$") }).first();
    let ok = false;
    try {
      await tab.click({ timeout: 6000 });
      await page.waitForTimeout(600);
      ok = ((await main.innerText()).trim().length > 40) && !/failed to load|internal server error/i.test(await main.innerText());
    } catch (_) {}
    check(ok, `detail tab "${t}" renders`);
  }

  // service + task through the sub-grids
  const subCreate = async (tabName, expect) => {
    await page.locator(".top-tabs button").filter({ hasText: new RegExp("^\\s*" + tabName + "\\s*$") }).first().click();
    await page.waitForTimeout(600);
    await main.locator("[data-testid=subgrid-create]").click({ timeout: 6000 });
    await main.locator("[data-testid=subgrid-submit]").click({ timeout: 6000 });
    let ok = false;
    for (let i = 0; i < 15 && !ok; i++) { await page.waitForTimeout(500); ok = await main.locator("table.aws tr:has(td)").count() > 0 && expect.test(await main.innerText()); }
    check(ok, `${tabName}: create from the sub-grid shows a filled row`);
    const tds = (await main.locator("table.aws tr:has(td)").first().locator("td").allInnerTexts()).map((s) => s.trim());
    check(tds.length > 0 && tds.every((v) => !BLANK.has(v)), `${tabName}: every column filled`, tds.join("|"));
  };
  await subCreate("Services", /web-service/);
  await subCreate("Tasks", /web/);

  // delete the service first (clusters with services cannot be deleted), then the cluster
  await page.locator(".top-tabs button").filter({ hasText: /^\s*Services\s*$/ }).first().click();
  await page.waitForTimeout(600);
  await main.locator("table.aws tr:has(td)").first().locator("button").filter({ hasText: /^Delete$/ }).click({ timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(1200);
  await main.locator("button").filter({ hasText: /^\s*(delete)?\s*Delete\s*$/ }).first().click({ timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(800);
  const conf = page.locator("[role=dialog]:visible button, .modal:visible button").filter({ hasText: /delete|confirm|yes/i }).last();
  if (await conf.count()) await conf.click().catch(() => {});
  let gone = false;
  for (let i = 0; i < 15 && !gone; i++) {
    await page.waitForTimeout(600);
    await toList();
    gone = (await rowFor(name || "my-cluster").count()) === 0;
  }
  check(gone, "delete removes the cluster from the grid");
}
