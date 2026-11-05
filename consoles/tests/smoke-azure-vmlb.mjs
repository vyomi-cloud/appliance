/* Smoke: VM "Load balancing" blade is a real page over Microsoft.Network/loadBalancers (no Not-simulated panel), a VM can join/leave a pool,
 * and a Cosmos RU/s offer set in the Scale blade throttles the data plane with 429.
 *   BASE=http://127.0.0.1:9074 node consoles/tests/smoke-azure-vmlb.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9074";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `lb-rg-${n}`, VM = `vm${n}`, ACC = `ru${n}`;
let fails = 0, pg;
const check = (name, ok, d = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + d : ""}`); };
const call = (m, url, body, headers = {}) => pg.evaluate(async ([m, url, body, headers]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json", ...headers }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); let j = null; try { j = t ? JSON.parse(t) : null; } catch {} return { status: r.status, body: j };
}, [m, url, body, headers]);
const arm = (m, path, body, v = "2023-11-01") => call(m, `${WIRE}/subscriptions/${SUB}${path}?api-version=${v}`, body);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
const N = `/resourceGroups/${RG}/providers/Microsoft.Network`;
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `${N}/virtualNetworks/v1`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] }, subnets: [{ name: "s1", properties: { addressPrefix: "10.0.1.0/24" } }] } });
await arm("PUT", `${N}/networkInterfaces/${VM}-nic`, { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: `/subscriptions/${SUB}${N}/virtualNetworks/v1/subnets/s1` } } }] } });
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM}`, { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, networkProfile: { networkInterfaces: [{ id: `/subscriptions/${SUB}${N}/networkInterfaces/${VM}-nic` }] } } }, "2023-09-01");
await pg.goto(`${UI}#/vms/${RG}/${VM}/loadbalancing`); await pg.waitForTimeout(1500);
check("blade is a real page (no Not-simulated)", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
check("empty state before any load balancer", (await pg.getByTestId("lb-empty").count()) === 1);
await pg.getByLabel("Load balancer name").fill("lb1"); await pg.getByRole("button", { name: "Create load balancer" }).click(); await pg.waitForTimeout(1500);
const lb = await arm("GET", `${N}/loadBalancers/lb1`);
check("load balancer created over ARM with derived ids", lb.status === 200 && lb.body.properties.backendAddressPools[0].id.endsWith("/backendAddressPools/backend"), JSON.stringify(lb.body).slice(0, 200));
await pg.getByLabel("Member of lb1/backend").click(); await pg.waitForTimeout(1500);
const lb2 = await arm("GET", `${N}/loadBalancers/lb1`);
check("joining the pool lists the NIC as a backend ip configuration", (lb2.body?.properties?.backendAddressPools?.[0]?.properties?.backendIPConfigurations || []).length === 1);
check("state text is honest (probe not executed)", /probe not executed/.test(await pg.getByTestId("lb-state").first().innerText()));
const del = await arm("DELETE", `${N}/loadBalancers/lb1`);
check("LB with members cannot be deleted", del.status === 400);
// Standalone disk -> attach existing
await pg.goto(`${UI}#/vms/${RG}/${VM}/disks`); await pg.waitForTimeout(1500);
await pg.getByRole("button", { name: "Attach existing disks" }).click().catch(async () => { await pg.getByText("Attach existing disks").first().click(); });
await pg.waitForTimeout(800);
check("attach-existing dialog is real (no Not-simulated)", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0 && (await pg.getByTestId("no-free-disks").count()) === 1);
await pg.getByLabel("New disk name").fill("data1"); await pg.getByLabel("Create standalone disk").click(); await pg.waitForTimeout(1200);
await pg.getByLabel("Attach data1").click(); await pg.waitForTimeout(1500);
const dk = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Compute/disks/data1`, null, "2023-04-02");
check("disk is Attached to the VM", dk.body?.properties?.diskState === "Attached" && /virtualmachines/i.test(dk.body?.managedBy || ""), JSON.stringify(dk.body).slice(0, 160));
check("attached disk cannot be deleted", (await arm("DELETE", `/resourceGroups/${RG}/providers/Microsoft.Compute/disks/data1`, null, "2023-04-02")).status === 409);
// Cosmos RU/s offer -> 429
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${ACC}`, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "East US", failoverPriority: 0 }] } }, "2024-05-15");
const dp = (m, path, body) => call(m, `${WIRE}${path}`, body, { "x-ms-version": "2018-12-31", "x-ms-documentdb-partitionkey": '["a"]', "x-vyomi-account": ACC });
await dp("POST", "/dbs", { id: "d1" }); await dp("POST", "/dbs/d1/colls", { id: "c1", partitionKey: { paths: ["/pk"], kind: "Hash" } });
await pg.goto(`${UI}#/cosmos/${RG}/${ACC}/scale`); await pg.waitForTimeout(1500);
check("offer editor present", (await pg.getByTestId("offer-editor").count()) === 1);
await pg.getByLabel("Scope").selectOption("d1/c1"); await pg.getByLabel("RU/s").fill("400"); await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(1200);
check("offer saved and shown", /Manual, 400 RU\/s/.test(await pg.getByTestId("offer-current").innerText()));
let codes = [];
// ~40 KB documents (~200 RU each) so a 400 RU/s offer is exceeded within the window even when the
// substrate (Nano, Pyodide) is slow: the RU window is wall-clock, a fast burst of tiny writes proves nothing there.
const pad = "x".repeat(40 * 1024);
for (let i = 0; i < 30; i++) codes.push((await dp("POST", "/dbs/d1/colls/c1/docs", { id: "x" + i, pk: "a", pad })).status);
check("data plane throttled with 429 beyond the offer", codes.includes(429) && codes[0] === 201, codes.slice(0, 5).join(","));
console.log(fails ? `${fails} FAILED` : "all passed"); await b.close(); process.exit(fails ? 1 : 0);
