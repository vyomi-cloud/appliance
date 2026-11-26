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
const SUMMARY = 'Alpine Linux 3.21, 32-bit x86: Python 3, pip, apk, git';   // exactly what the one runnable image contains (core/compute_sizes.py NANO_SUMMARY)
const NOTE = /Alpine Linux 3\.21, 32-bit x86: Python 3, pip, apk, git/;
const REASON = "Not available on Nano: runs only in a Mesh";
// sizes a Nano VM can run (core/compute_sizes.py) - everything else must be listed AND disabled
const AWS_RUN = ["t2.nano", "t3.nano", "t3a.nano", "t2.micro", "t3.micro", "t3a.micro"], GCP_RUN = ["f1-micro", "e2-micro"], AZ_RUN = ["Standard_B1ls", "Standard_B1s"];
const same = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
const SUBS = { nano: `${NANO}/nano/v4`, mesh: `${MESH}/v4` };

// ── Regression: the AMI list must load on a FRESH browser profile (owner report "Amazon Machine Image (AMI) is not loading") ──
// Cause: on a first visit the service-worker register()/update() job sat ~60 s (nano-boot.js awaited it), so the page's one-shot catalog call was
// held by the worker for 60 s and then answered HTTP 500 "no client to run the in-browser backend"; the picker stayed empty for good.
// (1) deterministic: the FIRST DescribeImages / DescribeInstanceTypes answer is forced to that 500; the console must wait for the backend and retry.
// (2) the time from navigation to an enabled "Launch instance" is printed (a fresh profile used to take 60 - 180 s; now about 5 s, more only when the Pyodide CDN is slow).
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
  await ctx.addInitScript(() => {
    const orig = window.fetch.bind(window); window.__forced500 = 0;
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input.url;
      if (/\/_wire\/?$/.test(url) && /Action=(DescribeImages|DescribeInstanceTypes)\b/.test(String(init?.body || "")) && window.__forced500 < 2)
        { window.__forced500++; return new Response(JSON.stringify({ ok: false, error: "Error: no client to run the in-browser backend" }), { status: 500, headers: { "content-type": "application/json" } }); }
      return orig(input, init);
    };
  });
  const page = await ctx.newPage(); const t0 = Date.now();
  await page.goto(`${NANO}/nano/v4/aws/#/ec2/launch-instance`);
  const btn = page.getByRole("button", { name: "Launch instance" }).last();
  let loaded = true; try { await page.waitForFunction(() => [...document.querySelectorAll("button")].some((b) => /Launch instance/.test(b.innerText) && !b.disabled), null, { timeout: 240000 }); } catch { loaded = false; }
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`INFO fresh profile: Launch instance enabled after ${secs}s (loaded=${loaded})`);
  const forced = await page.evaluate(() => window.__forced500);
  check("[nano] AMI list loads on a fresh profile even when the first catalog calls are answered 500 'no client' (retried after the backend is up)", loaded && forced === 2 && /Alpine Linux 3\.21/.test(await page.getByLabel("Amazon Machine Image (AMI)").first().innerText()), `loaded=${loaded} forced=${forced}`);
  await page.screenshot({ path: `${OUT}/aws-nano-fresh-profile.png` });
  await ctx.close();
}

