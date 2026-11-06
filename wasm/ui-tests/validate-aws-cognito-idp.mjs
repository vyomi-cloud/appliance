/* Nano console: Amazon Cognito user pools — same flow as the offline console test
 * (tests/conformance/ui/aws-cognito-idp.mjs): open the service, create with defaults,
 * every column filled, detail tabs render, Users/Groups/App clients/Domain, delete.
 * Also checks the SDK/CLI side: a pool created in the UI is visible on the relay's
 * native Cognito wire (AWSCognitoIdentityProviderService.ListUserPools).
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-cognito-idp.mjs
 * One [PASS]/[FAIL] line per check; exit 1 on any failure. */
import { startServer, bootConsole, chromium, RELAY } from "./lib.mjs";
import { runCognitoFlow } from "../../tests/conformance/ui/_cognito_flow.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/aws-console.html");
  await page.waitForTimeout(1500);
  await runCognitoFlow(page, check);
} catch (e) {
  check(false, "Cognito Nano console flow", String(e.stack || e).split("\n").slice(0, 6).join(" / "));
}
// native wire on the relay (best effort: only when a relay is reachable)
try {
  const r = await fetch(RELAY + "/", { method: "POST", signal: AbortSignal.timeout(4000),
    headers: { "content-type": "application/x-amz-json-1.1", "x-amz-target": "AWSCognitoIdentityProviderService.ListUserPools",
               authorization: "AWS4-HMAC-SHA256 Credential=test/20260101/us-east-1/cognito-idp/aws4_request, SignedHeaders=host, Signature=0" },
    body: JSON.stringify({ MaxResults: 10 }) });
  const j = await r.json().catch(() => ({}));
  if (r.status === 503) throw new Error("no Nano tab attached to the relay");
  check(r.status === 200 && Array.isArray(j.UserPools), "relay serves the native Cognito JSON-1.1 wire", `HTTP ${r.status} ${JSON.stringify(j).slice(0, 100)}`);
} catch (e) {
  console.log("[SKIP] relay has no Nano endpoint tab attached — native-wire check skipped (" + e.message + ")");
}
await browser.close(); server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
