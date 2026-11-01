/* Nano halves of the sweep-A fixes (Azure RG delete cascade, SQL password echo, APIM key/404, ...).
 * Drives the real Nano service worker from a booted console via fetch(). */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const call = (method, path, body, headers) => page.evaluate(async ([m, p, b, h]) => {
  const r = await fetch(p, { method: m, headers: { "content-type": "application/json", ...(h || {}) }, body: b == null ? undefined : JSON.stringify(b) });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (_) {}
  return { status: r.status, json: j, text: t };
}, [method, path, body ?? null, headers ?? null]);
try {
  await bootConsole(page, base, "/azure-console.html");
  const sub = "00000000-0000-0000-0000-cloudlearn01";
  const rg = `/subscriptions/${sub}/resourceGroups/sweeprg`;
  await call("PUT", rg + "?api-version=2021-04-01", { location: "eastus" });
  // Item 3: SQL password never echoed
  const sql = await call("PUT", `${rg}/providers/Microsoft.Sql/servers/sweepsql?api-version=2021-11-01`,
    { location: "eastus", properties: { administratorLogin: "adm", administratorLoginPassword: "S3cret-Pass!" } });
  check("SQL server PUT omits administratorLoginPassword", !sql.text.includes("S3cret-Pass!"), sql.text.slice(0, 160));
  const sqlg = await call("GET", `${rg}/providers/Microsoft.Sql/servers/sweepsql?api-version=2021-11-01`);
  check("SQL server GET omits administratorLoginPassword", sqlg.status === 200 && !sqlg.text.includes("S3cret-Pass!"), sqlg.text.slice(0, 160));
  // Item 1: RG delete destroys Key Vault data
  await call("PUT", `${rg}/providers/Microsoft.KeyVault/vaults/sweepkv?api-version=2023-07-01`,
    { location: "eastus", properties: { sku: { family: "A", name: "standard" }, tenantId: "00000000-0000-0000-0000-000000000000" } });
  const put = await call("PUT", "/azure-data/keyvault/sweepkv/secrets/s1", { value: "topsecret" });
  check("Key Vault secret set", put.status === 200, `HTTP ${put.status} ${put.text.slice(0, 100)}`);
  const pre = await call("GET", "/azure-data/keyvault/sweepkv/secrets/s1");
  check("Key Vault secret readable before delete", pre.status === 200 && pre.text.includes("topsecret"), `HTTP ${pre.status}`);
  const del = await call("DELETE", rg + "?api-version=2021-04-01");
  check("RG delete accepted", del.status < 300, `HTTP ${del.status}`);
  const got = await call("GET", "/azure-data/keyvault/sweepkv/secrets/s1");
  check("RG delete destroyed Key Vault secrets", got.status !== 200, `HTTP ${got.status}`);
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
