// Recovery Services vault: create is a dialog on the browse blade (#/recoveryservices), not a /create wizard.
export default async function ({ page, base, name, sleep, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/recoveryservices`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const open = page.getByRole("button", { name: /^Create$|Create/ }).first();
  await open.waitFor({ timeout: 30000 });
  await dispatch(open);
  const dlg = page.getByRole("dialog", { name: /Create Recovery Services vault/ });
  await dlg.waitFor({ timeout: 15000 });
  // pick the harness test resource group (bd-rg-*), if listed
  const rg = dlg.getByLabel("Resource group");
  await sleep(1500);
  const opts = await rg.locator("option").allTextContents();
  const bd = opts.filter((o) => /^bd-rg-/.test(o)).pop();
  if (bd) await rg.selectOption({ label: bd });
  await dlg.getByLabel("Vault name").fill(name);
  await dispatch(dlg.getByRole("button", { name: /^Create$/ }));
}
