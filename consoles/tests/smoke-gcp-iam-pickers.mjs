/* GCP IAM pickers (Grant access role popup + Condition panel + Add permissions dialog) against the BUILT bundle (wasm/v4/gcp),
 * with the REAL verbatim catalog files served as GET /_wire/api/iam/gcp/catalog/<svc> and a recording fake of the project policy API.
 *   NODE_PATH=<dir with playwright> SHOTS=<dir> node consoles/tests/smoke-gcp-iam-pickers.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname, CAT = new URL("../../core/iam_catalog/gcp", import.meta.url).pathname;
const SHOTS = process.env.SHOTS || "/tmp/gcp-pickers-shots"; mkdirSync(SHOTS, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  const p = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  let f = join(ROOT, p.endsWith("/") ? p + "index.html" : p);
  if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
let fails = 0; const check = (n, ok, d = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 220) : ""}`); };
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage(); const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await ctx.addInitScript(() => { window.__vyomiNanoReady = true; });
await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
let policy = { version: 1, etag: "abc", bindings: [{ role: "roles/owner", members: ["user:admin@vyomi.cloud"] }] };
const sets = []; const J = (r, b, s = 200) => r.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(b) });
await page.route("**/_wire/**", async (r) => {
  const u = new URL(r.request().url()), m = r.request().method(), p = u.pathname;
  let mm;
  if ((mm = /\/api\/iam\/gcp\/catalog\/([\w.-]+)$/.exec(p))) { const f = join(CAT, mm[1] + ".json"); return existsSync(f) ? r.fulfill({ status: 200, contentType: "application/json", body: await readFile(f, "utf8") }) : J(r, { error: "none" }, 404); }
  if (p.includes("/api/iam/gcp/enforcement")) return J(r, { global: "off", space: "off", services: {}, resources: {} });
  if (p.endsWith(":getIamPolicy")) return J(r, policy);
  if (p.endsWith(":setIamPolicy")) { const b = JSON.parse(r.request().postData()); sets.push(b); policy = b.policy; return J(r, policy); }
  if (/\/serviceAccounts$/.test(p)) return J(r, { accounts: [{ email: "app@vyomi-project.iam.gserviceaccount.com", displayName: "App SA" }] });
  if (/\/groups$/.test(p)) return J(r, { groups: [{ groupKey: { id: "devs@vyomi.cloud" }, displayName: "Developers" }] });
  if (/\/roles$/.test(p)) return J(r, { roles: [] });
  if (/\/policyActivity$/.test(p)) return J(r, { activity: [] });
  if (/\/v3\/projects\//.test(p)) return J(r, { name: "projects/1", projectId: "vyomi-project" });
  return J(r, {}, 404);
});
const shot = async (n) => { await page.waitForTimeout(600); await page.screenshot({ path: `${SHOTS}/${n}.png` }); };

// ── Grant access ─────────────────────────────────────────────────────────────
await page.goto(`${BASE}/v4/gcp/#/iam-admin/iam`);
await page.getByRole("button", { name: "Grant access" }).first().click();
const panel = page.getByRole("dialog", { name: "Grant access" });
await panel.waitFor({ timeout: 30000 });
await panel.getByLabel("New principals").fill("devs@vyomi.cloud");
await page.getByRole("option", { name: /Developers/ }).click().catch(async () => { await panel.getByLabel("New principals").press("Enter"); });
check("principal chosen from stores (group)", (await panel.innerText()).includes("group:devs@vyomi.cloud"), (await panel.innerText()).slice(0, 200));
await panel.getByLabel("New principals").fill("new.person@example.com"); await panel.getByLabel("New principals").press("Enter");
check("free-typed email accepted as user:", (await panel.innerText()).includes("user:new.person@example.com"));
await panel.getByRole("button", { name: "Select a role" }).click();
const popup = page.getByTestId("role-popup"); await popup.waitFor();
await shot("grant-role-popup-default");
const ptxt = await popup.innerText();
check("default view groups roles (Currently used / Basic / All roles)", ["Currently used", "Basic", "All roles"].every((t) => ptxt.includes(t)));
check("Manage Roles link present", await popup.getByRole("link", { name: "Manage Roles" }).isVisible());
await popup.getByLabel("Search roles").fill("storage object");
await popup.getByText("Top results").waitFor();
const first = await popup.locator("[data-role-id]").allInnerTexts();
check("search 'storage object' -> Top results with titles + descriptions", first.length > 3 && /Storage Object Creator/.test(first[0] + first[1] + first[2] + first[3]) && first.some((t) => /create objects/i.test(t)), first.slice(0, 3).join(" | "));
await shot("grant-role-popup-search");
await popup.locator('[data-role-id="roles/storage.objectViewer"]').click();
check("role chosen", (await panel.innerText()).includes("Storage Object Viewer"));
await panel.getByRole("button", { name: "Add IAM condition" }).click();
const cond = page.getByRole("dialog", { name: "Add condition" }); await cond.waitFor();
await cond.getByLabel("Condition title").fill("Dev buckets only");
await cond.getByRole("combobox", { name: "Condition type 1" }).click().catch(async () => { await cond.getByLabel("Condition type 1").click(); });
await page.getByRole("option", { name: "Name" }).click();
await cond.getByRole("combobox", { name: "Operator" }).click(); await page.getByRole("option", { name: "starts with" }).click();
await cond.getByLabel("Resource name value").fill("projects/_/buckets/dev-");
await cond.getByRole("button", { name: "Add another condition" }).click();
await cond.getByRole("combobox", { name: "Condition type 2" }).click(); await page.getByRole("option", { name: "Expiry" }).click();
await cond.getByLabel("Expiry date and time").fill("2027-01-01T00:00");
const cel = await cond.getByTestId("cel-preview").innerText();
check("builder generates CEL", /^resource\.name\.startsWith\("projects\/_\/buckets\/dev-"\) && request\.time < timestamp\("20\d\d-\d\d-\d\dT[\d:.]+Z"\)$/.test(cel), cel);
check("CEL validated by engine subset", await cond.getByTestId("cel-ok").isVisible());
await page.keyboard.press("Escape").catch(() => {});
await shot("condition-builder");
await cond.getByRole("tab", { name: "Condition editor" }).click();
const ed = cond.getByLabel("CEL expression");
check("editor shows generated expression", (await ed.inputValue()) === cel);
await ed.fill('resource.name.exists(x, x == "a")');
check("editor flags unsupported CEL", (await cond.getByTestId("cel-error").innerText()).includes("exists"));
await ed.fill('resource.type == "storage.googleapis.com/Bucket" && request.time < timestamp("2027-01-01T00:00:00.000Z")');
await cond.getByRole("tab", { name: "Condition builder" }).click();
check("editor -> builder sync (2 rows)", (await cond.getByTestId("cond-row").count()) === 2);
await cond.getByLabel("Remove condition 2").click();
const cel2 = await cond.getByTestId("cel-preview").innerText();
check("builder -> expression sync after remove", cel2 === 'resource.type == "storage.googleapis.com/Bucket"', cel2);
await cond.getByRole("button", { name: "Save" }).click();
await panel.getByText("Condition: Dev buckets only").waitFor();
await shot("grant-after-condition");
await panel.getByRole("button", { name: "Save", exact: true }).click();
await page.waitForTimeout(800);
const body = sets[0]?.policy;
const b = body?.bindings?.find((x) => x.role === "roles/storage.objectViewer");
check("setIamPolicy payload has role + members + condition", !!b && b.members.includes("group:devs@vyomi.cloud") && b.members.includes("user:new.person@example.com") &&
  b.condition?.title === "Dev buckets only" && b.condition.expression === cel2 && body.version === 3, JSON.stringify(b));
check("owner binding preserved", body?.bindings?.some((x) => x.role === "roles/owner"));

// ── Create role > Add permissions ───────────────────────────────────────────
await page.goto(`${BASE}/v4/gcp/#/iam-admin/roles/create`);
await page.getByRole("button", { name: "Add permissions" }).first().click();
const dlg = page.getByRole("dialog", { name: "Add permissions" }); await dlg.waitFor();
await dlg.getByTestId("perm-range").waitFor();
const r0 = await dlg.getByTestId("perm-range").innerText(); const total = Number(r0.split(" of ")[1]);
check("table paginates over the full catalog", /^1 – 10 of \d+$/.test(r0) && total > 5000, r0);
await shot("add-permissions-dialog");
await dlg.getByLabel("Next page").click();
check("next page", (await dlg.getByTestId("perm-range").innerText()).startsWith("11 – 20"));
await dlg.getByLabel("Select all on page").check();
await dlg.getByLabel("Previous page").click();
await dlg.getByLabel("Select all on page").check();
check("selection spans pages", (await dlg.getByTestId("perm-selected").innerText()) === "20 selected");
await dlg.getByRole("textbox", { name: "Filter permissions" }).fill("service:storage object");
const r1 = await dlg.getByTestId("perm-range").innerText();
const names = await dlg.locator("[data-perm]").evaluateAll((e) => e.map((x) => x.dataset.perm));
check("property filter service:storage + text", Number(r1.split(" of ")[1]) > 0 && Number(r1.split(" of ")[1]) < total && names.every((n) => n.startsWith("storage.") && /object/i.test(n)), r1 + " " + names.slice(0, 2));
check("selection kept across filter change", (await dlg.getByTestId("perm-selected").innerText()) === "20 selected");
await dlg.getByRole("textbox", { name: "Filter permissions" }).fill("");
await dlg.getByLabel("Filter permissions by role").click(); await dlg.getByLabel("Filter permissions by role").fill("Storage Object Viewer");
await page.getByRole("option", { name: /Storage Object Viewer/ }).first().click();
const r2 = await dlg.getByTestId("perm-range").innerText();
check("Filter permissions by role narrows table", Number(r2.split(" of ")[1]) > 0 && Number(r2.split(" of ")[1]) < 100, r2);
await dlg.getByRole("button", { name: "Add", exact: true }).click();
await page.getByLabel("Remove accessapproval.requests.approve").waitFor().catch(() => {});
const added = await page.getByLabel(/^Remove /).count();
check("Add puts the 20 selected permissions on the role", added === 20, String(added));
check("no page errors", errs.length === 0, errs[0]);
console.log(fails ? `${fails} FAILED` : "ALL PASSED"); await browser.close(); server.close(); process.exit(fails ? 1 : 0);
