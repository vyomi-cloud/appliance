// Sweep A (Nano halves, v4 wire): SQL server PUT/GET never echo administratorLoginPassword; deleting a resource group destroys
// the Key Vault data inside it; APIM listSecrets returns distinct, stable primary/secondary keys.
export default { id: "sweepA", title: "Sweep A (ARM semantics)", fn: async ({ arm, v, SUB, rec, sleep }) => {
  const t = Date.now() % 100000, rg = `sweeprg${t}`, rp = `/subscriptions/${SUB}/resourceGroups/${rg}`;
  await arm("PUT", rp + v("2021-04-01"), { location: "eastus" });
  const sql = await arm("PUT", `${rp}/providers/Microsoft.Sql/servers/sweepsql${v("2021-11-01")}`, { location: "eastus", properties: { administratorLogin: "adm", administratorLoginPassword: "S3cret-Pass!" } });
  rec("SQL server PUT omits administratorLoginPassword", sql.status < 300 && !sql.text.includes("S3cret-Pass!") ? "PASS" : "FAIL", sql.text.slice(0, 120));
  const sg = await arm("GET", `${rp}/providers/Microsoft.Sql/servers/sweepsql${v("2021-11-01")}`);
  rec("SQL server GET omits administratorLoginPassword", sg.status === 200 && !sg.text.includes("S3cret-Pass!") ? "PASS" : "FAIL", sg.text.slice(0, 120));
  const kv = `sweepkv${t}`, H = { "x-vyomi-vault": kv };
  const mk = await arm("PUT", `${rp}/providers/Microsoft.KeyVault/vaults/${kv}${v("2023-07-01")}`, { location: "eastus", properties: { sku: { family: "A", name: "standard" }, tenantId: "00000000-0000-0000-0000-000000000000" } });
  rec("Key Vault created", mk.status < 300 ? "PASS" : "FAIL", mk.status);
  const put = await arm("PUT", "/secrets/s1?api-version=7.4", { value: "topsecret" }, null, H);
  const put2 = put.status >= 300 ? await arm("POST", "/secrets/s1?api-version=7.4", { value: "topsecret" }, null, H) : put;
  rec("Key Vault secret set over the data plane", put2.status < 300 ? "PASS" : "FAIL", `${put.status}/${put2.status} ${put2.text.slice(0, 80)}`);
  const pre = await arm("GET", "/secrets/s1?api-version=7.4", null, null, H);
  rec("Key Vault secret readable before the group is deleted", pre.status === 200 && pre.json?.value === "topsecret" ? "PASS" : "FAIL", `${pre.status} ${pre.text.slice(0, 80)}`);
  const del = await arm("DELETE", rp + v("2021-04-01"));
  rec("Resource group delete accepted", del.status < 300 ? "PASS" : "FAIL", del.status);
  await sleep(1500);
  const got = await arm("GET", "/secrets/s1?api-version=7.4", null, null, H);
  rec("Resource group delete destroyed the Key Vault secrets", got.status !== 200 || got.json?.value !== "topsecret" ? "PASS" : "FAIL", `${got.status} ${got.text.slice(0, 80)}`);
  const rg2 = `/subscriptions/${SUB}/resourceGroups/sweeprg2${t}`;
  await arm("PUT", rg2 + v("2021-04-01"), { location: "eastus" });
  await arm("PUT", `${rg2}/providers/Microsoft.ApiManagement/service/sweepapim${v("2022-08-01")}`, { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "qa" } });
  const k1 = await arm("POST", `${rg2}/providers/Microsoft.ApiManagement/service/sweepapim/subscriptions/master/listSecrets${v("2022-08-01")}`, {});
  const k2 = await arm("POST", `${rg2}/providers/Microsoft.ApiManagement/service/sweepapim/subscriptions/master/listSecrets${v("2022-08-01")}`, {});
  rec("APIM listSecrets returns distinct primary/secondary keys", k1.status === 200 && k1.json?.primaryKey && k1.json?.secondaryKey && k1.json.primaryKey !== k1.json.secondaryKey ? "PASS" : "FAIL", k1.text.slice(0, 100));
  rec("APIM listSecrets is stable across calls", k1.json && k2.json && k1.json.primaryKey === k2.json.primaryKey ? "PASS" : "FAIL");
  await arm("DELETE", rg2 + v("2021-04-01"));
} };
