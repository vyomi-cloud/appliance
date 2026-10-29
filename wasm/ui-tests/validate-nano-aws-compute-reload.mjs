/* Nano: a Lambda function, API Gateway API and VPC created in the console must
 * survive a full page reload (their models live in the persisted registry). */
const _k = setTimeout(() => { console.log("[FAIL] harness timeout"); process.exit(1); }, 150000);
_k.unref && _k.unref();
import { chromium, startServer, bootConsole } from "./lib.mjs";

const stamp = Date.now().toString(36);
const FN = "reloadfn" + stamp, API = "reloadapi" + stamp, VPC = "reloadvpc" + stamp, RULE = "reloadrule" + stamp;
const call = (page, method, path, body) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: b ? { "content-type": "application/json" } : undefined, body: b ? JSON.stringify(b) : undefined });
  const t = await r.text(); try { return JSON.parse(t); } catch { return { text: t }; }
}, [method, path, body]);
const checks = [];
const check = (n, ok, x = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + String(x).slice(0, 200)}`); };
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/aws-console.html");
  await call(page, "POST", "/api/lambda/functions", { name: FN });
  await call(page, "POST", "/api/apigateway/apis", { name: API });
  await call(page, "POST", "/api/vpc/vpcs", { name: VPC, cidr_block: "10.9.0.0/16" });
  await call(page, "POST", "/api/aws/extras/eventbridge/rules", { name: RULE });
  await page.waitForTimeout(1500);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => navigator.serviceWorker?.controller && document.querySelectorAll(s).length > 0,
    "#rail a, #rail button, #rail li, #rail [data-service]", { timeout: 60000, polling: 500 });
  const seen = { fn: false, api: false, vpc: false, rule: false };
  for (let i = 0; i < 40 && !(seen.fn && seen.api && seen.vpc && seen.rule); i++) {
    seen.fn = JSON.stringify(await call(page, "GET", "/api/lambda/functions")).includes(FN);
    seen.api = JSON.stringify(await call(page, "GET", "/api/apigateway/apis")).includes(API);
    seen.vpc = JSON.stringify(await call(page, "GET", "/api/vpc/vpcs")).includes("10.9.0.0/16");
    seen.rule = JSON.stringify(await call(page, "GET", "/api/aws/extras/eventbridge/rules")).includes(RULE);
    await page.waitForTimeout(500);
  }
  check("Lambda function survives reload", seen.fn);
  check("API Gateway API survives reload", seen.api);
  check("VPC survives reload", seen.vpc);
  check("EventBridge rule survives reload", seen.rule, JSON.stringify(await call(page, "GET", "/api/aws/extras/eventbridge/rules")));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
