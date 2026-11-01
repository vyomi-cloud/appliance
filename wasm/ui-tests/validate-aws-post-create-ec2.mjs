/* Nano post-create probe (PLAN: tests/conformance/post_create/PLAN.md): a launched EC2
 * instance must be USABLE from the console, not just listed. In Nano the instance lives in
 * the browser, so "usable" means an in-browser terminal, not a real ssh.
 *
 * Contract this probe holds Nano to (the offline twin is tests/conformance/post_create/probes/aws/ec2_ssh.py):
 *   GET  /api/aws/ec2/instances/<id>/connect-info  -> 200 {ok:true, ...}      (today: 409 NoRuntime)
 *   POST /api/aws/ec2/instances/<id>/exec {command} -> {stdout, exit_code}    (runs in the instance VM)
 * Checks: launch via the console, connect info available, `whoami` runs, a file written is read back.
 * Registered `pending` in suites.json until Nano has in-browser compute (v86); remove the key then. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const call = (method, path, body) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  return { status: r.status, body: await r.json().catch(() => null) };
}, [method, path, body]);
try {
  await bootConsole(page, base, "/aws-console.html");
  await page.locator("#rail >> text=EC2").first().click();
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /launch instances/i }).first().click();
  await sleep(1200);
  await page.locator("#main button").filter({ hasText: /^\s*(rocket_launch)?\s*Launch instance\s*$/i }).last().click();
  await sleep(3000);
  const list = await page.evaluate(async () => (await (await fetch("/api/ec2/instances")).json()).items || []);
  const id = (list[list.length - 1] || {}).instance_id;
  check("instance launched through the console", /^i-/.test(id || ""), JSON.stringify(list).slice(0, 160));
  const ci = await call("GET", `/api/aws/ec2/instances/${id}/connect-info`);
  check("connect info available (CONNECT_INFO_MISSING)", ci.status === 200 && ci.body && ci.body.ok !== false,
        `status ${ci.status} ${JSON.stringify(ci.body).slice(0, 160)}`);
  const who = await call("POST", `/api/aws/ec2/instances/${id}/exec`, { command: "whoami" });
  check("command runs in the instance (POST_CREATE_UNUSABLE)", who.status === 200 && /\S/.test((who.body && who.body.stdout) || ""),
        `status ${who.status} ${JSON.stringify(who.body).slice(0, 120)}`);
  const w = await call("POST", `/api/aws/ec2/instances/${id}/exec`, { command: "echo vyomi > /tmp/pc.txt; cat /tmp/pc.txt" });
  check("file write + read back on the instance", w.status === 200 && /vyomi/.test((w.body && w.body.stdout) || ""), `status ${w.status}`);
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
