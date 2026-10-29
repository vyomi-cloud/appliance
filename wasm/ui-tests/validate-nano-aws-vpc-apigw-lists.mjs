/* Nano: VPC subnets / route tables / internet gateways and API Gateway
 * resources / stages list endpoints must answer (they returned 501). */
const _k = setTimeout(() => { console.log("[FAIL] harness timeout"); process.exit(1); }, 150000);
_k.unref && _k.unref();
import { chromium, startServer, bootConsole } from "./lib.mjs";

const stamp = Date.now().toString(36);
const call = (page, method, path, body) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: b ? { "content-type": "application/json" } : undefined, body: b ? JSON.stringify(b) : undefined });
  const t = await r.text(); try { return { status: r.status, ...JSON.parse(t) }; } catch { return { status: r.status, text: t }; }
}, [method, path, body]);
const checks = [];
const check = (n, ok, x = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + String(x).slice(0, 200)}`); };
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/aws-console.html");
  const v = await call(page, "POST", "/api/vpc/vpcs", { name: "lv" + stamp, cidr_block: "10.7.0.0/16" });
  const vid = v.id || v.vpc_id;
  await call(page, "POST", "/api/vpc/subnets", { vpcId: vid, cidr: "10.7.1.0/24" });
  const sn = await call(page, "GET", "/api/vpc/subnets");
  check("GET /api/vpc/subnets lists the subnet", sn.status === 200 && (sn.subnets || []).some((s) => s.vpc_id === vid && s.cidr_block === "10.7.1.0/24" && s.availability_zone), JSON.stringify(sn));
  const rt = await call(page, "GET", "/api/vpc/route-tables");
  check("GET /api/vpc/route-tables lists the VPC's main table", rt.status === 200 && (rt.route_tables || []).some((r) => r.vpc_id === vid && r.routes.length >= 1), JSON.stringify(rt));
  const ig = await call(page, "GET", "/api/vpc/internet-gateways");
  check("GET /api/vpc/internet-gateways answers", ig.status === 200 && Array.isArray(ig.internet_gateways), JSON.stringify(ig));
  const a = await call(page, "POST", "/api/apigateway/apis", { name: "la" + stamp, path: "items", method: "GET" });
  const res = await call(page, "GET", `/api/apigateway/apis/${a.id}/resources`);
  check("API Gateway resources lists /items with GET", res.status === 200 && (res.resources || []).some((r) => r.path === "/items" && "GET" in r.resource_methods), JSON.stringify(res));
  const st = await call(page, "GET", `/api/apigateway/apis/${a.id}/stages`);
  check("API Gateway stages lists prod with an invoke URL", st.status === 200 && (st.stages || []).some((s) => s.stage_name === "prod" && /execute-api/.test(s.invoke_url)), JSON.stringify(st));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
