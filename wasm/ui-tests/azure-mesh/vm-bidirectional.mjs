/* Azure Virtual Machines UI <-> API/CLI bi-directional E2E on the LIVE Mesh appliance (VMs are Docker containers).
 *   SIM_URL=http://127.0.0.1:19000 MESH_TOKEN=... NANO_DIR=$PWD/wasm node wasm/ui-tests/azure-mesh/vm-bidirectional.mjs
 * The proxy injects X-Vyomi-Session-Token on every request. The token is never printed or written.
 * Optional: SSH_HOST (default host.vyomi) is used read-only (`docker inspect`) to confirm the container behind a VM. */
import { chromium, sleep, NANO_DIR } from "../lib.mjs";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const run = promisify(execFile);

const SIM = (process.env.SIM_URL || "http://127.0.0.1:19000").replace(/\/$/, "");
const TOKEN = process.env.MESH_TOKEN || "";
if (!TOKEN) { console.error("MESH_TOKEN is required"); process.exit(2); }
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const T = `${Date.now() % 1000000}`;
const RG = `bd-rg-${T}`;
const NAMES = { api: `bd-a${T}`, cli: `bd-c${T}`, ui: `bd-u${T}` };
const VMV = "2023-09-01", NETV = "2023-11-01";
const rows = []; let fails = 0;
const rec = (check, status, detail = "") => { rows.push({ check, status, detail }); if (status === "FAIL") fails++; console.log(`[${status}] ${check}${detail ? " :: " + String(detail).slice(0, 220) : ""}`); };
const chk = (check, ok, detail = "") => rec(check, ok ? "PASS" : "FAIL", detail);

