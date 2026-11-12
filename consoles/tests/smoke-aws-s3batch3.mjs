/* S3 sweep S3-3 pages: Table buckets, IAM Access Analyzer for S3, Storage Lens dashboards + groups. Drives the
 * real UI, cross-checks over the native wire, and asserts none of the four is the "Not simulated" panel.
 *
 *   BASE=http://127.0.0.1:9071 node consoles/tests/smoke-aws-s3batch3.mjs                       (offline)
 *   BASE=http://127.0.0.1:9073 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-s3batch3.mjs   (Nano)
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
const TBK = `ui-tb-${N}`, NS = "sales", TBL = "orders", SLA = `sl3-a-${N}`, SLB = `sl3-b-${N}`, PUB = `aa3-pub-${N}`, SHR = `aa3-shr-${N}`;
const DASH = `ui-dash-${N}`, GRP = `ui-grp-${N}`;
const ACCT = "123456789012";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const s3 = (method, path, { body, headers = {} } = {}) => wire(path, { method, body, headers: { authorization: auth("s3"), "x-amz-account-id": ACCT, ...headers } });
const tb = (method, path, body) => wire(path, { method, body: body === undefined ? undefined : JSON.stringify(body), headers: { authorization: auth("s3tables"), "content-type": "application/json" } });
const vy = async (path) => JSON.parse((await s3("GET", `/v20180820/_vyomi/${path}`)).text);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const notSim = async () => /Not simulated/i.test(await page.locator("body").innerText());
const arnOf = (n) => `arn:aws:s3tables:us-east-1:${ACCT}:bucket/${n}`;
const pick = async (label, optionText) => {
  await page.getByRole("button", { name: new RegExp("^" + label, "i") }).first().click();
  await page.getByRole("option", { name: new RegExp(optionText) }).first().click();
};
const radio = (rowText) => page.getByRole("row", { name: new RegExp(rowText) }).getByRole("radio").click({ force: true });

await page.goto(UI + "#/s3");
await page.getByText("General purpose buckets").first().waitFor({ timeout: 30000 });

// fixtures over the native wire
for (const b of [SLA, SLB, PUB, SHR]) await s3("PUT", `/${b}`);
await s3("PUT", `/${SLA}?versioning`, { body: "<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>" });
for (const [k, n, t] of [["logs/2026/a.log", 120, "team=ops"], ["logs/2026/b.log", 300, "team=ops"], ["img/p.png", 1000, ""]]) await s3("PUT", `/${SLA}/${k}`, { body: "x".repeat(n), headers: t ? { "x-amz-tagging": t } : {} });
await s3("PUT", `/${SLA}/logs/2026/a.log`, { body: "y".repeat(60), headers: { "x-amz-tagging": "team=ops" } });
await s3("PUT", `/${SLB}/d/q.bin`, { body: "q".repeat(500) });
await s3("PUT", `/${PUB}?policy`, { body: JSON.stringify({ Version: "2012-10-17", Statement: [{ Sid: "Open", Effect: "Allow", Principal: "*", Action: "s3:GetObject", Resource: `arn:aws:s3:::${PUB}/*` }] }) });
await s3("PUT", `/${SHR}?policy`, { body: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { AWS: "arn:aws:iam::999999999999:root" }, Action: "s3:GetObject", Resource: `arn:aws:s3:::${SHR}/*` }] }) });

// ── 1. Table buckets
await page.goto(UI + "#/s3/table-buckets");
await page.getByRole("heading", { name: /^Table buckets/ }).first().waitFor({ timeout: 15000 });
check("Table buckets page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create table bucket" }).first().click();
await page.getByLabel("Table bucket name").fill("Bad_Name");
await page.getByRole("dialog").getByRole("button", { name: "Create table bucket" }).click();
await page.getByText(/must begin and end with a letter or number|can consist only of lowercase/).first().waitFor({ timeout: 10000 });
check("invalid name shows the real validation error from the API", true);
await page.getByLabel("Table bucket name").fill(TBK);
await page.getByRole("dialog").getByRole("button", { name: "Create table bucket" }).click();
await page.getByRole("cell", { name: TBK, exact: true }).waitFor({ timeout: 10000 });
const got = await tb("GET", `/buckets/${encodeURIComponent(arnOf(TBK))}`);
check("table bucket created in UI -> native GetTableBucket", got.status === 200 && JSON.parse(got.text).name === TBK, got.text);
await radio(TBK);
await page.getByRole("button", { name: "Create namespace" }).first().waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Create namespace" }).first().click();
await page.getByLabel("Namespace name").fill(NS);
await page.getByRole("dialog").getByRole("button", { name: "Create namespace" }).click();
await page.getByRole("cell", { name: NS, exact: true }).first().waitFor({ timeout: 10000 });
const nl = await tb("GET", `/namespaces/${encodeURIComponent(arnOf(TBK))}`);
check("namespace created in UI -> native ListNamespaces", JSON.parse(nl.text).namespaces?.[0]?.namespace?.[0] === NS, nl.text);
await page.getByRole("button", { name: "Create table", exact: true }).click();
await page.getByLabel("Table name").fill(TBL);
await page.getByRole("dialog").getByRole("button", { name: "Create table" }).click();
await page.getByRole("cell", { name: TBL, exact: true }).first().waitFor({ timeout: 10000 });
const gt = JSON.parse((await tb("GET", `/get-table?tableBucketARN=${encodeURIComponent(arnOf(TBK))}&namespace=${NS}&name=${TBL}`)).text);
const wb = String(gt.warehouseLocation || "").replace("s3://", "");
check("table created in UI -> native GetTable (ICEBERG, warehouse s3://<id>--table-s3, metadata location)", gt.format === "ICEBERG" && /--table-s3$/.test(wb) && gt.metadataLocation?.startsWith(gt.warehouseLocation + "/metadata/"), JSON.stringify(gt).slice(0, 200));
const mj = JSON.parse((await s3("GET", `/${wb}/${gt.metadataLocation.slice(gt.warehouseLocation.length + 1)}`)).text || "{}");
check("Iceberg metadata JSON with the schema is in the object store", mj["format-version"] === 2 && mj.schemas?.[0]?.fields?.some((f) => f.name === "id" && f.required), JSON.stringify(mj).slice(0, 120));
await radio(TBL);
await page.getByTestId("table-detail").waitFor({ timeout: 10000 });
check("table detail shows warehouse + metadata location", (await page.getByTestId("table-warehouse").innerText()) === gt.warehouseLocation && (await page.getByTestId("table-metadata-location").innerText()) === gt.metadataLocation);
check("warehouse file list shows the metadata file", (await page.locator("body").innerText()).includes("metadata/00000-"));
await s3("PUT", `/${wb}/data/part-0.parquet`, { body: "PAR1....PAR1" });
await page.getByRole("button", { name: "Refresh table" }).click();
await page.getByRole("cell", { name: "data/part-0.parquet", exact: true }).waitFor({ timeout: 10000 });
check("a file uploaded through the S3 API appears in the table's files", true);
await shot("s3batch3-tables");
await page.getByRole("button", { name: "Delete table", exact: true }).click();
await page.getByRole("cell", { name: TBL, exact: true }).first().waitFor({ state: "detached", timeout: 10000 });
check("DeleteTable from UI removes the table and its warehouse bucket", (await tb("GET", `/get-table?tableArn=${encodeURIComponent(gt.tableARN)}`)).status === 404 && (await s3("GET", `/${wb}?list-type=2`)).status === 404);
await radio(NS);
await page.getByRole("button", { name: "Delete namespace" }).click();
await page.getByRole("cell", { name: NS, exact: true }).first().waitFor({ state: "detached", timeout: 10000 });
// the bucket is selected still: delete it through the confirm dialog
await page.getByRole("button", { name: "Delete table bucket" }).click();
await page.getByLabel("Confirm table bucket name").fill(TBK);
await page.getByRole("dialog").getByRole("button", { name: "Delete table bucket" }).click();
await page.getByRole("cell", { name: TBK, exact: true }).waitFor({ state: "detached", timeout: 10000 });
check("table bucket deleted from UI (after namespace + table)", (await tb("GET", `/buckets/${encodeURIComponent(arnOf(TBK))}`)).status === 404);

// ── 2. IAM Access Analyzer for S3
await page.goto(UI + "#/s3/access-analyzer");
await page.getByRole("heading", { name: "IAM Access Analyzer for S3" }).first().waitFor({ timeout: 15000 });
check("Access Analyzer page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("cell", { name: PUB, exact: true }).waitFor({ timeout: 15000 });
const aa = await vy("access-analysis");
const fp = aa.findings.find((f) => f.resource === PUB), fs = aa.findings.find((f) => f.resource === SHR);
check("native analysis: policy-public bucket is Public, cross-account bucket is Shared (999999999999)", fp?.kind === "Public" && fs?.kind === "Shared" && fs.principal === "account:999999999999", JSON.stringify([fp?.kind, fs?.principal]));
check("UI lists both findings with their classification", (await page.getByRole("row", { name: new RegExp(PUB) }).innerText()).includes("Public") && (await page.getByRole("row", { name: new RegExp(SHR) }).innerText()).includes("Shared"));
await radio(PUB);
await page.getByTestId("finding-detail").waitFor({ timeout: 10000 });
check("finding detail names the statement (Sid Open)", (await page.getByTestId("finding-detail").innerText()).includes("Sid Open"));
await page.getByRole("button", { name: "Archive", exact: true }).click();
await page.getByRole("cell", { name: PUB, exact: true }).waitFor({ state: "detached", timeout: 10000 });
check("Archive moves the finding to Archived (native state)", (await vy("access-analysis")).findings.find((f) => f.resource === PUB)?.status === "Archived");
await page.getByRole("tab", { name: "Archived" }).click();
await page.getByRole("cell", { name: PUB, exact: true }).waitFor({ timeout: 10000 });
await radio(PUB);
await page.getByRole("button", { name: "Unarchive" }).click();
await page.getByRole("tab", { name: "Active" }).click();
await page.getByRole("cell", { name: PUB, exact: true }).waitFor({ timeout: 10000 });
check("Unarchive brings it back to Active", (await vy("access-analysis")).findings.find((f) => f.resource === PUB)?.status === "Active");
await radio(PUB);
await page.getByRole("button", { name: "Block public access" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Block all public access" }).click();
await page.getByRole("cell", { name: PUB, exact: true }).waitFor({ state: "detached", timeout: 10000 });
const pab = await s3("GET", `/${PUB}?publicAccessBlock`);
check("Block-public-access shortcut: bucket BPA set and the public finding disappears on the next read (cross-account share stays)",
  pab.text.includes("<RestrictPublicBuckets>true</RestrictPublicBuckets>") && !(await vy("access-analysis")).findings.some((f) => f.resource === PUB) && (await vy("access-analysis")).findings.some((f) => f.resource === SHR), pab.text.slice(0, 120));
await shot("s3batch3-analyzer");
await s3("PUT", `/${SHR}?policy`, { body: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { AWS: `arn:aws:iam::${ACCT}:root` }, Action: "s3:GetObject", Resource: "*" }] }) });
await page.getByRole("button", { name: "Refresh findings" }).click();
await page.getByRole("cell", { name: SHR, exact: true }).waitFor({ state: "detached", timeout: 10000 });
check("changing the policy removes the finding on the next read (no stale cache)", true);
await page.goto(UI + "#/s3");
await page.getByTestId("ext-public").waitFor({ timeout: 15000 });
check("buckets page shows a real External access summary (not a Not-simulated panel)", !(await notSim()) && /^\d+$/.test((await page.getByTestId("ext-public").locator("h1,div").nth(1).innerText().catch(() => "0")).trim() || "0"));

// ── 3. Storage Lens groups
await page.goto(UI + "#/s3/lens/groups");
await page.getByRole("heading", { name: /^Storage Lens groups/ }).first().waitFor({ timeout: 15000 });
check("Storage Lens groups page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create Storage Lens group" }).first().click();
await page.getByLabel("Group name").fill(GRP);
await page.getByLabel("Prefixes").fill("logs/");
await page.getByLabel("Object tags").fill("team=ops");
await page.getByRole("dialog").getByRole("button", { name: "Create Storage Lens group" }).click();
await page.getByRole("cell", { name: GRP, exact: true }).waitFor({ timeout: 10000 });
const gx = (await s3("GET", `/v20180820/storagelensgroup/${GRP}`)).text;
check("group created in UI -> native GetStorageLensGroup (And: prefix + tag)", gx.includes("<And>") && gx.includes("<Prefix>logs/</Prefix>") && gx.includes("<Key>team</Key>"), gx.slice(0, 200));
await radio(GRP);
await page.getByTestId("group-detail").waitFor({ timeout: 10000 });
check("group detail describes the filter", (await page.getByTestId("group-detail").innerText()).includes("prefix: logs/"));
await shot("s3batch3-groups");

// ── 4. Storage Lens dashboards
await page.goto(UI + "#/s3/lens/dashboards");
await page.getByRole("heading", { name: /^Dashboards/ }).first().waitFor({ timeout: 15000 });
check("Storage Lens dashboards page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("cell", { name: "default-account-dashboard", exact: true }).waitFor({ timeout: 10000 });
check("the built-in default-account-dashboard is listed", true);
await radio("default-account-dashboard");
await page.getByTestId("lens-dashboard").waitFor({ timeout: 15000 });
const dd = await vy("storage-lens/default-account-dashboard");
const total = (await page.getByTestId("lens-total").innerText());
check("dashboard tiles come from the real store (object count and bytes match the native data)", (await page.getByTestId("lens-objects").innerText()).includes(String(dd.summary.objectCount)) && total.includes(`${dd.summary.totalBytes} bytes`) && dd.summary.noncurrentBytes >= 120, total.replace(/\n/g, " "));
check("noncurrent + current accounting for the versioned bucket", dd.byBucket.find((b) => b.bucket === SLA)?.noncurrentBytes === 120 && dd.byBucket.find((b) => b.bucket === SLA)?.currentBytes === 60 + 300 + 1000);
await page.getByRole("tab", { name: "By storage class" }).click();
check("by storage class table is populated", (await page.locator("body").innerText()).includes("STANDARD"));
await page.getByRole("tab", { name: "By prefix" }).click();
check("by prefix table shows real prefixes", (await page.locator("body").innerText()).includes("logs/2026/"));
await page.getByRole("tab", { name: "Activity" }).click();
check("activity metrics are explicitly not modelled", (await page.getByTestId("lens-activity").innerText()).includes("not modelled"));
check("trend recorded a snapshot", (await vy("storage-lens/default-account-dashboard")).trend.length >= 1);
await shot("s3batch3-lens-default");
// create a custom dashboard that includes SLA and aggregates by the group
await page.getByRole("button", { name: "Create dashboard" }).first().click();
await page.getByLabel("Dashboard name").fill(DASH);
await page.getByRole("button", { name: /^Buckets to include/ }).click();
await page.getByRole("option", { name: new RegExp(SLA) }).click();
await page.keyboard.press("Escape");
await page.getByRole("button", { name: /^Storage Lens groups/ }).click();
await page.getByRole("option", { name: new RegExp(GRP) }).click();
await page.keyboard.press("Escape");
await page.getByRole("dialog").getByRole("button", { name: "Create dashboard" }).click();
await page.getByRole("cell", { name: DASH, exact: true }).waitFor({ timeout: 10000 });
const cx = (await s3("GET", `/v20180820/storagelens/${DASH}`)).text;
check("dashboard created in UI -> native GetStorageLensConfiguration (Include bucket, group level, prefix level)", cx.includes(`arn:aws:s3:::${SLA}`) && cx.includes(`storage-lens-group/${GRP}`) && cx.includes("<MaxDepth>"), cx.slice(0, 200));
await page.getByTestId("lens-dashboard").waitFor({ timeout: 15000 });
const cd = await vy(`storage-lens/${DASH}`);
check("custom dashboard is scoped to the included bucket only", JSON.stringify(cd.scope.buckets) === JSON.stringify([SLA]) && cd.summary.bucketCount === 1);
await page.getByRole("tab", { name: "By Storage Lens group" }).click();
const row = page.getByRole("row", { name: new RegExp(GRP) });
await row.waitFor({ timeout: 10000 });
check("group aggregation applies the group's filter (logs/ AND team=ops: the 2 current tagged objects)", cd.byGroup[0]?.group === GRP && cd.byGroup[0].objects === 2 && cd.byGroup[0].bytes === 60 + 300, JSON.stringify(cd.byGroup[0]));
await shot("s3batch3-lens-custom");
// edit then delete
await page.getByRole("button", { name: "Edit dashboard" }).click();
await page.getByText("Enable dashboard").click();
await page.getByRole("dialog").getByRole("button", { name: "Save changes" }).click();
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
const edited = (await s3("GET", `/v20180820/storagelens/${DASH}`)).text;
check("edit saved in UI -> native config is disabled (and the default dashboard untouched)", /<IsEnabled>false<\/IsEnabled><StorageLensArn>/.test(edited)
  && /<IsEnabled>true<\/IsEnabled><StorageLensArn>/.test((await s3("GET", "/v20180820/storagelens/default-account-dashboard")).text), edited.slice(-160));
await page.getByRole("button", { name: "Delete dashboard" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Delete dashboard" }).click();
await page.getByRole("cell", { name: DASH, exact: true }).waitFor({ state: "detached", timeout: 10000 });
check("dashboard deleted from the UI", (await s3("GET", `/v20180820/storagelens/${DASH}`)).status === 404);
// delete the group
await page.goto(UI + "#/s3/lens/groups");
await page.getByRole("cell", { name: GRP, exact: true }).waitFor({ timeout: 10000 });
await radio(GRP);
await page.getByRole("button", { name: "Delete group" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Delete group" }).click();
await page.getByRole("cell", { name: GRP, exact: true }).waitFor({ state: "detached", timeout: 10000 });
check("group deleted from the UI", (await s3("GET", `/v20180820/storagelensgroup/${GRP}`)).status === 404);

check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
