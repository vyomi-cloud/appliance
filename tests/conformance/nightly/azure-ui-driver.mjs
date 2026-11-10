// Azure console driver for the round-trip check (UI side): node azure-ui-driver.mjs <create|read|delete> <rg-name>
// Prints one JSON line: {ok, data?, error?}. Needs VYOMI_CONSOLE_URL (e.g. http://localhost:9100/console/azure) and playwright on NODE_PATH.
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright"); // require() honours NODE_PATH, ESM import does not
const [cmd, name] = process.argv.slice(2);
const url = process.env.VYOMI_CONSOLE_URL;
const out = (o) => { console.log(JSON.stringify(o)); process.exit(o.ok ? 0 : 1); };
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await (await browser.newContext()).newPage();
const route = async (hash) => { await page.goto(`${url}#${hash}`, { waitUntil: "domcontentloaded" }); await page.reload({ waitUntil: "domcontentloaded" }); };
try {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#navItems .navitem, #root *", { timeout: 60000 });
  if (cmd === "create") {
    await route("/resourcegroups/create");
    await page.getByLabel("Resource group name").fill(name);
    await page.getByRole("button", { name: /Review \+ create/ }).first().click();
    await page.getByRole("button", { name: /^Create$/ }).first().click();
    await page.waitForFunction((n) => document.body.innerText.includes(n) && !/Review \+ create/.test(document.body.innerText), name, { timeout: 20000 }).catch(() => {});
    out({ ok: true });
  } else if (cmd === "read") {
    await route("/resourcegroups");
    await page.waitForFunction(() => document.querySelectorAll("table tr td").length > 0 || /No resource groups/i.test(document.body.innerText), null, { timeout: 20000 }).catch(() => {});
    const row = page.locator("table tr", { hasText: name }).first();
    if (!(await row.count())) out({ ok: true, data: null });
    const cells = (await row.locator("td").allInnerTexts()).map((s) => s.trim());
    out({ ok: true, data: { name: cells.find((c) => c === name) || cells[0], cells } });
  } else if (cmd === "delete") {
    await route(`/resourcegroups/${encodeURIComponent(name)}/delete`);
    await page.getByLabel("Enter resource group name to confirm deletion").fill(name);
    await page.getByRole("button", { name: /^Delete$/ }).first().click();
    await page.waitForTimeout(1500);
    out({ ok: true });
  } else out({ ok: false, error: "unknown command" });
} catch (e) { out({ ok: false, error: String(e.message || e).split("\n")[0] }); }
finally { await browser.close(); }
