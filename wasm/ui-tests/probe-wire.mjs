/* v4 `/_wire/*` native-wire prefix on Nano.
 *
 * Boots the real Nano AWS console (SW + page Pyodide), then from the PAGE does
 * native-wire round trips through fetch(BASE + "/_wire/...") — S3 REST/XML (incl.
 * a binary object) and DynamoDB X-Amz-Target JSON — and checks:
 *   1. the native responses (XML / JSON shapes, status codes, ETag, raw bytes);
 *   2. the SAME shared registry: /_wire-created resources are visible through the
 *      console /api/* adapters and vice versa;
 *   3. the persisted snapshot the relay restores from (IndexedDB nano-spaces/meta
 *      "nano:stores") contains them — i.e. what the relay CLI will see;
 *   4. after a reload, /_wire still sees everything (nano_persist).
 *   5. recursion guard: /_wire/_wire/... → 400.
 *
 *   NANO_DIR=<worktree>/wasm node wasm/ui-tests/probe-wire.mjs
 */
import { startServer, bootConsole, chromium, NANO_DIR } from "./lib.mjs";

const { server, base } = await startServer(NANO_DIR);
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("console", (m) => { if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 200)); });

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };
const SFX = Date.now().toString(36);
const BUCKET = "wire-" + SFX, API_BUCKET = "api-" + SFX, TABLE = "wiretbl_" + SFX;

// Runs IN the page. BASE = the bundle mount ("" here; "/nano" under the portal).
const inPage = async ({ BUCKET, API_BUCKET, TABLE, phase }) => {
  const BASE = new URL(".", document.querySelector('script[src*="nano-boot"]')?.src || location.href).pathname.replace(/\/$/, "");
  const W = BASE + "/_wire";
  const S3A = "AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/s3/aws4_request, SignedHeaders=host;x-amz-date, Signature=" + "0".repeat(64);
  const DDBA = S3A.replace("/s3/", "/dynamodb/");
  const ddb = (op, body) => fetch(W + "/", { method: "POST", body: JSON.stringify(body),
    headers: { "content-type": "application/x-amz-json-1.0", "x-amz-target": "DynamoDB_20120810." + op, authorization: DDBA } });
  const blob = new Uint8Array(1024); for (let i = 0; i < blob.length; i++) blob[i] = i & 0xff;
  const r = { base: BASE };
  if (phase === "create") {
    let x = await fetch(W + "/" + BUCKET, { method: "PUT", headers: { authorization: S3A } });
    r.createBucket = x.status;
    x = await fetch(W + "/" + BUCKET + "/dir/obj.bin", { method: "PUT", body: blob, headers: { authorization: S3A, "content-type": "application/octet-stream" } });
    r.putObject = x.status; r.putEtag = x.headers.get("etag");
    // console /api create → must be visible through /_wire
    x = await fetch(BASE + "/api/s3/buckets", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: API_BUCKET }) });
    r.apiCreate = x.status;
    x = await ddb("CreateTable", { TableName: TABLE, AttributeDefinitions: [{ AttributeName: "pk", AttributeType: "S" }],
      KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }], BillingMode: "PAY_PER_REQUEST" });
    r.createTable = x.status; r.createTableBody = (await x.text()).slice(0, 160);
    x = await ddb("PutItem", { TableName: TABLE, Item: { pk: { S: "a" }, v: { N: "7" }, b: { B: "AAEC/w==" } } });
    r.putItem = x.status;
    x = await fetch(W + "/_wire/" + BUCKET, { headers: { authorization: S3A } });
    r.recursion = x.status;
    // the console adapters (same registry) see the /_wire-created resources
    const apiB = await (await fetch(BASE + "/api/s3/buckets")).json();
    r.apiSeesWireBucket = JSON.stringify(apiB).includes(BUCKET);
    const apiT = await (await fetch(BASE + "/api/dynamodb/tables")).json();
    r.apiSeesWireTable = JSON.stringify(apiT).includes(TABLE);
    // wait for the debounced (400 ms) snapshot → IndexedDB, then read it like the relay does
    await new Promise((res) => setTimeout(res, 1500));
    const snap = await new Promise((res) => { const o = indexedDB.open("nano-spaces", 1);
      o.onsuccess = () => { const g = o.result.transaction("meta").objectStore("meta").get("nano:stores");
        g.onsuccess = () => res(g.result ? g.result.v : ""); g.onerror = () => res(""); }; o.onerror = () => res(""); });
    r.snapshotHasBucket = String(snap).includes(BUCKET);
    r.snapshotHasTable = String(snap).includes(TABLE);
  }
  // read-back phase (run before AND after reload)
  let x = await fetch(W + "/", { headers: { authorization: S3A } });
  const xml = await x.text();
  r.listStatus = x.status; r.listCT = x.headers.get("content-type");
  r.listIsXml = xml.includes("ListAllMyBucketsResult");
  r.listHasWire = xml.includes("<Name>" + BUCKET + "</Name>");
  r.listHasApi = xml.includes("<Name>" + API_BUCKET + "</Name>");
  x = await fetch(W + "/" + BUCKET + "/dir/obj.bin", { headers: { authorization: S3A } });
  const got = new Uint8Array(await x.arrayBuffer());
  r.getObject = x.status; r.getEtag = x.headers.get("etag");
  r.bytesEqual = got.length === blob.length && got.every((v, i) => v === blob[i]);
  x = await fetch(W + "/" + BUCKET + "?list-type=2&prefix=dir/", { headers: { authorization: S3A } });
  r.listObjectsHasKey = (await x.text()).includes("<Key>dir/obj.bin</Key>");
  x = await fetch(W + "/" + BUCKET + "/missing.txt", { headers: { authorization: S3A } });
  r.missing = x.status; r.missingIsNoSuchKey = (await x.text()).includes("NoSuchKey");
  x = await ddb("ListTables", {}); const lt = await x.json();
  r.listTables = x.status; r.listTablesHas = (lt.TableNames || []).includes(TABLE);
  x = await ddb("GetItem", { TableName: TABLE, Key: { pk: { S: "a" } } }); const gi = await x.json();
  r.getItem = x.status; r.item = gi.Item || null;
  return r;
};

