/* Secrets Manager rotation function (AWS-08): pick a Lambda in the UI, rotate, verify the function really ran. UI <-> native wire.
 *   BASE=http://127.0.0.1:9110 node consoles/tests/smoke-aws-smrotation.mjs
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-smrotation.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9110";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const SEC = `smrot-${N}`, FN = `smrot-fn-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const sm = (op, body) => wire("/", { method: "POST", headers: { authorization: auth("secretsmanager"), "x-amz-target": `secretsmanager.${op}`, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(body) }).then((r) => ({ status: r.status, json: r.text ? JSON.parse(r.text) : {} }));
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });

await page.goto(UI + "#/secretsmanager");
await page.getByText("Secrets Manager").first().waitFor({ timeout: 30000 });
const src = "import json\ndef lambda_handler(event, context):\n    if event['Step'] == 'createSecret':\n        return {'SecretString': json.dumps({'password': 'ui-rotated-' + event['ClientRequestToken'][:5]})}\n    return None\n";
const mk = await wire("/2015-03-31/functions", { method: "POST", headers: { authorization: auth("lambda"), "content-type": "application/json" }, body: JSON.stringify({ FunctionName: FN, Runtime: "python3.12", Handler: "lambda_function.lambda_handler", Role: "arn:aws:iam::123456789012:role/x", Code: { Source: src } }) });
check("fixture rotation Lambda created", mk.status === 200 || mk.status === 201, mk.text.slice(0, 100));
await sm("CreateSecret", { Name: SEC, SecretString: JSON.stringify({ password: "initial" }) });

await page.goto(UI + `#/secretsmanager/secret/${SEC}`);
await page.getByRole("tab", { name: "Rotation" }).click();
await page.getByRole("button", { name: "Edit rotation" }).click();
await page.getByRole("button", { name: /Lambda rotation function/ }).click();
await page.getByRole("option", { name: new RegExp(FN) }).click();
check("rotation modal has a real function picker (no Not-simulated panel)", !/Not simulated in Vyomi/.test(await page.locator("body").innerText()));
await shot("smrot-modal");
await page.getByRole("button", { name: "Save", exact: true }).click();
await page.getByText(FN).first().waitFor({ timeout: 20000 });
const v = await sm("GetSecretValue", { SecretId: SEC });
check("saving the rotation ran the Lambda and the secret holds its generated value", v.status === 200 && JSON.parse(v.json.SecretString).password.startsWith("ui-rotated-"), v.json.SecretString);
const d = await sm("DescribeSecret", { SecretId: SEC });
check("DescribeSecret shows the rotation function", d.json.RotationLambdaARN?.endsWith(FN));
const prev = await sm("GetSecretValue", { SecretId: SEC, VersionStage: "AWSPREVIOUS" });
check("previous value kept as AWSPREVIOUS", JSON.parse(prev.json.SecretString || "{}").password === "initial");
await shot("smrot-done");
await page.getByRole("tab", { name: "Rotation" }).click();
await page.getByRole("button", { name: "Rotate secret immediately" }).click();
await page.waitForTimeout(1500);
const v2 = await sm("GetSecretValue", { SecretId: SEC });
check("Rotate immediately invokes the function again (new version)", v2.json.VersionId !== v.json.VersionId);
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
