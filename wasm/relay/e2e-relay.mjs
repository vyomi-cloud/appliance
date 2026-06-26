/* End-to-end proof of the Nano relay loop, fully local:
 *   external HTTP client → local relay → browser tab (Pyodide + real S3 core) → response
 *
 * This is the CORE GOAL demonstrated: an external client (standing in for
 * aws-cli/boto3) validates against the in-browser sim — no install on the
 * "sim" side beyond a browser tab. Same WS protocol the Cloudflare relay uses.
 *
 * Prereqs: a repo-root static server on :8000 (so /core/*.py and
 * /wasm/relay/*.html are reachable), the local relay running on :8090, and
 * Playwright available. The harness (run-e2e.sh) wires these up.
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright");

const RELAY_HTTP = process.env.RELAY_HTTP || "http://localhost:8090";
const TAB_URL = process.env.TAB_URL ||
  "http://localhost:8000/wasm/relay/nano-endpoint.html?relay=ws://localhost:8090/register&core=/core";

const fail = (m) => { console.log("FAIL:", m); process.exit(1); };

// the "external app" — raw HTTP, like aws-cli would do (native S3 wire protocol)
async function s3(method, path, body) {
  const r = await fetch(RELAY_HTTP + path, {
    method, body: body ?? undefined,
    headers: body ? { "content-type": "text/plain" } : {},
  });
  return { status: r.status, headers: Object.fromEntries(r.headers), text: await r.text() };
}

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("[tab pageerror]", e.message));
try {
  await page.goto(TAB_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__nano && window.__nano.registered, { timeout: 90000 })
    .catch(() => fail("tab never registered with the relay (Pyodide/core/WS boot)"));
  console.log("0. PASS — Nano tab booted core + registered with the relay");

  // external client drives the native S3 wire protocol THROUGH the relay
  const mb = await s3("PUT", "/demo");                          // aws s3 mb s3://demo
  if (mb.status !== 200) fail("create bucket: " + mb.status);
  const put = await s3("PUT", "/demo/hello.txt", "hello from an EXTERNAL client");
  if (put.status !== 200 || !put.headers.etag) fail("put: " + JSON.stringify(put));
  console.log("1. PASS — external PUT → 200 + ETag (handled by in-browser core)");

  const get = await s3("GET", "/demo/hello.txt");
  if (get.status !== 200 || get.text !== "hello from an EXTERNAL client")
    fail("get round-trip: " + JSON.stringify(get));
  console.log("2. PASS — external GET round-trips the body from the browser tab");

  const list = await s3("GET", "/demo");                       // aws s3 ls s3://demo
  if (!list.text.includes("<Key>hello.txt</Key>")) fail("list: " + list.text.slice(0, 200));
  console.log("3. PASS — external LIST returns the key (ListBucketResult XML)");

  const del = await s3("DELETE", "/demo/hello.txt");           // aws s3 rm
  const after = await s3("GET", "/demo/hello.txt");
  if (del.status !== 204 || after.status !== 404) fail("delete: " + del.status + "/" + after.status);
  console.log("4. PASS — external DELETE 204, then GET 404 (NoSuchKey)");

  const served = await page.evaluate(() => window.__nano.served);
  console.log(`\nRESULT: PASS — external client validated against the IN-BROWSER sim via the relay (${served} requests served by the tab).`);
} catch (e) {
  fail(String(e));
} finally {
  await browser.close();
}
