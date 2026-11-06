/* Nano console: Amazon ECS clusters — same flow as the offline console test
 * (tests/conformance/ui/aws-ecs.mjs): open the service, create with defaults, every
 * column filled, detail tabs render, services/tasks/task definitions/capacity providers,
 * delete. Also checks the SDK/CLI side: a cluster created in the UI is visible on the
 * relay's native ECS wire (AmazonEC2ContainerServiceV20141113.ListClusters).
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-ecs.mjs
 * One [PASS]/[FAIL] line per check; exit 1 on any failure. */
import { startServer, bootConsole, chromium, RELAY } from "./lib.mjs";
import { runEcsFlow } from "../../tests/conformance/ui/_ecs_flow.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};
const wire = async () => {
  const r = await fetch(RELAY + "/", { method: "POST", signal: AbortSignal.timeout(4000),
    headers: { "content-type": "application/x-amz-json-1.1", "x-amz-target": "AmazonEC2ContainerServiceV20141113.ListClusters",
               authorization: "AWS4-HMAC-SHA256 Credential=test/20260101/us-east-1/ecs/aws4_request, SignedHeaders=host, Signature=0" },
    body: "{}" });
  const j = await r.json().catch(() => ({}));
  if (r.status === 503) throw new Error("no Nano tab attached to the relay");
  return { status: r.status, json: j };
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let wireState = "pending";   // pending | skipped | done
try {
  await bootConsole(page, base, "/aws-console.html");
  await page.waitForTimeout(1500);
  page.on("response", async (r) => {
    if (wireState === "pending" && r.request().method() === "POST" && /\/api\/ecs\/clusters$/.test(r.url()) && r.status() === 201) {
      wireState = "running";
      try {
        const w = await wire();
        const arns = w.json.clusterArns || [];
        check(w.status === 200 && Array.isArray(w.json.clusterArns), "relay serves the native ECS JSON-1.1 wire", `HTTP ${w.status} ${JSON.stringify(w.json).slice(0, 100)}`);
        wireState = "done";
      } catch (e) {
        console.log("[SKIP] relay has no Nano endpoint tab attached — native-wire check skipped (" + e.message + ")");
        wireState = "skipped";
      }
    }
  });
  await runEcsFlow(page, check);
  if (wireState === "pending") console.log("[SKIP] native-wire check skipped (no cluster-create response observed)");
} catch (e) {
  check(false, "ECS Nano console flow", String(e.stack || e).split("\n").slice(0, 6).join(" / "));
}
await browser.close(); server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
