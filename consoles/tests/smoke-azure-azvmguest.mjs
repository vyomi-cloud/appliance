/* VM Boot diagnostics, Serial console and Bastion pages. The appliance-only /api/azure/vm/* host routes are mocked with page.route
 * (hermetic); the ARM retrieveBootDiagnosticsData + Bastion discovery run for real against the dev server.
 *   PW=... BASE=http://127.0.0.1:9082 node consoles/tests/smoke-azure-azvmguest.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9082";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vg-rg${n}`, VM = `gvm${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: "networkidle" });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2023-09-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
const NET = `/resourceGroups/${RG}/providers/Microsoft.Network`;
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `${NET}/virtualNetworks/v1`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] }, subnets: [{ name: "default", properties: { addressPrefix: "10.0.0.0/24" } }, { name: "AzureBastionSubnet", properties: { addressPrefix: "10.0.1.0/26" } }] } });
await arm("PUT", `${NET}/networkInterfaces/nic1`, { location: "eastus", properties: { ipConfigurations: [{ name: "ipc", properties: { subnet: { id: `/subscriptions/${SUB}${NET}/virtualNetworks/v1/subnets/default` } } }] } });
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM}`, { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, osProfile: { adminUsername: "azureuser" }, networkProfile: { networkInterfaces: [{ id: `/subscriptions/${SUB}${NET}/networkInterfaces/nic1` }] } } });

// mock the appliance-only routes
await page.route("**/api/azure/vm/*/serial-console", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, log: "[    0.000000] Linux version 6.1.0 (mock guest)\n[    0.9] systemd[1]: Started sshd", exec: `/api/console/azurevm/instances/${VM}/exec`, note: "Serial console is a docker-exec shell on the guest (line-at-a-time), not a UART." }) }));
await page.route("**/api/console/azurevm/instances/*/exec", async (r) => { const b = JSON.parse(r.request().postData() || "{}"); await r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ output: `ran: ${b.command}\n`, exit_code: 0, cwd: "/home/azureuser" }) }); });
await page.route("**/api/azure/vm/*/bastion/connect", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, session_id: "bastion-abc123", exec: `/api/console/azurevm/instances/${VM}/exec`, ssh_command: "ssh azureuser@10.0.0.4" }) }));

// Boot diagnostics: off -> warning, on -> real ARM blobs
await page.goto(UI + `#/vms/${RG}/${VM}/bootdiagnostics`);
await page.getByText("Boot diagnostics is disabled").waitFor({ timeout: 20000 });
check("disabled state is explained, no Not-simulated panel", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
await arm("PATCH", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM}`, { properties: { diagnosticsProfile: { bootDiagnostics: { enabled: true } } } });
await page.reload();
await page.getByText("Placeholder image").waitFor({ timeout: 20000 });
await page.waitForFunction(() => document.querySelector("[data-testid=serial-log]")?.textContent.includes("mock guest"), null, { timeout: 10000 });
check("serial log shows the guest dmesg and the screenshot is labelled a placeholder", true);

// Serial console
await page.goto(UI + `#/vms/${RG}/${VM}/serialconsole`);
const input = page.getByRole("textbox", { name: "Terminal command" });
await input.waitFor({ timeout: 20000 });
await input.fill("uname -a");
await input.press("Enter");
await page.waitForFunction(() => document.querySelector("[data-testid=vm-terminal]")?.textContent.includes("ran: uname -a"), null, { timeout: 8000 });
check("serial console runs a command through the exec route", true);

// Bastion: no host -> explained; deploy -> connect
await page.goto(UI + `#/vms/${RG}/${VM}/bastion`);
await page.getByText("No Bastion host in this virtual network").waitFor({ timeout: 20000 });
check("without a Bastion host the page says so", true);
await arm("PUT", `${NET}/publicIPAddresses/bpip`, { location: "eastus", sku: { name: "Standard" }, properties: { publicIPAllocationMethod: "Static" } });
await arm("PUT", `${NET}/bastionHosts/bst1`, { location: "eastus", sku: { name: "Standard" }, properties: { ipConfigurations: [{ name: "ip", properties: { subnet: { id: `/subscriptions/${SUB}${NET}/virtualNetworks/v1/subnets/AzureBastionSubnet` }, publicIPAddress: { id: `/subscriptions/${SUB}${NET}/publicIPAddresses/bpip` } } }] } });
await page.reload();
await page.getByText("Bastion host bst1").waitFor({ timeout: 20000 });
await page.getByRole("textbox", { name: "Password" }).fill("secret");
await page.locator("button.fui-Button", { hasText: /^Connect$/ }).click();
await page.getByText("Session bastion-abc123").waitFor({ timeout: 8000 });
await page.getByRole("textbox", { name: "Terminal command" }).fill("whoami");
await page.getByRole("textbox", { name: "Terminal command" }).press("Enter");
await page.waitForFunction(() => document.querySelector("[data-testid=vm-terminal]")?.textContent.includes("ran: whoami"), null, { timeout: 8000 });
check("Bastion connect opens a session and a shell", true);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
