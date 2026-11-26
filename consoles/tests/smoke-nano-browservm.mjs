/* Nano in-browser VM life cycle in the v4 consoles (AWS EC2 / Azure VMs / GCP Compute Engine).
 *   cd consoles && node nano_preview.mjs --port 8783   (wait ~40 s)
 *   CLOUD=aws UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire NANO=1 SUBSTRATE=nano BASE=http://127.0.0.1:8783 node tests/smoke-nano-browservm.mjs
 * Flow: flag off -> honest "Turn on in-browser VMs" panel -> click (no page reload) -> launch -> pending (pulse hook) -> running ->
 * shell types `echo hi`. BOOT=0 stops after the boot request (when a real v86 boot is not feasible on this machine). */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const CLOUD = process.env.CLOUD || "aws";
const BASE = process.env.BASE || "http://127.0.0.1:8783";
const UI = `${BASE}${process.env.UI_PATH || `/nano/v4/${CLOUD}/`}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/nano/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const BOOT = process.env.BOOT !== "0";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1300 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const ready = () => page.waitForFunction(() => window.__vyomiNanoReady === true, null, { timeout: 180000 });

// ── cloud adapters: start page, create the VM through the wire, open its detail ──
const A = {
  aws: {
    home: "#/ec2",
    async create(img) {
      const ec2 = (action, params) => page.evaluate(async ([u, a, p]) => (await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2016-11-15", ...p }).toString() })).text(), [WIRE, action, params]);
      const ami = (img && img.id) || (await this.runnable())[0].id;
      return (await ec2("RunInstances", { ImageId: ami, MinCount: "1", MaxCount: "1", InstanceType: "t3.micro" })).match(/<instanceId>(i-\w+)<\/instanceId>/)[1];
    },
    // every image the core flags runnable (DescribeImages vyomiRunnable=true): each one must boot and pass the toolchain check below
    async runnable() {
      const x = await page.evaluate(async (u) => (await (await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: "Action=DescribeImages&Version=2016-11-15" })).text()), WIRE);
      return [...x.matchAll(/<item><imageId>(ami-\w+)<\/imageId>.*?<name>([^<]*)<\/name>.*?<vyomiRunnable>(true|false)<\/vyomiRunnable>/gs)].filter((m) => m[3] === "true").map((m) => ({ id: m[1], name: m[2] }));
    },
    detail: (id) => `#/ec2/instances/${id}`,
    connect: (id) => `#/ec2/instances/${id}`,
    list: "#/ec2/instances",
    openShell: async (page) => { await page.getByTestId("open-shell").click(); },
    pending: (page) => page.locator('[data-vy-pending]').first(),
  },
};
const wjson = (path, method, body) => page.evaluate(async ([u, m, b]) => { const r = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch {} return { status: r.status, body: j, text: t.slice(0, 900) }; }, [WIRE + path, method, body]);
const SUB = "00000000-0000-0000-0000-cloudlearn01";
A.azure = {
  home: "#/",
  async runnable() { return [{ id: "vyomi:alpine-nano:3.21-i386", name: "Alpine Linux 3.21 (32-bit x86) - Vyomi Nano", ref: { publisher: "vyomi", offer: "alpine-nano", sku: "3.21-i386", version: "latest" } }]; },   // the console's image list (no core catalog for Azure images)
  async create(img) {
    const n = Date.now() % 100000, RG = `vmrg${n}`, VM = `vm${n}`;
    await wjson(`/subscriptions/${SUB}/resourceGroups/${RG}?api-version=2021-04-01`, "PUT", { location: "eastus" });
    const r = await wjson(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM}?api-version=2023-09-01`, "PUT",
      { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, osProfile: { computerName: VM, adminUsername: "azureuser", linuxConfiguration: { disablePasswordAuthentication: true } },
        storageProfile: { imageReference: (img && img.ref) || { publisher: "vyomi", offer: "alpine-nano", sku: "3.21-i386", version: "latest" }, osDisk: { createOption: "FromImage", osType: "Linux" } } } });
    if (r.status >= 300) throw new Error("create VM failed: " + r.text);
    this.rg = RG; return VM;
  },
  detail(id) { return `#/vms/${this.rg}/${id}`; },
  connect(id) { return `#/vms/${this.rg}/${id}/connect`; },
  list: "#/vms",
  pending: (page) => page.locator("[data-vy-pending]").first(),
  openShell: async () => {},
};
A.gcp = {
  home: "#/",
  async runnable() {
    const out = [];
    for (const prj of ["debian-cloud", "ubuntu-os-cloud", "cos-cloud", "rocky-linux-cloud", "vyomi-nano-cloud"]) {
      const j = (await wjson(`/compute/v1/projects/${prj}/global/images`, "GET")).body || {};
      for (const i of j.items || []) if (i.vyomiRunnable === true) out.push({ id: `projects/${prj}/global/images/${i.name}`, name: i.name });
    }
    return out;
  },
  async create(img) {
    await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
    const project = "nano-project";   // Nano's one project (core/gcp_project.NANO_PROJECT)
    const name = `vm-${Date.now() % 100000}`, zone = "us-central1-a";
    const r = await wjson(`/compute/v1/projects/${project}/zones/${zone}/instances`, "POST", { name, machineType: "e2-micro", disks: [{ boot: true, initializeParams: { diskSizeGb: "10", sourceImage: (img && img.id) || "projects/vyomi-nano-cloud/global/images/family/alpine-3-21-i386" } }] });
    if (r.status >= 300) throw new Error("create instance failed: " + r.text);
    this.zone = zone; return name;
  },
  detail(id) { return `#/compute/instances/${this.zone}/${id}`; },
  connect(id) { return `#/compute/instances/${this.zone}/${id}`; },
  list: "#/compute/instances",
  pending: (page) => page.locator("[data-vy-pending]").first(),
  openShell: async () => {},
};
const cl = A[CLOUD];
// EVERY image the catalog flags runnable on Nano must give a working Python 3, pip, apk and git (owner requirement 2026-11-26, NANO_TOOLS in
// core/compute_sizes.py). Data-driven: a future runnable image is booted and probed too, and cannot be enabled without passing.
const TOOLS = [
  ["python3 --version", /^Python 3\.\d+\.\d+/m],
  ["python3 -c 'print(sum(range(1,11))*6)'", /^330$/m],
  ["pip --version", /^pip \d+\.\d+/m],
  ["apk --version", /^apk-tools \d+/m],
  ["git --version", /^git version \d+\.\d+/m],
  ["cat /etc/os-release | head -2", /^NAME="?Alpine Linux"?$/m],
];
async function probeTools(label) {
  const term = page.locator(".vy-term").first();
  for (const [cmd, re] of TOOLS) {
    const mark = "T" + Math.random().toString(36).slice(2, 7);
    await term.click();
    await page.keyboard.type(`echo ${mark}-begin; ${cmd}; echo ${mark}-end\r`, { delay: 25 });
    let out = "";
    try {
      await page.waitForFunction((m) => new RegExp(`^${m}-end$`, "m").test(document.querySelector(".vy-term")?.innerText || ""), mark, { timeout: 120000 });
      const all = await term.innerText(); out = all.slice(all.lastIndexOf(mark + "-begin\n") + mark.length + 7, all.lastIndexOf(mark + "-end"));
    } catch { out = "(timeout) " + (await term.innerText()).slice(-200); }
    check(`${label}: \`${cmd}\` -> ${re}`, re.test(out), out.trim().slice(0, 120));
    console.log(`   OUT ${cmd}: ${out.trim().replace(/\s+/g, " ").slice(0, 160)}`);
  }
}
await page.goto(UI + cl.home);
await ready();
check("Nano backend ready", true);
const IMAGES = await cl.runnable();
check("the catalog flags at least one runnable image", IMAGES.length >= 1, IMAGES.map((i) => i.name).join(" | "));
const vmId = await cl.create(IMAGES[0]);
check("instance created through the wire", !!vmId, vmId);

// 1. flag off -> honest panel
await page.goto(UI + cl.connect(vmId));
await page.evaluate(() => { window.__noReload = "same-page"; });
if (CLOUD === "aws") await page.getByRole("button", { name: /^Connect$/ }).first().click();
await page.getByText(/In-browser VMs are off/i).first().waitFor({ timeout: 30000 }).catch(async (e) => { await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-fail.png` }); console.log(await page.evaluate(() => location.href)); console.log((await page.locator("body").innerText()).slice(0, 300)); throw e; });
check("flag off: honest 'In-browser VMs are off' panel with a Turn on button", await page.getByRole("button", { name: /Turn on in-browser VMs/ }).isVisible());
check("flag off: no Not-simulated panel", !/Coming soon/i.test(await page.locator("body").innerText()));
await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-off.png` });

// 2. turn on without reload
await page.getByRole("button", { name: /Turn on in-browser VMs/ }).click();
await page.waitForTimeout(1500);
check("turn on: page did not reload", (await page.evaluate(() => window.__noReload)) === "same-page");
check("turn on: flag stored", (await page.evaluate(() => localStorage.getItem("nano_vm_compute"))) === "1");
await page.getByText(/VM not ready|In-browser VM is (booting|starting|launching)|The in-browser VM is/i).first().waitFor({ timeout: 60000 }).catch(() => {});
await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-booting.png` });
const panelTxt = await page.locator('[data-testid="nano-vm-panel"]').innerText();
check("turn on: panel shows boot state (not off)", !/In-browser VMs are off/.test(panelTxt), panelTxt.replace(/\s+/g, " ").slice(0, 150));
await page.keyboard.press("Escape");

// 3. pending with the pulse hook, then running
await page.goto(UI + cl.list); await ready();
await page.waitForFunction(() => document.querySelector("[data-vy-pending]"), null, { timeout: 60000 }).catch(() => {});
check("list: pending state carries the pulse hook", await cl.pending(page).count() > 0);
await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-pending.png` });
if (!BOOT) { console.log("BOOT=0: stopped before waiting on the v86 boot"); }
else {
  try {
    await page.waitForFunction(() => /\brunning\b/i.test(document.body.innerText || "") && !document.querySelector("[data-vy-pending]"), null, { timeout: 240000, polling: 2000 });
    check("list: state flipped pending -> running without a manual reload", true);
  } catch { check("list: state flipped pending -> running without a manual reload", false, "VM did not boot within 240 s"); }
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-running.png` });
  await page.goto(UI + cl.connect(vmId)); await ready();
  await cl.openShell(page);
  const term = page.locator(".vy-term .xterm-helper-textarea, .vy-term textarea").first();
  await term.waitFor({ state: "attached", timeout: 60000 });
  await page.locator(".vy-term").first().click();
  await page.keyboard.type("echo hi-from-$((40+2))\r", { delay: 40 });
  try {
    await page.waitForFunction(() => /^hi-from-42$/m.test(document.querySelector(".vy-term")?.innerText || ""), null, { timeout: 60000 });
    check("shell: typed command ran in the VM (echo -> hi-from-42)", true);
  } catch { check("shell: typed command ran in the VM", false, (await page.locator(".vy-term").first().innerText()).slice(-200)); }
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-shell.png` });
  await probeTools(`[${IMAGES[0].name}]`);
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-tools.png` });
  // a power repaint (the event the host fires on a state change) must not yank the open shell
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("nano-vm-power", { detail: { id: null, state: "running" } })));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-repaint.png` });
  if (process.env.DBG) console.log(await page.evaluate(() => JSON.stringify({ terms: document.querySelectorAll(".vy-term").length, html: (document.querySelector(".vy-term")?.innerHTML || "").slice(0, 600), shells: document.querySelectorAll("[data-nano-shell]").length })));
  check("shell survives a power-state repaint (session kept)", /^hi-from-42$|^T\w+-end$/m.test(await page.locator(".vy-term").first().innerText().catch(() => "")));
}
if (CLOUD === "azure" && BOOT) {
  await page.goto(UI + `#/vms/${cl.rg}/${vmId}/serialconsole`); await ready();
  await page.locator(".vy-term").first().waitFor({ timeout: 60000 }).catch(() => {});
  check("azure Serial console blade is the in-browser shell (not Not-simulated)", (await page.locator(".vy-term").count()) === 1 && !/Coming soon/i.test(await page.locator("body").innerText()));
}
// every further runnable image (none today): create, boot, shell, same tool probe
for (const img of IMAGES.slice(1)) {
  if (!BOOT) break;
  const id2 = await cl.create(img);
  await page.goto(UI + cl.list); await ready();
  try { await page.waitForFunction(() => /\brunning\b/i.test(document.body.innerText || "") && !document.querySelector("[data-vy-pending]"), null, { timeout: 240000, polling: 2000 }); } catch {}
  await page.goto(UI + cl.connect(id2)); await ready(); await cl.openShell(page);
  await page.locator(".vy-term").first().waitFor({ timeout: 60000 });
  await probeTools(`[${img.name}]`);
}
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