for (const [sub, root] of Object.entries(SUBS)) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
  const page = await ctx.newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  const posts = []; page.on("request", (r) => { if (r.method() !== "GET" && /_wire|\/compute\/|\/subscriptions\//.test(r.url())) posts.push({ url: r.url(), body: r.postData() || "" }); });
  const ready = () => sub === "nano" ? page.waitForFunction(() => window.__vyomiNanoReady === true, null, { timeout: 180000 }) : Promise.resolve();
  const optionTexts = async () => (await optionStates()).map((o) => o.t);
  // every open option with whether it is disabled (Cloudscape / MUI mark aria-disabled; native <option> uses .disabled)
  const optionStates = async () => { const seen = new Map(); for (const o of await page.getByRole("option").evaluateAll((els) => els.map((e) => ({ t: e.innerText.split("\n")[0].trim(), off: e.getAttribute("aria-disabled") === "true" || e.disabled === true })))) if (!seen.has(o.t)) seen.set(o.t, o); return [...seen.values()]; };
  const enabled = (os) => os.filter((o) => !o.off).map((o) => o.t), disabledOf = (os) => os.filter((o) => o.off).map((o) => o.t);

  const wireAws = (body) => page.evaluate(async (b) => { const r = await fetch("/nano/_wire/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: b }); return { s: r.status, t: await r.text() }; }, body);

  // ── AWS: EC2 > Launch instance ──
  await page.goto(`${root}/aws/#/ec2/launch-instance`); await ready();
  await page.getByText("Quick Start").first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(1500);
  const quick = await page.getByRole("radio").evaluateAll((els) => els.map((e) => ({ t: (e.parentElement.parentElement.innerText || "").split("\n")[0].trim(), off: e.disabled, on: e.checked })).filter((r) => /Linux|Ubuntu|Windows|macOS|Red Hat|SUSE|Debian/.test(r.t)));
  await page.getByLabel("Amazon Machine Image (AMI)").first().click(); await page.waitForTimeout(400);
  const amis = await optionStates(); await page.keyboard.press("Escape");
  await page.getByLabel("Architecture").first().click(); await page.waitForTimeout(300);
  const archs = await optionStates(); await page.keyboard.press("Escape");
  await page.getByText("All generations").first().click();
  await page.getByLabel("Instance type").first().click(); await page.waitForTimeout(400);
  const types = await optionStates(); await page.keyboard.press("Escape");
  const awsSel = { ami: await page.getByLabel("Amazon Machine Image (AMI)").first().innerText(), arch: await page.getByLabel("Architecture").first().innerText(), type: await page.getByLabel("Instance type").first().innerText() };
  const awsBody = await page.locator("body").innerText();
  await page.screenshot({ path: `${OUT}/aws-${sub}.png`, fullPage: false });
  if (sub === "nano") {
    check("[nano] aws note shown", await page.getByText(NOTE).count() > 0);
    check("[nano] aws Quick Start lists the full set, only Alpine Linux enabled + selected", quick.length === 8 && same(quick.filter((q) => !q.off).map((q) => q.t), ["Alpine Linux"]) && quick.find((q) => q.t === "Alpine Linux").on && quick.some((q) => q.t === "Ubuntu" && q.off), JSON.stringify(quick));
    check("[nano] aws AMI list keeps the catalog, only the Alpine i386 AMI enabled", amis.length >= 7 && enabled(amis).length === 1 && /^Alpine Linux 3\.21 \(i386\) - Vyomi Nano \(ami-/.test(enabled(amis)[0]) && disabledOf(amis).some((a) => /Amazon Linux/.test(a)), JSON.stringify(amis));
    check("[nano] aws AMI preselected is Alpine", /Alpine Linux 3\.21/.test(awsSel.ami), awsSel.ami);
    check("[nano] aws Architecture lists all three, only 32-bit (x86) enabled + selected", same(archs.map((a) => a.t), ["32-bit (x86)", "64-bit (x86)", "64-bit (Arm)"]) && same(enabled(archs), ["32-bit (x86)"]) && /32-bit/.test(awsSel.arch), JSON.stringify(archs));
    check("[nano] aws Instance type lists the full catalog, only the Nano sizes enabled", types.length > 14 && same(enabled(types).map((t) => t.split(" ")[0]), AWS_RUN) && disabledOf(types).some((t) => t.startsWith("m5.2xlarge")), JSON.stringify(types.map((t) => t.t)));
    check("[nano] aws Instance type preselected is a runnable one", AWS_RUN.includes(awsSel.type.split(" ")[0]), awsSel.type);
    await page.getByLabel("Name").first().fill("images-smoke");
    posts.length = 0;
    await page.getByRole("button", { name: "Launch instance" }).last().click();
    await page.waitForTimeout(3000);
    const run = posts.find((p) => /RunInstances/.test(p.body));
    check("[nano] aws RunInstances carries the Alpine AMI", run && /ImageId=ami-/.test(run.body), JSON.stringify(run));
    const arch = (await wireAws("Action=DescribeInstances&Version=2016-11-15")).t.match(/<architecture>([^<]+)<\/architecture>/)?.[1];
    check("[nano] aws launched instance is i386", arch === "i386", String(arch));
    const ims = (await wireAws("Action=DescribeImages&Version=2016-11-15")).t;
    const x86 = ims.match(/<imageId>(ami-\w+)<\/imageId>(?:(?!<imageId>).)*?<architecture>x86_64<\/architecture>/s)?.[1];
    const bad = await wireAws(`Action=RunInstances&Version=2016-11-15&MinCount=1&MaxCount=1&InstanceType=t3.micro&ImageId=${x86}`);
    check("[nano] aws DescribeImages describes the runnable AMI exactly as the summary", new RegExp(`<name>Alpine Linux 3\\.21 \\(i386\\) - Vyomi Nano</name><description>${SUMMARY}</description>`).test(ims), ims.slice(0, 200));
    check("[nano] aws AMI field states what the image contains", awsBody.includes(SUMMARY));
    check("[nano] aws RunInstances with a listed-but-disabled x86 AMI is still refused natively (Unsupported 400)", bad.s === 400 && /<Code>Unsupported<\/Code>/.test(bad.t), bad.t.slice(0, 160));
    const bigT = await wireAws("Action=RunInstances&Version=2016-11-15&MinCount=1&MaxCount=1&InstanceType=m5.2xlarge");
    check("[nano] aws RunInstances with a disabled size is still refused (Unsupported 400)", bigT.s === 400 && /<Code>Unsupported<\/Code>/.test(bigT.t), bigT.t.slice(0, 160));
  } else {
    check("[mesh] aws no Nano note", await page.getByText(NOTE).count() === 0);
    check("[mesh] aws Quick Start keeps the full list, nothing disabled except Windows (disable-windows-images)", ["Amazon Linux", "macOS", "Ubuntu", "Windows", "Red Hat", "SUSE Linux", "Debian"].every((n) => quick.some((q) => q.t.includes(n))) && quick.every((q) => !q.off || /Windows/.test(q.t)) && !quick.some((q) => /Alpine/.test(q.t)), JSON.stringify(quick));
    check("[mesh] aws AMI list is the full catalog, nothing disabled except Windows", ["Amazon Linux", "Ubuntu", "Windows Server", "Red Hat", "SUSE", "Debian"].every((n) => amis.some((a) => a.t.includes(n))) && !amis.some((a) => /Alpine/.test(a.t)) && disabledOf(amis).every((a) => /Windows/.test(a)), JSON.stringify(amis));
    check("[mesh] aws Architecture offers x86 and Arm, enabled", same(archs.map((a) => a.t), ["64-bit (x86)", "64-bit (Arm)"]) && !disabledOf(archs).length, JSON.stringify(archs));
    check("[mesh] aws sizes unchanged (the Mesh runnable list, none disabled)", !disabledOf(types).length && !types.some((t) => t.t.startsWith("m5.2xlarge")), JSON.stringify(types.map((t) => t.t)));
  }

  // ── GCP: Compute Engine > Create instance ──
  await page.goto(`${root}/gcp/#/compute/instances/create`); await ready();
  await page.getByRole("combobox", { name: "Operating system" }).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.getByRole("combobox", { name: "Operating system" }).first().click(); await page.waitForTimeout(300);
  const oses = await optionStates(); await page.keyboard.press("Escape");
  const gcpOsSel = await page.getByRole("combobox", { name: "Operating system" }).first().innerText();
  const gcpMt = {};
  for (const fam of ["General purpose", "Compute optimized"]) {
    const radio = page.getByRole("radio", { name: fam });
    if (await radio.count() && await radio.first().isEnabled()) { await radio.first().check(); await page.getByRole("combobox", { name: "Machine type" }).first().click(); await page.waitForTimeout(300); gcpMt[fam] = await optionStates(); await page.keyboard.press("Escape"); }
  }
  await page.getByRole("radio", { name: "General purpose" }).first().check(); await page.waitForTimeout(300);
  const gcpTypeSel = await page.getByRole("combobox", { name: "Machine type" }).first().innerText();
  await page.screenshot({ path: `${OUT}/gcp-${sub}.png`, fullPage: false });
  const gcpAll = Object.values(gcpMt).flat();
  if (sub === "nano") {
    check("[nano] gcp note shown", await page.getByText(NOTE).count() > 0);
    check("[nano] gcp Operating system keeps the catalog, only Alpine enabled + selected", oses.length === 5 && same(enabled(oses), ["Alpine Linux"]) && /Alpine Linux/.test(gcpOsSel) && disabledOf(oses).some((o) => o.startsWith("Debian")), JSON.stringify(oses));
    check("[nano] gcp Version is the Alpine 3.21 (32-bit x86)", await page.getByLabel("Version").first().inputValue() === "Alpine Linux 3.21 (32-bit x86)");
    check("[nano] gcp Machine types list the full catalog, only the Nano sizes enabled", gcpAll.length > 5 && same(enabled(gcpAll).map((t) => t.split(" ")[0]), GCP_RUN) && disabledOf(gcpAll).some((t) => t.startsWith("e2-standard-4")), JSON.stringify(gcpAll.map((t) => t.t)));
    check("[nano] gcp preselected machine type is a runnable one", GCP_RUN.includes(gcpTypeSel.split(" ")[0]), gcpTypeSel);
    check("[nano] gcp disabled entries carry the reason", oses.filter((o) => o.off).every((o) => o.t.includes(REASON)));
    await page.getByLabel("Name").first().fill("images-smoke-gcp"); posts.length = 0;
    await page.getByRole("button", { name: "Create", exact: true }).last().click(); await page.waitForTimeout(3000);
    const ins = posts.find((p) => /\/instances/.test(p.url) && p.body);
    check("[nano] gcp insert carries the Alpine sourceImage + a runnable machineType", ins && /vyomi-nano-cloud\/global\/images\/family\/alpine-3-21-i386/.test(ins.body) && GCP_RUN.includes(JSON.parse(ins.body).machineType.split("/").pop()), JSON.stringify(ins));
    const call = (img, mt) => page.evaluate(async ([i, m]) => { const r = await fetch("/nano/_wire/compute/v1/projects/nano-project/zones/us-central1-a/instances", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "x-" + Math.random().toString(36).slice(2, 8), machineType: m, disks: [{ boot: true, initializeParams: { sourceImage: i } }] }) }); return { s: r.status, t: await r.text() }; }, [img, mt]);
    const bad = await call("projects/debian-cloud/global/images/family/debian-12", "e2-micro");
    check("[nano] gcp insert of a (listed, disabled) Debian image is still refused natively (404 NOT_FOUND)", bad.s === 404 && /NOT_FOUND/.test(bad.t), bad.t.slice(0, 160));
    const badMt = await call("projects/vyomi-nano-cloud/global/images/family/alpine-3-21-i386", "e2-standard-4");
    check("[nano] gcp insert of a disabled machine type is still refused (400 INVALID_ARGUMENT)", badMt.s === 400 && /INVALID_ARGUMENT/.test(badMt.t), badMt.t.slice(0, 160));
  } else {
    check("[mesh] gcp no Nano note", await page.getByText(NOTE).count() === 0);
    check("[mesh] gcp Operating system keeps the catalog, nothing disabled", ["Debian", "Ubuntu", "Rocky Linux", "Container-Optimized OS"].every((n) => oses.some((o) => o.t === n)) && !oses.some((o) => o.t === "Alpine Linux") && !disabledOf(oses).length, JSON.stringify(oses));
    check("[mesh] gcp machine types: none disabled", !disabledOf(gcpAll).length && gcpAll.length > 0, JSON.stringify(gcpAll));
  }

  // ── Azure: Create a virtual machine ──
  await page.goto(`${root}/azure/#/vms/create`); await ready();
  await page.locator("#vm-image").waitFor({ timeout: 60000 });
  await page.waitForTimeout(2000);
  const imgs = await page.locator("#vm-image option").evaluateAll((els) => els.map((e) => ({ t: e.textContent.trim(), off: e.disabled })));
  const imgSel = await page.locator("#vm-image").inputValue();
  const azSizes = await page.locator("#vm-size option").evaluateAll((els) => els.map((e) => ({ t: e.textContent.trim(), off: e.disabled })));
  const azSizeSel = await page.locator("#vm-size").inputValue();
  const azArch = await page.getByRole("radio", { name: /Arm64|x64/ }).evaluateAll((els) => els.map((e) => ({ t: (e.closest("label")?.innerText || e.value).trim(), off: e.disabled, on: e.checked })));
  await page.screenshot({ path: `${OUT}/azure-${sub}.png`, fullPage: false });
  if (sub === "nano") {
    check("[nano] azure note shown", await page.getByText(NOTE).count() > 0);
    check("[nano] azure Image keeps the catalog, only Alpine enabled + selected", imgs.length === 4 && same(enabled(imgs), ["Alpine Linux 3.21 (32-bit x86) - Vyomi Nano"]) && imgSel.startsWith("Alpine Linux 3.21") && disabledOf(imgs).some((i) => /Ubuntu/.test(i) && i.includes(REASON)), JSON.stringify(imgs));
    check("[nano] azure VM architecture lists Arm64 (disabled) and x64 (enabled, selected)", azArch.length === 2 && azArch.find((a) => /Arm64/.test(a.t)).off && !azArch.find((a) => /x64/.test(a.t)).off && azArch.find((a) => /x64/.test(a.t)).on, JSON.stringify(azArch));
    check("[nano] azure Size lists the full catalog, only the Nano sizes enabled + a runnable one selected", azSizes.length > 5 && same(enabled(azSizes).map((t) => t.split(" ")[0]), AZ_RUN) && disabledOf(azSizes).some((t) => t.startsWith("Standard_D4s_v5")) && AZ_RUN.includes(azSizeSel), JSON.stringify(azSizes.map((t) => t.t)) + azSizeSel);
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
    const put = (ref, size) => page.evaluate(async ([rf, sz]) => { const sub = (await (await fetch("/nano/_wire/subscriptions?api-version=2020-01-01")).json()).value[0].subscriptionId;
      await fetch(`/nano/_wire/subscriptions/${sub}/resourceGroups/imgrg?api-version=2021-04-01`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus" }) });
      const r = await fetch(`/nano/_wire/subscriptions/${sub}/resourceGroups/imgrg/providers/Microsoft.Compute/virtualMachines/ubu${Math.random().toString(36).slice(2, 6)}?api-version=2023-09-01`, { method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ location: "eastus", properties: { hardwareProfile: { vmSize: sz }, storageProfile: { imageReference: rf } } }) }); return { s: r.status, t: await r.text() }; }, [ref, size]);
    const bad = await put({ publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts", version: "latest" }, "Standard_B1s");
    check("[nano] azure VM PUT with a (listed, disabled) Ubuntu image is still refused natively (400 PlatformImageNotFound)", bad.s === 400 && /PlatformImageNotFound/.test(bad.t), bad.t.slice(0, 160));
    const badSz = await put({ publisher: "vyomi", offer: "alpine-nano", sku: "3.21-i386", version: "latest" }, "Standard_D4s_v5");
    check("[nano] azure VM PUT with a disabled size is still refused (409 SkuNotAvailable)", badSz.s === 409 && /SkuNotAvailable/.test(badSz.t), badSz.t.slice(0, 160));
  } else {
    check("[mesh] azure no Nano note", await page.getByText(NOTE).count() === 0);
    check("[mesh] azure Image keeps the catalog, nothing disabled except Windows", imgs.length === 3 && imgs.some((i) => /Ubuntu/.test(i.t)) && imgs.some((i) => /Windows/.test(i.t)) && imgs.every((i) => !i.off || /Windows/.test(i.t)), JSON.stringify(imgs));
    check("[mesh] azure VM architecture offers Arm64 and x64, enabled", azArch.length === 2 && !azArch.some((a) => a.off), JSON.stringify(azArch));
    check("[mesh] azure sizes: none disabled", !azSizes.some((i) => i.off), JSON.stringify(azSizes));
  }
  check(`[${sub}] no page errors`, errors.length === 0, errors.join(" | "));
  await ctx.close();
}
await browser.close();
const bad = results.filter((x) => !x).length;
console.log(bad ? `FAILED ${bad}/${results.length}` : `ALL PASS ${results.length}/${results.length}`);
process.exit(bad ? 1 : 0);
