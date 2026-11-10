/* Nano: Memorystore and Artifact Registry have no data plane in the browser, so the console must
 * not show a fake working endpoint (a private IP + redis-cli, or no push host). It must say so. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
try {
  await bootConsole(page, base, "/gcp-console.html");
  const post = (p, b) => page.evaluate(async ([p, b]) => { const r = await fetch(p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) }); return r.status; }, [p, b]);
  const get = (p) => page.evaluate(async (p) => (await (await fetch(p)).json()), p);
  await post("/api/gcp/redis/instances", { name: "shown-redis", region: "us-central1", tier: "BASIC", memorySizeGb: "1" });
  await post("/api/gcp/artifactregistry/repositories", { name: "shown-repo", format: "DOCKER", location: "us-central1" });
  await sleep(1500);
  const r = ((await get("/api/gcp/redis/instances")).items || []).find((x) => /shown-redis/.test(JSON.stringify(x)));
  check("redis instance listed", !!r);
  check("redis does not advertise a redis-cli command to a private IP", !!r && !/redis-cli -h/.test(r.connect_cmd || ""), r && r.connect_cmd);
  check("redis says plainly there is no data plane here", !!r && /not available|control plane/i.test(r.connect_cmd || "") , r && r.connect_cmd);
  const a = ((await get("/api/gcp/artifactregistry/repositories")).items || []).find((x) => /shown-repo/.test(JSON.stringify(x)));
  check("repo listed", !!a);
  check("repo push host is an honest limitation, not a fake host", !!a && /not available/i.test(a.push_host || "") && !/docker push/.test(a.push_example || ""), a && a.push_host);
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note || ""}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
