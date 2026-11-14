// Service Bus: create queue (UI), API queue in UI, send/peek message via data plane, delete queue + namespace.
export default { id: "servicebus", title: "Service Bus", fn: async ({ shows, uiRowDelete, arm, v, go, body, click, tab, poll, uiDelete, page, RG, P, sleep, rec }) => {
  const ns = "actsb1", np = `${P}/Microsoft.ServiceBus/namespaces/${ns}`, blade = `/servicebus/${RG}/${ns}`, V = v("2022-10-01-preview");
  rec("API create namespace", (await arm("PUT", np + V, { location: "eastus", sku: { name: "Standard", tier: "Standard" } })).status < 300 ? "PASS" : "FAIL");
  await arm("PUT", `${np}/queues/apiq${V}`, { properties: {} });
  await go(blade); await tab("Queues"); rec("API->UI: queue created over ARM is listed", (await shows(/apiq/)) ? "PASS" : "FAIL");
  try {
    await click(/^Queue$/); await sleep(800);
    await page.getByLabel("Name", { exact: true }).last().fill("uiq"); await click(/^Create$/);
    const ok = await poll(async () => (await arm("GET", `${np}/queues/uiq${V}`)).status === 200, 20000);
    rec("UI->API: Create queue in the console exists in ARM", ok ? "PASS" : "FAIL", ((await body()).match(/Failed to create queue.{0,160}/) || [""])[0]);
  } catch (e) { rec("UI->API: Create queue", "FAIL", String(e.message).split("\n")[0]); }
  // data plane: the console-created queue (provisions the data-plane entity) takes a message; an ARM-only queue is checked separately
  await sleep(3000);   // the console PUTs the ARM queue, then the data-plane entity
  const SH = { "x-vyomi-namespace": ns, "content-type": "text/plain", brokerproperties: "{}" };
  const snd = await arm("POST", `/uiq/messages`, "hello-sb", "text/plain", SH);
  const pk = await arm("GET", `/uiq/messages`, null, null, SH);
  rec("data plane: message sent to the console-created queue is peeked back", snd.status < 300 && /hello-sb/.test(pk.text) ? "PASS" : "FAIL", `${snd.status} ${pk.text.slice(0, 80)}`);
  const snd2 = await arm("POST", `/apiq/messages`, "hello-arm", "text/plain", SH);
  rec("ARM->data plane: a queue created over ARM accepts a data-plane send (real Service Bus does)", snd2.status < 300 ? "PASS" : "FAIL", `${snd2.status} ${snd2.text.slice(0, 80)}`);
  await arm("DELETE", `${np}/queues/apiq${V}`);
  await go(blade); await tab("Queues"); rec("API->UI: queue deleted over ARM disappears", !/apiq/.test(await body()) ? "PASS" : "FAIL");
  try {
    await go(blade); await tab("Queues"); await uiRowDelete("uiq");
    rec("UI->API: Delete queue in the console removes it from ARM", (await poll(async () => (await arm("GET", `${np}/queues/uiq${V}`)).status === 404, 20000)) ? "PASS" : "FAIL");
  } catch (e) { rec("UI->API: Delete queue", "FAIL", String(e.message).split("\n")[0]); }
  await uiDelete(ns, blade);
  rec("UI->API: Delete namespace removes it from ARM", (await poll(async () => (await arm("GET", np + V)).status === 404, 25000)) ? "PASS" : "FAIL");
} };
