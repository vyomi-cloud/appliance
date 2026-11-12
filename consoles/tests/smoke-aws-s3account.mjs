/* S3 account-level pages (sweep S3-1): Block Public Access for this account, directory buckets
 * (S3 Express One Zone) and Object Lambda Access Points. Drives the real UI, cross-checks over
 * the native wire, and asserts none of the three is the "Not simulated" panel any more.
 *
 *   BASE=http://127.0.0.1:9051 node consoles/tests/smoke-aws-s3account.mjs                       (offline)
 *   BASE=http://127.0.0.1:9053 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-s3account.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9051";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const B = `s3acct-${N}`, AP = `s3acct-ap-${N}`, FN = `s3acct-fn-${N}`, OL = `s3acct-ol-${N}`, DIR = `ui-dir-${N}`;
const ACCT = "123456789012";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const s3 = (method, path, { body, headers = {} } = {}) => wire(path, { method, body, headers: { authorization: auth("s3"), "x-amz-account-id": ACCT, ...headers } });
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const notSim = async () => /Not simulated/i.test(await page.locator("body").innerText());

await page.goto(UI + "#/s3");
await page.getByText("General purpose buckets").first().waitFor({ timeout: 30000 });

// ── fixtures over the native wire (what an SDK would do)
await s3("PUT", `/${B}`);
await s3("PUT", `/${B}/doc.txt`, { body: "hello olap" });
await s3("PUT", `/v20180820/accesspoint/${AP}`, { body: `<CreateAccessPointRequest xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"><Bucket>${B}</Bucket></CreateAccessPointRequest>` });
const src = "import base64\ndef lambda_handler(event, context):\n    t = base64.b64decode(event['getObjectContext']['vyomiInputBase64']).decode()\n    return {'statusCode': 200, 'body': t.upper(), 'headers': {'content-type': 'text/plain'}}\n";
const mk = await wire("/2015-03-31/functions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ FunctionName: FN, Runtime: "python3.12", Handler: "lambda_function.lambda_handler", Role: "arn:aws:iam::123456789012:role/x", Code: { Source: src } }) });
check("fixture Lambda created", mk.status === 200 || mk.status === 201, mk.text.slice(0, 100));

// ── 1. Block Public Access settings for this account
await page.goto(UI + "#/s3/settings");
await page.getByRole("heading", { name: "Block Public Access settings for this account" }).first().waitFor({ timeout: 15000 });
await page.getByTestId("account-pab-summary").waitFor({ timeout: 15000 });
check("account BPA page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Edit" }).first().click();
await page.getByText("Block all public access", { exact: true }).last().click();
await page.getByLabel("Confirm", { exact: true }).fill("confirm");
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByText("Block all public access: On").waitFor({ timeout: 10000 });
const pab = await s3("GET", "/v20180820/configuration/publicAccessBlock");
check("account BPA saved in UI -> native s3control GetPublicAccessBlock", ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"].every((k) => pab.text.includes(`<${k}>true</${k}>`)), pab.text.slice(0, 160));
const denied = await s3("PUT", `/${B}?acl`, { headers: { "x-amz-acl": "public-read" } });
check("account BPA enforced: public ACL on a bucket without its own BPA is denied", denied.status === 403 && /account/.test(denied.text), `${denied.status} ${denied.text.slice(0, 120)}`);
await shot("s3acct-bpa");
await s3("DELETE", "/v20180820/configuration/publicAccessBlock");
const allowed = await s3("PUT", `/${B}?acl`, { headers: { "x-amz-acl": "public-read" } });
check("after removing the account BPA the same ACL is allowed", allowed.status === 200, String(allowed.status));

// ── 2. Directory buckets
await page.goto(UI + "#/s3/directory-buckets");
await page.getByRole("heading", { name: "Directory buckets" }).first().waitFor({ timeout: 15000 });
check("directory buckets page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create bucket" }).first().click();
await page.getByLabel("Bucket base name").fill(DIR);
await page.getByRole("dialog").getByRole("button", { name: "Create bucket" }).click();
const full = `${DIR}--usw2-az1--x-s3`;
await page.getByRole("cell", { name: full, exact: true }).waitFor({ timeout: 10000 });
const ld = await wire("/", { headers: { authorization: auth("s3express") } });
check("directory bucket created in UI -> native ListDirectoryBuckets", ld.text.includes(full) && ld.text.includes("ListAllMyDirectoryBucketsResult"), ld.text.slice(0, 160));
const lb = await s3("GET", "/");
check("directory bucket is NOT in the general ListBuckets", !lb.text.includes(full));
await page.getByRole("row", { name: new RegExp(full) }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "Create object" }).first().click();
await page.getByLabel("Object key").fill("dir/hello.txt");
await page.getByRole("dialog").locator("textarea").fill("express data");
await page.getByRole("dialog").getByRole("button", { name: "Create object" }).click();
await page.getByRole("cell", { name: "dir/hello.txt", exact: true }).waitFor({ timeout: 10000 });
const got = await s3("GET", `/${full}/dir/hello.txt`);
check("object created in UI readable over the wire", got.text === "express data", got.text);
const hd = await wire(`/${full}/dir/hello.txt`, { method: "HEAD", headers: { authorization: auth("s3") } });
check("object listed with EXPRESS_ONEZONE storage class", (await page.locator("body").innerText()).includes("EXPRESS_ONEZONE"));
await shot("s3acct-directory");
await page.getByRole("button", { name: "Empty" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Empty" }).click();
await page.getByText("No objects").waitFor({ timeout: 10000 });
const li = await s3("GET", `/${full}?list-type=2`);
check("Empty from UI removes the objects", !li.text.includes("hello.txt"), li.text.slice(0, 100));
await page.getByRole("button", { name: "Delete" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
await page.getByRole("cell", { name: full, exact: true }).waitFor({ state: "detached", timeout: 10000 });
const ld2 = await wire("/", { headers: { authorization: auth("s3express") } });
check("Delete from UI removes the directory bucket", !ld2.text.includes(full));
await page.goto(UI + "#/s3");
await page.getByRole("tab", { name: "Directory buckets" }).click();
await page.getByRole("button", { name: "Create bucket" }).first().waitFor({ timeout: 10000 });
check("Directory buckets tab on the Buckets page is the live page too", !/Not simulated/i.test(await page.getByRole("tabpanel").first().innerText()));

// ── 3. Object Lambda Access Points
await page.goto(UI + "#/s3/olap");
await page.getByRole("heading", { name: "Object Lambda Access Points" }).first().waitFor({ timeout: 15000 });
check("Object Lambda Access Points page is not the Not-simulated panel", !(await notSim()));
await page.getByRole("button", { name: "Create Object Lambda Access Point" }).first().click();
await page.getByLabel("Object Lambda Access Point name").fill(OL);
await page.getByRole("button", { name: /Supporting access point/i }).click();
await page.getByRole("option", { name: new RegExp(AP) }).click();
await page.getByRole("button", { name: /Lambda function/i }).click();
await page.getByRole("option", { name: new RegExp(FN) }).click();
await page.getByLabel("Payload").fill("p1");
await page.getByRole("dialog").getByRole("button", { name: "Create Object Lambda Access Point" }).click();
await page.getByRole("cell", { name: OL, exact: true }).waitFor({ timeout: 10000 });
const lst = await s3("GET", "/v20180820/accesspointforobjectlambda");
check("OLAP created in UI -> native ListAccessPointsForObjectLambda", lst.text.includes(OL) && lst.text.includes("--ol-s3"), lst.text.slice(0, 160));
const alias = (lst.text.match(new RegExp(`<Name>${OL}</Name>[\\s\\S]*?<Value>([^<]+)</Value>`)) || [])[1];
const viaOl = await s3("GET", `/${alias}/doc.txt`);
check("GetObject through the OLAP alias runs the Lambda (UI-created config)", viaOl.status === 200 && viaOl.text === "HELLO OLAP", `${viaOl.status} ${viaOl.text.slice(0, 100)}`);
await page.getByRole("row", { name: new RegExp(OL) }).getByRole("radio").click({ force: true });
await page.getByText(`Configuration - ${OL}`).waitFor({ timeout: 10000 });
check("selecting the OLAP shows its stored configuration (supporting AP + Lambda)", (await page.locator("body").innerText()).includes(FN));
await shot("s3acct-olap");
await page.getByRole("button", { name: "Delete" }).first().click();
await page.getByRole("cell", { name: OL, exact: true }).waitFor({ state: "detached", timeout: 10000 });
const lst2 = await s3("GET", "/v20180820/accesspointforobjectlambda");
check("Delete from UI removes the OLAP", !lst2.text.includes(OL));

check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
