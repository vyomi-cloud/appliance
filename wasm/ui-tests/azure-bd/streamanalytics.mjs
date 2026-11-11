// Stream Analytics: console has no wizard route; create is a dialog opened from the browse blade (#/streamanalytics).
export default async function ({ page, base, name, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/streamanalytics`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const open = page.getByRole("button", { name: /^\+?\s*Create/ }).first();
  const link = page.getByText("Create Stream Analytics job").first();
  await open.or(link).first().waitFor({ timeout: 20000 });
  await dispatch(open.or(link).first());
  const dlg = page.getByRole("dialog", { name: /New Stream Analytics job/ });
  await dlg.waitFor({ timeout: 10000 });
  await dlg.getByLabel("Job name").fill(name);
  await dispatch(dlg.getByRole("button", { name: /^Create$/ }));
  await dlg.waitFor({ state: "hidden", timeout: 15000 }); // stays open on a creation error
}
