// Network managers: create is a dialog opened from the list (no /create wizard route).
export default async function ({ page, base, name, sleep, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/networkmanagers`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const btn = page.getByRole("button", { name: /^\+?\s*Create/ }).first();
  await btn.waitFor({ timeout: 30000 });
  await dispatch(btn);
  const dlg = page.getByRole("dialog", { name: /Create network manager/i });
  await dlg.waitFor({ timeout: 15000 });
  await dlg.getByLabel("Network manager name").fill(name);
  await dispatch(dlg.getByRole("button", { name: /^Create$/ }));
  await page.getByText(/created\./).first().waitFor({ timeout: 20000 }); // success toast = ARM PUT done
}
