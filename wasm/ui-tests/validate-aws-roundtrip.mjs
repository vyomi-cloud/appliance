/* AWS Nano UI <-> SDK bi-directional round-trip (check 5).
 * A: UI creates -> boto3 sees it   B: boto3 creates -> UI lists it
 * C: boto3 deletes -> UI no longer lists   D: UI deletes -> boto3 no longer sees it
 * Env: RELAY_HTTP (relay base, also the SDK endpoint), NANO_DIR, PY (python with boto3), ONLY=s3,sqs */
import { chromium, sleep, RAIL_SEL, startServer, bootConsole, RELAY } from "./lib.mjs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const HERE = dirname(fileURLToPath(import.meta.url));
const SDK = join(HERE, "_aws_roundtrip_sdk.py");
const PY = process.env.PY || "python3";
const sdk = (svc, op, name) => JSON.parse(execFileSync(PY, [SDK, svc, op, name], { env: { ...process.env, VYOMI_BASE_URL: RELAY }, encoding: "utf8" }).trim().split("\n").pop());
const ONLY = (process.env.ONLY || "s3,sqs,sns,dynamodb,kms,secretsmanager").split(",");
const RAIL = { s3: /^s3$|simple storage/i, sqs: /\bsqs\b/i, sns: /\bsns\b/i, dynamodb: /dynamodb/i, kms: /\bkms\b|key management/i, secretsmanager: /secrets/i };

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
await page.addInitScript((r) => { try { localStorage.setItem("nano_local_ext", r); localStorage.setItem("nano_local_health", r + "/health"); localStorage.setItem("nano_local_ws", r.replace(/^http/, "ws") + "/register"); localStorage.setItem("nano_tunnel_on", "1"); localStorage.setItem("nano_relay_mode", "local"); } catch (_) {} }, RELAY);
page.on("dialog", (d) => d.accept("delete").catch(() => {}));
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
const openSvc = async (svc) => { await page.evaluate(([sel, re]) => { const r = new RegExp(re.s, re.f); [...document.querySelectorAll(sel)].find((e) => r.test(e.innerText.trim()))?.click(); }, [RAIL_SEL, { s: RAIL[svc].source, f: RAIL[svc].flags }]); await sleep(1500); };
const dump = () => page.evaluate(() => [...document.querySelectorAll("button")].filter((e) => e.offsetParent).map((e) => e.innerText.trim().replace(/\n/g, " ")).filter(Boolean).slice(-14).join(" | "));
const mainText = () => page.evaluate(() => document.querySelector("#main")?.innerText || "");
const listed = async (svc, name) => { await openSvc(svc); await sleep(800); return (await mainText()).includes(name); };

const vis = (sel, re) => page.locator(sel, { hasText: re }).filter({ visible: true });
async function cancelWizard() { await page.locator("button", { hasText: /maybe later/i }).first().click({ timeout: 500 }).catch(() => {}); for (let i = 0; i < 3; i++) { const c = vis("button", /^\s*cancel\s*$/i); if (await c.count() === 0) break; await c.first().click().catch(() => {}); await sleep(300); } }
async function uiCreate(svc, name) {
  await cancelWizard(); await openSvc(svc);
  await page.locator("#main button", { hasText: /create/i }).filter({ visible: true }).first().click({ timeout: 8000 });
  await sleep(1000);
  const INP = "input:visible:not(#topSearch):not([type=radio]):not([type=checkbox]):not([type=file]):not([type=number]), textarea:visible";
  const fillName = async () => { const els = page.locator(INP); for (let i = 0; i < await els.count(); i++) { const e = els.nth(i); const v = await e.inputValue().catch(() => "x"); if (!v || /^(my|My|Music)/.test(v)) await e.fill(name).catch(() => {}); } };
  const FINAL = /^\s*(rocket_launch\s*)?create(?!\s+resource)(\s+\w+)?\s*$/i;
  await fillName();
  for (let i = 0; i < 10 && (await vis("#main button, .wizard button, .modal button, button", FINAL).count()) === 0; i++) { const nx = vis("button", /^\s*(next|review and create)/i); if (await nx.count() === 0) break; await nx.last().click(); await sleep(600); await fillName(); }
  await vis("button", FINAL).last().click({ timeout: 8000 });
  await sleep(3000);
}
let step = "";
async function uiDelete(svc, name) {
  await cancelWizard(); await openSvc(svc);
  step = "select row";
  const row = page.locator("#main tr", { hasText: name }).first();
  await row.locator("input[type=checkbox], input[type=radio]").first().click({ timeout: 8000 });
  step = "open Actions"; await page.locator("#main button", { hasText: /actions/i }).first().click({ timeout: 8000 }); await sleep(500);
  step = "Delete menu item"; await vis("li, a, button, [role=menuitem]", /^\s*(permanently )?delete/i).first().click({ timeout: 8000 }); await sleep(800);
  step = "confirm"; await sleep(800);
  const confirm = page.locator("input:visible:not(#topSearch):not([type=checkbox])").last();
  if (await confirm.count()) await confirm.fill("delete").catch(() => {});
  const ok = vis(".modal button, [role=dialog] button, .dialog button", /^\s*(permanently )?delete\b/i);
  if (await ok.count()) await ok.last().click({ timeout: 8000 });
  await sleep(3000);
}

try {
  await bootConsole(page, base, "/aws-console.html");
  for (let i = 0; i < 60 && !(await (await fetch(RELAY + "/health")).json()).tab; i++) await sleep(1000);
  for (const svc of ONLY) {
    await page.goto(base + "/aws-console.html", { waitUntil: "domcontentloaded" });
    await page.waitForFunction((sel) => navigator.serviceWorker?.controller && document.querySelectorAll(sel).length > 0, RAIL_SEL, { timeout: 120000, polling: 500 });
    for (let i = 0; i < 60 && !(await (await fetch(RELAY + "/health")).json()).tab; i++) await sleep(1000);
    await sleep(1500);
    let aOk = false;
    const tag = `[${svc}]`; const a = "rta" + Date.now().toString(36), b = "rtb" + Date.now().toString(36);
    try { await uiCreate(svc, a); const d = sdk(svc, "describe", a); aOk = !!d.exists; check(`${tag} A UI create -> SDK sees it`, aOk, JSON.stringify(d) + (aOk ? "" : ` | UI lists it: ${await listed(svc, a)} | toast/main: ${(await mainText()).replace(/\s+/g, " ").slice(0, 220)}`)); } catch (e) { check(`${tag} A UI create -> SDK sees it`, false, String(e).split("\n")[0] + " BTNS: " + await dump()); }
    try { const c = sdk(svc, "create", b); check(`${tag} B SDK create -> UI lists it`, await listed(svc, b), JSON.stringify(c)); } catch (e) { check(`${tag} B SDK create -> UI lists it`, false, String(e).split("\n")[0]); }
    try { sdk(svc, "delete", b); check(`${tag} C SDK delete -> UI drops it`, !(await listed(svc, b))); } catch (e) { check(`${tag} C SDK delete -> UI drops it`, false, String(e).split("\n")[0]); }
    if (!aOk) { check(`${tag} D UI delete -> SDK no longer sees it`, false, "skipped: A failed, nothing to delete"); continue; }
    try { await uiDelete(svc, a); const d = sdk(svc, "describe", a); check(`${tag} D UI delete -> SDK no longer sees it`, !d.exists, JSON.stringify(d)); } catch (e) { check(`${tag} D UI delete -> SDK no longer sees it`, false, `step=${step}: ` + String(e).split("\n")[0].slice(0, 400)); }
  }
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
