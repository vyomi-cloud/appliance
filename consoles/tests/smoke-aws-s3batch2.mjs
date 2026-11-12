/* S3 sweep S3-2 pages: Multi-Region Access Points, Access Grants, Batch Operations. Drives the
 * real UI, cross-checks over the native wire, and asserts none of the three is the "Not simulated"
 * panel any more.
 *
 *   BASE=http://127.0.0.1:9061 node consoles/tests/smoke-aws-s3batch2.mjs                       (offline)
 *   BASE=http://127.0.0.1:9063 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-s3batch2.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9061";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const BA = `s3b-a-${N}`, BB = `s3b-b-${N}`, MR = `ui-mrap-${N}`, REP = `s3b-rep-${N}`;
const ACCT = "123456789012";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc, key = "X") => `AWS4-HMAC-SHA256 Credential=${key}/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const s3 = (method, path, { body, headers = {}, key } = {}) => wire(path, { method, body, headers: { authorization: auth("s3", key), "x-amz-account-id": ACCT, ...headers } });
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const notSim = async () => /Not simulated/i.test(await page.locator("body").innerText());
const pick = async (label, optionText) => {            // Cloudscape Select by its aria label
  await page.getByRole("button", { name: new RegExp("^" + label, "i") }).first().click();
  await page.getByRole("option", { name: new RegExp(optionText) }).first().click();
};
const tag = (t, n) => (t.match(new RegExp(`<${n}>([^<]*)</${n}>`)) || [])[1] || "";

await page.goto(UI + "#/s3");
await page.getByText("General purpose buckets").first().waitFor({ timeout: 30000 });

// fixtures over the native wire
await s3("PUT", `/${BA}`);
await s3("PUT", `/${BB}`, { body: "<CreateBucketConfiguration><LocationConstraint>eu-west-1</LocationConstraint></CreateBucketConfiguration>" });
await s3("PUT", `/${REP}`);
for (const k of ["pre/one.txt", "pre/two.txt", "other.txt"]) await s3("PUT", `/${BA}/${k}`, { body: `data-${k}` });

// ── 1. Multi-Region Access Points
await page.goto(UI + "#/s3/mrap");
await page.getByRole("heading", { name: "Multi-Region Access Points" }).first().waitFor({ timeout: 15000 });
check("MRAP page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create Multi-Region Access Point" }).first().click();
await page.getByLabel("Multi-Region Access Point name").fill(MR);
await page.getByRole("button", { name: /^Buckets/ }).click();
await page.getByRole("option", { name: new RegExp(BA) }).click();
await page.getByRole("option", { name: new RegExp(BB) }).click();
await page.keyboard.press("Escape");
await page.getByRole("dialog").getByRole("button", { name: "Create Multi-Region Access Point" }).click();
await page.getByRole("cell", { name: MR, exact: true }).waitFor({ timeout: 10000 });
const got = await s3("GET", `/v20180820/mrap/instances/${MR}`);
const alias = tag(got.text, "Alias");
check("MRAP created in UI -> native GetMultiRegionAccessPoint (alias xxxx.mrap, 2 regions)", /\.mrap$/.test(alias) && got.text.includes("eu-west-1") && got.text.includes("us-east-1"), got.text.slice(0, 160));
await s3("PUT", `/${alias}/via-mrap.txt`, { body: "global" });
const mirrored = await s3("GET", `/${BB}/via-mrap.txt`);
check("PUT through the MRAP alias lands in the primary and is mirrored to the other region", (await s3("GET", `/${BA}/via-mrap.txt`)).text === "global" && mirrored.text === "global");
await page.getByRole("row", { name: new RegExp(MR) }).getByRole("radio").click({ force: true });
await page.getByText(`Details - ${MR}`).waitFor({ timeout: 10000 });
const dial = page.getByLabel(`Traffic dial ${BA}`);
await dial.fill("0");
await page.getByRole("button", { name: "Save traffic dials" }).click();
await page.getByText("Successfully updated traffic dials").waitFor({ timeout: 10000 });
const routes = await s3("GET", `/v20180820/mrap/instances/arn:aws:s3::${ACCT}:accesspoint/${alias}/routes`);
check("traffic dial saved in UI -> native GetMultiRegionAccessPointRoutes", new RegExp(`<Bucket>${BA}</Bucket><Region>us-east-1</Region><TrafficDialPercentage>0<`).test(routes.text), routes.text.slice(0, 200));
await page.getByLabel(/Multi-Region Access Point policy/).fill(JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { AWS: "*" }, Action: "s3:GetObject", Resource: `arn:aws:s3::${ACCT}:accesspoint/${alias}/object/*` }] }));
await page.getByRole("button", { name: "Save policy" }).click();
await page.getByText("Successfully saved the policy").waitFor({ timeout: 10000 });
const ps = await s3("GET", `/v20180820/mrap/instances/${MR}/policystatus`);
check("policy saved in UI -> native GetMultiRegionAccessPointPolicyStatus (public)", ps.text.includes("<IsPublic>true</IsPublic>"), ps.text.slice(0, 160));
await shot("s3batch2-mrap");
await page.getByRole("button", { name: "Delete", exact: true }).first().click();
await page.getByRole("cell", { name: MR, exact: true }).waitFor({ state: "detached", timeout: 10000 });
const gone = await s3("GET", `/v20180820/mrap/instances/${MR}`);
check("Delete from UI removes the MRAP (buckets and data survive)", gone.status === 404 && (await s3("GET", `/${BA}/via-mrap.txt`)).text === "global");

// ── 2. Access Grants
await page.goto(UI + "#/s3/access-grants");
await page.getByRole("heading", { name: "S3 Access Grants instance" }).first().waitFor({ timeout: 15000 });
check("Access Grants page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create S3 Access Grants instance" }).first().click();
await page.getByRole("button", { name: "Register location" }).first().click();
await page.getByRole("button", { name: /Bucket/ }).first().click();
await page.getByRole("option", { name: new RegExp(`^${BA}`) }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Register location" }).click();
await page.getByRole("cell", { name: `s3://${BA}`, exact: true }).waitFor({ timeout: 10000 });
const locs = await s3("GET", "/v20180820/accessgrantsinstance/locations");
check("location registered in UI -> native ListAccessGrantsLocations", locs.text.includes(`s3://${BA}`), locs.text.slice(0, 160));
await page.getByRole("button", { name: "Create grant" }).first().click();
await page.getByLabel("Sub-prefix").fill("pre/*");
await page.getByRole("dialog").getByRole("button", { name: "Create grant" }).click();
await page.getByRole("cell", { name: `s3://${BA}/pre/*`, exact: true }).waitFor({ timeout: 10000 });
const gl = await s3("GET", "/v20180820/accessgrantsinstance/grants");
check("grant created in UI -> native ListAccessGrants (scope + READ)", gl.text.includes(`<GrantScope>s3://${BA}/pre/*</GrantScope>`) && gl.text.includes("<Permission>READ</Permission>"), gl.text.slice(0, 200));
await page.getByRole("row", { name: new RegExp(`s3://${BA}/pre/`) }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "Get temporary credentials" }).click();
await page.getByText("Matched grant target").waitFor({ timeout: 10000 });
check("UI shows temporary credentials for the grant", (await page.locator("body").innerText()).includes("ASIA"));
await shot("s3batch2-grants");
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
const da = await s3("GET", `/v20180820/accessgrantsinstance/dataaccess?target=${encodeURIComponent(`s3://${BA}/pre/*`)}&permission=READ`);
const akid = tag(da.text, "AccessKeyId"), tok = tag(da.text, "SessionToken");
const inScope = await s3("GET", `/${BA}/pre/one.txt`, { key: akid, headers: { "x-amz-security-token": tok } });
const outScope = await s3("GET", `/${BA}/other.txt`, { key: akid, headers: { "x-amz-security-token": tok } });
const write = await s3("PUT", `/${BA}/pre/new.txt`, { key: akid, body: "x", headers: { "x-amz-security-token": tok } });
check("GetDataAccess credentials are enforced: in-scope read ok, out-of-scope read and any write denied", inScope.text === "data-pre/one.txt" && outScope.status === 403 && write.status === 403, `${inScope.status} ${outScope.status} ${write.status}`);
await page.getByRole("button", { name: "Delete", exact: true }).nth(1).click();   // grant
await page.getByRole("cell", { name: `s3://${BA}/pre/*`, exact: true }).waitFor({ state: "detached", timeout: 10000 });
await page.getByRole("row", { name: new RegExp(`s3://${BA}`) }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "Delete", exact: true }).first().click();   // location
await page.getByRole("cell", { name: `s3://${BA}`, exact: true }).waitFor({ state: "detached", timeout: 10000 });
await page.getByRole("button", { name: "Delete instance" }).click();
await page.getByRole("button", { name: "Create S3 Access Grants instance" }).first().waitFor({ timeout: 10000 });
check("deleting grant, location and instance from the UI removes them", (await s3("GET", "/v20180820/accessgrantsinstance")).status === 404);

// ── 3. Batch Operations
await s3("PUT", `/${BA}/manifest.csv`, { body: `${BA},pre%2Fone.txt\n${BA},pre%2Ftwo.txt\n${BA},nothing-here.txt\n` });
await page.goto(UI + "#/s3/batch-operations");
await page.getByRole("heading", { name: "Batch Operations jobs" }).first().waitFor({ timeout: 15000 });
check("Batch Operations page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create job" }).first().click();
await pick("Manifest bucket", `^${BA}`);
await page.getByLabel("Manifest object key").fill("manifest.csv");
await page.getByRole("button", { name: "Next" }).click();
await pick("Operation", "Replace all object tags");
await page.getByLabel("Tags", { exact: true }).fill("team=data\nenv=prod");
await page.getByRole("button", { name: "Next" }).click();
await page.getByLabel("Description").fill(`ui job ${N}`);
await pick("Completion report bucket", `^${REP}`);
await page.getByRole("button", { name: "Next" }).click();
await page.getByText("Review").first().waitFor();
await page.getByRole("button", { name: "Create job" }).last().click();
await page.getByRole("cell", { name: `ui job ${N}`, exact: true }).waitFor({ timeout: 15000 });
const jl = await s3("GET", "/v20180820/jobs");
const jid = tag(jl.text.slice(jl.text.indexOf("<JobId>")), "JobId");
check("job created in the wizard -> native ListJobs, waiting for confirmation (Suspended)", jl.text.includes("<Status>Suspended</Status>") && jl.text.includes("S3PutObjectTagging"), jl.text.slice(0, 200));
await page.getByRole("row", { name: new RegExp(`ui job ${N}`) }).getByRole("radio").click({ force: true });
await page.getByTestId("job-detail").waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Confirm and run" }).click();
await page.getByRole("row", { name: new RegExp(`ui job ${N}`) }).getByText("Complete").waitFor({ timeout: 30000 });
const d = (await s3("GET", `/v20180820/jobs/${jid}`)).text;
check("job ran: 2 succeeded, 1 failed of 3 (missing key), reported in the UI", tag(d, "NumberOfTasksSucceeded") === "2" && tag(d, "NumberOfTasksFailed") === "1" && (await page.getByTestId("job-detail").innerText()).includes("2 succeeded, 1 failed of 3"), d.slice(0, 200));
const tg = await s3("GET", `/${BA}/pre/two.txt?tagging`);
check("S3PutObjectTagging executed against the store (tags visible via GetObjectTagging)", tg.text.includes("<Key>team</Key><Value>data</Value>") && tg.text.includes("<Key>env</Key>"), tg.text.slice(0, 160));
await page.getByText("Completion report objects").waitFor({ timeout: 10000 });
check("completion report objects listed in the job details", (await page.getByTestId("job-detail").locator("xpath=following::table[1]").innerText().catch(() => "")).includes(`job-${jid}`) || (await page.locator("body").innerText()).includes(`job-${jid}/manifest.json`));
const rl = await s3("GET", `/${REP}?list-type=2&prefix=batch-reports/job-${jid}/`);
check("report + manifest.json written to the report bucket/prefix", rl.text.includes("manifest.json") && rl.text.includes("/results/"), rl.text.slice(0, 200));
await shot("s3batch2-jobs");

check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
