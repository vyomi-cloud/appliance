/* Amazon SNS console conformance — Nano (in-browser backend, serves wasm/).
 *
 * Same flows as tests/conformance/ui/aws-sns.mjs on the Nano console.
 * Opens Amazon SNS from the service rail, creates a topic with the form's default
 * values, checks every grid column is filled, opens the detail page and every tab,
 * publishes from the Publish tab, exercises subscriptions / mobile push
 * applications / SMS sandbox / message log, checks the space's cost savings moved,
 * then deletes the topic from the UI.
 *
 *   NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-aws-sns.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, RAIL_SEL } from "./lib.mjs";

const DEFAULT_NAME = "MyTopic";   // the create form's default
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const BLANK = /^\s*(-|—|–|undefined|null|nan)?\s*$/i;

const { server, base: BASE } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
const text = (sel) => page.locator(sel).first().innerText().catch(() => "");

async function openRail(label) {
  await page.locator(RAIL_SEL).filter({ hasText: label }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1500);
}
async function gridRows() {
  return page.evaluate(() => {
    const tbl = document.querySelector("#main table.aws, #main table");
    if (!tbl) return { headers: [], rows: [] };
    const trs = [...tbl.querySelectorAll("tr")];
    const headers = [...(trs[0]?.querySelectorAll("th") || [])].map((e) => e.innerText.replace(/[▲▼]/g, "").trim());
    const rows = trs.slice(1).map((tr) => [...tr.querySelectorAll("td")].map((e) => e.innerText.trim())).filter((r) => r.length);
    return { headers, rows };
  });
}
function filled(headers, rows, what) {
  const empty = [];
  rows.forEach((r) => r.forEach((c, i) => { if (headers[i] && BLANK.test(c)) empty.push(`${headers[i]}`); }));
  check(rows.length > 0 && empty.length === 0, `${what}: every column filled`, empty.length ? `blank: ${[...new Set(empty)].join(", ")}` : "no rows");
}
const mk = (method, path, body) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  return r.status;
}, [method, path, body]);
const snsSavings = () => page.evaluate(async () => {
  const j = await (await fetch("/api/spaces")).json();
  const sp = (j.spaces || []).find((s) => s.space_id === j.active_space_id) || (j.spaces || [])[0] || {};
  return Number(((sp.cost_savings || {}).by_service || {})["aws.sns"] || 0);
});

try {
  // start from a clean slate (a previous run may have left the default-named topic)
  await bootConsole(page, BASE, "/aws-console.html");
  await page.evaluate(async (n) => { await fetch(`/api/aws/sns/topics/${n}`, { method: "DELETE" }); }, DEFAULT_NAME);
  await page.waitForTimeout(1500);
  const rail = await page.locator(RAIL_SEL).filter({ hasText: "Amazon SNS" }).count();
  check(rail > 0, "Amazon SNS is on the AWS service rail");
  if (!rail) throw new Error("Amazon SNS missing from the rail");

  await openRail("Amazon SNS");
  check(!(await text("#main")).includes("Failed to load"), "Amazon SNS list loads");
  check(await page.locator("#main button").filter({ hasText: /Create/ }).count() > 0, "Create button is shown");

  // ── create with the form defaults ──────────────────────────────────────
  const before = await snsSavings();
  await page.locator("#main button").filter({ hasText: /Create/ }).first().click();
  await page.waitForTimeout(1200);
  const defaults = await page.evaluate(() => [...document.querySelectorAll("#main input")].map((i) => i.value));
  check(defaults.includes(DEFAULT_NAME), "create form has realistic defaults", JSON.stringify(defaults));
  let created = null;
  page.on("response", (r) => { if (r.request().method() === "POST" && /\/api\/aws\/sns\/topics$/.test(r.url())) created = r.status(); });
  await page.locator("#main .wizard-footer button.primary, #main button.primary").filter({ hasText: /Create/ }).last().click();
  for (let i = 0; i < 20 && created === null; i++) await page.waitForTimeout(400);
  check(created === 200, "create with defaults returns 200", `HTTP ${created}`);
  await page.waitForTimeout(1500);
  if (!(await text("#main")).includes(DEFAULT_NAME)) await openRail("Topics");

  const { headers, rows } = await gridRows();
  check(rows.some((r) => r.includes(DEFAULT_NAME)), "new topic appears in the grid", JSON.stringify(rows));
  check(["Name", "Type", "ARN", "Subscriptions confirmed", "Subscriptions pending", "Display name", "Encryption", "Created"].every((h) => headers.includes(h)),
    "grid has the expected columns", headers.join(", "));
  filled(headers, rows, "topics grid");
  check(rows.some((r) => r.includes("Standard")), "topic is a Standard topic");
  await page.waitForTimeout(500);
  check((await snsSavings()) > before, "creating a topic moves the space's cost-savings metrics", `${before} -> ${await snsSavings()}`);

  // ── detail page + every tab ────────────────────────────────────────────
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME }).first().click();
  await page.waitForTimeout(1800);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((e) => e.innerText.trim()).filter(Boolean));
  check(tabs.length >= 3, "detail page has tabs", tabs.join(", "));
  for (const t of tabs) {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp(`^${t}$`) }).first().click();
    await page.waitForTimeout(900);
    const body = await page.evaluate(() => {
      const kids = [...document.querySelectorAll("#main > *")];
      const host = kids[kids.length - 1];
      return host ? host.innerText : "";
    });
    check(body.trim().length > 25 && !/Renderer error|Not yet wired|Failed to load|undefined/i.test(body), `detail tab "${t}" renders`, body.slice(0, 80));
  }
  const summary = await text("#main .summary-grid");
  check(/arn:aws:sns/.test(summary) && /Standard/.test(summary), "detail summary shows the topic's real values", summary.slice(0, 160));

  // ── publish from the Publish tab ───────────────────────────────────────
  await page.locator("#main .top-tabs button").filter({ hasText: /^Publish message$/ }).first().click();
  await page.waitForTimeout(800);
  let published = null;
  page.on("response", (r) => { if (r.request().method() === "POST" && /\/topics\/MyTopic\/publish$/.test(r.url())) published = r.status(); });
  await page.locator("#main button").filter({ hasText: /Publish message/ }).last().click();
  for (let i = 0; i < 20 && published === null; i++) await page.waitForTimeout(400);
  check(published === 200, "Publish message from the tab returns 200", `HTTP ${published}`);

  // ── child lists: create through the console REST, see them in the grid ──
  const kids = [
    ["subscriptions", "Subscriptions", { topic: DEFAULT_NAME, protocol: "email", endpoint: "ui-dev@example.net" }, "ui-dev@example.net", null],
    ["platform-applications", "Mobile push applications", { name: "ui-push", platform: "GCM" }, "ui-push", "ui-push"],
    ["sms-sandbox", "SMS sandbox", { phone: "+15555550123" }, "+15555550123", "+15555550123"],
  ];
  for (const [kind, label, body, shown, delName] of kids) {
    check((await mk("POST", `/api/aws/sns/${kind}`, body)) === 200, `create ${label.toLowerCase()} entry`);
    await openRail(label);
    const g = await gridRows();
    check(g.rows.some((r) => r.includes(shown)), `${label} grid lists the new entry`, JSON.stringify(g.rows.slice(0, 2)));
    filled(g.headers, g.rows, label);
    if (delName) await mk("DELETE", `/api/aws/sns/${kind}/${encodeURIComponent(delName)}`);
  }
  // message log: the pending email subscription and a publish to the confirmed one are recorded
  const subs = await page.evaluate(async () => (await (await fetch("/api/aws/sns/subscriptions")).json()).items);
  const mine = subs.find((x) => x.endpoint === "ui-dev@example.net");
  check(mine && (await mk("POST", `/api/aws/sns/subscriptions/${mine.name}/confirm`)) === 200, "confirm the pending email subscription");
  check((await mk("POST", `/api/aws/sns/topics/${DEFAULT_NAME}/publish`, { message: "to-the-log", subject: "ui" })) === 200, "publish to the confirmed subscription");
  await openRail("Message log");
  const log = await gridRows();
  check(log.rows.some((r) => r.includes("SubscriptionConfirmation")), "Message log lists the subscription confirmation", JSON.stringify(log.rows.slice(0, 2)));
  check(log.rows.some((r) => r.includes("Notification")), "Message log lists the published notification", JSON.stringify(log.rows.slice(0, 3)));
  filled(log.headers, log.rows, "Message log");

  // ── delete from the UI ─────────────────────────────────────────────────
  await openRail("Topics");
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME }).first().click();
  await page.waitForTimeout(1500);
  await page.locator("#main button").filter({ hasText: /Delete/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(2000);
  if (!(await text("#main")).includes("You have no") && (await text("#main")).includes(DEFAULT_NAME)) await openRail("Topics");
  const after = await gridRows();
  check(!after.rows.some((r) => r.includes(DEFAULT_NAME)), "topic is gone after Delete", JSON.stringify(after.rows));
  await mk("DELETE", "/api/aws/sns/deliveries");
  check(!bad.length, "no API 5xx during the flow", bad.join(", "));
} catch (e) {
  check(false, "Amazon SNS console flow", String(e.message || e).split("\n")[0]);
} finally {
  await browser.close();
  server.close();
}
console.log(`sns ui (nano): ${fails ? "FAILED" : "ok"}`);
process.exit(fails ? 1 : 0);
