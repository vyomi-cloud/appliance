/* Nano console validation — AWS CloudWatch (the in-browser Nano bundle, same flows as the offline console).
 *
 * Boots the Nano AWS console, creates an alarm with the form's DEFAULT values, checks every grid
 * column is filled, renders every detail tab, deletes it — and cross-checks the alarm through the
 * Nano relay with the real wire (Query `DescribeAlarms`), the way aws-cli / an SDK would.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-cloudwatch.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, RAIL_SEL, RELAY } from "./lib.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const STACK = "my-alarm";   // the create form's default name (an alarm, here)

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let createStatus = null;
page.on("dialog", (d) => d.accept().catch(() => {}));
page.on("response", (r) => {
  if (r.request().method() === "POST" && /\/api\/aws\/cloudwatch\/alarms/.test(r.url())) createStatus = r.status();
});
const api = (method, path) => page.evaluate(async ([m, p]) => {
  const r = await fetch(p, { method: m });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [method, path]);
try {
  await bootConsole(page, base, "/aws-console.html");
  await api("DELETE", `/api/aws/cloudwatch/alarms/${STACK}`);
  const rail = page.locator(RAIL_SEL).filter({ hasText: /CloudWatch\s*$/ }).first();
  check(await rail.count() > 0, "CloudWatch is on the Nano AWS console rail");
  await rail.click({ timeout: 5000 });
  await page.waitForTimeout(1500);

  await page.locator("#main button, #main [role=button]").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1200);
  check((await page.locator("#main input").count()) >= 2, "create form shows the alarm name + metric fields");
  await page.locator("#main button.primary, #main button").filter({ hasText: /^\s*create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 40 && createStatus === null; i++) await page.waitForTimeout(500);
  check(createStatus !== null && createStatus < 300, "create with the default values returns 2xx", `HTTP ${createStatus}`);

  await page.waitForTimeout(1500);
  const headers = await page.locator("#main table th").allInnerTexts();
  const cells = await page.locator("#main table tr:has(td)").filter({ hasText: STACK }).first().locator("td").allInnerTexts();
  check(cells.length > 0, "the new alarm appears in the list", `rows with ${STACK}: ${cells.length}`);
  const dataCells = cells.slice(Math.max(0, cells.length - headers.length));   // skip a leading checkbox cell
  const blank = dataCells.map((c, i) => [headers[i], c.trim()]).filter(([h, c]) => (c === "" || c === "-" || c === "—") && h.trim() !== "");
  check(cells.length > 0 && !blank.length, "every grid column of the new row is filled", `blank: ${JSON.stringify(blank)}`);
  check(cells.some((c) => /INSUFFICIENT_DATA/.test(c)), "alarm state is INSUFFICIENT_DATA until data arrives", cells.join(" | "));

  // when a Nano tab is registered on the relay, the console-created alarm is visible on the native wire
  const health = await fetch(RELAY + "/health").then((r) => r.json()).catch(() => ({}));
  if (health.tab) {
    const r = await fetch(RELAY + "/", { method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded",
        authorization: "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/monitoring/aws4_request, SignedHeaders=host, Signature=x" },
      body: "Action=DescribeAlarms&Version=2010-08-01" }).catch(() => null);
    const xml = r ? await r.text() : "";
    check(r && r.ok && xml.includes(`<AlarmName>${STACK}</AlarmName>`), "the alarm is visible through the relay's native CloudWatch wire", xml.slice(0, 160));
  }

  await page.locator("#main table a.id, #main table td a").filter({ hasText: STACK }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const tabs = await page.locator("#main .top-tabs button").allInnerTexts();
  for (const want of ["Details", "History", "Actions"])
    check(tabs.some((t) => t.trim() === want), `detail tab "${want}" is present`, tabs.join(", "));
  for (let i = 0; i < tabs.length; i++) {
    await page.locator("#main .top-tabs button").nth(i).click();
    await page.waitForTimeout(500);
    const txt = await page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText.trim() : ""; });
    check(txt.length >= 10, `detail tab "${tabs[i].trim()}" renders content`, `len=${txt.length}`);
  }
  const detTab = tabs.findIndex((t) => t.trim() === "Details");
  await page.locator("#main .top-tabs button").nth(detTab).click();
  await page.waitForTimeout(500);
  const detText = await page.locator("#main").innerText();
  check(/CPUUtilization/.test(detText) && /AWS\/EC2/.test(detText), "Details tab shows the metric the alarm watches");
  const actTab = tabs.findIndex((t) => t.trim() === "Actions");
  await page.locator("#main .top-tabs button").nth(actTab).click();
  await page.waitForTimeout(500);
  check(/arn:aws:sns:us-east-1:123456789012:alerts/.test(await page.locator("#main").innerText()), "Actions tab lists the SNS alarm action");

  await page.locator("#main button").filter({ hasText: /delete/i }).last().click({ timeout: 5000 });
  let gone = false;
  for (let i = 0; i < 12 && !gone; i++) {
    await page.waitForTimeout(800);
    gone = (await page.locator("#main table tr:has(td)").filter({ hasText: STACK }).count()) === 0;
  }
  check(gone, "deleting the alarm removes it from the list");
  const list = await api("GET", "/api/aws/cloudwatch/alarms");
  check(!(list.body.items || []).some((s) => s.name === STACK), "alarm is gone from the store too");
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
