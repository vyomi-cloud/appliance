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
const browser = await pw.chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1300 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const ready = () => page.waitForFunction(() => window.__vyomiNanoReady === true, null, { timeout: 180000 });

// ── cloud adapters: start page, create the VM through the wire, open its detail ──
const A = {
  aws: {
    home: "#/ec2",
    async create() {
      const ec2 = (action, params) => page.evaluate(async ([u, a, p]) => (await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2016-11-15", ...p }).toString() })).text(), [WIRE, action, params]);
      const ami = (await ec2("DescribeImages", {})).match(/<imageId>(ami-\w+)<\/imageId>/)[1];
      return (await ec2("RunInstances", { ImageId: ami, MinCount: "1", MaxCount: "1", InstanceType: "t3.micro" })).match(/<instanceId>(i-\w+)<\/instanceId>/)[1];
    },
    detail: (id) => `#/ec2/instances/${id}`,
    list: "#/ec2/instances",
    pending: (page) => page.locator('[data-vy-pending]').first(),
  },
};
const cl = A[CLOUD];
await page.goto(UI + cl.home);
await ready();
check("Nano backend ready", true);
const vmId = await cl.create();
check("instance created through the wire", !!vmId, vmId);

// 1. flag off -> honest panel
await page.goto(UI + cl.detail(vmId));
await page.evaluate(() => { window.__noReload = "same-page"; });
await page.getByRole("button", { name: /^Connect$/ }).first().click();
await page.getByText(/In-browser VMs are off/i).first().waitFor({ timeout: 30000 }).catch(async (e) => { await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-fail.png` }); console.log((await page.locator("body").innerText()).slice(0, 600)); throw e; });
check("flag off: honest 'In-browser VMs are off' panel with a Turn on button", await page.getByRole("button", { name: /Turn on in-browser VMs/ }).isVisible());
check("flag off: no Not-simulated panel", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
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
    await page.waitForFunction(() => /\brunning\b/i.test(document.querySelector("main, #root")?.innerText || "") && !document.querySelector("[data-vy-pending]"), null, { timeout: 240000, polling: 2000 });
    check("list: state flipped pending -> running without a manual reload", true);
  } catch { check("list: state flipped pending -> running without a manual reload", false, "VM did not boot within 240 s"); }
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-running.png` });
  await page.goto(UI + cl.detail(vmId)); await ready();
  await page.getByTestId("open-shell").click().catch(async () => { await page.getByRole("button", { name: /^Connect$/ }).first().click(); });
  const term = page.locator(".vy-term .xterm-helper-textarea, .vy-term textarea").first();
  await term.waitFor({ state: "attached", timeout: 60000 });
  await page.locator(".vy-term").first().click();
  await page.keyboard.type("echo hi-from-$((40+2))\r", { delay: 40 });
  try {
    await page.waitForFunction(() => /^hi-from-42$/m.test(document.querySelector(".vy-term")?.innerText || ""), null, { timeout: 60000 });
    check("shell: typed command ran in the VM (echo -> hi-from-42)", true);
  } catch { check("shell: typed command ran in the VM", false, (await page.locator(".vy-term").first().innerText()).slice(-200)); }
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-shell.png` });
  // a power repaint (the event the host fires on a state change) must not yank the open shell
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("nano-vm-power", { detail: { id: null, state: "running" } })));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/browservm-${CLOUD}-repaint.png` });
  if (process.env.DBG) console.log(await page.evaluate(() => JSON.stringify({ terms: document.querySelectorAll(".vy-term").length, html: (document.querySelector(".vy-term")?.innerHTML || "").slice(0, 600), shells: document.querySelectorAll("[data-nano-shell]").length })));
  check("shell survives a power-state repaint (session kept)", /^hi-from-42$/m.test(await page.locator(".vy-term").first().innerText().catch(() => "")));
}
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
