/* Visual/functional smoke for the IAM enforcement + effective-access + audit UI in the three v4 consoles, against the BUILT bundle
 * (wasm/v4/<cloud>) served statically, with a mocked /api/iam backend (common/iamEnforce.js mockIam). Exercises BOTH address modes:
 *   mesh : page at /v4/<cloud>/        -> /_wire/api/iam/<cloud>/...
 *   nano : page at /nano/v4/<cloud>/   -> /nano/_wire/api/iam/<cloud>/...   (the in-browser service worker path; SW itself is stubbed)
 *   NODE_PATH=<dir with playwright> SHOTS=<dir> node consoles/tests/smoke-iam-ui.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { mockIam } from "../src/common/iamEnforce.js";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname, SHOTS = process.env.SHOTS || "/tmp/iam-ui-shots";
mkdirSync(SHOTS, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  let p = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^\/nano\//, "/");
  if (p.endsWith("/")) p += "index.html";
  const f = join(ROOT, p);
  if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
const results = []; const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());

async function open(cloud, mode, viewport, hash) {
  const prefix = mode === "nano" ? "/nano" : "";
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
  const mock = mockIam(cloud, { allow: (r) => !/delete|write/i.test(r.action) });
  mock.seedAudit({ ts: "2026-11-23T10:00:01Z", principal: "alice", action: cloud === "aws" ? "s3:DeleteBucket" : cloud === "gcp" ? "storage.buckets.delete" : "Microsoft.Storage/storageAccounts/delete", resource: "r/1", service: "s", mode: "audit", allowed: false, reason: "implicit_deny" });
  mock.seedAudit({ ts: "2026-11-23T10:00:02Z", principal: "bob", action: "x:Get", resource: "r/2", service: "s", mode: "enforce", allowed: true, reason: "allow" });
  mock.seedAudit({ ts: "2026-11-23T10:00:03Z", principal: "carol", action: "x:Put", resource: "r/3", service: "s", mode: "enforce", allowed: false, reason: "explicit_deny" });
  const iamCalls = [];
  await ctx.addInitScript(() => { window.__vyomiNanoReady = true; });
  await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
  await page.route("**/_wire/**", async (r) => {
    const u = new URL(r.request().url());
    if (u.pathname.includes("/_wire/api/iam/")) {
      iamCalls.push(u.pathname);
      const rq = r.request();
      const cm = u.pathname.match(/\/api\/iam\/aws\/catalog\/([\w.-]+)$/);
      if (cm) return r.fulfill({ status: 200, contentType: "application/json", body: await readFile(new URL(`../../core/iam_catalog/aws/${cm[1]}.json`, import.meta.url).pathname, "utf8") });
      const resp = await mock.fetcher(u.pathname + u.search, { method: rq.method(), body: rq.postData() });
      return r.fulfill({ status: resp.status, contentType: "application/json", body: await resp.text() });
    }
    if (r.request().method() === "POST" && /Action=(ListUsers|ListRoles)/.test(r.request().postData() || "")) {
      const a = /Action=(\w+)/.exec(r.request().postData())[1];
      return r.fulfill({ status: 200, contentType: "text/xml", body: a === "ListUsers" ? `<ListUsersResponse><ListUsersResult><Users><member><UserName>alice</UserName><Arn>arn:aws:iam::000000000000:user/alice</Arn></member></Users></ListUsersResult></ListUsersResponse>` : `<ListRolesResponse><ListRolesResult><Roles/></ListRolesResult></ListRolesResponse>` });
    }
    const SUBID = "00000000-0000-0000-0000-cloudlearn01";
    if (r.request().method() === "GET" && u.pathname.endsWith(`/subscriptions/${SUBID}`)) return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: `/subscriptions/${SUBID}`, subscriptionId: SUBID, displayName: "Vyomi subscription", state: "Enabled" }) });
    if (r.request().method() === "GET" && /storageAccounts\/iamsa$/.test(u.pathname)) return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: `/subscriptions/${SUBID}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/iamsa`, name: "iamsa", type: "Microsoft.Storage/storageAccounts", location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { provisioningState: "Succeeded", primaryEndpoints: {} } }) });
    if (r.request().method() === "GET" && u.pathname.includes("roleAssignments")) return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ value: [] }) });
    return r.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.goto(`${BASE}${prefix}/v4/${cloud}/${hash}`);
  return { page, ctx, iamCalls, errs, prefix, mock };
}
const shot = (page, n) => page.screenshot({ path: `${SHOTS}/${n}.png` });
const wideOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

for (const mode of ["mesh", "nano"]) {
  const tag = (s) => `${mode}: ${s}`;
  // ---------------- AWS ----------------
  let t = await open("aws", mode, { width: 1440, height: 900 }, "#/iam/enforcement");
  await t.page.getByRole("heading", { name: "Enforcement", exact: true }).first().waitFor({ timeout: 30000 });
  await t.page.getByText("Per-service").first().waitFor();
  await t.page.getByRole("radio", { name: "Audit" }).first().waitFor().catch(() => {});
  await shot(t.page, `aws-${mode}-enforcement`);
  // set s3 service to Enforce
  const s3row = t.page.locator("tr").filter({ has: t.page.getByText("s3", { exact: true }) }).first();
  await s3row.locator("button", { hasText: "Enforce" }).click();
  await t.page.waitForTimeout(600);
  check(tag("aws: service override saved via PUT"), t.mock.settings.services.s3 === "enforce", JSON.stringify(t.mock.settings));
  check(tag("aws: effective mode shows service source"), /the service setting/.test(await s3row.innerText()), await s3row.innerText());
  check(tag("aws: address path"), t.iamCalls.length > 0 && t.iamCalls.every((p) => p.startsWith(`${t.prefix}/_wire/api/iam/aws/`)), t.iamCalls[0]);
  await t.page.getByRole("tab", { name: "Audit" }).click();
  await t.page.getByText("Would deny").first().waitFor();
  await shot(t.page, `aws-${mode}-audit`);
  check(tag("aws: audit would-deny badge"), (await t.page.getByText("Would deny", { exact: true }).count()) >= 1);
  await t.page.goto(`${BASE}${t.prefix}/v4/aws/#/iam/effective-access`);
  await t.page.getByRole("button", { name: /Choose a user or role/ }).click();
  await t.page.getByRole("option", { name: /^alice/ }).click();
  await t.page.getByRole("button", { name: /Choose a service/ }).first().click();
  await t.page.getByRole("option", { name: /^S3/ }).first().click();
  await t.page.getByRole("button", { name: /Choose an action/ }).click();
  await t.page.getByRole("option", { name: /^DeleteBucket(\s|$)/ }).first().click();
  await t.page.getByRole("button", { name: "Evaluate" }).click();
  await t.page.getByTestId("iam-eval-result").waitFor();
  check(tag("aws: effective access denied + reason"), /Denied/.test(await t.page.getByTestId("iam-eval-result").innerText()));
  await shot(t.page, `aws-${mode}-effective`);
  await t.ctx.close();
  t = await open("aws", mode, { width: 390, height: 844 }, "#/iam/enforcement");
  await t.page.waitForTimeout(3000);
  await t.page.getByRole("button", { name: /close navigation|navigation/i }).first().click().catch(() => {});
  await t.page.waitForTimeout(800);
  await shot(t.page, `aws-${mode}-phone`);
  const ov = await wideOverflow(t.page);
  await t.page.goto(`${BASE}${t.prefix}/v4/aws/#/iam/roles`); await t.page.waitForTimeout(2500);
  const base = await wideOverflow(t.page);
  check(tag("aws: phone overflow no worse than an existing IAM page"), ov <= base + 2, `enforcement=${ov} roles=${base}`);
  await t.ctx.close();

  // ---------------- GCP ----------------
  t = await open("gcp", mode, { width: 1440, height: 900 }, "#/iam-admin/enforcement");
  await t.page.getByText("Default modes").waitFor({ timeout: 30000 });
  await t.page.getByRole("group", { name: "Global enforcement mode" }).getByRole("button", { name: "Audit" }).click();
  await t.page.waitForTimeout(600);
  check(tag("gcp: global set to audit"), t.mock.settings.global === "audit", JSON.stringify(t.mock.settings));
  await shot(t.page, `gcp-${mode}-enforcement`);
  check(tag("gcp: address path"), t.iamCalls.length > 0 && t.iamCalls.every((p) => p.startsWith(`${t.prefix}/_wire/api/iam/gcp/`)), t.iamCalls[0]);
  await t.page.getByRole("tab", { name: "Audit" }).click();
  await t.page.getByText("Would deny").first().waitFor();
  await shot(t.page, `gcp-${mode}-audit`);
  await t.page.goto(`${BASE}${t.prefix}/v4/gcp/#/iam-admin/effective-access`);
  await t.page.getByLabel("Principal").fill("user:alice@example.com");
  await t.page.getByLabel("Permission").fill("storage.buckets.delete");
  await t.page.getByRole("button", { name: "Check access" }).click();
  await t.page.getByTestId("iam-eval-result").waitFor();
  check(tag("gcp: effective access denied"), /Denied/.test(await t.page.getByTestId("iam-eval-result").innerText()));
  await shot(t.page, `gcp-${mode}-effective`);
  await t.ctx.close();
  t = await open("gcp", mode, { width: 390, height: 844 }, "#/iam-admin/enforcement");
  await t.page.waitForTimeout(4000);
  await shot(t.page, `gcp-${mode}-phone`);
  await t.ctx.close();

  // ---------------- Azure (Access control (IAM) > Enforcement / Effective access / Audit tabs) ----------------
  for (const [label, hash] of [["subscription", "#/subscriptions/00000000-0000-0000-0000-cloudlearn01/iam"], ["storage account", "#/storage/rg1/iamsa/iam"]]) {
    t = await open("azure", mode, { width: 1440, height: 900 }, hash);
    await t.page.getByRole("tab", { name: "Enforcement" }).waitFor({ timeout: 30000 });
    await t.page.getByRole("tab", { name: "Enforcement" }).click();
    await t.page.getByText("Effective mode").waitFor();
    await t.page.locator("label", { hasText: "Enforce" }).first().click();
    await t.page.waitForTimeout(700);
    const set = t.mock.settings;
    check(tag(`azure ${label}: resource override saved`), Object.values(set.resources).includes("enforce"), JSON.stringify(set));
    check(tag(`azure ${label}: address path`), t.iamCalls.length > 0 && t.iamCalls.every((p) => p.startsWith(`${t.prefix}/_wire/api/iam/azure/`)), t.iamCalls[0]);
    await shot(t.page, `azure-${mode}-${label.replace(" ", "")}-enforcement`);
    await t.page.getByRole("tab", { name: "Effective access" }).click();
    await t.page.getByLabel("Principal object ID").fill("11111111-1111-1111-1111-111111111111");
    await t.page.getByLabel("Action", { exact: true }).fill("Microsoft.Storage/storageAccounts/delete");
    await t.page.getByRole("button", { name: "Check access" }).click();
    await t.page.getByTestId("iam-eval-result").waitFor();
    check(tag(`azure ${label}: effective access denied`), /Denied/.test(await t.page.getByTestId("iam-eval-result").innerText()));
    await shot(t.page, `azure-${mode}-${label.replace(" ", "")}-effective`);
    await t.page.getByRole("tab", { name: "Audit" }).click();
    await t.page.waitForTimeout(1500);
    await shot(t.page, `azure-${mode}-${label.replace(" ", "")}-audit`);
    check(tag(`azure ${label}: audit would-deny`), (await t.page.getByText("Would deny").count()) >= 1);
    await t.ctx.close();
  }
  t = await open("azure", mode, { width: 390, height: 844 }, "#/storage/rg1/iamsa/iam");
  await t.page.getByRole("tab", { name: "Enforcement" }).click().catch(() => {});
  await t.page.waitForTimeout(2500);
  await shot(t.page, `azure-${mode}-phone`);
  await t.ctx.close();
}
await browser.close(); server.close();
const bad = results.filter((r) => !r).length;
console.log(`\n${results.length - bad}/${results.length} checks passed`);
process.exit(bad ? 1 : 0);
