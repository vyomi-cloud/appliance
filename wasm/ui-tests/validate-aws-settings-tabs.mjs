/* Nano: detail-tab settings that were never saved (DynamoDB TTL/streams/capacity/
 * encryption, SQS encryption/purge, Secrets Manager rotation/key, KMS rotation)
 * load the service defaults with HTTP 200 — no 404 — and a saved edit survives a
 * console reload. */
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
  const get = (ns) => page.evaluate(async (ns) => {
    const r = await fetch("/api/aws/sub/" + encodeURIComponent(ns) + "/get/_settings");
    return { status: r.status, body: await r.json().catch(() => null) };
  }, ns);
  for (const ns of ["dynamodb~Music~ttl", "dynamodb~Music~streams", "dynamodb~Music~capacity", "dynamodb~Music~encryption",
                    "sqs~MyQueue~encryption", "sqs~MyQueue~purge", "secretsmanager~my-secret~rotation",
                    "secretsmanager~my-secret~kmsKey", "kms~abc~rotation"]) {
    const r = await get(ns);
    check(`unsaved settings ${ns} → 200`, r.status === 200 && r.body && r.body.ok !== false, `status ${r.status}`);
  }
  await page.evaluate(async () => {
    await fetch("/api/aws/sub/" + encodeURIComponent("dynamodb~Music~ttl") + "/create", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "_settings", ttl_enabled: true, ttl_attribute: "expires" }) });
  });
  await sleep(1500);
  await page.goto(base + "/aws-console.html");
  await sleep(6000);
  const saved = await get("dynamodb~Music~ttl");
  check("a saved settings edit survives a reload", saved.status === 200 && saved.body && saved.body.ttl_attribute === "expires", JSON.stringify(saved.body));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
