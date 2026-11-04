/* S3 Vectors (AWS-01): drives the real Vector buckets page (create bucket -> index -> add vectors -> similarity query
 * with a metadata filter -> delete), cross-checks over the native s3vectors wire, asserts it is not a "Not simulated" panel.
 *
 *   BASE=http://127.0.0.1:9031 node consoles/tests/smoke-aws-s3vectors.mjs                                  (offline)
 *   BASE=http://127.0.0.1:8743 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-s3vectors.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9031";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || ""}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const VB = `vsmoke-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/s3vectors/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/s3");
const sv = (op, payload) => page.evaluate(async ([u, o, p, a]) => { const r = await fetch(`${u}/${o}`, { method: "POST", headers: { authorization: a, "content-type": "application/json" }, body: JSON.stringify(p) }); return { status: r.status, body: await r.json().catch(() => ({})) }; }, [WIRE, op, payload, auth]);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const body = () => page.locator("body").innerText();

await page.goto(UI + "#/s3/vector-buckets");
await page.getByRole("button", { name: "Create vector bucket" }).first().waitFor();
check("page is not the Not-simulated panel", !/Not simulated in Vyomi/i.test(await body()));
check("nav has Vector buckets", await page.getByRole("link", { name: "Vector buckets" }).first().isVisible());

// create bucket
await page.getByRole("button", { name: "Create vector bucket" }).first().click();
await page.getByLabel("Vector bucket name").fill(VB);
await page.getByRole("dialog").getByRole("button", { name: "Create vector bucket" }).click();
await page.getByText(VB, { exact: true }).first().waitFor({ timeout: 10000 });
check("bucket created in UI + on wire", (await sv("GetVectorBucket", { vectorBucketName: VB })).status === 200);
await page.getByRole("row", { name: new RegExp(VB) }).getByRole("radio").check();

// create index
await page.getByRole("button", { name: "Create vector index" }).first().click();
await page.getByLabel("Vector index name").fill("movies");
await page.getByLabel("Dimensions").fill("3");
await page.getByRole("dialog").getByRole("button", { name: "Create vector index" }).click();
await page.getByText("movies", { exact: true }).first().waitFor({ timeout: 10000 });
const ix = await sv("GetIndex", { vectorBucketName: VB, indexName: "movies" });
check("index created (dimension 3, cosine)", ix.body.index?.dimension === 3 && ix.body.index?.distanceMetric === "cosine");
await page.getByRole("row", { name: /movies/ }).getByRole("radio").check();

// add vectors in UI
const add = async (key, data, meta) => {
  await page.getByRole("button", { name: "Add vector" }).first().click();
  await page.getByLabel("Vector key").fill(key);
  await page.getByLabel("Vector data").fill(data);
  if (meta) await page.getByLabel(/Metadata \(optional JSON object\)/).fill(meta);
  await page.getByRole("dialog").getByRole("button", { name: "Add vector" }).click();
  await page.getByText(key, { exact: true }).first().waitFor({ timeout: 10000 });
};
await add("alien", "1, 0, 0", '{"genre":"scifi"}');
await add("heat", "0, 1, 0", '{"genre":"crime"}');
await add("dune", "0.9, 0.1, 0", '{"genre":"scifi"}');
const lv = await sv("ListVectors", { vectorBucketName: VB, indexName: "movies" });
check("3 vectors stored (wire)", lv.body.vectors?.length === 3);
await shot("s3vectors-vectors");

// query tab
await page.getByRole("tab", { name: "Query" }).click();
await page.getByLabel("Query vector").fill("1, 0, 0");
await page.getByLabel("Top K").fill("2");
await page.getByRole("button", { name: "Query", exact: true }).click();
await page.getByText("Nearest vectors").waitFor({ timeout: 10000 });
const results1 = async () => (await page.locator("table").filter({ hasText: "Distance" }).locator("tbody tr").allInnerTexts()).map((t) => t.split(/\s+/)[0]);
const r1 = await results1();
check("query returns alien then dune", JSON.stringify(r1) === '["alien","dune"]', r1.join(","));
await page.getByLabel("Metadata filter").fill('{"genre":"crime"}');
await page.getByRole("button", { name: "Query", exact: true }).click();
await page.waitForFunction(() => [...document.querySelectorAll("table")].some((t) => /Distance/.test(t.innerText) && /heat/.test(t.innerText) && !/alien/.test(t.innerText)), null, { timeout: 10000 });
const r2 = await results1();
check("filter narrows to crime", JSON.stringify(r2) === '["heat"]', r2.join(","));
await shot("s3vectors-query");
const qw = await sv("QueryVectors", { vectorBucketName: VB, indexName: "movies", queryVector: { float32: [1, 0, 0] }, topK: 3, filter: { genre: "crime" }, returnDistance: true });
check("wire filter query = [heat]", JSON.stringify(qw.body.vectors?.map((v) => v.key)) === '["heat"]');

// validation surfaces from the UI
await page.getByRole("tab", { name: "Vectors" }).click();
await page.getByRole("button", { name: "Add vector" }).first().click();
await page.getByLabel("Vector key").fill("bad");
await page.getByLabel("Vector data").fill("1, 2");
await page.getByRole("dialog").getByRole("button", { name: "Add vector" }).click();
await page.getByText(/does not match the index dimension/).first().waitFor({ timeout: 10000 });
check("dimension mismatch surfaces an error", true);
await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

// cleanup via wire + delete guard
check("delete bucket with index refused", (await sv("DeleteVectorBucket", { vectorBucketName: VB })).status === 409);
await sv("DeleteIndex", { vectorBucketName: VB, indexName: "movies" });
check("cleanup", (await sv("DeleteVectorBucket", { vectorBucketName: VB })).status === 200);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
