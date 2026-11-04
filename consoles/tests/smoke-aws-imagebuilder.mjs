/* EC2 Image Builder console: component -> recipe -> infrastructure -> distribution -> pipeline -> run -> image detail.
 * On a substrate without a container builder (Nano, dev server) the build must end FAILED with the honest reason and no AMI;
 * with BuildKit (offline appliance) it must end AVAILABLE with an AMI (EXPECT=AVAILABLE).
 *   BASE=http://127.0.0.1:9084 node consoles/tests/smoke-aws-imagebuilder.mjs      (Nano: UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9084";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const EXPECT = process.env.EXPECT || "FAILED";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, d = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/imagebuilder/aws4_request, SignedHeaders=host, Signature=0`;
const ib = (m, op, body, qs = "") => page.evaluate(async ([u, m, op, b, a, qs]) => { const r = await fetch(`${u}/${op}${qs}`, { method: m, headers: { authorization: a, "content-type": "application/json" }, body: m === "GET" || m === "DELETE" ? undefined : JSON.stringify(b) }); return { status: r.status, body: await r.json().catch(() => ({})) }; }, [WIRE, m, op, body, auth, qs]);
const dialog = () => page.getByRole("dialog");
const pick = async (label, text) => { await dialog().getByRole("button", { name: new RegExp(label) }).click(); await page.getByRole("option", { name: new RegExp(text) }).first().click(); };
const body = () => page.locator("body").innerText();
const C = `smoke-c-${N}`, R = `smoke-r-${N}`, I = `smoke-i-${N}`, D = `smoke-d-${N}`, P = `smoke-p-${N}`;

await page.goto(UI + "#/ec2/image-builder");
await page.waitForURL(/#\/imagebuilder\/pipelines/);
check("EC2 /image-builder link lands on the real console", !/Not simulated in Vyomi/i.test(await body()));
// component
await page.goto(UI + "#/imagebuilder/components");
await page.getByRole("button", { name: "Create component" }).first().click();
await dialog().getByLabel("Component name").fill(C);
await dialog().getByRole("button", { name: "Create component" }).click();
await page.getByRole("link", { name: C }).waitFor({ timeout: 10000 });
check("component created (wire)", (await ib("GET", "GetComponent", null, `?componentBuildVersionArn=${encodeURIComponent(`arn:aws:imagebuilder:us-east-1:123456789012:component/${C}/1.0.0/1`)}`)).status === 200);
// invalid component surfaces the real error
await page.getByRole("button", { name: "Create component" }).first().click();
await dialog().getByLabel("Component name").fill(C + "x");
await dialog().getByLabel("Definition document").fill("schemaVersion: 1.0\nphases:\n  - name: build\n    steps:\n      - name: a\n        action: Bogus\n");
await dialog().getByRole("button", { name: "Create component" }).click();
await dialog().getByText(/unknown action/).waitFor({ timeout: 10000 });
check("invalid document error surfaces", true);
await dialog().getByRole("button", { name: "Cancel" }).click();
// recipe
await page.goto(UI + "#/imagebuilder/recipes");
await page.getByRole("button", { name: "Create image recipe" }).first().click();
await dialog().getByLabel("Recipe name").fill(R);
await dialog().getByRole("button", { name: /Choose components/ }).click();
await page.getByRole("option", { name: new RegExp(C) }).first().click();
await page.keyboard.press("Escape").catch(() => {});
await dialog().getByRole("button", { name: "Create image recipe" }).click();
await page.getByRole("link", { name: R }).waitFor({ timeout: 10000 });
check("recipe created", true);
// infra + dist
await page.goto(UI + "#/imagebuilder/infrastructure");
await page.getByRole("button", { name: "Create infrastructure configuration" }).first().click();
await dialog().getByLabel("Configuration name").fill(I);
await dialog().getByRole("button", { name: "Create infrastructure configuration" }).click();
await page.getByText(I, { exact: true }).waitFor({ timeout: 10000 });
check("infrastructure configuration created", true);
await page.goto(UI + "#/imagebuilder/distributions");
await page.getByRole("button", { name: "Create distribution settings" }).first().click();
await dialog().getByLabel("Settings name").fill(D);
await dialog().getByRole("button", { name: "Create distribution settings" }).click();
await page.getByText(D, { exact: true }).waitFor({ timeout: 10000 });
check("distribution settings created", true);
// pipeline
await page.goto(UI + "#/imagebuilder/pipelines");
await page.getByRole("button", { name: "Create image pipeline" }).first().click();
await dialog().getByLabel("Pipeline name").fill(P);
await pick("Choose a recipe", R); await pick("Choose an infrastructure configuration", I); await pick("Choose distribution settings", D);
await dialog().getByRole("button", { name: "Create image pipeline" }).click();
await page.getByRole("link", { name: P }).waitFor({ timeout: 10000 });
check("pipeline created", true);
await page.getByRole("link", { name: P }).click();
await page.getByRole("button", { name: "Run pipeline" }).first().click();
await page.getByText(new RegExp(`${R} / 1.0.0/1|1.0.0/1`)).first().waitFor({ timeout: 90000 });
await page.screenshot({ path: `${OUT}/imagebuilder-pipeline.png`, fullPage: true });
await page.getByRole("link", { name: "1.0.0/1" }).click();
await page.getByText("Build log").first().waitFor({ timeout: 10000 });
const txt = await body();
if (EXPECT === "FAILED") {
  check("honest FAILED with reason on a substrate without a builder", /FAILED/.test(txt) && /No container builder/.test(txt));
  check("no output AMI", /No output AMIs/.test(txt));
} else {
  check("AVAILABLE with an output AMI", /AVAILABLE/.test(txt) && /ami-/.test(txt));
}
check("build log shows the compiled Dockerfile", /FROM ubuntu/.test(txt));
await page.screenshot({ path: `${OUT}/imagebuilder-image.png`, fullPage: true });
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
