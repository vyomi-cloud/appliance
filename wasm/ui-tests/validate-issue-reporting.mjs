/* Issue reporting UI: the consent dialog shows ONCE after sign-in, "Not now" is as visible as
 * "Yes", the choice is saved (PUT mode), never shown again, and Settings -> Issue reporting
 * changes the mode. Offline: VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws. Nano: no URL
 * (NANO_DIR). The settings endpoint is mocked (the portal account / appliance licence is the
 * real owner of the choice; this checks the console side). */
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = "1";   // let context.route see SW fetches (Nano)
import { chromium, sleep, RAIL_SEL, startServer, bootConsole } from "./lib.mjs";

let url = process.env.VYOMI_CONSOLE_URL, server = null, nanoBase = null;
if (!url) { const s = await startServer(); server = s.server; nanoBase = s.base; }
const nano = !url;
const SETTINGS = nano ? "**/api/issues/settings" : "**/api/issue-reporting";
const browser = await chromium.launch();
const context = await browser.newContext();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
const state = { mode: null, puts: [] };
await context.route(SETTINGS, async (route) => {
  const req = route.request();
  if (req.method() === "PUT") { const m = JSON.parse(req.postData() || "{}").mode; state.mode = m; state.puts.push(m); return route.fulfill({ json: { mode: m, consent_asked: true, enabled: true } }); }
  return route.fulfill({ json: { mode: state.mode, consent_asked: !!state.mode, signed_in: true, enabled: true } });
});
const open = async () => {
  const page = await context.newPage();
  if (nano) await bootConsole(page, nanoBase, "/aws-console.html");
  else { await page.goto(url, { waitUntil: "domcontentloaded" }); await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 }); }
  return page;
};
try {
  let page = await open();
  await page.waitForSelector("#vyomi-consent", { timeout: 15000 });
  const txt = await page.innerText("#vyomi-consent");
  check("dialog shows the approved copy", /Help us make Vyomi better for you/.test(txt) && /under your GitHub account/.test(txt) && /never send your data, secrets, keys or resource names/.test(txt) && /anonymous reports/.test(txt), txt.slice(0, 200));
  const yes = await page.locator("#vyomi-consent-yes").boundingBox(), no = await page.locator("#vyomi-consent-no").boundingBox();
  check("'Not now' is as visible as the main button", no && yes && no.height >= yes.height * 0.9 && no.width > 60);
  await page.click("#vyomi-consent-no");
  await sleep(800);
  check("'Not now' saves anonymous mode", state.puts.at(-1) === "anonymous", JSON.stringify(state));
  check("dialog closes after the choice", (await page.locator("#vyomi-consent").count()) === 0);
  await page.close();

  page = await open();
  await sleep(4000);
  check("dialog never shows again after a choice", (await page.locator("#vyomi-consent").count()) === 0);
  await page.click("#vyomi-ir-link");
  await page.waitForSelector("#vyomi-ir-settings");
  check("Settings shows the current mode (anonymous)", await page.locator("#vyomi-ir-anonymous").isChecked());
  await page.click("#vyomi-ir-named");
  await sleep(600);
  check("Settings toggle changes the mode to named", state.puts.at(-1) === "named", JSON.stringify(state));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
