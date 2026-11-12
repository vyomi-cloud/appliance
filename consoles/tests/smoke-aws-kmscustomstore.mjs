/* KMS custom key store: create+connect a software-HSM store from the console, create a key in it, use it, disconnect -> unusable.
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-kmscustomstore.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/kms/aws4_request, SignedHeaders=host, Signature=0`;
const K = (op, body) => page.evaluate(async ([u, a, t, b]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, body: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth, "TrentService." + op, body]);
await page.goto(UI + "#/kms/cloudhsm-key-stores");
await page.waitForFunction(() => !/booting Pyodide|Loading aws cloudhsm/.test(document.body.innerText), null, { timeout: 120000 });
await page.getByRole("button", { name: "Create software-HSM key store" }).click(); await page.waitForTimeout(2000);
check("store listed as CONNECTED in the console", await page.getByText("CONNECTED", { exact: true }).count() >= 1);
const list = (await K("DescribeCustomKeyStores", {})).body.CustomKeyStores;
const cks = list.find((c) => c.ConnectionState === "CONNECTED");
const key = await K("CreateKey", { Origin: "AWS_CLOUDHSM", CustomKeyStoreId: cks.CustomKeyStoreId });
check("CreateKey in the connected store", key.status === 200 && key.body.KeyMetadata?.CustomKeyStoreId === cks.CustomKeyStoreId, JSON.stringify(key.body));
const kid = key.body.KeyMetadata.KeyId;
const enc = await K("Encrypt", { KeyId: kid, Plaintext: btoa("hello") });
const dec = await K("Decrypt", { CiphertextBlob: enc.body.CiphertextBlob });
check("Encrypt/Decrypt through the HSM partition", atob(dec.body.Plaintext) === "hello");
await K("DisconnectCustomKeyStore", { CustomKeyStoreId: cks.CustomKeyStoreId });
const dead = await K("Decrypt", { CiphertextBlob: enc.body.CiphertextBlob });
check("key unusable once the store is disconnected", dead.body.__type === "KMSInvalidStateException", JSON.stringify(dead.body));
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