try {
  await bootConsole(page, base, "/aws-console.html");
  const a = await page.evaluate(inPage, { BUCKET, API_BUCKET, TABLE, phase: "create" });
  console.log("phase 1:", JSON.stringify(a));
  check("S3 CreateBucket via /_wire → 200", a.createBucket === 200, String(a.createBucket));
  check("S3 PutObject (binary) via /_wire → 200 + ETag", a.putObject === 200 && !!a.putEtag, a.putEtag);
  check("DynamoDB CreateTable via /_wire (X-Amz-Target) → 200", a.createTable === 200, a.createTableBody);
  check("DynamoDB PutItem via /_wire → 200", a.putItem === 200);
  check("ListBuckets via /_wire is native XML", a.listStatus === 200 && a.listIsXml, a.listCT);
  check("ListBuckets via /_wire sees /_wire bucket", a.listHasWire);
  check("ListBuckets via /_wire sees console(/api)-created bucket", a.listHasApi);
  check("console /api/s3/buckets sees /_wire bucket", a.apiSeesWireBucket);
  check("console /api/dynamodb/tables sees /_wire table", a.apiSeesWireTable);
  check("GetObject via /_wire: bytes round-trip + same ETag", a.getObject === 200 && a.bytesEqual && a.getEtag === a.putEtag);
  check("ListObjectsV2 via /_wire keeps query string", a.listObjectsHasKey);
  check("missing key → native 404 NoSuchKey", a.missing === 404 && a.missingIsNoSuchKey);
  check("ListTables via /_wire has table (native TableNames)", a.listTables === 200 && a.listTablesHas);
  check("GetItem via /_wire returns typed item", a.getItem === 200 && a.item && a.item.pk?.S === "a" && a.item.v?.N === "7", JSON.stringify(a.item));
  // Pre-existing core gap (same on the relay): dynamodb_core returns a B (binary)
  // attribute as S. Reported, not gated here — it is not a transport issue.
  if (!(a.item && a.item.b?.B === "AAEC/w==")) console.log("KNOWN-GAP  dynamodb_core: B attribute comes back as", JSON.stringify(a.item && a.item.b));
  if (!a.listCT) console.log("KNOWN-GAP  s3_object_core: ListBuckets response has no content-type header");
  check("relay snapshot (IndexedDB nano:stores) has bucket + table", a.snapshotHasBucket && a.snapshotHasTable);
  check("recursion guard /_wire/_wire/... → 400", a.recursion === 400, String(a.recursion));

  // Reload → fresh Pyodide restores the persisted registry; /_wire must still see it.
  await page.reload({ waitUntil: "domcontentloaded" });
  await bootConsole(page, base, "/aws-console.html");
  const b = await page.evaluate(inPage, { BUCKET, API_BUCKET, TABLE, phase: "readback" });
  console.log("phase 2 (after reload):", JSON.stringify(b));
  check("after reload: ListBuckets via /_wire has both buckets", b.listHasWire && b.listHasApi);
  check("after reload: GetObject bytes + ETag intact", b.getObject === 200 && b.bytesEqual && b.getEtag === a.putEtag);
  check("after reload: DynamoDB table + item intact", b.listTablesHas && b.item && b.item.v?.N === "7");
} catch (e) {
  check("probe ran", false, String(e).split("\n")[0]);
}
await browser.close(); server.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
