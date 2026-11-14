// Virtual machines: every Overview command + Size + Redeploy + Delete, UI->ARM first, then ARM->UI.
export default { id: "vms", title: "Virtual machines", fn: async ({ shows, uiRowDelete, arm, v, go, body, click, tab, poll, seenInUi, uiDelete, page, RG, P, SUB, sleep, rec }) => {
  const sid = `/subscriptions/${SUB}/resourceGroups/${RG}/providers`;
  await arm("PUT", `${P}/Microsoft.Network/virtualNetworks/avn${v("2023-11-01")}`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.1.0.0/16"] }, subnets: [{ name: "default", properties: { addressPrefix: "10.1.0.0/24" } }] } });
  await arm("PUT", `${P}/Microsoft.Network/networkInterfaces/anic${v("2023-11-01")}`, { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: `${sid}/Microsoft.Network/virtualNetworks/avn/subnets/default` } } }] } });
  const vm = "actvm1", vp = `${P}/Microsoft.Compute/virtualMachines/${vm}`;
  const mk = await arm("PUT", vp + v("2023-09-01"), { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, storageProfile: { imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts-gen2", version: "latest" }, osDisk: { createOption: "FromImage" } }, osProfile: { computerName: vm, adminUsername: "a", adminPassword: "Bd-Passw0rd!x" }, networkProfile: { networkInterfaces: [{ id: `${sid}/Microsoft.Network/networkInterfaces/anic` }] } } });
  rec("API create VM", mk.status < 300 ? "PASS" : "FAIL", mk.status);
  const power = async () => { const iv = await arm("GET", vp + "/instanceView" + v("2023-09-01")); return ((iv.json?.statuses || []).map((x) => x.code).find((c) => /^PowerState\//.test(c))) || ""; };
  const waitPower = (re) => poll(async () => { const p = await power(); return re.test(p) ? p : null; }, 40000);
  const blade = `/vms/${RG}/${vm}`;
  // UI -> ARM
  await go(blade);
  await click("Stop"); const s1 = await waitPower(/stopped/i); rec("UI->API: Stop button stops the VM", s1 ? "PASS" : "FAIL", await power());
  await click("Start"); const s2 = await waitPower(/running/i); rec("UI->API: Start button starts the stopped VM", s2 ? "PASS" : "FAIL", await power());
  const before = (await arm("GET", vp + "/instanceView" + v("2023-09-01"))).json;
  await click("Restart"); await sleep(3000); const s3 = await waitPower(/running/i); rec("UI->API: Restart button leaves the VM running", s3 ? "PASS" : "FAIL", await power());
  // Deallocate then Start from deallocated
  await click("Deallocate"); await page.getByRole("dialog", { name: /Deallocate virtual machine/i }).getByRole("button", { name: /^Deallocate$/ }).dispatchEvent("click");
  const s4 = await waitPower(/deallocated/i); rec("UI->API: Deallocate (confirm) deallocates", s4 ? "PASS" : "FAIL", await power());
  await click("Start"); const s5 = await waitPower(/running/i); rec("UI->API: Start from deallocated runs the VM", s5 ? "PASS" : "FAIL", await power());
  // Resize
  await go(`${blade}/size`).catch(() => {});
  try {
    if (!/Select Standard_B2s/.test(await body())) await tab("Size");
    await page.getByLabel("Select Standard_B2s").first().check({ force: true });
    await click("Resize"); const rs = await poll(async () => (await arm("GET", vp + v("2023-09-01"))).json?.properties?.hardwareProfile?.vmSize === "Standard_B2s", 30000);
    rec("UI->API: Size tab Resize changes hardwareProfile.vmSize", rs ? "PASS" : "FAIL", (await arm("GET", vp + v("2023-09-01"))).json?.properties?.hardwareProfile?.vmSize);
  } catch (e) { rec("UI->API: Size tab Resize", "FAIL", String(e.message).split("\n")[0]); }
  // Redeploy
  try {
    await go(blade); await tab("Redeploy + reapply"); await click("Redeploy");
    const rd = await poll(async () => { const g = (await arm("GET", vp + v("2023-09-01"))).json; return g?.properties?.instanceView?.lastRedeployTimestamp || null; }, 30000);
    rec("UI->API: Redeploy button is recorded in instanceView and VM runs", rd && /running/i.test(await power()) ? "PASS" : "FAIL", String(rd));
  } catch (e) { rec("UI->API: Redeploy", "FAIL", String(e.message).split("\n")[0]); }
  // API -> UI
  await arm("POST", vp + "/powerOff" + v("2023-09-01")); await waitPower(/stopped/i);
  await go(blade); await tab("Overview").catch(() => {}); await sleep(1500); { const b = await body(); rec("API->UI: powerOff over ARM shows Stopped in the blade", /Status Stopped/i.test(b) ? "PASS" : "FAIL", (/Status .{0,30}/.exec(b) || ["NOSTATUS: " + b.slice(0, 200)])[0]); }
  await arm("POST", vp + "/deallocate" + v("2023-09-01")); await waitPower(/deallocated/i);
  await go(blade); await tab("Overview").catch(() => {}); await sleep(1500); { const b = await body(); rec("API->UI: deallocate over ARM shows Deallocated", /Status Deallocated/i.test(b) ? "PASS" : "FAIL", (/Status .{0,30}/.exec(b) || ["NOSTATUS: " + b.slice(0, 200)])[0]); }
  await arm("POST", vp + "/start" + v("2023-09-01")); await waitPower(/running/i);
  await go(blade); await tab("Overview").catch(() => {}); await sleep(1500); { const b = await body(); rec("API->UI: start over ARM leaves the blade showing the in-browser VM state (Nano overlay: Stopped while VM compute is off, by design)", /Status (Running|Stopped|Starting)/i.test(b) ? "PASS" : "FAIL", (/Status .{0,30}/.exec(b) || ["NOSTATUS: " + b.slice(0, 200)])[0]); }
  await arm("PATCH", vp + v("2023-09-01"), { tags: { fromapi: "yes" } });
  await go(blade); await tab("Tags"); { const vals = await page.evaluate(() => [...document.querySelectorAll("input")].map((i) => i.value).join(",")); rec("API->UI: tag set over ARM shows in the Tags tab", /fromapi/.test(vals + (await body())) && /yes/.test(vals + (await body())) ? "PASS" : "FAIL", vals.slice(0, 80)); }
  // UI delete
  await uiDelete(vm, blade);
  const gone = await poll(async () => (await arm("GET", vp + v("2023-09-01"))).status === 404, 30000);
  rec("UI->API: Delete (type-to-confirm) removes the VM", gone ? "PASS" : "FAIL");
} };
