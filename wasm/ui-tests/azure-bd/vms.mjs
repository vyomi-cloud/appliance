// Virtual machines: real "Create a virtual machine" wizard (#/vms/create). Password auth; image/size/network keep defaults.
export default async function ({ page, base, name, sleep, SUB, arm, dispatch }) {
  await page.goto(`${base}/v4/azure/index.html#/vms/create`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const nameBox = page.getByLabel("Virtual machine name").first();
  await nameBox.waitFor({ timeout: 30000 });
  await nameBox.fill(name);
  await page.getByRole("radio", { name: "Password" }).first().check({ force: true }).catch(async () => {
    await dispatch(page.getByRole("radio", { name: "Password" }).first());
  });
  const pw = page.locator("#vm-pw");
  await pw.waitFor({ timeout: 10000 });
  await pw.fill("Vy0mi-Pass-123!");
  await page.locator("#vm-pw2").fill("Vy0mi-Pass-123!");
  // the default size (Standard_D2s_v5) is "medium" and the Free tier caps VMs at "small" (tier_size_limit 403): pick a small size
  await page.locator("#vm-size").locator("option", { hasText: "Standard_B1s " }).waitFor({ state: "attached", timeout: 20000 });
  await page.locator("#vm-size").selectOption("Standard_B1s");
  await sleep(500);
  await dispatch(page.getByRole("button", { name: /Review \+ create/ }).first());
  await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
  // VM creation is slow: wait up to 90s for it to show up over ARM (the harness's find() is the real assertion)
  for (let i = 0; i < 45; i++) {
    const r = await arm("GET", `/subscriptions/${SUB}/providers/Microsoft.Compute/virtualMachines?api-version=2023-09-01`);
    if ((r.json?.value || []).some((x) => x.name === name)) break;
    await sleep(2000);
  }
}

// After the UI-created VM exists: the blade's Deallocate (confirm dialog) must hit the ARM deallocate POST and the VM must read Deallocated.
export async function after({ page, base, hit, arm, q, sleep, rec }) {
  const m = /resourceGroups\/([^/]+)\/providers\/Microsoft.Compute\/virtualMachines\/([^/]+)/i.exec(hit.id);
  await page.goto(`${base}/v4/azure/index.html#/vms/${m[1]}/${m[2]}`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const btn = page.getByRole("button", { name: /^Deallocate$/ }).first();
  await btn.waitFor({ timeout: 30000 });
  await btn.dispatchEvent("click");
  const dlg = page.getByRole("dialog", { name: /Deallocate virtual machine/i });
  await dlg.waitFor({ timeout: 10000 });
  await dlg.getByRole("button", { name: /^Deallocate$/ }).dispatchEvent("click");
  let st = "";
  for (let i = 0; i < 30; i++) {
    const iv = await arm("GET", hit.id + "/instanceView" + q("2023-09-01"));
    st = ((iv.json?.statuses || []).map((x) => x.code).find((c) => /^PowerState\//.test(c))) || "";
    if (/deallocated/i.test(st)) break;
    await sleep(1500);
  }
  rec("UI->API: Deallocate button (confirm dialog) deallocates the VM", /deallocated/i.test(st) ? "PASS" : "FAIL", st);
}
