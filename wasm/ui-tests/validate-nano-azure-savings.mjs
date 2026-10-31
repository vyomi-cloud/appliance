/* Nano: ARM resources created through the Azure console (storage account, key vault,
 * virtual network) move the space's cost_savings (resource_count + azure savings).
 * The census read a non-existent `state` attribute of the ARM core, so they never counted. */
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
const put = (type, name, body) => page.evaluate(async ([t, n, b]) => {
  const r = await fetch(`/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/${t}/${n}?api-version=2023-01-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
  return r.status;
}, [type, name, body]);
async function rises(label, type, name, body, billed) {
  const before = await snap();
  const st = await put(type, name, body);
  let after = before;
  for (let i = 0; i < 20; i++) { await sleep(1500); after = await snap(); if (after && after.resource_count > before.resource_count) break; }
  check(`${label}: ARM PUT ok`, st < 300, String(st));
  check(`${label}: resource_count rises`, after.resource_count > before.resource_count, `${before.resource_count} → ${after.resource_count}`);
  if (billed) check(`${label}: azure savings rise`, after.by_provider.azure > before.by_provider.azure, `${before.by_provider.azure} → ${after.by_provider.azure}`);
}
try {
  await bootConsole(page, base, "/azure-console.html");
  const s = Date.now().toString(36);
  await rises("Storage account", "Microsoft.Storage/storageAccounts", "sav" + s, { location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2" }, true);
  await rises("Key vault", "Microsoft.KeyVault/vaults", "sav" + s, { location: "eastus", properties: {} }, true);
  await rises("Virtual network", "Microsoft.Network/virtualNetworks", "sav" + s, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] } } }, false);
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
