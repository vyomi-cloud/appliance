/* Nano console conformance for the Key Vault blade's Secrets and Keys tabs: they are backed by the
 * /azure-data/keyvault/{vault}/secrets|keys data plane (served in-browser by the KV cores), a secret and
 * a key added in the blade are listed, a saved secret value survives re-opening the tab, delete works.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-keyvault-tabs.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const bad = [];
page.on("response", (r) => { if (r.status() >= 400 && r.url().includes("/azure-data/keyvault/") && r.request().method() === "GET" && !/\/(secrets|keys)\/[^/]+$/.test(r.url())) bad.push(`${r.status()} ${r.url().replace(base, "")}`); });
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const answers = [];
page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()).catch(() => {}));

const openTab = (label) => page.evaluate(async (label) => {
  const el = [...document.querySelectorAll(".sub-nav-item")].find((e) => (e.querySelector(".lbl")?.innerText || e.innerText || "").trim() === label);
  if (!el) return false;
  el.click();
  await new Promise((r) => setTimeout(r, 1200));
  return true;
}, label);
const content = () => page.locator(".sub-content").innerText();

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  bad.length = 0;
  await page.evaluate(async () => {
    const svc = CATALOG.services.find((s) => s.key === "keyvault");
    const body = { location: LOCATION, properties: {} };
    (svc.createFields || []).forEach((f) => { if (f.name && f.name !== "name" && f.default !== undefined) setPath(body, f.name, f.default); });
    const put = await arm("PUT", resPath(svc, "kv-uitest"), body, svc.apiVersion);
    await openDetail(svc, put.json || { id: resPath(svc, "kv-uitest"), name: "kv-uitest", ...body });
    for (let i = 0; i < 40 && !document.querySelectorAll(".sub-nav-item").length; i++) await new Promise((r) => setTimeout(r, 120));
  });

  check(await openTab("Secrets"), "vault blade has a Secrets tab");
  check(!/could not load/i.test(await content()), "Secrets tab loads from the data plane", (await content()).slice(0, 80));
  answers.push("db-password", "s3cr3t-v1");
  await page.locator(".sub-content button").filter({ hasText: /New secret/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/db-password/.test(await content()), "secret added in the blade is listed");
  await openTab("Overview"); await openTab("Secrets");
  check(/db-password/.test(await content()), "secret is still listed after re-opening the tab");
  const val = await page.evaluate(async () => (await (await fetch("/azure-data/keyvault/kv-uitest/secrets/db-password")).json()).value);
  check(val === "s3cr3t-v1", "secret value is readable from the data plane", String(val));
  page.once("dialog", () => {});
  await page.locator(".sub-content button[title='Delete secret']").first().click({ timeout: 5000 });
  await sleep(1500);
  check(!/db-password/.test(await content()), "deleting the secret removes it from the list");

  check(await openTab("Keys"), "vault blade has a Keys tab");
  check(!/could not load/i.test(await content()), "Keys tab loads from the data plane", (await content()).slice(0, 80));
  answers.push("signing-key");
  await page.locator(".sub-content button").filter({ hasText: /New key/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/signing-key/.test(await content()) && /Enabled/.test(await content()), "key added in the blade is listed as Enabled");
  await page.locator(".sub-content button[title='Disable key']").first().click({ timeout: 5000 });
  await sleep(1500);
  await openTab("Overview"); await openTab("Keys");
  check(/Disabled/.test(await content()), "disabled state survives re-opening the tab");
  await page.locator(".sub-content button[title='Delete key']").first().click({ timeout: 5000 });
  await sleep(1500);
  check(!/signing-key/.test(await content()), "deleting the key removes it from the list");
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
process.exit(fails ? 1 : 0);
