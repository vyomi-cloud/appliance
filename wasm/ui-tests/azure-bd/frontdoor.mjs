// Front Door: the console creates a profile through a dialog on the list page (#/frontdoor), not a #/create wizard.
export default async function ({ page, base, name, sleep, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/frontdoor`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await sleep(2500);
  const btn = page.getByRole("button", { name: /^\+?\s*Create/i }).first();
  await btn.waitFor({ timeout: 15000 });
  await dispatch(btn);
  const dlg = page.getByRole("dialog");
  await dlg.waitFor({ timeout: 10000 });
  await dlg.getByLabel("Profile name").fill(name);
  await dispatch(dlg.getByRole("button", { name: /^Create$/ }));
  await dlg.waitFor({ state: "hidden", timeout: 15000 }); // dialog closes only after the PUT succeeded
}
