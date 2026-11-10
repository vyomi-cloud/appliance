/* Nano: an IAM user created through the console opens its detail (GET /api/iam/users/<name>
 * answers 200 with ARN, user id, path, groups and attached policies) instead of a 404. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
try {
  await bootConsole(page, base, "/aws-console.html");
  const r = await page.evaluate(async () => {
    const post = await fetch("/api/iam/users", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "new-user" }) });
    const get = await fetch("/api/iam/users/new-user");
    const missing = await fetch("/api/iam/users/nobody");
    return { post: post.status, get: get.status, body: await get.json().catch(() => null), missing: missing.status };
  });
  check("create user", r.post === 200);
  check("GET /api/iam/users/new-user → 200", r.get === 200, `status ${r.get}`);
  check("detail has arn, user_id, path, groups, policies",
    !!r.body && /^arn:aws:iam::\d+:user\/new-user$/.test(r.body.arn || "") && !!r.body.user_id && r.body.path === "/" && Array.isArray(r.body.groups) && Array.isArray(r.body.policies),
    JSON.stringify(r.body));
  check("unknown user → 404", r.missing === 404, `status ${r.missing}`);
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
