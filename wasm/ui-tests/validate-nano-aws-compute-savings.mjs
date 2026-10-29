/* Nano: Lambda functions, API Gateway APIs, VPCs and EventBridge rules created in
 * the AWS console move the space's cost_savings (resource_count + aws savings). */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (name, ok, note = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + note}`); };
const snap = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  return (d.spaces[0] || {}).cost_savings || null;
});
const post = (path, body) => page.evaluate(async ([p, b]) => {
  await fetch(p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
}, [path, body]);
async function rises(label, create) {
  const before = await snap();
  await create();
  let after = before;
  for (let i = 0; i < 20; i++) { await sleep(1500); after = await snap(); if (after && before && after.resource_count > before.resource_count) break; }
  check(`${label}: resource_count rises`, !!after && after.resource_count > (before?.resource_count ?? 0), `${before?.resource_count} → ${after?.resource_count}`);
  return { before, after };
}
try {
  await bootConsole(page, base, "/aws-console.html");
  const s = Date.now().toString(36);
  const l = await rises("Lambda", () => post("/api/lambda/functions", { name: "sav" + s }));
  check("Lambda: aws savings rise", (l.after?.by_provider.aws ?? 0) > (l.before?.by_provider.aws ?? 0), `${l.before?.by_provider.aws} → ${l.after?.by_provider.aws}`);
  const a = await rises("API Gateway", () => post("/api/apigateway/apis", { name: "sav" + s }));
  check("API Gateway: aws savings rise", (a.after?.by_provider.aws ?? 0) > (a.before?.by_provider.aws ?? 0), `${a.before?.by_provider.aws} → ${a.after?.by_provider.aws}`);
  await rises("VPC", () => post("/api/vpc/vpcs", { name: "sav" + s, cidr_block: "10.8.0.0/16" }));
  await rises("EventBridge", () => post("/api/aws/extras/eventbridge/rules", { name: "sav" + s }));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
