// Key vault: secrets (Generate/Import in UI, API->UI, delete), vault UI delete.
export default { id: "keyvaults", title: "Key vaults", fn: async ({ shows, uiRowDelete, arm, v, go, body, click, tab, poll, uiDelete, page, RG, P, sleep, rec }) => {
  const kv = "actkv1", H = { "x-vyomi-vault": kv };
  const mk = await arm("PUT", `${P}/Microsoft.KeyVault/vaults/${kv}${v("2023-07-01")}`, { location: "eastus", properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } });
  rec("API create vault", mk.status < 300 ? "PASS" : "FAIL", mk.status);
  const blade = `/keyvaults/${RG}/${kv}`;
  const sec = (n) => arm("GET", `/secrets/${n}?api-version=7.4`, null, null, H);
  const put = await arm("PUT", `/secrets/fromapi?api-version=7.4`, { value: "api-secret" }, null, H);
  const put2 = put.status >= 300 ? await arm("POST", `/secrets/fromapi?api-version=7.4`, { value: "api-secret" }, null, H) : put;
  await go(blade); await tab("Secrets");
  rec("API->UI: secret set over the Key Vault REST API is listed", (await shows(/fromapi/)) ? "PASS" : "FAIL", `set ${put.status}/${put2.status}`);
  try {
    await click(/^Generate\/Import$/); await sleep(800);
    await page.getByLabel("Name", { exact: true }).last().fill("fromui"); await page.getByLabel("Secret value").fill("ui-secret");
    await click(/^Create$/);
    const ok = await poll(async () => (await sec("fromui")).json?.value === "ui-secret", 20000);
    rec("UI->API: Generate/Import secret in the console is readable over the Key Vault API with the same value", ok ? "PASS" : "FAIL", (await sec("fromui")).text.slice(0, 100));
  } catch (e) { rec("UI->API: Generate/Import secret", "FAIL", String(e.message).split("\n")[0]); }
  await arm("DELETE", `/secrets/fromapi?api-version=7.4`, null, null, H);
  await go(blade); await tab("Secrets"); rec("API->UI: secret deleted over the API disappears from the list", !/fromapi/.test(await body()) ? "PASS" : "FAIL");
  try {
    await go(blade); await tab("Secrets"); await uiRowDelete("fromui");
    const ok = await poll(async () => (await sec("fromui")).status === 404 || (await sec("fromui")).json?.error, 20000);
    rec("UI->API: Delete secret in the console removes it via the API", ok ? "PASS" : "FAIL", (await sec("fromui")).text.slice(0, 80));
  } catch (e) { rec("UI->API: Delete secret", "FAIL", String(e.message).split("\n")[0]); }
  await uiDelete(kv, blade);
  rec("UI->API: Delete vault removes it from ARM", (await poll(async () => (await arm("GET", `${P}/Microsoft.KeyVault/vaults/${kv}${v("2023-07-01")}`)).status === 404, 25000)) ? "PASS" : "FAIL");
} };
