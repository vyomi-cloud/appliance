/* Compute create flows offer ONLY the images the substrate can run (images / OS / architecture), and the launch payload carries them.
 * Nano = the REAL Nano bundle (service worker + Pyodide cores) from `node consoles/nano_preview.mjs --port 8341`; Mesh = a dev server whose core
 * engines run as the Mesh substrate (full catalog must still show):
 *   VYOMI_COMPUTE_SUBSTRATE=mesh VYOMI_MESH_CAP_MB=11468 VYOMI_MESH_CPUS=4 python3 consoles/dev_server.py --port 8342
 * Run:  NANO=http://127.0.0.1:8341 MESH=http://127.0.0.1:8342 node consoles/tests/smoke-compute-images.mjs
 * (PW=playwright module path, CHROME=chrome path, OUT=screenshot dir.) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const NANO = process.env.NANO || "http://127.0.0.1:8341", MESH = process.env.MESH || "http://127.0.0.1:8342";
const OUT = process.env.OUT || "smoke-out";
const results = [];
const check = (n, ok, extra = "") => { results.push(!!ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${ok ? "" : "  " + extra}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
const NOTE = /only the image below is available \(Alpine Linux 3\.21, 32-bit x86\)/;
const SUBS = { nano: `${NANO}/nano/v4`, mesh: `${MESH}/v4` };

for (const [sub, root] of Object.entries(SUBS)) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
  const page = await ctx.newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  const posts = []; page.on("request", (r) => { if (r.method() !== "GET" && /_wire|\/compute\/|\/subscriptions\//.test(r.url())) posts.push({ url: r.url(), body: r.postData() || "" }); });
  const ready = () => sub === "nano" ? page.waitForFunction(() => window.__vyomiNanoReady === true, null, { timeout: 180000 }) : Promise.resolve();
  const optionTexts = async () => [...new Set((await page.getByRole("option").allInnerTexts()).map((s) => s.split("\n")[0].trim()))];

  // ── AWS: EC2 > Launch instance ──
  await page.goto(`${root}/aws/#/ec2/launch-instance`); await ready();
  await page.getByText("Quick Start").first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(1500);
  const quick = await page.getByRole("radio").evaluateAll((els) => els.map((e) => e.closest("label")?.innerText.trim() || e.getAttribute("value") || ""));
  await page.getByLabel("Amazon Machine Image (AMI)").first().click(); await page.waitForTimeout(400);
  const amis = await optionTexts(); await page.keyboard.press("Escape");
  await page.getByLabel("Architecture").first().click(); await page.waitForTimeout(300);
  const archs = await optionTexts(); await page.keyboard.press("Escape");
  await page.screenshot({ path: `${OUT}/aws-${sub}.png`, fullPage: false });
  if (sub === "nano") {
    check("[nano] aws note shown", await page.getByText(NOTE).count() > 0);
    check("[nano] aws Quick Start offers only Alpine Linux", JSON.stringify(quick.filter((q) => !/Allow|Create|Select existing/.test(q) && /Linux|Ubuntu|Windows|macOS|Red Hat|SUSE|Debian/.test(q))) === JSON.stringify(["Alpine Linux"]), quick.join("|"));
    check("[nano] aws AMI list is exactly the Alpine i386 image", amis.length === 1 && /^Alpine Linux 3\.21 \(i386\) - Vyomi Nano \(ami-/.test(amis[0]), amis.join("|"));
    check("[nano] aws Architecture offers only 32-bit (x86)", JSON.stringify(archs) === JSON.stringify(["32-bit (x86)"]), archs.join("|"));
    await page.getByLabel("Name").first().fill("images-smoke");
    posts.length = 0;
    await page.getByRole("button", { name: "Launch instance" }).last().click();
    await page.waitForTimeout(3000);
    const run = posts.find((p) => /RunInstances/.test(p.body));
    check("[nano] aws RunInstances carries the Alpine AMI", run && /ImageId=ami-/.test(run.body), JSON.stringify(run));
    const arch = await page.evaluate(async () => (await (await fetch("/nano/_wire/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: "Action=DescribeInstances&Version=2016-11-15" })).text()).match(/<architecture>([^<]+)<\/architecture>/)?.[1]);
    check("[nano] aws launched instance is i386", arch === "i386", String(arch));
    const bad = await page.evaluate(async () => { const f = (b) => fetch("/nano/_wire/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: b }).then(async (r) => ({ s: r.status, t: await r.text() }));
      const ims = await f("Action=DescribeImages&Version=2016-11-15"); const own = ims.t.match(/<imageId>(ami-\w+)<\/imageId>/)[1];
      return await f("Action=RunInstances&Version=2016-11-15&MinCount=1&MaxCount=1&InstanceType=t3.micro&ImageId=ami-0123456789abcdef0"); });
    check("[nano] aws RunInstances with an unknown/x86 AMI is refused natively (InvalidAMIID.NotFound 400)", bad.s === 400 && /InvalidAMIID\.NotFound/.test(bad.t), bad.t.slice(0, 160));
  } else {
    check("[mesh] aws no Nano note", await page.getByText(NOTE).count() === 0);
    check("[mesh] aws Quick Start keeps the full list", ["Amazon Linux", "macOS", "Ubuntu", "Windows", "Red Hat", "SUSE Linux", "Debian"].every((n) => quick.some((q) => q.includes(n))), quick.join("|"));
    check("[mesh] aws AMI list is the full catalog", ["Amazon Linux", "Ubuntu", "Windows Server", "Red Hat", "SUSE", "Debian"].every((n) => amis.some((a) => a.includes(n))) && !amis.some((a) => /Alpine/.test(a)), amis.join("|"));
    check("[mesh] aws Architecture offers x86 and Arm", archs.includes("64-bit (x86)") && archs.includes("64-bit (Arm)"), archs.join("|"));
  }

  // ── GCP: Compute Engine > Create instance ──
  await page.goto(`${root}/gcp/#/compute/instances/create`); await ready();
  await page.getByRole("combobox", { name: "Operating system" }).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.getByRole("combobox", { name: "Operating system" }).first().click(); await page.waitForTimeout(300);
  const oses = await optionTexts(); await page.keyboard.press("Escape");
  await page.screenshot({ path: `${OUT}/gcp-${sub}.png`, fullPage: false });
  if (sub === "nano") {
    check("[nano] gcp note shown", await page.getByText(NOTE).count() > 0);
    check("[nano] gcp Operating system lists only Alpine", JSON.stringify(oses) === JSON.stringify(["Alpine Linux"]), oses.join("|"));
    check("[nano] gcp Version is the Alpine 3.21 (32-bit x86)", await page.getByLabel("Version").first().inputValue() === "Alpine Linux 3.21 (32-bit x86)");
    await page.getByLabel("Name").first().fill("images-smoke-gcp"); posts.length = 0;
    await page.getByRole("button", { name: "Create", exact: true }).last().click(); await page.waitForTimeout(3000);
    const ins = posts.find((p) => /\/instances/.test(p.url) && p.body);
    check("[nano] gcp insert carries the Alpine sourceImage", ins && /vyomi-nano-cloud\/global\/images\/family\/alpine-3-21-i386/.test(ins.body), JSON.stringify(ins));
    const bad = await page.evaluate(async () => { const r = await fetch("/nano/_wire/compute/v1/projects/nano-project/zones/us-central1-a/instances", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "debian-x", machineType: "e2-micro", disks: [{ boot: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }] }) }); return { s: r.status, t: await r.text() }; });
    check("[nano] gcp insert of a Debian image is refused natively (404 NOT_FOUND)", bad.s === 404 && /NOT_FOUND/.test(bad.t), bad.t.slice(0, 160));
  } else {
    check("[mesh] gcp no Nano note", await page.getByText(NOTE).count() === 0);
    check("[mesh] gcp Operating system keeps the catalog", ["Debian", "Ubuntu", "Rocky Linux", "Container-Optimized OS"].every((n) => oses.includes(n)) && !oses.includes("Alpine Linux"), oses.join("|"));
  }

  // ── Azure: Create a virtual machine ──
  await page.goto(`${root}/azure/#/vms/create`); await ready();
  await page.locator("#vm-image").waitFor({ timeout: 60000 });
  await page.waitForTimeout(2000);
  const imgs = await page.locator("#vm-image option").allInnerTexts();
  const azArch = await page.getByRole("radio", { name: /Arm64|x64/ }).evaluateAll((els) => els.map((e) => e.closest("label")?.innerText.trim() || e.value));
  await page.screenshot({ path: `${OUT}/azure-${sub}.png`, fullPage: false });
  if (sub === "nano") {
    check("[nano] azure note shown", await page.getByText(NOTE).count() > 0);
    check("[nano] azure Image lists only Alpine", JSON.stringify(imgs) === JSON.stringify(["Alpine Linux 3.21 (32-bit x86) - Vyomi Nano"]), imgs.join("|"));
    check("[nano] azure VM architecture offers only x64 (no Arm64)", JSON.stringify(azArch) === JSON.stringify(["x64"]), azArch.join("|"));
    // create through the wizard and read the ARM body the console sent
    await page.getByLabel("Virtual machine name").first().fill("imgsmoke");
    await page.getByLabel("Username").first().fill("azureuser");
    await page.getByRole("radio", { name: /Password/ }).first().check().catch(() => {});
    await page.locator("#vm-pw").fill("Vyomi-Pass-12345");
    await page.locator("#vm-pw2").fill("Vyomi-Pass-12345");
    posts.length = 0;
    await page.getByRole("button", { name: /Review \+ create/ }).first().click().catch(() => {}); await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/azure-nano-review.png` });
    await page.getByRole("button", { name: /^Create$/ }).first().click().catch(() => {}); await page.waitForTimeout(5000);
    const vm = posts.find((p) => /virtualMachines\/imgsmoke/.test(p.url) && p.body);
    check("[nano] azure VM PUT carries the Alpine imageReference", vm && /"publisher":"vyomi"/.test(vm.body) && /"offer":"alpine-nano"/.test(vm.body), JSON.stringify(vm));
    const bad = await page.evaluate(async () => { const sub = (await (await fetch("/nano/_wire/subscriptions?api-version=2020-01-01")).json()).value[0].subscriptionId;
      await fetch(`/nano/_wire/subscriptions/${sub}/resourceGroups/imgrg?api-version=2021-04-01`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus" }) });
      const r = await fetch(`/nano/_wire/subscriptions/${sub}/resourceGroups/imgrg/providers/Microsoft.Compute/virtualMachines/ubu?api-version=2023-09-01`, { method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, storageProfile: { imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts", version: "latest" } } } }) }); return { s: r.status, t: await r.text() }; });
    check("[nano] azure VM PUT with Ubuntu is refused natively (400 PlatformImageNotFound)", bad.s === 400 && /PlatformImageNotFound/.test(bad.t), bad.t.slice(0, 160));
  } else {
    check("[mesh] azure no Nano note", await page.getByText(NOTE).count() === 0);
    check("[mesh] azure Image keeps the catalog", imgs.length === 3 && imgs.some((i) => /Ubuntu/.test(i)) && imgs.some((i) => /Windows/.test(i)), imgs.join("|"));
    check("[mesh] azure VM architecture offers Arm64 and x64", azArch.length === 2, azArch.join("|"));
  }
  check(`[${sub}] no page errors`, errors.length === 0, errors.join(" | "));
  await ctx.close();
}
await browser.close();
const bad = results.filter((x) => !x).length;
console.log(bad ? `FAILED ${bad}/${results.length}` : `ALL PASS ${results.length}/${results.length}`);
process.exit(bad ? 1 : 0);
