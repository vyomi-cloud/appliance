// DNS zone: add A record set (UI), API record shows in UI, delete, zone delete.
export default { id: "dns", title: "DNS zones", fn: async ({ shows, uiRowDelete, arm, v, go, body, click, poll, uiDelete, page, RG, P, sleep, rec }) => {
  const z = "act1.example.com", zp = `${P}/Microsoft.Network/dnsZones/${z}`, blade = `/dns/${RG}/${z}`, V = v("2018-05-01");
  rec("API create zone", (await arm("PUT", zp + V, { location: "global", properties: {} })).status < 300 ? "PASS" : "FAIL");
  await arm("PUT", `${zp}/A/apirec${V}`, { properties: { TTL: 300, ARecords: [{ ipv4Address: "10.1.2.3" }] } });
  await go(blade); rec("API->UI: A record created over ARM is listed on the zone Overview", (await shows(/apirec/)) && /10\.1\.2\.3/.test(await body()) ? "PASS" : "FAIL");
  try {
    await click(/Record set/); await sleep(800);
    await page.getByLabel("Name", { exact: true }).last().fill("uirec");
    const ip = page.getByLabel(/IP address/i).last(); if (await ip.count()) await ip.fill("10.9.8.7");
    await click(/^OK$/);
    const ok = await poll(async () => (await arm("GET", `${zp}/A/uirec${V}`)).status === 200, 20000);
    const g = (await arm("GET", `${zp}/A/uirec${V}`)).json?.properties || {};
    rec("UI->API: Add record set in the console exists in ARM", ok ? "PASS" : "FAIL");
    if (ok) rec("UI->API: record data (IP 10.9.8.7) matches", g.ARecords?.[0]?.ipv4Address === "10.9.8.7" ? "PASS" : "FAIL", JSON.stringify(g.ARecords));
  } catch (e) { rec("UI->API: Add record set", "FAIL", String(e.message).split("\n")[0]); }
  await arm("DELETE", `${zp}/A/apirec${V}`);
  await go(blade); rec("API->UI: record deleted over ARM disappears", !/apirec/.test(await body()) ? "PASS" : "FAIL");
  await uiDelete(z, blade);
  rec("UI->API: Delete zone removes it from ARM", (await poll(async () => (await arm("GET", zp + V)).status === 404, 25000)) ? "PASS" : "FAIL");
} };
