/* S3 sweep S3-4 sections: S3 Metadata (journal + live inventory), CloudTrail S3 data events, Transfer acceleration,
 * bucket-level Storage Lens. Drives the real bucket-detail UI, cross-checks over the native wire, and asserts none of the
 * four is the "Not simulated" panel.
 *
 *   BASE=http://127.0.0.1:9077 node consoles/tests/smoke-aws-s3batch4.mjs                       (offline)
 *   BASE=http://127.0.0.1:9073 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-s3batch4.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9071";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const BK = `s34-bkt-${N}`, LOGS = `s34-logs-${N}`, TRAIL = `s34-trail-${N}`;
const ACCT = "123456789012";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const s3 = (method, path, { body, headers = {} } = {}) => wire(path, { method, body, headers: { authorization: auth("s3"), "x-amz-account-id": ACCT, ...headers } });
const ct = (action, payload) => wire("/", { method: "POST", body: JSON.stringify(payload), headers: { authorization: auth("cloudtrail"), "content-type": "application/x-amz-json-1.1", "x-amz-target": `com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101.${action}` } });
const vy = async (path) => JSON.parse((await s3("GET", `/v20180820/_vyomi/${path}`)).text);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const notSim = async () => /Not simulated in Vyomi/i.test(await page.locator("body").innerText());
const openTab = async (name) => { await page.getByRole("tab", { name, exact: true }).click(); };

await page.goto(UI + "#/s3");
await page.getByText("General purpose buckets").first().waitFor({ timeout: 30000 });
for (const b of [BK, LOGS]) await s3("PUT", `/${b}`);
await s3("PUT", `/${BK}/seed/one.txt`, { body: "hello" });

await page.goto(UI + `#/s3/buckets/${BK}`);
await page.getByRole("tab", { name: "Properties", exact: true }).waitFor({ timeout: 30000 });

// ── 1. Metadata
await openTab("Metadata");
await page.getByText("Metadata configuration").first().waitFor({ timeout: 15000 });
check("Metadata tab is not the Not-simulated panel", !(await notSim()));
await page.getByTestId("meta-create").click();
await page.getByRole("dialog").getByRole("button", { name: "Create configuration" }).click();
await page.getByText("Journal table", { exact: false }).first().waitFor({ timeout: 10000 });
const cfg = await s3("GET", `/${BK}?metadataConfiguration`);
check("config created in UI -> native GetBucketMetadataConfiguration", cfg.status === 200 && /JournalTableConfigurationResult/.test(cfg.text) && /<ConfigurationState>ENABLED/.test(cfg.text), cfg.text);
await s3("PUT", `/${BK}/docs/a.txt`, { body: "aaa" });
await s3("PUT", `/${BK}/docs/b.txt`, { body: "bbbb" });
await s3("DELETE", `/${BK}/docs/a.txt`);
await page.getByRole("button", { name: "Refresh" }).first().click();
await page.getByRole("cell", { name: "docs/b.txt", exact: true }).first().waitFor({ timeout: 10000 });
const j = await vy(`bucket-metadata/${BK}?table=journal`);
check("journal table lists the 3 mutations after config (CREATE, CREATE, DELETE)", j.total === 3 && j.rows[0].record_type === "DELETE", JSON.stringify(j.rows.map((r) => r.record_type)));
check("UI journal shows the DELETE record", await page.getByRole("cell", { name: "DELETE", exact: true }).count() >= 1);
await page.getByRole("button", { name: /^Journal table/ }).first().click();
await page.getByRole("option", { name: "Live inventory table" }).click();
await page.getByRole("cell", { name: "seed/one.txt", exact: true }).first().waitFor({ timeout: 10000 });
check("live inventory shows current objects (incl. pre-config seed object)", true);
check("live inventory omits the deleted object", await page.getByRole("cell", { name: "docs/a.txt", exact: true }).count() === 0);
await shot("s34-metadata");
await page.getByTestId("meta-delete").click();
await page.getByTestId("meta-empty").waitFor({ timeout: 10000 });
check("delete in UI -> native config gone", (await s3("GET", `/${BK}?metadataConfiguration`)).status === 404);

// ── 2. Properties: transfer acceleration + CloudTrail data events
await openTab("Properties");
await page.getByText("Transfer acceleration").first().waitFor({ timeout: 15000 });
check("Properties tab has no Not-simulated panel", !(await notSim()));
await page.getByTestId("accel-edit").click();
await page.getByRole("dialog").getByText("Enable", { exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: "Save changes" }).click();
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
await page.getByTestId("accel-status").filter({ hasText: "Enabled" }).waitFor({ timeout: 10000 });
const ac = await s3("GET", `/${BK}?accelerate`);
check("acceleration enabled in UI -> native GetBucketAccelerateConfiguration", /<Status>Enabled<\/Status>/.test(ac.text), ac.text);

await page.getByTestId("trail-configure").click();
await page.getByLabel("Log destination bucket").fill(LOGS);
await page.getByLabel("Trail name").fill(TRAIL);
await page.getByRole("dialog").getByRole("button", { name: "Create trail" }).click();
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
await page.getByTestId("trail-table").getByRole("cell", { name: TRAIL, exact: true }).waitFor({ timeout: 10000 });
const gt = await ct("GetTrailStatus", { Name: TRAIL });
check("trail created in UI -> native CloudTrail GetTrailStatus IsLogging", JSON.parse(gt.text).IsLogging === true, gt.text);
const sel = JSON.parse((await ct("GetEventSelectors", { TrailName: TRAIL })).text);
check("event selector targets this bucket's objects", sel.EventSelectors?.[0]?.DataResources?.[0]?.Values?.[0] === `arn:aws:s3:::${BK}/`, JSON.stringify(sel));
await s3("PUT", `/${BK}/traced.txt`, { body: "t" });
await s3("GET", `/${BK}/traced.txt`);
await s3("DELETE", `/${BK}/traced.txt`);
await page.getByRole("button", { name: "Refresh" }).first().click();
await page.getByTestId("events-table").getByRole("cell", { name: "DeleteObject", exact: true }).first().waitFor({ timeout: 10000 });
const ev = await vy(`bucket-trail/${BK}`);
const names = ev.events.map((e) => e.eventName);
check("data events recorded for Put/Get/Delete", ["PutObject", "GetObject", "DeleteObject"].every((n) => names.includes(n)), names.join(","));
await shot("s34-properties");
await page.getByTestId("trail-table").getByRole("button", { name: "Stop logging" }).click();
await page.getByTestId("trail-table").getByText("Not logging").waitFor({ timeout: 10000 });
check("stop logging in UI -> native status", JSON.parse((await ct("GetTrailStatus", { Name: TRAIL })).text).IsLogging === false);
await page.getByTestId("trail-table").getByRole("button", { name: "Delete trail" }).click();
await page.getByTestId("trail-table").getByRole("cell", { name: TRAIL, exact: true }).waitFor({ state: "detached", timeout: 10000 });
check("delete trail in UI -> native TrailNotFound", JSON.parse((await ct("GetTrail", { Name: TRAIL })).text).__type === "TrailNotFoundException");

// ── 3. Metrics: bucket Storage Lens
await openTab("Metrics");
await page.getByTestId("bucket-lens").waitFor({ timeout: 15000 });
check("Metrics tab Storage Lens is not the Not-simulated panel", !(await notSim()));
const lens = await vy(`bucket-lens/${BK}`);
const uiTotal = await page.getByTestId("lens-total").innerText();
const uiObjs = await page.getByTestId("lens-objects").innerText();
check("UI object count matches the live store (wire)", Number(uiObjs.replace(/,/g, "")) === lens.storage.currentObjects, `${uiObjs} vs ${lens.storage.currentObjects}`);
check("UI total storage rendered", uiTotal.length > 0 && lens.storage.totalBytes > 0, uiTotal);
check("request activity counted real requests", lens.activity.AllRequests >= 5 && lens.activity.GetRequests >= 1, JSON.stringify({ a: lens.activity.AllRequests, g: lens.activity.GetRequests }));
await shot("s34-metrics");

check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
