/* Nano: /api/runtime/budget answers 200 (was 501 → console budget chip errored) and
 * /api/spaces carries cost_savings that moves when a resource is created. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
try {
  await bootConsole(page, base, "/azure-console.html");
  const b = await page.evaluate(async () => {
    const r = await fetch("/api/runtime/budget");
    return { status: r.status, body: await r.json().catch(() => null) };
  });
  check("budget returns 200", b.status === 200, `status ${b.status}`);
  check("budget has cpu/memory shape", !!(b.body && b.body.budget && b.body.used && b.body.host && b.body.clamp));

  const snap = () => page.evaluate(async () => {
    const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
    const cs = (d.spaces[0] || {}).cost_savings;
    return cs || null;
  });
  const before = await snap();
  check("spaces carry cost_savings", !!before && typeof before.resource_count === "number" && before.by_provider, JSON.stringify(before));
  // create a Key Vault secret through the console API, then wait for the census tick
  await page.evaluate(async () => {
    await fetch("/api/azure/kvsecrets", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "sav-check", value: "x" }) });
  });
  let after = before;
  for (let i = 0; i < 20; i++) { await sleep(1500); after = await snap(); if (after && before && after.resource_count > before.resource_count) break; }
  check("resource_count rises after create", !!after && after.resource_count > (before?.resource_count ?? 0), `${before?.resource_count} → ${after?.resource_count}`);
  check("azure savings rise after create", !!after && after.by_provider.azure > (before?.by_provider.azure ?? 0), `${before?.by_provider.azure} → ${after?.by_provider.azure}`);
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
