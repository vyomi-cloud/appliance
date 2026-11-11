// SQL database: create a new server through the wizard's inline dialog, then the database `name` on it.
export default async function ({ page, base, name, sleep, SUB, arm, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/sql/create`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const db = page.getByLabel("Database name").first();
  await db.waitFor({ timeout: 20000 });
  await db.fill(name);
  // new server via inline dialog
  const srv = ("bdsv" + name.replace(/[^a-z0-9]/gi, "")).toLowerCase().slice(0, 40);
  await page.getByRole("button", { name: /^Create new$/ }).last().dispatchEvent("click");
  const dlg = page.getByRole("dialog", { name: /Create SQL Database Server/ });
  await dlg.waitFor({ timeout: 10000 });
  await dlg.getByLabel("Server name").fill(srv);
  const login = dlg.getByLabel("Server admin login");
  if (await login.count()) {
    await login.fill("bdadmin");
    await dlg.getByLabel("Password", { exact: true }).fill("Vy0mi-Pass-123!");
    await dlg.getByLabel("Confirm password").fill("Vy0mi-Pass-123!");
  }
  await dispatch(dlg.getByRole("button", { name: /^OK$/ }));
  await dlg.waitFor({ state: "hidden", timeout: 15000 });
  await sleep(1500);
  await dispatch(page.getByRole("button", { name: /Review \+ create/ }).first());
  await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
}
export async function find({ arm, SUB, name, q }) {
  const sv = await arm("GET", `/subscriptions/${SUB}/providers/Microsoft.Sql/servers${q("2021-11-01")}`);
  for (const s of sv.json?.value || []) {
    const r = await arm("GET", `${s.id}/databases${q("2021-11-01")}`);
    const hit = (r.json?.value || []).find((d) => d.name === name);
    if (hit) return hit;
  }
  return null;
}
