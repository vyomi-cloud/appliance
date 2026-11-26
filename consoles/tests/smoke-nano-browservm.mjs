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
  async runnable() {   // the console's image select (consoles/src/common/computeSizes.js NANO_CATALOG): every runnable reference
    return [["Alpine Linux 3.21 (32-bit x86) - Vyomi Nano", "alpine-nano", "3.21-i386"], ["Debian GNU/Linux 12 (32-bit x86) - Vyomi Nano", "debian-nano", "12-i386"], ["Buildroot 2024.05 (32-bit x86, minimal) - Vyomi Nano", "buildroot-nano", "2024-i386"]]
      .map(([name, offer, sku]) => ({ id: `vyomi:${offer}:${sku}`, name, ref: { publisher: "vyomi", offer, sku, version: "latest" } }));
  },   // the console's image list (no core catalog for Azure images)
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
// Each runnable image is booted and probed against exactly what it CLAIMS (core/compute_sizes.py NANO_CATALOG `claims` / `summary`); no image claims what it lacks.
const keyOf = (img) => (/debian/i.test(img.name + img.id) ? "debian" : /buildroot/i.test(img.name + img.id) ? "buildroot" : "alpine");
const PY = [["python3 --version", /^Python 3\.\d+\.\d+/m], ["python3 -c 'print(sum(range(1,11))*6)'", /^330$/m], ["pip --version", /^pip \d+\.\d+/m], ["git --version", /^git version \d+\.\d+/m]];
const TOOLS = {
  alpine: [...PY, ["apk --version", /^apk-tools \d+/m], ["cat /etc/os-release | head -2", /^NAME="?Alpine Linux"?$/m]],
  debian: [...PY, ["dpkg --version | head -1", /Debian .dpkg. package management program/m], ["apt --version", /^apt \d+\.\d+/m],
           ["cat /etc/os-release | head -3", /^PRETTY_NAME="Debian GNU\/Linux 12 \(bookworm\)"$/m], ["uname -m", /^i[36]86$/m]],
  buildroot: [["cat /etc/os-release | head -3", /^NAME=Buildroot$/m], ["busybox 2>&1 | head -1", /^BusyBox v\d/m], ["uname -m", /^i[36]86$/m],
              ["for t in git python3 pip apk apt; do command -v $t >/dev/null 2>&1 && echo HAS-$t; done; echo none-checked", /^none-checked$/m],
              ["command -v git python3 pip apk apt | wc -l", /^0$/m]],     // the image claims none of them, and has none
};
async function probeTools(label, key) {
  const term = page.locator(".vy-term").first();
  for (const [cmd, re] of TOOLS[key]) {
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
let IMAGES = await cl.runnable();
check("the catalog flags exactly the three runnable images (Alpine, Debian, Buildroot)", IMAGES.length === 3 && ["alpine", "debian", "buildroot"].every((k) => IMAGES.some((i) => keyOf(i) === k)), IMAGES.map((i) => i.name).join(" | "));
if (process.env.ONLY) IMAGES = IMAGES.filter((i) => process.env.ONLY.split(",").includes(keyOf(i)));   // dev aid: ONLY=debian,buildroot
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
  await probeTools(`[${IMAGES[0].name}]`, keyOf(IMAGES[0]));
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
// every further runnable image: create, boot, shell, the tool probe for what THAT image claims
for (const img of IMAGES.slice(1)) {
  if (!BOOT) break;
  const t0 = Date.now();
  const id2 = await cl.create(img);
  await page.goto(UI + cl.connect(id2)); await ready(); await cl.openShell(page);
  try { await page.locator(".vy-term").first().waitFor({ timeout: 280000 }); check(`[${img.name}] boots to a shell on ${CLOUD}`, true, `${Math.round((Date.now() - t0) / 1000)} s`); }
  catch { check(`[${img.name}] boots to a shell on ${CLOUD}`, false, "no shell within 280 s"); await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-${keyOf(img)}-fail.png` }); continue; }
  await probeTools(`[${img.name}]`, keyOf(img));
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-${keyOf(img)}-tools.png` });
  // the Connect text must be accurate per image
  const txt = await page.locator("body").innerText();
  const want = keyOf(img) === "debian" ? /Debian GNU\/Linux 12 \(bookworm\), 32-bit x86: Python 3, pip, apt\/dpkg, git/ : keyOf(img) === "buildroot" ? /Buildroot 2024\.05, 32-bit x86, minimal: busybox shell only/ : /Alpine Linux 3\.21, 32-bit x86: Python 3, pip, apk, git/;
  check(`[${img.name}] Connect page states exactly what the image contains`, want.test(txt), (txt.match(/Image: [^\n]*/) || [""])[0]);
  if (keyOf(img) === "buildroot") check(`[${img.name}] Connect page says serial console only (no ssh claimed)`, /Serial console only/.test(txt) && !/SSH from your terminal/.test(txt));
}
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
