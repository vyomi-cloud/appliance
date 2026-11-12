// Cosmos DB account: API picker (NoSQL) -> Basics (name) -> Review + create -> Create
export default async function ({ page, base, name, sleep, dispatch, arm, SUB }) {
  await page.goto(`${base}/v4/azure/index.html#/cosmos/create`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const nosql = page.getByRole("radio", { name: /Azure Cosmos DB for NoSQL/ });
  await nosql.waitFor({ timeout: 20000 });
  await nosql.check().catch(() => nosql.dispatchEvent("click"));
  await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
  const nameBox = page.getByLabel("Account Name").first();
  await nameBox.waitFor({ timeout: 20000 });
  await nameBox.fill(name);
  await dispatch(page.getByRole("button", { name: /Review \+ create/i }).first());
  await sleep(1000);
  await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
  // Cosmos account creation is an ARM LRO: wait (bounded) for it to land before the harness looks it up
  for (let i = 0; i < 30; i++) {
    const r = await arm("GET", `/subscriptions/${SUB}/providers/Microsoft.DocumentDB/databaseAccounts?api-version=2023-11-15`);
    if ((r.json?.value || []).some((x) => x.name === name)) return;
    await sleep(2000);
  }
}
