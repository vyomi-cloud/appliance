/* Amazon SES (v2) console conformance — Nano (in-browser backend, serves wasm/).
 *
 * Same flows as tests/conformance/ui/aws-sesv2.mjs on the Nano console. Opens Amazon SES from the service rail, creates a verified identity with the
 * form's default values, checks every grid column is filled, opens the detail page
 * and every tab, exercises configuration sets / templates / contact lists /
 * suppression list / sent emails, checks the space's cost savings moved, then
 * deletes the identity from the UI.
 *
 *   NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-aws-sesv2.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, RAIL_SEL } from "./lib.mjs";

const DEFAULT_NAME = "noreply@vyomi.example.com";   // the create form's default
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
const sesSavings = () => page.evaluate(async () => {
  const j = await (await fetch("/api/spaces")).json();
  const sp = (j.spaces || []).find((s) => s.space_id === j.active_space_id) || (j.spaces || [])[0] || {};
  return Number((sp.cost_savings || {}).savings_usd || 0);
});

try {
  // start from a clean slate (a previous run may have left the default-named identity)
  await bootConsole(page, BASE, "/aws-console.html");
  await page.evaluate(async (n) => { await fetch(`/api/aws/sesv2/identities/${encodeURIComponent(n)}`, { method: "DELETE" }); }, DEFAULT_NAME);
  await page.waitForTimeout(1500);
  const rail = await page.locator(RAIL_SEL).filter({ hasText: "Amazon SES" }).count();
  check(rail > 0, "Amazon SES is on the AWS service rail");
  if (!rail) throw new Error("Amazon SES missing from the rail");

  await openRail("Amazon SES");
  check(!(await text("#main")).includes("Failed to load"), "Amazon SES list loads");
  check(await page.locator("#main button").filter({ hasText: /Create/ }).count() > 0, "Create button is shown");

  // ── create with the form defaults ──────────────────────────────────────
  const before = await sesSavings();
  await page.locator("#main button").filter({ hasText: /Create/ }).first().click();
  await page.waitForTimeout(1200);
  const defaults = await page.evaluate(() => [...document.querySelectorAll("#main input")].map((i) => i.value));
  check(defaults.includes(DEFAULT_NAME), "create form has realistic defaults", JSON.stringify(defaults));
  let created = null;
  page.on("response", (r) => { if (r.request().method() === "POST" && /\/api\/aws\/sesv2\/identities$/.test(r.url())) created = r.status(); });
  await page.locator("#main .wizard-footer button.primary, #main button.primary").filter({ hasText: /Create/ }).last().click();
  for (let i = 0; i < 20 && created === null; i++) await page.waitForTimeout(400);
  check(created === 200, "create with defaults returns 200", `HTTP ${created}`);
  await page.waitForTimeout(1500);
  if (!(await text("#main")).includes(DEFAULT_NAME)) await openRail("Verified identities");

  const { headers, rows } = await gridRows();
  check(rows.some((r) => r.includes(DEFAULT_NAME)), "new identity appears in the grid", JSON.stringify(rows));
  check(["Identity", "Identity type", "Identity status", "Sending status", "DKIM", "Custom MAIL FROM domain", "Default configuration set", "Region"].every((h) => headers.includes(h)),
    "grid has the expected columns", headers.join(", "));
  filled(headers, rows, "identities grid");
  check(rows.some((r) => r.includes("Verified")), "identity is verified");
  await page.waitForTimeout(500);
  check((await sesSavings()) > before, "creating an identity moves the space's cost-savings metrics", `${before} -> ${await sesSavings()}`);

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
  check(/Verified/.test(summary) && /Email address/.test(summary), "detail summary shows the identity's real values", summary.slice(0, 160));

  // ── child lists: create through the console REST, see them in the grid ──
  const kids = [
    ["configuration-sets", "Configuration sets", { name: "ui-cs" }, "ui-cs"],
    ["templates", "Email templates", { name: "ui-tpl" }, "ui-tpl"],
    ["contact-lists", "Contact lists", { name: "ui-list" }, "ui-list"],
    ["suppression", "Suppression list", { name: "ui-bounce@example.net", reason: "bounce" }, "ui-bounce@example.net"],
  ];
  for (const [kind, label, body, name] of kids) {
    check((await mk("POST", `/api/aws/sesv2/${kind}`, body)) === 200, `create ${label.toLowerCase()} entry`);
    await openRail(label);
    const g = await gridRows();
    check(g.rows.some((r) => r.includes(name)), `${label} grid lists the new entry`, JSON.stringify(g.rows.slice(0, 2)));
    filled(g.headers, g.rows, label);
    await mk("DELETE", `/api/aws/sesv2/${kind}/${encodeURIComponent(name)}`);
  }
  // ── delivery settings: Nano keeps the API + Sent list; real SMTP needs the offline appliance ──
  await openRail("Delivery settings");
  const ds = await gridRows();
  check(ds.rows.length >= 5, "Delivery settings lists the mail plane", JSON.stringify(ds.rows.map((r) => r[0])));
  filled(ds.headers, ds.rows, "Delivery settings");
  check(ds.rows.some((r) => r.join(" ").includes("Not available in Nano")), "Nano says real delivery needs the offline appliance");
  await page.locator("#mailSettingsBtn").click({ timeout: 8000 });
  await page.waitForTimeout(800);
  check(await page.locator("#mailSettingsSave").count() === 1, "Configure delivery opens the 'Deliver to real inboxes' form");
  await page.locator("#mailSettingsSave").click();
  await page.waitForTimeout(1200);
  check(/offline appliance/i.test(await text("#main")) || /browser cannot speak SMTP/i.test(await text("body")), "saving in Nano explains it needs the offline appliance");
  await page.keyboard.press("Escape");
  await page.evaluate(() => { const b = [...document.querySelectorAll("button")].find((x) => x.innerText.trim() === "Cancel"); if (b) b.click(); });
  await openRail("Received emails");
  check(/Received emails/.test(await text("#main")) && !/Renderer error|Failed to load/i.test(await text("#main")), "Received emails page renders");
  // ── delete from the UI ─────────────────────────────────────────────────
  await openRail("Verified identities");
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME }).first().click();
  await page.waitForTimeout(1500);
  await page.locator("#main button").filter({ hasText: /Delete/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(2000);
  if (!(await text("#main")).includes("You have no") && (await text("#main")).includes(DEFAULT_NAME)) await openRail("Verified identities");
  const after = await gridRows();
  check(!after.rows.some((r) => r.includes(DEFAULT_NAME)), "identity is gone after Delete", JSON.stringify(after.rows));
  check(!bad.length, "no API 5xx during the flow", bad.join(", "));
} catch (e) {
  check(false, "Amazon SES console flow", String(e.message || e).split("\n")[0]);
} finally {
  await browser.close();
  server.close();
}
console.log(`sesv2 ui (nano): ${fails ? "FAILED" : "ok"}`);
process.exit(fails ? 1 : 0);
