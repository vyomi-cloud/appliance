// App Service web app + Function app: Stop/Start/Restart in the blade, ARM state both ways, delete.
const mkSection = (id, title, route, kind, extra) => ({ id, title, fn: async ({ arm, v, go, body, click, poll, shows, uiDelete, page, RG, P, sleep, rec }) => {
  const V = v("2022-09-01"), pl = `act${id}pl`, name = `act${id}1`, sp = `${P}/Microsoft.Web/sites/${name}`, blade = `/${route}/${RG}/${name}`;
  await arm("PUT", `${P}/Microsoft.Web/serverfarms/${pl}${V}`, { location: "eastus", sku: kind === "app" ? { name: "B1" } : { name: "Y1", tier: "Dynamic" } });
  const mk = await arm("PUT", sp + V, { location: "eastus", kind, properties: { serverFarmId: `${P}/Microsoft.Web/serverfarms/${pl}` } });
  rec("API create", mk.status < 300 ? "PASS" : "FAIL", mk.status);
  const state = async () => (await arm("GET", sp + V)).json?.properties?.state;
  await go(blade);
  await click(/^Stop$/); await sleep(800); const dlg = page.getByRole("dialog"); if (await dlg.count()) await dlg.last().getByRole("button", { name: /^(Yes|Stop|OK)$/ }).first().dispatchEvent("click").catch(() => {});
  rec("UI->API: Stop button stops the app (ARM properties.state)", (await poll(async () => /stopped/i.test(await state()), 20000)) ? "PASS" : "FAIL", await state());
  await click(/^Start$/);
  rec("UI->API: Start button starts the stopped app", (await poll(async () => /running/i.test(await state()), 20000)) ? "PASS" : "FAIL", await state());
  const r0 = (await arm("GET", sp + V)).json;
  await click(/^Restart$/); await sleep(800); if (await page.getByRole("dialog").count()) await page.getByRole("dialog").last().getByRole("button", { name: /^(Yes|Restart|OK)$/ }).first().dispatchEvent("click").catch(() => {});
  await sleep(3000);
  rec("UI->API: Restart button leaves the app running", /running/i.test(await state()) ? "PASS" : "FAIL", await state());
  await arm("POST", `${sp}/stop${V}`);
  await go(blade); rec("API->UI: stop over ARM flips the toolbar to Start", (await shows(/Start/)) && !(await page.getByRole("button", { name: /^Stop$/ }).count()) ? "PASS" : "FAIL");
  await arm("POST", `${sp}/start${V}`);
  await go(blade); rec("API->UI: start over ARM flips the toolbar back to Stop", (await poll(async () => (await page.getByRole("button", { name: /^Stop$/ }).count()) || null, 15000)) ? "PASS" : "FAIL");
  if (extra) await extra({ arm, v, go, body, click, poll, shows, page, RG, P, sleep, rec, sp, V, blade });
  await uiDelete(name, blade);
  rec("UI->API: Delete (type-to-confirm) removes it from ARM", (await poll(async () => (await arm("GET", sp + V)).status === 404, 25000)) ? "PASS" : "FAIL");
} });
export default [mkSection("appservices", "App Service web apps", "appservices", "app"), mkSection("functionapp", "Function apps", "functionapp", "functionapp")];
