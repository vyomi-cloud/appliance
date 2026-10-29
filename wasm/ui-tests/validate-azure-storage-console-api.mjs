/* Nano: Azure storage-account console routes (/api/azure/storage/{acct}/containers|queues)
 * were HTTP 501 (Containers + Queues tabs empty/errored). They must list, create and
 * delete against the blob/queue cores and survive a reload. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const api = (method, path, body) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  return { status: r.status, body: await r.json().catch(() => null) };
}, [method, path, body]);
const A = "/api/azure/storage/stconf";
try {
  await bootConsole(page, base, "/azure-console.html");
  let r = await api("GET", A + "/containers");
  check("containers list is 200 (not 501)", r.status === 200 && Array.isArray(r.body?.value), `status ${r.status}`);
  r = await api("POST", A + "/containers", { name: "conf-cont" });
  check("container create", r.status === 200 && r.body?.ok === true, `status ${r.status}`);
  r = await api("GET", A + "/containers");
  check("created container is listed with blobCount", (r.body?.value || []).some((c) => c.name === "conf-cont" && c.blobCount === 0), JSON.stringify(r.body));
  r = await api("GET", A + "/containers/conf-cont/blobs");
  check("blob list of new container is empty 200", r.status === 200 && (r.body?.value || []).length === 0, `status ${r.status}`);
  await sleep(1500); // let the debounced store snapshot flush before navigating
  await page.goto(base + "/azure-console.html", { waitUntil: "domcontentloaded" }); await sleep(500);
  r = await api("GET", A + "/containers");
  check("container survives reload", (r.body?.value || []).some((c) => c.name === "conf-cont"), JSON.stringify(r.body));
  r = await api("DELETE", A + "/containers/conf-cont");
  check("container delete", r.status === 200, `status ${r.status}`);
  r = await api("GET", A + "/containers");
  check("deleted container gone", !(r.body?.value || []).some((c) => c.name === "conf-cont"));

  r = await api("GET", A + "/queues");
  check("queues list is 200 (not 501)", r.status === 200 && Array.isArray(r.body?.value), `status ${r.status}`);
  r = await api("POST", A + "/queues", { name: "confq" });
  check("queue create", r.status === 200 && r.body?.ok === true, `status ${r.status}`);
  r = await api("GET", A + "/queues");
  check("created queue is listed", (r.body?.value || []).includes("confq"), JSON.stringify(r.body));
  r = await api("DELETE", A + "/queues/confq");
  check("queue delete", r.status === 200, `status ${r.status}`);
  r = await api("GET", A + "/queues");
  check("deleted queue gone", !(r.body?.value || []).includes("confq"));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