const H = { "content-type": "application/json", "X-Vyomi-Session-Token": TOKEN };
const arm = async (method, path, body) => {
  const r = await fetch(SIM + path, { method, headers: H, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(60000) });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* */ }
  return { status: r.status, json: j, text: t };
};
const rgP = (rg) => `/subscriptions/${SUB}/resourcegroups/${rg}?api-version=2021-04-01`;
const vmP = (rg, n) => `/subscriptions/${SUB}/resourceGroups/${rg}/providers/Microsoft.Compute/virtualMachines/${n}`;
const netP = (rg, t, n) => `/subscriptions/${SUB}/resourceGroups/${rg}/providers/Microsoft.Network/${t}/${n}`;
const vmBody = (nicId, name) => ({ location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, storageProfile: { imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts-gen2", version: "latest" }, osDisk: { createOption: "FromImage" } }, osProfile: { computerName: name.slice(0, 15), adminUsername: "bdadmin", adminPassword: "Bd-Passw0rd!x" }, networkProfile: { networkInterfaces: [{ id: nicId }] } } });
const powerOf = async (rg, n) => {
  const r = await arm("GET", `${vmP(rg, n)}/instanceView?api-version=${VMV}`);
  const s = (r.json?.statuses || []).find((x) => /^PowerState\//.test(x.code || ""));
  return s ? s.code.replace("PowerState/", "") : `(none; HTTP ${r.status})`;
};
const waitPower = async (rg, n, want, secs = 120) => { let p; for (let i = 0; i < secs / 3; i++) { p = await powerOf(rg, n); if (p === want) return p; await sleep(3000); } return p; };
const sshHost = process.env.SSH_HOST || "host.vyomi";
const dockerState = async (cname) => {   // read-only: docker inspect of the container behind OUR vm
  try { const o = await run("ssh", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=25", sshHost, `docker inspect -f '{{.State.Status}}' ${cname} 2>/dev/null || echo absent`], { timeout: 45000 }); return o.stdout.trim().split("\n").pop(); } catch { return "ssh-failed"; }
};
const azRest = (method, url, body, extra = []) => run("az", ["rest", "--skip-authorization-header", "--only-show-errors", "--method", method, "--url", SIM + url, "--headers", `X-Vyomi-Session-Token=${TOKEN}`, "Content-Type=application/json", ...(body ? ["--body", JSON.stringify(body)] : []), ...extra], { env: { ...process.env, AZURE_CORE_COLLECT_TELEMETRY: "false" }, timeout: 90000 });

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, "http://x");
    if (/^\/(_wire|api|subscriptions|azure-data)\b/.test(u.pathname)) {
      const chunks = []; for await (const c of req) chunks.push(c);
      const hd = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k)));
      hd["x-vyomi-session-token"] = TOKEN;
      const r = await fetch(SIM + req.url, { method: req.method, headers: hd, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
      res.writeHead(r.status, Object.fromEntries([...r.headers].filter(([k]) => !["content-encoding", "transfer-encoding", "content-length"].includes(k))));
      return res.end(Buffer.from(await r.arrayBuffer()));
    }
    let p = normalize(decodeURIComponent(u.pathname)); if (p === "/") p = "/index.html";
    const f = join(NANO_DIR, p);
    if (!f.startsWith(NANO_DIR) || !existsSync(f)) { res.writeHead(404); return res.end("404"); }
    let body = await readFile(f);
    if (/\/v4\/\w+\/index\.html$/.test(p)) body = Buffer.from(body.toString().replace('content="nano"', 'content="offline"')
      .replace(/<script[^>]*nano-boot\.js[^>]*><\/script>/g, "").replace(/<script[^>]*nano-kernel\.js[^>]*><\/script>/g, "").replace(/<script>window\.__nk[^<]*<\/script>/g, ""));
    res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream", "cache-control": "no-cache" }); res.end(body);
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ serviceWorkers: "block", viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));
const click = (loc) => loc.dispatchEvent("click");
const goto = async (hash) => { await page.goto(`${base}/v4/azure/index.html#/${hash}`, { waitUntil: "domcontentloaded" }); await page.reload({ waitUntil: "domcontentloaded" }); };
const listRow = async (name, tries = 4) => {   // the list row text for `name`, or null
  for (let i = 0; i < tries; i++) {
    await goto("vms");
    await page.waitForFunction(() => /Name|No .* to display|Create/i.test(document.body.innerText), null, { timeout: 30000 }).catch(() => {});
    await sleep(1500);
    const row = page.locator("tr", { hasText: name }).first();
    if (await row.count()) return (await row.innerText()).replace(/\s+/g, " ");
    await sleep(2000);
  }
  return null;
};
const bladeText = async (rg, name) => { await goto(`vms/${rg}/${name}`); await page.getByRole("button", { name: /^Stop/ }).first().waitFor({ timeout: 30000 }).catch(() => {}); await sleep(1500); return (await page.locator("body").innerText()).replace(/\s+/g, " "); };
const fillWizard = async (name, pw, pw2) => {
  await goto("vms/create");
  const nameBox = page.getByLabel("Virtual machine name").first();
  await nameBox.waitFor({ timeout: 30000 });
  await nameBox.fill(name);
  await page.getByRole("radio", { name: "Password" }).first().check({ force: true }).catch(() => click(page.getByRole("radio", { name: "Password" }).first()));
  await page.locator("#vm-pw").waitFor({ timeout: 10000 });
  await page.locator("#vm-pw").fill(pw); await page.locator("#vm-pw2").fill(pw2 ?? pw);
  await page.locator("#vm-size").locator("option", { hasText: "Standard_B1s " }).waitFor({ state: "attached", timeout: 20000 });
  await page.locator("#vm-size").selectOption("Standard_B1s");
  await sleep(400);
};
const findVm = async (name) => ((await arm("GET", `/subscriptions/${SUB}/providers/Microsoft.Compute/virtualMachines?api-version=${VMV}`)).json?.value || []).find((x) => x.name === name);
const created = [];   // [rg, name]

try {
  const h = await (await fetch(SIM + "/healthz", { headers: H })).json().catch(() => ({}));
  chk("setup: Mesh appliance reachable with the session token", h.status === "ok", JSON.stringify(h));
  if (h.status !== "ok") throw new Error("mesh not reachable");
  await arm("POST", "/api/spaces/space-azure-default/switch");
  const g = await arm("PUT", rgP(RG), { location: "eastus" });
  chk("setup: test resource group created over ARM", g.status < 300, `HTTP ${g.status}`);
  const subnetId = netP(RG, "virtualNetworks", "bdvn") + "/subnets/default";
  await arm("PUT", netP(RG, "virtualNetworks", "bdvn") + `?api-version=${NETV}`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.1.0.0/16"] }, subnets: [{ name: "default", properties: { addressPrefix: "10.1.0.0/24" } }] } });
  for (const k of ["api", "cli"]) await arm("PUT", netP(RG, "networkInterfaces", `${NAMES[k]}-nic`) + `?api-version=${NETV}`, { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: subnetId } } }] } });

  // ---------------- (1) UI -> API: wizard
  await fillWizard(NAMES.ui, "Vy0mi-Pass-123!");
  await click(page.getByRole("button", { name: /Review \+ create/ }).first());
  await click(page.getByRole("button", { name: /^Create$/ }).first());
  let uiVm = null;
  for (let i = 0; i < 40 && !uiVm; i++) { uiVm = await findVm(NAMES.ui); if (!uiVm) await sleep(3000); }
  let why = "";
  if (!uiVm) { const bt0 = (await page.locator("body").innerText()).replace(/\s+/g, " "); why = (bt0.match(/(Deployment failed|Allocation|failed|error)[^.]{0,200}/i) || [bt0.slice(-200)])[0]; await page.screenshot({ path: process.env.SHOT_DIR ? process.env.SHOT_DIR + "/vm-wizard-fail.png" : "/dev/null" }).catch(() => {}); }
  chk("UI->API: VM created in the console wizard is returned by ARM", !!uiVm, uiVm ? "" : "not in the VM list after 120s; page says: " + why);
  let uiRg = RG;
  if (uiVm) {
    uiRg = uiVm.id.split("/")[4]; created.push([uiRg, NAMES.ui]);
    const g1 = await arm("GET", `${vmP(uiRg, NAMES.ui)}?api-version=${VMV}`);
    const p = g1.json?.properties || {};
    chk("UI->API: same name, location, size", g1.json?.name === NAMES.ui && g1.json?.location === "eastus" && p.hardwareProfile?.vmSize === "Standard_B1s", JSON.stringify({ n: g1.json?.name, l: g1.json?.location, s: p.hardwareProfile?.vmSize }));
    chk("UI->API: provisioningState Succeeded", p.provisioningState === "Succeeded", p.provisioningState);
    const pw = await waitPower(uiRg, NAMES.ui, "running", 120);
    chk("UI->API: instanceView powerState running within 120s", pw === "running", pw);
    const nic = await arm("GET", `${netP(uiRg, "networkInterfaces", NAMES.ui + "-nic")}?api-version=${NETV}`);
    chk("UI->API: the wizard's NIC exists over ARM", nic.status === 200, `HTTP ${nic.status}`);
    const diskName = p.storageProfile?.osDisk?.name;
    const dk = diskName ? await arm("GET", `/subscriptions/${SUB}/resourceGroups/${uiRg}/providers/Microsoft.Compute/disks/${diskName}?api-version=2023-04-02`) : { status: "no osDisk name" };
    chk("UI->API: the OS disk exists over ARM", dk.status === 200, `HTTP ${dk.status} ${diskName || ""}`);
  }

  // ---------------- (3) lifecycle, UI-created VM: UI actions -> ARM
  if (uiVm) {
    const cname = (await arm("GET", `${vmP(uiRg, NAMES.ui)}?api-version=${VMV}`)).json?.properties?.runtime?.containerName;
    const d0 = cname ? await dockerState(cname) : "no runtime.containerName";
    chk("real compute: the UI-created VM's Docker container is running", d0 === "running", `${cname || ""} -> ${d0}`);
    await bladeText(uiRg, NAMES.ui);
    await click(page.getByRole("button", { name: /^Stop$/ }).first());
    let pw = await waitPower(uiRg, NAMES.ui, "stopped", 30);
    chk("UI Stop -> ARM instanceView powerState stopped", pw === "stopped", pw);
    const d1 = cname ? await dockerState(cname) : "n/a";
    chk("real compute: container is stopped after the UI Stop", d1 !== "running" && d1 !== "ssh-failed", `container ${d1}`);
    rec("UI Deallocate button -> ARM", "NOT-AUTOMATED", "the v4 VM blade toolbar has Start/Restart/Stop only (Stop = powerOff); no Deallocate control exists in the UI");
    await bladeText(uiRg, NAMES.ui);
    await click(page.getByRole("button", { name: /^Start$/ }).first());
    pw = await waitPower(uiRg, NAMES.ui, "running", 60);
    chk("UI Start -> ARM instanceView powerState running", pw === "running", pw);
    const d2 = cname ? await dockerState(cname) : "n/a";
    chk("real compute: container is running again after the UI Start", d2 === "running", `container ${d2}`);
    // ARM actions -> UI
    await arm("POST", `${vmP(uiRg, NAMES.ui)}/powerOff?api-version=${VMV}`);
    let bt = await bladeText(uiRg, NAMES.ui);
    chk("ARM powerOff -> UI blade Status Stopped", /Status\s*Stopped/i.test(bt) && (await powerOf(uiRg, NAMES.ui)) === "stopped", (bt.match(/Status\s*\S+/) || [""])[0]);
    let row = await listRow(NAMES.ui);
    chk("ARM powerOff -> UI list Status Stopped", !!row && /Stopped/i.test(row), row || "not listed");
    await arm("POST", `${vmP(uiRg, NAMES.ui)}/start?api-version=${VMV}`);
    bt = await bladeText(uiRg, NAMES.ui);
    chk("ARM start -> UI blade Status Running", /Status\s*Running/i.test(bt), (bt.match(/Status\s*\S+/) || [""])[0]);
    await arm("POST", `${vmP(uiRg, NAMES.ui)}/deallocate?api-version=${VMV}`);
    pw = await powerOf(uiRg, NAMES.ui);
    row = await listRow(NAMES.ui);
    chk("ARM deallocate -> instanceView deallocated and UI list Status Deallocated", pw === "deallocated" && !!row && /Deallocated/i.test(row), `${pw} | ${row || "not listed"}`);
    const d3 = cname ? await dockerState(cname) : "n/a";
    chk("real compute: container is not running after deallocate", d3 !== "running" && d3 !== "ssh-failed", `container ${d3}`);
    await arm("POST", `${vmP(uiRg, NAMES.ui)}/start?api-version=${VMV}`); await waitPower(uiRg, NAMES.ui, "running", 60);
    // (4) run command
    const rc = await arm("POST", `${vmP(uiRg, NAMES.ui)}/runCommand?api-version=${VMV}`, { commandId: "RunShellScript", script: ["echo hello"] });
    const msg = (rc.json?.value || []).map((v) => v.message).join("\n");
    chk("real compute: runCommand `echo hello` returns hello from the guest", rc.status < 300 && /^hello\s*$/m.test(msg) && !/metadata-only|not reachable/i.test(msg), `HTTP ${rc.status} ${msg.slice(0, 160)}`);
    // UI delete -> ARM 404
    await bladeText(uiRg, NAMES.ui);
    await click(page.getByRole("button", { name: /^Delete$/ }).first());
    await page.getByLabel("Confirm deletion").fill(NAMES.ui);
    await click(page.getByRole("dialog").getByRole("button", { name: /^Delete$/ }));
    let st = 0; for (let i = 0; i < 20; i++) { st = (await arm("GET", `${vmP(uiRg, NAMES.ui)}?api-version=${VMV}`)).status; if (st === 404) break; await sleep(2000); }
    chk("UI delete -> ARM GET 404", st === 404, `HTTP ${st}`);
    const d4 = cname ? await dockerState(cname) : "n/a";
    chk("real compute: container removed after the UI delete", d4 === "absent", `container ${d4}`);
    if (st === 404) created.splice(created.findIndex((c) => c[1] === NAMES.ui), 1);
  }

  // (the Mesh admits only ~1 running B1s VM at a time: AllocationFailed otherwise, so the ARM/CLI VMs are created after the UI VM is deleted)
  // ---------------- (2) API -> UI (ARM PUT + az rest)
  const put = await arm("PUT", `${vmP(RG, NAMES.api)}?api-version=${VMV}`, vmBody(netP(RG, "networkInterfaces", `${NAMES.api}-nic`), NAMES.api));
  chk("API: VM PUT over ARM accepted", put.status < 300, `HTTP ${put.status} ${put.status >= 300 ? put.text.slice(0, 120) : ""}`);
  if (put.status < 300) created.push([RG, NAMES.api]);
  await waitPower(RG, NAMES.api, "running", 120);
  const rowA = await listRow(NAMES.api);
  chk("API->UI: console list shows the ARM-created VM with same name/size/location/status", !!rowA && /Standard_B1s/.test(rowA) && /East US/i.test(rowA) && /Running/i.test(rowA), rowA || "not listed");
  // ---------------- lifecycle, API VM: ARM actions -> UI, ARM delete -> UI gone
  await arm("POST", `${vmP(RG, NAMES.api)}/powerOff?api-version=${VMV}`);
  const rb = await listRow(NAMES.api);
  chk("ARM powerOff (API VM) -> UI list Status Stopped", !!rb && /Stopped/i.test(rb), rb || "not listed");
  await arm("POST", `${vmP(RG, NAMES.api)}/start?api-version=${VMV}`);
  const rc2 = await listRow(NAMES.api);
  chk("ARM start (API VM) -> UI list Status Running", !!rc2 && /Running/i.test(rc2), rc2 || "not listed");
  const dl = await arm("DELETE", `${vmP(RG, NAMES.api)}?api-version=${VMV}`);
  await sleep(2000);
  const gone = await listRow(NAMES.api, 2);
  chk("ARM delete -> UI list no longer shows the VM", dl.status < 300 && gone === null, `DELETE ${dl.status}`);
  if (dl.status < 300) created.splice(created.findIndex((c) => c[1] === NAMES.api), 1);

  // free the capacity slot of the API VM before the CLI VM is created
  try {
    await azRest("put", `${vmP(RG, NAMES.cli)}?api-version=${VMV}`, vmBody(netP(RG, "networkInterfaces", `${NAMES.cli}-nic`), NAMES.cli));
    created.push([RG, NAMES.cli]);
    await waitPower(RG, NAMES.cli, "running", 120);
    const rowC = await listRow(NAMES.cli);
    chk("CLI->UI: `az rest` VM shows in the console list with same name/size/location/status", !!rowC && /Standard_B1s/.test(rowC) && /East US/i.test(rowC) && /Running/i.test(rowC), rowC || "not listed");
  } catch (e) { rec("CLI->UI: `az rest` VM PUT", "FAIL", String(e.stderr || e.message).replace(TOKEN, "***").slice(0, 200)); }

  await arm("DELETE", `${vmP(RG, NAMES.cli)}?api-version=${VMV}`); created.splice(Math.max(0, created.findIndex((c) => c[1] === NAMES.cli)), 1);
  // ---------------- (5) form validation
  await fillWizard("bad_name!", "Vy0mi-Pass-123!");
  await click(page.getByRole("button", { name: /Review \+ create/ }).first());
  await sleep(1500);
  let bodyT = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  chk("validation: invalid VM name is refused with a meaningful message", /1-15 characters|start and end with a letter or number/i.test(bodyT) && !(await findVm("bad_name!")), (bodyT.match(/Virtual machine name must[^.]*\./) || ["no message shown"])[0]);
  chk("validation: no raw error text (undefined/[object Object]/stack) on invalid name", !/\[object Object\]|undefined|Traceback|TypeError/.test(bodyT), "");
  await fillWizard(`bd-p${T}`, "short1", "different");
  await click(page.getByRole("button", { name: /Review \+ create/ }).first());
  await sleep(1500);
  bodyT = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  chk("validation: mismatched password refused with a meaningful message", /Password and confirm password must match/i.test(bodyT), (bodyT.match(/Password[^.]*match[^.]*\./) || ["no message shown"])[0]);
  // short but matching password: UI check, then ARM check
  await fillWizard(`bd-s${T}`, "abc");
  await click(page.getByRole("button", { name: /Review \+ create/ }).first());
  await sleep(1000);
  await click(page.getByRole("button", { name: /^Create$/ }).first()).catch(() => {});
  await sleep(6000);
  bodyT = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  const shortVm = await findVm(`bd-s${T}`);
  if (shortVm) created.push([shortVm.id.split("/")[4], shortVm.name]);
  chk("validation: a 3-char password is refused (UI message, VM not created)", !shortVm && /password[^.]{0,60}(characters|length|complex|at least|too short)|(characters|at least)[^.]{0,40}password/i.test(bodyT) && !/\[object Object\]|Traceback/.test(bodyT), shortVm ? "VM WAS CREATED with a 3-char password (no length validation)" : "VM not created but no length message shown on the page");
  const shortApi = await arm("PUT", `${vmP(RG, "bd-short" + T)}?api-version=${VMV}`, { ...vmBody(netP(RG, "networkInterfaces", `${NAMES.api}-nic`), "bd-short"), properties: { ...vmBody("x", "x").properties, osProfile: { computerName: "bdshort", adminUsername: "bdadmin", adminPassword: "abc" }, networkProfile: { networkInterfaces: [{ id: netP(RG, "networkInterfaces", `${NAMES.api}-nic`) }] } } });
  chk("validation: ARM PUT with a 3-char password gives a clear 4xx error (not 5xx/raw)", shortApi.status >= 400 && shortApi.status < 500 && !!shortApi.json?.error?.message, `HTTP ${shortApi.status} ${shortApi.text.slice(0, 140)}`);
  if (shortApi.status < 300) created.push([RG, "bd-short" + T]);
} catch (e) {
  rec("harness ran to completion", "FAIL", String(e.message).split("\n")[0]);
}
// ---------------- cleanup (only what this run created)
for (const [rg, n] of created) await arm("DELETE", `${vmP(rg, n)}?api-version=${VMV}`).catch(() => {});
await sleep(3000);
const dg = await arm("DELETE", rgP(RG)); rec("cleanup: test resource group deleted", dg.status < 300 ? "PASS" : "FAIL", `HTTP ${dg.status}`);
rec("no uncaught page errors", pageErrors.length ? "NOTE" : "PASS", pageErrors.slice(0, 3).join(" | "));

const outDir = new URL("../../../tests/conformance/hourly/out/", import.meta.url).pathname;
mkdirSync(outDir, { recursive: true });
let md = "# Azure Virtual Machines UI <-> API bi-directional (Mesh)\n\n| Check | Result | Detail |\n|---|---|---|\n";
for (const r of rows) md += `| ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 160)} |\n`;
const n = (s) => rows.filter((r) => r.status === s).length;
md += `\n**${n("PASS")} pass, ${n("FAIL")} fail, ${n("NOT-AUTOMATED")} not automated.**\n`;
writeFileSync(outDir + "azure-mesh-vm-bidirectional.md", md);
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
