// Function App: step 1 hosting picker (#/functionapp/create -> Select), then the Flex Consumption wizard. Only the name is needed.
export default async function ({ page, base, name, sleep, SUB, arm }) {
  await page.goto(`${base}/v4/azure/index.html#/functionapp/create`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const sel = page.getByRole("button", { name: /^Select$/ }).first();
  await sel.waitFor({ timeout: 30000 });
  await sel.dispatchEvent("click");
  const nameBox = page.getByLabel("Function App name");
  await nameBox.waitFor({ timeout: 30000 });
  await nameBox.fill(name);
  await sleep(500);
  await page.getByRole("button", { name: /Review \+ create/ }).first().dispatchEvent("click");
  await page.getByRole("button", { name: /^Create$/ }).first().dispatchEvent("click");
  for (let i = 0; i < 30; i++) {
    const r = await arm("GET", `/subscriptions/${SUB}/providers/Microsoft.Web/sites?api-version=2022-09-01`);
    if ((r.json?.value || []).some((x) => x.name === name)) break;
    await sleep(2000);
  }
  await sleep(3000);
}
