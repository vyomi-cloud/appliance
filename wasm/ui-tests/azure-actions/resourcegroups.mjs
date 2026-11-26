// Resource groups (v4): list -> detail replaces the list, detail shows location + tags + the resources the group holds
// (API->UI), a tag set over ARM shows, and the console's type-to-confirm Delete removes the group from ARM (UI->API).
export default { id: "resourcegroups", title: "Resource groups", fn: async ({ shows, arm, v, go, body, click, poll, page, SUB, sleep, rec }) => {
  const g = `actrg${Date.now() % 100000}`, gp = `/subscriptions/${SUB}/resourceGroups/${g}`, V = v("2021-04-01");
  const mk = await arm("PUT", gp + V, { location: "westeurope", tags: { team: "qa" } });
  rec("API create resource group (westeurope, tag team=qa)", mk.status < 300 ? "PASS" : "FAIL", mk.status);
  const kv = await arm("PUT", `${gp}/providers/Microsoft.KeyVault/vaults/${g}kv${v("2023-07-01")}`, { location: "westeurope", properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } });
  rec("API create a key vault inside the group", kv.status < 300 ? "PASS" : "FAIL", kv.status);
  await go("/resourcegroups");
  rec("API->UI: group created over ARM is listed with its location", (await shows(new RegExp(g))) && /West Europe/.test(await body()) ? "PASS" : "FAIL");
  // list -> detail: the Resource groups list must not stay under the detail header
  await go(`/resourcegroups/${g}`);
  await shows(/West Europe/, 15000); await shows(/team\s*:\s*qa/, 8000);
  const t = await body();
  rec("Detail opens as the group (heading + Resource group type), the list is gone", new RegExp(`${g}\\s+Resource group`).test(t) && !/Showing 1 to \d+ of \d+ records/.test(t.split("Overview")[0] || "") ? "PASS" : "FAIL", t.slice(0, 160));
  rec("Detail shows the group location (West Europe)", /West Europe/.test(t) ? "PASS" : "FAIL");
  rec("API->UI: tag team : qa set over ARM is shown on Overview", /team\s*:\s*qa/.test(t) ? "PASS" : "FAIL");
  rec("API->UI: the key vault inside the group is listed under Resources", (await shows(new RegExp(g + "kv"), 20000)) ? "PASS" : "FAIL");
  await arm("PATCH", gp + V, { tags: { team: "qa", viaapi: "yes" } });
  await go(`/resourcegroups/${g}`);
  rec("API->UI: a tag added over ARM later shows after reload", (await shows(/viaapi\s*:\s*yes/)) ? "PASS" : "FAIL");
  try {
    await go(`/resourcegroups/${g}`);
    await page.getByText(/^Delete resource group$/).first().click(); await sleep(1200);
    await page.getByLabel("Enter resource group name to confirm deletion").fill(g);
    await page.getByRole("button", { name: /^Delete$/ }).last().dispatchEvent("click");
    const ok = await poll(async () => (await arm("GET", gp + V)).status === 404 || (await arm("GET", gp + V)).json?.properties?.provisioningState === "Deleting", 30000);
    rec("UI->API: Delete resource group (type-to-confirm page) removes it from ARM", ok ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Delete resource group", "FAIL", String(e.message).split("\n")[0]); await arm("DELETE", gp + V); }
} };
