// API Management create wizard: Basics needs name + organization name + admin email.
export default async function ({ page, base, name, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/apim/create`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const nameBox = page.getByLabel("Resource name").first();
  await nameBox.waitFor({ timeout: 20000 });
  await nameBox.fill(name);
  await page.getByLabel("Organization name").first().fill("Vyomi BD");
  await page.getByLabel("Administrator email").first().fill("bd@example.com");
  await dispatch(page.getByRole("button", { name: /Review \+ install/ }).first());
  await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
  // the PUT is slow: wait for the console success toast (real completion), else fail
  await page.getByText("Deployment succeeded").first().waitFor({ timeout: 30000 });
}
