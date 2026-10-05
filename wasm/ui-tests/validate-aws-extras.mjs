/* Goal-2: the AWS "extras" stub family (Volumes, Snapshots, Launch Templates, Spot
 * Requests, Endpoint services) — previously 501 — now a real CRUD. Validate list +
 * create + list + delete for each family. */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const FAMILIES = [
  { key: "ec2/volumes", body: { size: 100, type: "gp3", az: "us-east-1a" } },
  { key: "ec2/snapshots", body: { volume: "vol-1", description: "backup" } },
  { key: "ec2/launch-templates", body: { name: "web-lt", instanceType: "t3.micro" } },
  { key: "ec2/spot-requests", body: { instanceType: "t3.large", maxPrice: "0.05" } },
  { key: "vpc/endpoint-services", body: { name: "svc-a" } },
];
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
try {
  await bootConsole(page, base, "/aws-console.html");
  for (const f of FAMILIES) {
    const r = await page.evaluate(async ([key, body]) => {
      const EP = "/api/aws/extras/" + key;
      const list0 = await fetch(EP); const j0 = await list0.json().catch(() => ({}));
      const cr = await fetch(EP, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const cj = await cr.json().catch(() => ({}));
      const list1 = await (await fetch(EP)).json().catch(() => ({}));
      const nm = cj.name;
      const del = await fetch(EP + "/" + encodeURIComponent(nm), { method: "DELETE" });
      const list2 = await (await fetch(EP)).json().catch(() => ({}));
      return {
        listStatus: list0.status, listShape: Array.isArray(j0.value),
        created: cr.status === 200 && cj.ok !== false, name: nm,
        appeared: (list1.value || []).some((x) => x.name === nm),
        deleted: del.status === 200 && !(list2.value || []).some((x) => x.name === nm),
      };
    }, [f.key, f.body]);
    const pass = r.listStatus === 200 && r.listShape && r.created && r.appeared && r.deleted;
    results.push({ key: f.key, pass, ...r });
  }
} catch (e) { results.push({ key: "(boot)", pass: false, err: String(e).split("\n")[0] }); }
await browser.close(); server.close();

console.log("===== AWS extras stub family — CRUD validation =====");
for (const r of results) console.log(`  [${r.pass ? "PASS" : "FAIL"}] ${r.key.padEnd(22)} list:${r.listStatus} shape:${r.listShape} create:${r.created} appeared:${r.appeared} deleted:${r.deleted} ${r.err || ""}`);
const n = results.filter((r) => r.pass).length;
console.log(`\n${n}/${results.length} stub families now have working list+create+delete`);
process.exit(n === results.length ? 0 : 1);
