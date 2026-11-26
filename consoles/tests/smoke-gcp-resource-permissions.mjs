/* Playwright smoke for the shared GCP ResourcePermissionsPanel on Cloud Storage bucket, Pub/Sub topic and Cloud Run service against the BUILT
 * bundle (wasm/v4/gcp), with a stateful recording fake of each resource's native getIamPolicy / setIamPolicy. Asserts the real stored bindings
 * are shown and the setIamPolicy payload (role, members, condition) for Grant, and the payload after Remove.
 *   NODE_PATH=<dir with playwright> SHOTS=<dir> node consoles/tests/smoke-gcp-resource-permissions.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname, CAT = new URL("../../core/iam_catalog/gcp", import.meta.url).pathname;
const SHOTS = process.env.SHOTS || "/tmp/gcp-rperm-shots"; mkdirSync(SHOTS, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  const p = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  let f = join(ROOT, p.endsWith("/") ? p + "index.html" : p);
  if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
let fails = 0; const check = (n, ok, d = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 260) : ""}`); };
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage(); const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await ctx.addInitScript(() => { window.__vyomiNanoReady = true; });
await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
const J = (r, b, s = 200) => r.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(b) });
const pols = {
  bucket: { version: 1, etag: "e1", bindings: [{ role: "roles/storage.objectViewer", members: ["allUsers"] }] },
  topic: { version: 1, etag: "e1", bindings: [{ role: "roles/pubsub.publisher", members: ["serviceAccount:app@vyomi-project.iam.gserviceaccount.com"] }] },
  run: { version: 1, etag: "e1", bindings: [] },
};
const sets = { bucket: [], topic: [], run: [] };
const kindOf = (p) => /\/storage\/v1\/b\/b1\/iam$/.test(p) ? "bucket" : /\/topics\/t1:(get|set)IamPolicy$/.test(p) ? "topic" : /\/services\/svc1:(get|set)IamPolicy$/.test(p) ? "run" : null;
await page.route("**/_wire/**", async (r) => {
  const u = new URL(r.request().url()), m = r.request().method(), p = u.pathname; let mm;
  if ((mm = /\/api\/iam\/gcp\/catalog\/([\w.-]+)$/.exec(p))) { const f = join(CAT, mm[1] + ".json"); return existsSync(f) ? r.fulfill({ status: 200, contentType: "application/json", body: readFileSync(f, "utf8") }) : J(r, {}, 404); }
  if (p.includes("/api/iam/gcp/enforcement")) return J(r, { global: "off", space: "off", services: {}, resources: {} });
  const k = kindOf(p);
  if (k && (m === "GET" || p.endsWith(":getIamPolicy"))) return J(r, pols[k]);
  if (k) { const b = JSON.parse(r.request().postData()); const pol = b.policy || b; sets[k].push(pol); pols[k] = pol; return J(r, pol); }
  if (/\/serviceAccounts$/.test(p)) return J(r, { accounts: [{ email: "app@vyomi-project.iam.gserviceaccount.com", displayName: "App SA" }] });
  if (/\/groups$/.test(p)) return J(r, { groups: [] });
  if (/\/roles$/.test(p)) return J(r, { roles: [] });
  if (/\/storage\/v1\/b\/b1$/.test(p)) return J(r, { name: "b1", location: "US", storageClass: "STANDARD", iamConfiguration: {}, timeCreated: "2026-01-01T00:00:00Z" });
  if (/\/topics\/t1$/.test(p)) return J(r, { name: "projects/vyomi-project/topics/t1" });
  if (/\/services\/svc1$/.test(p)) return J(r, { name: "projects/vyomi-project/locations/us-central1/services/svc1", uri: "https://svc1.run.app", template: { containers: [{ image: "x" }] }, createTime: "2026-01-01T00:00:00Z", updateTime: "2026-01-01T00:00:00Z" });
  if (/\/v3\/projects\//.test(p)) return J(r, { name: "projects/1", projectId: "vyomi-project" });
  return J(r, {}, 200);
});
const shot = async (n) => { await page.waitForTimeout(500); await page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true }); };
async function grant(kind, principal, roleSearch, roleId) {
  const panel0 = page.getByTestId("resource-permissions");
  await panel0.getByRole("button", { name: "Grant access" }).click();
  const panel = page.getByRole("dialog", { name: "Grant access" }); await panel.waitFor();
  await panel.getByLabel("New principals").fill(principal); await panel.getByLabel("New principals").press("Enter");
  await panel.getByRole("button", { name: "Select a role" }).click();
  const popup = page.getByTestId("role-popup"); await popup.waitFor();
  await popup.getByLabel("Search roles").fill(roleSearch);
  await popup.locator(`[data-role-id="${roleId}"]`).click();
  await shot(`${kind}-grant`);
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await page.waitForTimeout(800);
}
const bindingOf = (pol, role) => pol?.bindings?.find((b) => b.role === role);

// bucket
await page.goto(`${BASE}/v4/gcp/#/storage/browser/b1?tab=permissions`);
await page.getByTestId("resource-permissions").waitFor({ timeout: 30000 });
check("bucket: shows REAL stored binding (allUsers / Storage Object Viewer)", /allUsers/.test(await page.getByTestId("resource-permissions").innerText()) && /Storage Object Viewer/.test(await page.getByTestId("resource-permissions").innerText()));
await grant("bucket", "dev@example.com", "storage object admin", "roles/storage.objectAdmin");
check("bucket: setIamPolicy (PUT /storage/v1/b/b1/iam) has objectAdmin for user:dev@example.com and keeps allUsers viewer",
  !!bindingOf(sets.bucket.at(-1), "roles/storage.objectAdmin")?.members.includes("user:dev@example.com") && bindingOf(sets.bucket.at(-1), "roles/storage.objectViewer")?.members.includes("allUsers"), JSON.stringify(sets.bucket.at(-1)));
// remove (view by principals, select allUsers row)
await page.getByTestId("resource-permissions").getByRole("row", { name: /allUsers/ }).getByRole("checkbox").check();
await page.getByTestId("resource-permissions").getByRole("button", { name: "Remove access" }).click();
await page.waitForTimeout(800);
check("bucket: Remove access sends policy without allUsers", !bindingOf(sets.bucket.at(-1), "roles/storage.objectViewer"), JSON.stringify(sets.bucket.at(-1)));

// pubsub topic
await page.goto(`${BASE}/v4/gcp/#/pubsub/topics/t1`);
await page.getByRole("tab", { name: "Permissions" }).click({ timeout: 30000 });
await page.getByTestId("resource-permissions").waitFor();
await page.getByText("Pub/Sub Publisher").waitFor();
check("topic: shows REAL stored binding (publisher SA)", /pubsub\.publisher|Pub\/Sub Publisher/.test(await page.getByTestId("resource-permissions").innerText()));
await page.getByRole("button", { name: "View by roles" }).click();
check("topic: View by roles lists the role", /Publisher/.test(await page.getByTestId("resource-permissions").innerText()));
await grant("topic", "reader@example.com", "pub/sub subscriber", "roles/pubsub.subscriber");
check("topic: setIamPolicy (POST topics/t1:setIamPolicy {policy}) has pubsub.subscriber for user:reader@example.com",
  !!bindingOf(sets.topic.at(-1), "roles/pubsub.subscriber")?.members.includes("user:reader@example.com"), JSON.stringify(sets.topic.at(-1)));
await shot("topic-after");

// cloud run service
await page.goto(`${BASE}/v4/gcp/#/run/detail/us-central1/svc1?tab=permissions`);
await page.getByTestId("resource-permissions").waitFor({ timeout: 30000 });
check("run: empty stored policy shown as empty", /No principals have been granted access/.test(await page.getByTestId("resource-permissions").innerText()));
await grant("run", "allUsers", "cloud run invoker", "roles/run.invoker");
check("run: setIamPolicy (v2 services/svc1:setIamPolicy) has run.invoker for allUsers", !!bindingOf(sets.run.at(-1), "roles/run.invoker")?.members.includes("allUsers"), JSON.stringify(sets.run.at(-1)));

check("no page errors", errs.length === 0, errs[0]);
await browser.close(); server.close();
console.log(fails ? `\n${fails} FAILED` : "\nall checks passed"); process.exit(fails ? 1 : 0);
