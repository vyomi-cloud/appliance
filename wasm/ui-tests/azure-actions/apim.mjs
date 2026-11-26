// API Management: Monitoring > Application Insights lists the service's own loggers (API->UI), a logger added in the tab
// is stored over ARM (UI->API), survives a reload, and the type-to-confirm service Delete removes it.
export default { id: "apim", title: "API Management", fn: async ({ shows, arm, v, go, body, click, tab, poll, uiDelete, page, RG, P, sleep, rec }) => {
  const n = `actapim${Date.now() % 100000}`, sp = `${P}/Microsoft.ApiManagement/service/${n}`, blade = `/apim/${RG}/${n}`, V = v("2022-08-01");
  const mk = await arm("PUT", sp + V, { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.co", publisherName: "act" } });
  rec("API create API Management service", mk.status < 300 ? "PASS" : "FAIL", `${mk.status} ${mk.text.slice(0, 100)}`);
  if (mk.status >= 300) return;
  const lg = (x) => arm("GET", `${sp}/loggers/${x}${V}`);
  await arm("PUT", `${sp}/loggers/apilogger${V}`, { properties: { loggerType: "applicationInsights", description: "api", credentials: { instrumentationKey: "11111111-1111-1111-1111-111111111111" } } });
  await go(blade); await tab("Application Insights");
  rec("API->UI: logger created over ARM is listed under Monitoring > Application Insights", (await shows(/apilogger/)) ? "PASS" : "FAIL");
  try {
    await click(/^Add$/); await sleep(800);
    await page.getByLabel("Name", { exact: true }).last().fill("uilogger");
    await page.getByRole("dialog").last().getByRole("button", { name: /^Create$/ }).dispatchEvent("click");
    const ok = await poll(async () => (await lg("uilogger")).status === 200, 20000);
    rec("UI->API: Add logger in the console exists in ARM", ok ? "PASS" : "FAIL");
    if (ok) rec("UI->API: logger type is applicationInsights", (await lg("uilogger")).json?.properties?.loggerType === "applicationInsights" ? "PASS" : "FAIL");
    await go(blade); await tab("Application Insights");
    rec("The added logger survives a reload and is listed beside the API-created one", (await shows(/uilogger/)) && /apilogger/.test(await body()) ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Add logger", "FAIL", String(e.message).split("\n")[0]); }
  await arm("DELETE", `${sp}/loggers/apilogger${V}`);
  await go(blade); await tab("Application Insights"); rec("API->UI: logger deleted over ARM disappears", !/apilogger/.test(await body()) ? "PASS" : "FAIL");
  await uiDelete(n, blade, /^Delete$/);
  rec("UI->API: Delete service removes it from ARM", (await poll(async () => (await arm("GET", sp + V)).status === 404, 30000)) ? "PASS" : "FAIL");
} };
