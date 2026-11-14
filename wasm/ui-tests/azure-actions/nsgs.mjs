// NSG: add inbound rule (UI), API rule shows in UI, delete rule, delete NSG.
export default { id: "nsgs", title: "Network security groups", fn: async ({ shows, uiRowDelete, arm, v, go, body, click, tab, poll, uiDelete, page, RG, P, sleep, rec }) => {
  const n = "actnsg1", np = `${P}/Microsoft.Network/networkSecurityGroups/${n}`, blade = `/nsgs/${RG}/${n}`;
  rec("API create NSG", (await arm("PUT", np + v("2023-11-01"), { location: "eastus", properties: {} })).status < 300 ? "PASS" : "FAIL");
  const rule = async (r) => (await arm("GET", `${np}/securityRules/${r}${v("2023-11-01")}`));
  await arm("PUT", `${np}/securityRules/api-rule${v("2023-11-01")}`, { properties: { priority: 300, direction: "Inbound", access: "Allow", protocol: "Tcp", sourcePortRange: "*", destinationPortRange: "8080", sourceAddressPrefix: "*", destinationAddressPrefix: "*" } });
  await go(blade); await tab("Inbound security rules");
  rec("API->UI: rule created over ARM is listed under Inbound security rules", (await shows(/api-rule/)) && /8080/.test(await body()) ? "PASS" : "FAIL");
  try {
    await click(/^Add$/); await sleep(800);
    await page.getByLabel("Name", { exact: true }).last().fill("ui-rule"); await page.getByLabel("Destination port ranges").fill("2222");
    await page.getByLabel("Priority").fill("310");
    const dlg = page.getByRole("dialog").last().or(page.locator("[role=dialog], .vy-panel").last());
    await page.getByRole("button", { name: /^Add$/ }).last().dispatchEvent("click");
    const ok = await poll(async () => (await rule("ui-rule")).status === 200, 20000);
    const g = (await rule("ui-rule")).json?.properties || {};
    rec("UI->API: Add rule in the console exists in ARM", ok ? "PASS" : "FAIL");
    if (ok) rec("UI->API: rule fields (port 2222, priority 310, Inbound) match", g.destinationPortRange === "2222" && g.priority === 310 && g.direction === "Inbound" ? "PASS" : "FAIL", JSON.stringify({ p: g.destinationPortRange, pr: g.priority, d: g.direction }));
  } catch (e) { rec("UI->API: Add rule", "FAIL", String(e.message).split("\n")[0]); }
  await arm("DELETE", `${np}/securityRules/api-rule${v("2023-11-01")}`);
  await go(blade); await tab("Inbound security rules"); rec("API->UI: rule deleted over ARM disappears", !/api-rule/.test(await body()) ? "PASS" : "FAIL");
  try {
    await go(blade); await tab("Inbound security rules"); await uiRowDelete("ui-rule");
    rec("UI->API: Delete rule in the console removes it from ARM", (await poll(async () => (await rule("ui-rule")).status === 404, 20000)) ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Delete rule", "FAIL", String(e.message).split("\n")[0]); }
  await uiDelete(n, blade);
  rec("UI->API: Delete NSG removes it from ARM", (await poll(async () => (await arm("GET", np + v("2023-11-01"))).status === 404, 25000)) ? "PASS" : "FAIL");
} };
