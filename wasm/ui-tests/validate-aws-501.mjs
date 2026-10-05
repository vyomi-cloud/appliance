/* Goal-1/2: confirm the AWS 501s are fixed — Security groups (GET list) + AMIs —
 * at the API level AND that creating a SG shows up (UI wiring intact). */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const out = {};
try {
  await bootConsole(page, base, "/aws-console.html");
  // 1) the two previously-501 endpoints now return 200 with the right shape
  out.sg = await page.evaluate(async () => { const r = await fetch("/api/vpc/security-groups"); return { status: r.status, body: await r.json().catch(() => ({})) }; });
  out.amis = await page.evaluate(async () => { const r = await fetch("/api/ec2/amis"); return { status: r.status, body: await r.json().catch(() => ({})) }; });
  // 2) create a VPC + SG, then list → the SG appears (end-to-end wiring)
  out.create = await page.evaluate(async () => {
    const vr = await (await fetch("/api/vpc/vpcs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ cidr: "10.0.0.0/16" }) })).json();
    const sgr = await (await fetch("/api/vpc/security-groups", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ vpcId: vr.id }) })).json();
    const list = await (await fetch("/api/vpc/security-groups")).json();
    return { vpc: vr.id, sg: sgr.id, listed: (list.security_groups || []).some((g) => g.id === sgr.id), count: (list.security_groups || []).length };
  });
} catch (e) { out.err = String(e).split("\n")[0]; }
await browser.close(); server.close();

console.log(JSON.stringify(out, null, 1));
const pass = out.sg?.status === 200 && Array.isArray(out.sg.body.security_groups) &&
             out.amis?.status === 200 && Array.isArray(out.amis.body.amis) &&
             out.create?.listed === true;
console.log("\nRESULT:", pass ? "PASS — AWS Security groups + AMIs no longer 501; SG create→list works" : "FAIL");
process.exit(pass ? 0 : 1);
