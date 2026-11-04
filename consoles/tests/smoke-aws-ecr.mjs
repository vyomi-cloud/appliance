/* ECR console: create a repository in the UI, push an image over the native wire, scan it, read findings, edit + dry-run a lifecycle
 * policy, delete the image/repo.   BASE=http://127.0.0.1:9084 node consoles/tests/smoke-aws-ecr.mjs   (Nano: UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9084";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const REPO = `smoke/app-${Date.now() % 100000}`;
const results = [];
const check = (name, ok, d = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ecr/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/ecr");
const ecr = (op, p) => page.evaluate(async ([u, o, p, a]) => { const r = await fetch(`${u}/`, { method: "POST", headers: { authorization: a, "x-amz-target": "AmazonEC2ContainerRegistry_V20150921." + o, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(p) }); return { status: r.status, body: await r.json().catch(() => ({})) }; }, [WIRE, op, p, auth]);
const sha = (b) => "sha256:" + createHash("sha256").update(b).digest("hex");
const b64 = (b) => Buffer.from(b).toString("base64");
const body = () => page.locator("body").innerText();

await page.getByRole("button", { name: "Create repository" }).first().waitFor();
check("not a Not-simulated panel", !/Not simulated in Vyomi/i.test(await body()));
await page.getByRole("button", { name: "Create repository" }).first().click();
await page.getByLabel("Repository name").fill(REPO);
await page.getByRole("dialog").getByText("Scan on push").click();
await page.getByRole("dialog").getByRole("button", { name: "Create repository" }).click();
await page.getByRole("link", { name: REPO }).waitFor({ timeout: 10000 });
const d = await ecr("DescribeRepositories", { repositoryNames: [REPO] });
check("repo created in UI + wire (scanOnPush)", d.body.repositories?.[0]?.imageScanningConfiguration?.scanOnPush === true);

// push an image over the wire
const cfg = Buffer.from(JSON.stringify({ architecture: "amd64", os: "linux", config: { Env: ["PYTHON_VERSION=3.8.1"] }, history: [{ created_by: "RUN pip install requests==2.19.0 pyyaml==5.3" }] }));
const layer = Buffer.from("layer-bytes");
for (const data of [cfg, layer]) {
  const up = (await ecr("InitiateLayerUpload", { repositoryName: REPO })).body.uploadId;
  await ecr("UploadLayerPart", { repositoryName: REPO, uploadId: up, partFirstByte: 0, partLastByte: data.length - 1, layerPartBlob: b64(data) });
  await ecr("CompleteLayerUpload", { repositoryName: REPO, uploadId: up, layerDigests: [sha(data)] });
}
const man = JSON.stringify({ schemaVersion: 2, mediaType: "application/vnd.docker.distribution.manifest.v2+json",
  config: { mediaType: "application/vnd.docker.container.image.v1+json", size: cfg.length, digest: sha(cfg) },
  layers: [{ mediaType: "application/vnd.docker.image.rootfs.diff.tar.gzip", size: layer.length, digest: sha(layer) }] });
check("image pushed", (await ecr("PutImage", { repositoryName: REPO, imageManifest: man, imageTag: "v1" })).status === 200);

await page.getByRole("link", { name: REPO }).click();
await page.getByText("v1", { exact: true }).first().waitFor({ timeout: 10000 });
check("detail shows image tag v1", true);
await page.screenshot({ path: `${OUT}/ecr-images.png`, fullPage: true });
// scan from the UI
await page.getByRole("row", { name: /v1/ }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Scan", exact: true }).click();
await page.getByText("COMPLETE").first().waitFor({ timeout: 15000 });
check("scan completes from UI", true);
await page.getByRole("tab", { name: "Scan findings" }).click();
await page.getByRole("button", { name: /Choose an image/ }).click();
await page.getByRole("option").first().click();
await page.getByText("Vulnerabilities").first().waitFor({ timeout: 10000 });
const sw = await ecr("DescribeImageScanFindings", { repositoryName: REPO, imageId: { imageTag: "v1" } });
check("findings on wire", sw.status === 200);
await page.screenshot({ path: `${OUT}/ecr-findings.png`, fullPage: true });
// lifecycle
await page.getByRole("tab", { name: "Lifecycle policy" }).click();
await page.getByRole("button", { name: "Insert example" }).click();
await page.getByRole("button", { name: "Save", exact: true }).click();
await page.waitForFunction(async () => true);
await page.getByText("Lifecycle policy saved").first().waitFor({ timeout: 10000 });
check("lifecycle saved on wire", (await ecr("GetLifecyclePolicy", { repositoryName: REPO })).status === 200);
await page.getByRole("button", { name: "Dry run" }).click();
await page.getByText("Dry run results").first().waitFor({ timeout: 10000 });
check("dry run table shown", true);
// invalid policy surfaces
await page.getByLabel("Lifecycle policy JSON").fill('{bad');
await page.getByRole("button", { name: "Save", exact: true }).click();
await page.getByText(/InvalidParameter|LifecyclePolicy/).first().waitFor({ timeout: 10000 });
check("invalid policy error surfaces", true);
await page.screenshot({ path: `${OUT}/ecr-lifecycle.png`, fullPage: true });
// registry page
await page.goto(UI + "#/ecr/registry");
await page.getByText("Replication rules").first().waitFor({ timeout: 10000 });
check("registry settings page renders", !/Not simulated in Vyomi/i.test(await body()));
// cleanup via UI
await page.goto(UI + "#/ecr/repositories");
await page.getByRole("row", { name: new RegExp(REPO) }).getByRole("radio").check();
await page.getByRole("button", { name: "Delete", exact: true }).click();
await page.getByRole("dialog").getByRole("textbox").fill(REPO);
await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
await page.waitForTimeout(800);
check("repo deleted", (await ecr("DescribeRepositories", { repositoryNames: [REPO] })).status === 400);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
