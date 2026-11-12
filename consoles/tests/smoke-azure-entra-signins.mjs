/* Entra sign-in logs: interactive (authorization-code), managed identity (IMDS token via VM Run command),
 * Columns and Troubleshoot over the native wire.
 *   PW=... BASE=http://127.0.0.1:9122 node consoles/tests/smoke-azure-entra-signins.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9122";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `si-rg${n}`, VM = `si-vm${n}`, UPN = `si${n}@vyomilearn.onmicrosoft.com`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: "domcontentloaded" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
await wire("/v1.0/users", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ displayName: "SI User", userPrincipalName: UPN, passwordProfile: { password: "S3cret!pass" } }) });
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
const vm = `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM}`;
await arm("PUT", vm, { location: "eastus", identity: { type: "SystemAssigned" }, properties: { hardwareProfile: { vmSize: "Standard_B1s" } } }, "2023-09-01");
const rc = await arm("POST", `${vm}/runCommand`, { commandId: "RunShellScript", script: ["curl -H Metadata:true \"http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/\""] }, "2023-09-01");
check("run command minted an IMDS token", rc.text.includes("access_token"), rc.text);

await page.goto(UI + "#/entra/signinlogs");
await page.getByRole("tab", { name: "Managed identity sign-ins" }).click();
await page.getByRole("cell", { name: VM, exact: true }).first().waitFor({ timeout: 15000 });
check("managed identity row shows the VM", true);

await page.getByRole("tab", { name: "User sign-ins (interactive)" }).click();
await page.getByLabel("Test sign-in user").fill(UPN);
await page.getByLabel("Test sign-in password").fill("wrong");
await page.getByRole("button", { name: "Test interactive sign-in" }).click();
await page.getByText(/Sign-in failed/).waitFor({ timeout: 10000 });
await page.getByLabel("Test sign-in password").fill("S3cret!pass");
await page.getByRole("button", { name: "Test interactive sign-in" }).click();
await page.getByText(/Sign-in succeeded/).waitFor({ timeout: 10000 });
check("interactive tab lists a Success and a Failure row", await page.getByRole("cell", { name: "Success", exact: true }).count() >= 1 && await page.getByRole("cell", { name: "Failure", exact: true }).count() >= 1);

await page.getByRole("button", { name: "Troubleshoot" }).click();
check("Troubleshoot explains AADSTS50126", await page.getByText(/AADSTS50126/).count() > 0);
await page.getByRole("button", { name: "Columns" }).click();
await page.getByLabel("IP address").uncheck();
check("Columns hides the IP address column", await page.getByRole("columnheader", { name: "IP address" }).count() === 0);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
