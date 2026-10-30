/* End-to-end smoke of the AWS lens against a running /_wire backend (dev_server.py, the
 * offline appliance, or Nano). Drives the UI like a user; cross-checks state over the
 * native wire (what an SDK/CLI would see). Screenshots → $OUT (default ./smoke-out).
 *
 *   BASE=http://127.0.0.1:8740 node consoles/tests/smoke-aws.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:8740";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const B = `v4-smoke-${Date.now() % 100000}`;
const T = `v4smoke${Date.now() % 100000}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;
// Native-wire cross-checks run INSIDE the page (same origin) — on Nano only the service
// worker answers /_wire, and it only sees requests from pages it controls.
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return r.text(); }, [WIRE + path, init]);
const ddb = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `DynamoDB_20120810.${target}`, "content-type": "application/x-amz-json-1.0", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Native 404s ("no tag set", "no encryption config") are expected answers, not page errors.
page.on("console", (m) => m.type() === "error" && !/status of 404/.test(m.text()) && errors.push(m.text()));
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });

try {
  await page.goto(UI, { waitUntil: "networkidle" });
  // Nano: the service worker must control the page (nano-boot reloads once) before /_wire works.
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller, null, { timeout: 180000, polling: 500 });
  await page.getByRole("heading", { name: "Console Home" }).waitFor({ timeout: 120000 });
  await shot("01-home");
  check("home renders", true);

  // S3: create bucket through the form
  await page.goto(UI + "#/s3/create");
  await page.getByLabel("Bucket name").fill(B);
  await page.getByRole("radio", { name: "Enable", exact: true }).first().check();   // Bucket Versioning
  await shot("02-s3-create-filled");
  await page.getByRole("button", { name: "Create bucket" }).last().click();
  await page.getByRole("heading", { name: B }).waitFor({ timeout: 10000 });
  const list = await wire("/");
  check("S3 create bucket → visible over native wire", list.includes(`<Name>${B}</Name>`));
  const ver = await wire(`/${B}?versioning=`);
  check("S3 versioning applied (native GetBucketVersioning)", /<Status>Enabled<\/Status>/.test(ver), ver.slice(0, 120));
  await shot("03-s3-bucket-objects");

  // Upload via UI, verify via wire
  await page.locator('input[type=file]').setInputFiles({ name: "hello.txt", mimeType: "text/plain", buffer: Buffer.from("hello v4") });
  await page.getByRole("link", { name: "hello.txt" }).waitFor({ timeout: 10000 });
  const obj = await wire(`/${B}/hello.txt`);
  check("S3 upload → object readable over native wire", obj === "hello v4", obj);
  await shot("04-s3-uploaded");
  for (const tab of ["Properties", "Permissions", "Management"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(800);
    await shot(`05-s3-tab-${tab.toLowerCase()}`);
  }
  check("S3 detail tabs render", true);

  // Bucket list shows it
  await page.goto(UI + "#/s3");
  await page.getByRole("link", { name: B }).waitFor({ timeout: 10000 });
  await shot("06-s3-buckets");
  check("S3 bucket list shows new bucket", true);

  // DynamoDB: create table via UI
  await page.goto(UI + "#/dynamodb/create-table");
  await page.getByLabel("Table name").fill(T);
  await page.getByRole("textbox", { name: "Partition key", exact: true }).fill("pk");
  await shot("07-ddb-create-filled");
  await page.getByRole("button", { name: "Create table" }).last().click();
  await page.getByRole("link", { name: T }).waitFor({ timeout: 10000 });
  const tables = await ddb("ListTables", {});
  check("DynamoDB create table → visible over native wire", (tables.TableNames || []).includes(T));
  await shot("08-ddb-tables");

  // Item created over the wire shows in Explore items (CLI → UI direction)
  await ddb("PutItem", { TableName: T, Item: { pk: { S: "order-1" }, total: { N: "42" } } });
  await page.goto(UI + `#/dynamodb/tables/${T}/items`);
  await page.getByText("order-1").first().waitFor({ timeout: 10000 });
  check("DynamoDB item put over wire → shown in Explore items", true);
  await shot("09-ddb-items");
  await page.goto(UI + `#/dynamodb/tables/${T}`);
  await page.getByRole("tab", { name: "Overview" }).waitFor();
  await shot("10-ddb-overview");

  // Dark mode
  await page.evaluate(() => localStorage.setItem("vyomi.v4.mode", "dark"));
  await page.reload();
  await page.waitForTimeout(1500);
  await shot("11-dark");
} catch (e) {
  check("smoke run", false, e.message.split("\n")[0]);
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
