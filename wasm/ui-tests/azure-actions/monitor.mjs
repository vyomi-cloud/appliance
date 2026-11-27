// Azure Monitor (v4): an action group and a metric alert rule created over ARM are listed (Action groups / Alerts > Alert rules)
// with their real columns (API->UI); deleting the rule in the console removes it from ARM (UI->API); the Metrics and Logs
// blades open without the Not-simulated panel.
export default { id: "monitor", title: "Monitor", fn: async ({ shows, arm, v, go, body, click, poll, page, RG, P, SUB, sleep, rec }) => {
  const sa = "actmonsa1", ag = "actmonag1", ru = "actmonrule1";
  const mkSa = await arm("PUT", `${P}/Microsoft.Storage/storageAccounts/${sa}${v("2023-01-01")}`, { location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2" });
  rec("API create the alert target (storage account)", mkSa.status < 300 ? "PASS" : "FAIL", mkSa.status);
  const mkAg = await arm("PUT", `${P}/microsoft.insights/actionGroups/${ag}${v("2023-01-01")}`, { location: "Global", properties: { groupShortName: "actag", enabled: true, emailReceivers: [{ name: "ops", emailAddress: "ops@example.com" }] } });
  rec("API create action group", mkAg.status < 300 ? "PASS" : "FAIL", `${mkAg.status} ${mkAg.text.slice(0, 100)}`);
  const scope = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${sa}`;
  const mkRu = await arm("PUT", `${P}/microsoft.insights/metricAlerts/${ru}${v("2018-03-01")}`, { location: "global", properties: { severity: 2, enabled: true, scopes: [scope], evaluationFrequency: "PT1M", windowSize: "PT5M", criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [{ criterionType: "StaticThresholdCriterion", name: "c1", metricName: "Transactions", metricNamespace: "Microsoft.Storage/storageAccounts", operator: "GreaterThan", threshold: 100, timeAggregation: "Total" }] }, actions: [] } });
  rec("API create metric alert rule", mkRu.status < 300 ? "PASS" : "FAIL", `${mkRu.status} ${mkRu.text.slice(0, 100)}`);
  await go("/monitor/actiongroups");
  rec("API->UI: action group created over ARM is listed", (await shows(new RegExp(ag))) ? "PASS" : "FAIL");
  await go("/monitor/alerts");
  const rt = page.getByRole("tab", { name: "Alert rules" }); await rt.waitFor({ timeout: 15000 }); await rt.click(); await sleep(1500);
  rec("API->UI: metric alert rule created over ARM is listed under Alert rules", (await shows(new RegExp(ru))) ? "PASS" : "FAIL");
  { const t = await body(); rec("API->UI: the rule row shows its signal type, severity and status", /Metric/.test(t) && /Warning|2/.test(t) && /Enabled/.test(t) ? "PASS" : "FAIL"); }
  try {
    const row = page.getByRole("row", { name: new RegExp(ru) }).first(); await row.waitFor({ timeout: 15000 });
    for (let i = 0; i < 6; i++) { const cb = row.getByRole("checkbox"); await row.evaluate((el) => el.scrollIntoView({ block: "center" })); await cb.click({ force: true }).catch(() => {}); if (await cb.isChecked().catch(() => false)) break; await sleep(700); }
    await click(/^Delete$/); const dlg = page.getByRole("dialog").last();
    const conf = dlg.getByLabel("Confirm deletion"); if (await conf.count()) await conf.fill(ru);
    await dlg.getByRole("button", { name: /^Delete$/ }).dispatchEvent("click");
    const ok = await poll(async () => (await arm("GET", `${P}/microsoft.insights/metricAlerts/${ru}${v("2018-03-01")}`)).status === 404, 20000);
    rec("UI->API: Delete the alert rule in the console removes it from ARM", ok ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Delete alert rule", "FAIL", String(e.message).split("\n")[0]); }
  for (const [h, re, what] of [["/monitor/metrics", /Metric|Scope/, "Metrics"], ["/monitor/logs", /Query|KQL|Logs/, "Logs"]]) {
    await go(h); const t = await body();
    rec(`${what} blade opens as a real page (no Not-simulated panel)`, re.test(t) && !/isn't backed by a Vyomi backend|Not simulated/i.test(t) ? "PASS" : "FAIL", t.slice(0, 120));
  }
  await arm("DELETE", `${P}/microsoft.insights/actionGroups/${ag}${v("2023-01-01")}`);
} };
