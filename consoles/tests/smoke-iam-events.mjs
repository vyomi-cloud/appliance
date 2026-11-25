/* Smoke for the IAM Event history (AWS), Activity (GCP) and Activity + Privileged access (Azure) pages against the BUILT bundles (wasm/v4/<cloud>).
 * The /api/iam/<cloud>/events payloads are REAL responses captured from the appliance server (EVENTS_FIXTURE = json {aws,gcp,azure}); the
 * PIM schedule calls and Azure role-definition list are small stubs. Verifies: rows render with the cloud's native vocabulary, filters send the
 * query, export links point at /events/export, no page errors.
 *   NODE_PATH=<dir with playwright> EVENTS_FIXTURE=<file> node consoles/tests/smoke-iam-events.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname;
const FIX = JSON.parse(await readFile(process.env.EVENTS_FIXTURE, "utf8"));
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  const p0 = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  let p = p0; if (p.endsWith("/")) p += "index.html";
  const f = join(ROOT, p);
  if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
const results = []; const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());

async function open(cloud, hash, viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  const errs = [], calls = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await ctx.addInitScript(() => { window.__vyomiNanoReady = true; });
  await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
  await page.route("**/_wire/**", async (r) => {
    const u = new URL(r.request().url());
    const j = (o) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(o) });
    const m = u.pathname.match(/\/api\/iam\/(aws|gcp|azure)\/events(\/export)?$/);
    if (m) { calls.push(u.pathname + u.search); return j(FIX[m[1]]); }
    if (/roleEligibilitySchedules$/.test(u.pathname)) return j({ value: [{ id: "e1", name: "e1", properties: { principalId: "11111111-1111-1111-1111-111111111111", roleDefinitionId: "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7", startDateTime: "2026-11-25T00:00:00Z", endDateTime: "2027-11-25T00:00:00Z" } }] });
    if (/roleAssignmentScheduleInstances$/.test(u.pathname)) return j({ value: [] });
    if (/roleDefinitions$/.test(u.pathname)) return j({ value: [{ id: "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7", name: "acdd72a7-3385-48ef-bd42-f606fba81ae7", properties: { roleName: "Reader" } }] });
    if (u.pathname.includes("/api/iam/")) return j({});
    return j({ value: [] });
  });
  await page.goto(`${BASE}/v4/${cloud}/${hash}`);
  return { page, ctx, errs, calls };
}

// AWS
let t = await open("aws", "#/iam/event-history");
await t.page.getByText("CreateRole").first().waitFor({ timeout: 30000 }).catch(() => {});
check("aws: event row renders (CreateRole)", await t.page.getByText("CreateRole").count() > 0);
check("aws: native event source column", await t.page.getByText("iam.amazonaws.com").count() > 0);
check("aws: export links target /events/export", await t.page.locator('a[href*="/events/export"]').count() >= 2);
await t.page.getByLabel("Filter by event name").fill("CreateRole"); await t.page.getByRole("button", { name: "Apply" }).click();
await t.page.waitForTimeout(400);
check("aws: filter is sent as a query parameter", t.calls.some((c) => c.includes("name=CreateRole")), t.calls.slice(-1)[0]);
check("aws: no page errors", t.errs.length === 0, t.errs.join(" | "));
await t.ctx.close();

// GCP
t = await open("gcp", "#/iam-admin/activity");
await t.page.getByText("CreateServiceAccount").first().waitFor({ timeout: 30000 }).catch(() => {});
check("gcp: audit entry renders (google.iam.admin.v1.CreateServiceAccount)", await t.page.getByText("google.iam.admin.v1.CreateServiceAccount").count() > 0);
await t.page.getByText("google.iam.admin.v1.CreateServiceAccount").first().click();
check("gcp: row expands to the native LogEntry (cloudaudit)", await t.page.getByText("cloudaudit.googleapis.com").count() > 0);
check("gcp: export links", await t.page.locator('a[href*="/events/export"]').count() >= 2);
check("gcp: no page errors", t.errs.length === 0, t.errs.join(" | "));
await t.ctx.close();

// Azure
t = await open("azure", "#/subscriptions/00000000-0000-0000-0000-cloudlearn01/iam");
await t.page.getByRole("tab", { name: "Activity" }).first().waitFor({ timeout: 30000 }).catch(() => {});
const tab = t.page.getByRole("tab", { name: "Activity" });
check("azure: Activity tab present on Access control (IAM)", await tab.count() > 0);
if (await tab.count()) {
  await tab.first().click();
  await t.page.getByText("Microsoft.Authorization/roleAssignments/write").first().waitFor({ timeout: 15000 }).catch(() => {});
  check("azure: Activity Log operation renders", await t.page.getByText("Microsoft.Authorization/roleAssignments/write").count() > 0);
  await t.page.getByRole("tab", { name: "Privileged access" }).click();
  await t.page.getByText("Reader").first().waitFor({ timeout: 15000 }).catch(() => {});
  check("azure: PIM eligible assignment lists with role name + Activate action", await t.page.getByText("Reader").count() > 0 && await t.page.getByRole("button", { name: /Activate Reader/ }).count() > 0);
}
check("azure: no page errors", t.errs.length === 0, t.errs.join(" | "));
await t.ctx.close();

await browser.close(); server.close();
console.log(results.every(Boolean) ? "ALL PASS" : "SOME FAILED");
process.exit(results.every(Boolean) ? 0 : 1);
