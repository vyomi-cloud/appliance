// AKS: real "Create Kubernetes cluster" wizard (#/aks/create). Only the cluster name is required; everything else keeps its default.
export default async function ({ page, base, name, sleep, SUB, arm }) {
  await page.goto(`${base}/v4/azure/index.html#/aks/create`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const nameBox = page.getByLabel("Kubernetes cluster name");
  await nameBox.waitFor({ timeout: 30000 });
  await nameBox.fill(name);
  await sleep(500);
  await page.getByRole("button", { name: /Review \+ create/ }).first().dispatchEvent("click");
  await page.getByRole("button", { name: /^Create$/ }).first().dispatchEvent("click");
  // the wizard first ensures a Log Analytics workspace, then PUTs the cluster: wait (up to 60s) for the cluster to appear; the harness's find() is the real assertion
  for (let i = 0; i < 30; i++) {
    const r = await arm("GET", `/subscriptions/${SUB}/providers/Microsoft.ContainerService/managedClusters?api-version=2023-10-01`);
    if ((r.json?.value || []).some((x) => x.name === name)) break;
    await sleep(2000);
  }
}
