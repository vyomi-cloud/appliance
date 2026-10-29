// Nano Azure Key Vault Secrets/Keys tabs: the console's data-plane calls must
// not 404, and a created secret/key must survive a list round-trip.
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000);
_k.unref && _k.unref();
import { chromium, startServer, bootConsole } from "./lib.mjs";

const J = (page, url, opts) => page.evaluate(async ([u, o]) => {
  const r = await fetch(u, o || {});
  let j = null; try { j = await r.json(); } catch {}
  return { status: r.status, j };
}, [url, opts]);
const H = { "Content-Type": "application/json" };
const checks = [];
const check = (name, ok, note = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${note ? " — " + note : ""}`); };

const srv = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, srv.base, "/azure-console.html");
  const V = srv.base + "/api/azure/keyvault/kv-test";
  let r = await J(page, V + "/secrets");
  check("list secrets is not 404", r.status === 200 && Array.isArray(r.j && r.j.value), "status " + r.status);
  r = await J(page, V + "/secrets/s1", { method: "PUT", headers: H, body: JSON.stringify({ value: "v1" }) });
  check("put secret", r.status === 200 && r.j.value === "v1", "status " + r.status);
  r = await J(page, V + "/secrets");
  check("secret listed", JSON.stringify(r.j).includes("/secrets/s1"));
  r = await J(page, V + "/secrets/s1");
  check("get secret value", r.status === 200 && r.j.value === "v1");
  r = await J(page, V + "/keys");
  check("list keys is not 404", r.status === 200 && Array.isArray(r.j && r.j.value), "status " + r.status);
  r = await J(page, V + "/keys/k1/create", { method: "POST", headers: H, body: JSON.stringify({ kty: "RSA" }) });
  check("create key", r.status === 200, "status " + r.status);
  r = await J(page, V + "/keys");
  check("key listed", JSON.stringify(r.j).includes("/keys/k1"));
  r = await J(page, V + "/secrets/s1", { method: "DELETE" });
  check("delete secret", r.status === 200, "status " + r.status);
  r = await J(page, V + "/secrets");
  check("secret gone", !JSON.stringify(r.j).includes("/secrets/s1"));
} catch (e) { check("harness", false, String(e).split("\n")[0]); }
await browser.close(); srv.server.close();
process.exit(checks.every(Boolean) && checks.length ? 0 : 1);
