/* Nano: the endpoints the Azure ARM records SHOW must work in Nano's own access path (the service
 * worker), never a fake *.vault.azure.net / hard-coded localhost:9000 host. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
try {
  await bootConsole(page, base, "/azure-console.html");
  const put = (t, ns, ver, n) => page.evaluate(async ([t, ns, ver, n]) => {
    const S = "00000000-0000-0000-0000-cloudlearn01", H = { "content-type": "application/json" };
    await fetch(`/subscriptions/${S}/resourceGroups/rg1?api-version=2021-04-01`, { method: "PUT", headers: H, body: JSON.stringify({ location: "eastus" }) });
    const r = await fetch(`/subscriptions/${S}/resourceGroups/rg1/providers/${ns}/${t}/${n}?api-version=${ver}`, { method: "PUT", headers: H, body: JSON.stringify({ location: "eastus", properties: {} }) });
    return (await r.json()).properties || {};
  }, [t, ns, ver, n]);
  const fetchStatus = (url, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return r.status; }, [url, init || {}]);
  const fake = (u) => /\.azure\.net|:9000|azurecontainerapps\.io/.test(u || "");
  const origin = new URL(base).origin;
  const kv = await put("vaults", "Microsoft.KeyVault", "2023-07-01", "nkv");
  check("Key Vault vaultUri is on the Nano origin", (kv.vaultUri || "").startsWith(origin) && !fake(kv.vaultUri), kv.vaultUri);
  check("secret set+get through the shown vaultUri",
    (await fetchStatus(kv.vaultUri + "secrets/s1", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ value: "v" }) })) < 300
    && (await fetchStatus(kv.vaultUri + "secrets/s1")) === 200);
  const sb = await put("namespaces", "Microsoft.ServiceBus", "2022-10-01-preview", "nsb");
  check("Service Bus endpoint is on the Nano origin, not :9000", (sb.serviceBusEndpoint || "").startsWith(origin) && !fake(sb.serviceBusEndpoint), sb.serviceBusEndpoint);
  check("Service Bus shown endpoint answers", (await fetchStatus(sb.serviceBusEndpoint)) === 200);
  const sql = await put("servers", "Microsoft.Sql", "2023-05-01-preview", "nsql");
  check("SQL FQDN is a working Nano URL", (sql.fullyQualifiedDomainName || "").startsWith(origin) && (await fetchStatus(sql.fullyQualifiedDomainName)) === 200, sql.fullyQualifiedDomainName);
  check("SQL says HTTP only, no TDS", /no TDS/i.test(JSON.stringify(sql.vyomiAccess || {})), JSON.stringify(sql.vyomiAccess));
  const eg = await put("topics", "Microsoft.EventGrid", "2024-06-01-preview", "neg");
  check("Event Grid shows no fake endpoint and says plainly it is not available", !eg.endpoint && /not available/i.test(JSON.stringify(eg.vyomiAccess || {})), JSON.stringify(eg.vyomiAccess));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note || ""}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
