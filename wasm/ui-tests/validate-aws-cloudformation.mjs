/* Nano console validation — AWS CloudFormation (the in-browser Nano bundle, same flows as the offline console).
 *
 * Boots the Nano AWS console, creates a stack with the form's DEFAULT values, checks every grid
 * column is filled, renders every detail tab, deletes it — and cross-checks the stack through the
 * Nano relay with the real wire (Query `ListStacks`), the way aws-cli / an SDK would.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-cloudformation.mjs
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
const STACK = "my-stack";   // the create form's default name

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let createStatus = null;
page.on("dialog", (d) => d.accept().catch(() => {}));
page.on("response", (r) => {
  if (r.request().method() === "POST" && /\/api\/aws\/cloudformation\/stacks/.test(r.url())) createStatus = r.status();
});
const api = (method, path) => page.evaluate(async ([m, p]) => {
  const r = await fetch(p, { method: m });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [method, path]);
try {
  await bootConsole(page, base, "/aws-console.html");
  await api("DELETE", `/api/aws/cloudformation/stacks/${STACK}`);
  const rail = page.locator(RAIL_SEL).filter({ hasText: /CloudFormation/i }).first();
  check(await rail.count() > 0, "CloudFormation is on the Nano AWS console rail");
  await rail.click({ timeout: 5000 });
  await page.waitForTimeout(1500);

  await page.locator("#main button, #main [role=button]").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1200);
  check((await page.locator("#main input").count()) >= 2, "create form shows the stack name + template fields");
  await page.locator("#main button.primary, #main button").filter({ hasText: /^\s*create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 40 && createStatus === null; i++) await page.waitForTimeout(500);
  check(createStatus !== null && createStatus < 300, "create with the default values returns 2xx", `HTTP ${createStatus}`);

  await page.waitForTimeout(1500);
  const headers = await page.locator("#main table th").allInnerTexts();
  const cells = await page.locator("#main table tr:has(td)").filter({ hasText: STACK }).first().locator("td").allInnerTexts();
  check(cells.length > 0, "the new stack appears in the list", `rows with ${STACK}: ${cells.length}`);
  const dataCells = cells.slice(Math.max(0, cells.length - headers.length));   // skip a leading checkbox cell
  const blank = dataCells.map((c, i) => [headers[i], c.trim()]).filter(([h, c]) => (c === "" || c === "-" || c === "—") && h.trim() !== "");
  check(cells.length > 0 && !blank.length, "every grid column of the new row is filled", `blank: ${JSON.stringify(blank)}`);
  check(cells.some((c) => /CREATE_COMPLETE/.test(c)), "stack status is CREATE_COMPLETE", cells.join(" | "));

  // when a Nano tab is registered on the relay, the console-created stack is visible on the native wire
  const health = await fetch(RELAY + "/health").then((r) => r.json()).catch(() => ({}));
  if (health.tab) {
    const r = await fetch(RELAY + "/", { method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded",
        authorization: "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/cloudformation/aws4_request, SignedHeaders=host, Signature=x" },
      body: "Action=ListStacks&Version=2010-05-15" }).catch(() => null);
    const xml = r ? await r.text() : "";
    check(r && r.ok && xml.includes(`<StackName>${STACK}</StackName>`), "the stack is visible through the relay's native CloudFormation wire", xml.slice(0, 160));
  }

  await page.locator("#main table a.id, #main table td a").filter({ hasText: STACK }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const tabs = await page.locator("#main .top-tabs button").allInnerTexts();
  for (const want of ["Resources", "Events", "Outputs", "Parameters", "Template", "Change sets"])
    check(tabs.some((t) => t.trim() === want), `detail tab "${want}" is present`, tabs.join(", "));
  for (let i = 0; i < tabs.length; i++) {
    await page.locator("#main .top-tabs button").nth(i).click();
    await page.waitForTimeout(500);
    const txt = await page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText.trim() : ""; });
    check(txt.length >= 10, `detail tab "${tabs[i].trim()}" renders content`, `len=${txt.length}`);
  }
  const resTab = tabs.findIndex((t) => t.trim() === "Resources");
  await page.locator("#main .top-tabs button").nth(resTab).click();
  await page.waitForTimeout(500);
  const resText = await page.locator("#main").innerText();
  check(/AWS::S3::Bucket/.test(resText) && /AWS::SQS::Queue/.test(resText), "Resources tab lists the bucket and the queue");

  await page.locator("#main button").filter({ hasText: /delete/i }).last().click({ timeout: 5000 });
  let gone = false;
  for (let i = 0; i < 12 && !gone; i++) {
    await page.waitForTimeout(800);
    gone = (await page.locator("#main table tr:has(td)").filter({ hasText: STACK }).count()) === 0;
  }
  check(gone, "deleting the stack removes it from the list");
  const list = await api("GET", "/api/aws/cloudformation/stacks");
  check(!(list.body.items || []).some((s) => s.name === STACK), "stack is gone from the store too");
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
