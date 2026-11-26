// Azure AI services (Azure OpenAI account): Model deployments tab lists a deployment created over ARM (API->UI), a deployment
// created in the "Deploy model" dialog is stored over ARM with the chosen name (UI->API), and the account Delete removes it.
export default { id: "cognitiveservices", title: "Azure AI services", fn: async ({ shows, arm, v, go, body, click, tab, poll, uiDelete, page, RG, P, sleep, rec }) => {
  const n = "actcs1", ap = `${P}/Microsoft.CognitiveServices/accounts/${n}`, blade = `/cognitiveservices/${RG}/${n}`, V = v("2024-10-01");
  const mk = await arm("PUT", ap + V, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: n } });
  rec("API create Azure OpenAI account", mk.status < 300 ? "PASS" : "FAIL", `${mk.status} ${mk.text.slice(0, 100)}`);
  if (mk.status >= 300) return;
  const dep = (x) => arm("GET", `${ap}/deployments/${x}${V}`);
  const d1 = await arm("PUT", `${ap}/deployments/apidep${V}`, { sku: { name: "Standard", capacity: 10 }, properties: { model: { format: "OpenAI", name: "gpt-4o", version: "2024-11-20" } } });
  rec("API create a model deployment", d1.status < 300 ? "PASS" : "FAIL", `${d1.status} ${d1.text.slice(0, 100)}`);
  await go(blade); await tab("Model deployments");
  rec("API->UI: deployment created over ARM is listed (name + model)", (await shows(/apidep/)) && /gpt-4o/.test(await body()) ? "PASS" : "FAIL");
  try {
    await click(/Create new deployment/); await sleep(800);
    await page.getByLabel("Select a model").selectOption("gpt-4o");   // the default (a local open model) is not deployable in-browser; an OpenAI-family model is
    await page.getByLabel("Deployment name").fill("uidep");
    await page.getByRole("dialog").last().getByRole("button", { name: /^Deploy$/ }).dispatchEvent("click");
    const ok = await poll(async () => (await dep("uidep")).status === 200, 25000);
    rec("UI->API: Deploy model in the console exists in ARM", ok ? "PASS" : "FAIL", ok ? "" : (await page.locator("[role=alert], [role=status], .fui-MessageBar, [class*=toast]").allInnerTexts()).join(" | ").slice(0, 200) + " :: " + (await body()).slice(-300));
    if (ok) { const m = (await dep("uidep")).json?.properties?.model || {}; rec("UI->API: deployment carries a model name and version", m.name && m.version ? "PASS" : "FAIL", JSON.stringify(m)); }
    await go(blade); await tab("Model deployments");
    rec("The UI-created deployment survives a reload", (await shows(/uidep/)) ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Deploy model", "FAIL", String(e.message).split("\n")[0]); }
  await arm("DELETE", `${ap}/deployments/apidep${V}`);
  await go(blade); await tab("Model deployments"); rec("API->UI: deployment deleted over ARM disappears", !/apidep/.test(await body()) ? "PASS" : "FAIL");
  await uiDelete(n, blade, /^Delete$/);
  rec("UI->API: Delete account removes it from ARM", (await poll(async () => (await arm("GET", ap + V)).status === 404 || (await arm("GET", ap + V)).json?.properties?.provisioningState === "Deleting", 30000)) ? "PASS" : "FAIL");
} };
