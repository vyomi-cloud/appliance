// Storage account: containers (create/delete in UI), blobs (upload/delete), API<->UI both ways.
export default { id: "storage", title: "Storage accounts", fn: async ({ shows, uiRowDelete, arm, v, go, body, click, tab, poll, seenInUi, uiDelete, page, RG, P, sleep, rec }) => {
  const acct = "actstor1";
  const mk = await arm("PUT", `${P}/Microsoft.Storage/storageAccounts/${acct}${v("2023-01-01")}`, { location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2" });
  rec("API create storage account", mk.status < 300 ? "PASS" : "FAIL", mk.status);
  const H = { "x-ms-version": "2023-11-03", authorization: `SharedKey ${acct}:x` };
  const blobs = async (c) => (await arm("GET", `/${acct}/${c}?restype=container&comp=list`, null, null, H)).text;
  const containers = async () => (await arm("GET", `/${acct}?comp=list`, null, null, H)).text;
  const blade = `/storage/${RG}/${acct}`;
  // API->UI first container
  const ac = await arm("PUT", `/${acct}/fromapi?restype=container`, null, null, H);
  await go(blade); await tab("Containers");
  rec("API->UI: container created over the blob API is listed", (await shows(/fromapi/)) ? "PASS" : "FAIL", `PUT ${ac.status}`);
  // UI->API container create
  try {
    await click(/^Create$/, {}); await sleep(800);
    const dlg = page.getByRole("dialog").last(); await dlg.getByRole("textbox").first().fill("fromui"); await dlg.getByRole("button", { name: /^Create$/ }).dispatchEvent("click");
    const ok = await poll(async () => /<Name>fromui<\/Name>/.test(await containers()), 20000);
    rec("UI->API: Create container in the console exists via the blob API", ok ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Create container", "FAIL", String(e.message).split("\n")[0]); }
  // UI blob upload
  try {
    await go(`${blade}/containers/fromapi`).catch(() => {});
    if (!/Upload/.test(await body())) { await go(blade); await tab("Containers"); await page.getByText("fromapi", { exact: true }).first().click(); await sleep(2500); }
    await click(/^Upload$/); await sleep(800);
    await page.locator("input[type=file]").last().setInputFiles({ name: "hello.txt", mimeType: "text/plain", buffer: Buffer.from("hello from ui") });
    const dlg = page.getByRole("dialog").last(); await dlg.getByRole("button", { name: /^Upload$/ }).dispatchEvent("click");
    const ok = await poll(async () => /hello\.txt/.test(await blobs("fromapi")), 20000);
    rec("UI->API: Upload blob in the console is listed by the blob API", ok ? "PASS" : "FAIL");
    if (ok) { const g = await arm("GET", `/${acct}/fromapi/hello.txt`, null, null, H); rec("UI->API: uploaded blob content matches", g.text === "hello from ui" ? "PASS" : "FAIL", g.text.slice(0, 40)); }
  } catch (e) { rec("UI->API: blob Upload", "FAIL", String(e.message).split("\n")[0]); }
  // API->UI blob
  await arm("PUT", `/${acct}/fromapi/viaapi.txt`, "api body", "text/plain", { ...H, "x-ms-blob-type": "BlockBlob" });
  await go(blade); await tab("Containers"); try { await page.getByText("fromapi", { exact: true }).first().click(); await sleep(2500); } catch (_) {}
  rec("API->UI: blob uploaded over the blob API is listed in the container", (await shows(/viaapi\.txt/)) ? "PASS" : "FAIL");
  // API->UI delete container
  await arm("DELETE", `/${acct}/fromui?restype=container`, null, null, H);
  await go(blade); await tab("Containers"); rec("API->UI: container deleted over the API disappears", !/fromui/.test(await body()) ? "PASS" : "FAIL");
  // UI delete container
  try {
    await go(blade); await tab("Containers"); await uiRowDelete("fromapi");
    const ok = await poll(async () => !/<Name>fromapi<\/Name>/.test(await containers()), 20000);
    rec("UI->API: Delete container in the console removes it via the blob API", ok ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Delete container", "FAIL", String(e.message).split("\n")[0]); }
  // account delete from UI
  await uiDelete(acct, blade);
  rec("UI->API: Delete storage account removes it from ARM", (await poll(async () => (await arm("GET", `${P}/Microsoft.Storage/storageAccounts/${acct}${v("2023-01-01")}`)).status === 404, 25000)) ? "PASS" : "FAIL");
} };
