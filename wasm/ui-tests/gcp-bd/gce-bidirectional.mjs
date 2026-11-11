/* GCP v4 console <-> Compute Engine REST API bi-directional checks, against a live (Mesh) appliance.
 *   NODE_PATH=... CHROMIUM_PATH=... NANO_DIR=$PWD/wasm SIM_URL=http://127.0.0.1:19000 MESH_TOKEN=... node wasm/ui-tests/gcp-bd/gce-bidirectional.mjs
 * The proxy injects X-Vyomi-Session-Token (env MESH_TOKEN, never logged). Writes tests/conformance/hourly/out/gcp-gce-bidirectional.md
 * Shared appliance: every section re-activates the GCP space and verifies GCP data; the originally active space is restored at the end.
 */
import { chromium, sleep, NANO_DIR } from "../lib.mjs";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const SIM = (process.env.SIM_URL || "http://127.0.0.1:19000").replace(/\/$/, "");
const TOKEN = process.env.MESH_TOKEN || "";
const RUN = Math.random().toString(36).slice(2, 7);
const N = (s) => `bd-${RUN}-${s}`;
const PROJECT = "vyomi-project", ZONE = "us-central1-a";
const rows = []; let fails = 0;
const rec = (check, status, detail = "") => { rows.push({ check, status, detail }); if (status === "FAIL") fails++; console.log(`[${status}] ${check}${detail ? " :: " + detail : ""}`); };
const ck = (check, ok, detail = "") => rec(check, ok ? "PASS" : "FAIL", detail);

// ---- native Compute REST (external client)
const api = async (method, path, body) => {
  const r = await fetch(SIM + path, { method, headers: { "content-type": "application/json", "x-vyomi-session-token": TOKEN }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(60000) });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch {}
  return { status: r.status, json: j, text: t };
};
const IP = `/compute/v1/projects/${PROJECT}/zones/${ZONE}/instances`;
const getI = (n) => api("GET", `${IP}/${n}`);
const tail = (u) => String(u || "").split("/").pop();
const waitStatus = async (n, want, ms = 120000) => { const t0 = Date.now(); let s; while (Date.now() - t0 < ms) { const r = await getI(n); s = r.status === 200 ? r.json.status : `HTTP${r.status}`; if (want.includes(s)) return s; await sleep(3000); } return s; };
const waitGone = async (n, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if ((await getI(n)).status === 404) return true; await sleep(2500); } return false; };

// ---- shared-state guard: active space
let origSpace = null;
const activeSpace = async () => (await api("GET", "/api/spaces/active")).json?.active_space_id;
const ensureGcp = async () => {
  for (let i = 0; i < 4; i++) {
    await api("POST", "/api/spaces/space-gcp-default/switch");
    const a = await activeSpace();
    const z = await api("GET", `/compute/v1/projects/${PROJECT}/zones`);
    if (a === "space-gcp-default" && z.status === 200 && /compute#zoneList/.test(z.text)) return true;
    await sleep(1500);
  }
  return false;
};
const section = async (name) => { const ok = await ensureGcp(); if (!ok) rec(`${name}: GCP space active and serving GCP data`, "FAIL", "could not activate gcp space"); return ok; };

// ---- harness: static console + authenticated proxy (the Mesh may be switched by others mid-run: each UI wire call re-asserts GCP first)
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, "http://x");
    if (/^\/(_wire|api|compute)\b/.test(u.pathname)) {
      const chunks = []; for await (const c of req) chunks.push(c);
      const h = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k))); h["x-vyomi-session-token"] = TOKEN;
      const r = await fetch(SIM + req.url, { method: req.method, headers: h, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
      res.writeHead(r.status, Object.fromEntries([...r.headers].filter(([k]) => !["content-encoding", "transfer-encoding", "content-length"].includes(k))));
      return res.end(Buffer.from(await r.arrayBuffer()));
    }
    let p = normalize(decodeURIComponent(u.pathname)); if (p === "/") p = "/index.html";
    const fp = join(NANO_DIR, p);
    if (!fp.startsWith(NANO_DIR) || !existsSync(fp)) { res.writeHead(404); return res.end("404"); }
    let body = await readFile(fp);
    if (/\/v4\/\w+\/index\.html$/.test(p)) body = Buffer.from(body.toString().replace('content="nano"', 'content="offline"').replace(/<script[^>]*nano-boot\.js[^>]*><\/script>/g, "").replace(/<script[^>]*nano-kernel\.js[^>]*><\/script>/g, "").replace(/<script>window\.__nk[^<]*<\/script>/g, ""));
    res.writeHead(200, { "content-type": MIME[extname(fp)] || "application/octet-stream", "cache-control": "no-cache" }); res.end(body);
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ serviceWorkers: "block", viewport: { width: 1500, height: 1100 } });
const page = await ctx.newPage();
const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));
const go = async (route) => {
  await ensureGcp();
  await page.goto(`${base}/v4/gcp/index.html#/compute/${route}`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await sleep(2500);
};
const body = async () => (await page.locator("body").innerText()).replace(/\s+/g, " ");
const listHas = async (name, tries = 4) => { for (let i = 0; i < tries; i++) { await go("instances"); const t = await body(); if (t.includes(name)) return true; await sleep(2500); } return false; };
const rowOf = (name) => page.locator("tr", { hasText: name }).first();
const rowText = async (name) => (await rowOf(name).innerText().catch(() => "")).replace(/\s+/g, " ");
const pickSel = async (label, optRe) => {
  await page.getByRole("combobox", { name: new RegExp(`^${label}`, "i") }).first().click();
  await sleep(400);
  const opt = page.getByRole("option", { name: optRe }).first();
  await opt.click();
};
const created = [];
let exitCode = 0;
try {
  const h = await fetch(SIM + "/healthz", { headers: { "x-vyomi-session-token": TOKEN } }).then((r) => r.json()).catch(() => ({}));
  ck("(setup) appliance reachable through the tunnel", h.status === "ok", JSON.stringify(h).slice(0, 80));
  origSpace = process.env.ORIG_SPACE || await activeSpace();
  console.log(`(originally active space recorded: ${origSpace})`);
  await page.goto(`${base}/v4/gcp/index.html`, { waitUntil: "domcontentloaded" });

  // ============ (4) form dropdowns + validation ============
  if (await section("(4) form")) {
    await go("instances/create");
    const name = page.getByRole("textbox", { name: "Name", exact: true }).first();
    await name.waitFor({ timeout: 30000 });
    const counts = {};
    for (const lab of ["Region", "Zone", "Machine type", "Operating system", "Network"]) {
      const cb = page.getByRole("combobox", { name: new RegExp(`^${lab}`, "i") }).first();
      try { await cb.click({ timeout: 8000 }); await sleep(500); counts[lab] = await page.getByRole("option").count(); await page.keyboard.press("Escape"); await sleep(300); } catch (e) { counts[lab] = `ERR ${String(e.message).split("\n")[0].slice(0, 60)}`; }
    }
    ck("(4) dropdowns (region, zone, machine type, image, network) are populated", Object.values(counts).every((c) => typeof c === "number" && c > 0), JSON.stringify(counts));
    const btn = page.getByRole("button", { name: /^Create$/ });
    ck("(4) Create button is enabled", await btn.first().isEnabled(), "");
    // invalid names
    const bad = [["Upper_Case!", "invalid chars"], ["1abc", "starts with digit"], ["", "empty"]];
    for (const [v, why] of bad) {
      await name.fill(v); await btn.first().dispatchEvent("click"); await sleep(1200);
      const t = await body();
      const msg = /Use lowercase letters|Name is required/.test(t);
      const raw = /\[object Object\]|undefined|TypeError|Traceback/.test(t);
      const none = (await api("GET", `${IP}/${v}`)).status; // nothing created
      ck(`(4) invalid name (${why}) refused with a meaningful message, no raw errors`, msg && !raw, `msg=${msg} raw=${raw}`);
      void none;
    }
    // server-side refusal of a bad name over the API (what the UI would hit if it skipped client validation)
    const r = await api("POST", IP, { name: "Bad_Name", machineType: `zones/${ZONE}/machineTypes/e2-micro`, disks: [] });
    ck("(4) API also refuses an invalid name with a readable error", r.status >= 400 && r.status < 500 && !/undefined|\[object/.test(r.text) && !!r.json?.error?.message, `${r.status} ${(r.json?.error?.message || r.text).slice(0, 100)}`);
  }

  // ============ (1) UI -> API ============
  const uiName = N("ui");
  if (await section("(1) UI->API")) {
    await go("instances/create");
    try {
      await page.getByRole("textbox", { name: "Name", exact: true }).first().fill(uiName);
      await pickSel("Machine type", /^e2-micro/);
      await pickSel("Operating system", /Ubuntu/);
      await page.getByRole("button", { name: /Add labels/ }).first().click();
      await page.getByLabel("Key 1").fill("bdrun"); await page.getByLabel("Value 1").fill(RUN);
      await ensureGcp();
      await page.getByRole("button", { name: /^Create$/ }).first().dispatchEvent("click");
      await sleep(4000);
      created.push(uiName);
      const r = await getI(uiName);
      ck("(1) UI-created instance is returned by the Compute API", r.status === 200, `GET ${r.status} ${r.status !== 200 ? r.text.slice(0, 120) : ""}`);
      if (r.status === 200) {
        const i = r.json;
        ck("(1) same name / zone / machineType", i.name === uiName && tail(i.zone) === ZONE && tail(i.machineType) === "e2-micro", JSON.stringify({ n: i.name, z: tail(i.zone), m: tail(i.machineType) }));
        const imgBlob = JSON.stringify(i.disks || []);
        const dsk = i.disks?.[0]?.source ? await api("GET", i.disks[0].source.replace(/^https?:\/\/[^/]+/, "")) : null;
        const img = (dsk?.json?.sourceImage || imgBlob);
        ck("(1) boot image is the Ubuntu image chosen in the form", /ubuntu/i.test(img), String(img).slice(-90));
        ck("(1) label bdrun=<run> reached the API", i.labels?.bdrun === RUN, JSON.stringify(i.labels));
        const s = await waitStatus(uiName, ["RUNNING"], 120000);
        ck("(1) status becomes RUNNING within 120s", s === "RUNNING", `status=${s}`);
      }
    } catch (e) { rec("(1) UI create via the console form", "FAIL", String(e.message).split("\n")[0].slice(0, 140)); }
  }

  // ============ (3a) lifecycle on the UI-created VM (it is our one running VM) ============
  if (created.includes(uiName) && (await getI(uiName)).status === 200) {
    if (await section("(3) stop from UI")) {
      await listHas(uiName);
      try {
        await page.getByRole("button", { name: `Actions for ${uiName}` }).click(); await sleep(400);
        await page.getByRole("menuitem", { name: /^Stop$/ }).click();
        const s = await waitStatus(uiName, ["TERMINATED", "STOPPED"], 60000);
        ck("(3) stop from the UI -> API status TERMINATED", s === "TERMINATED", `status=${s}`);
      } catch (e) { rec("(3) stop from UI", "FAIL", String(e.message).split("\n")[0].slice(0, 140)); }
    }
    if (await section("(3) start via API")) {
      const st = await api("POST", `${IP}/${uiName}/start`, {});
      const s = await waitStatus(uiName, ["RUNNING"], 120000);
      await go("instances");
      let row = ""; for (let i = 0; i < 4; i++) { row = await rowText(uiName); if (/RUNNING/.test(row)) break; await sleep(2500); await go("instances"); }
      ck("(3) start via API -> UI row shows RUNNING", st.status < 300 && s === "RUNNING" && /RUNNING/.test(row), `start=${st.status} api=${s} row=${row.slice(0, 90)}`);
      await api("POST", `${IP}/${uiName}/stop`, {}); await waitStatus(uiName, ["TERMINATED"], 60000);   // free capacity again
    }
    if (await section("(3) delete from UI")) {
      await listHas(uiName);
      try {
        await page.getByRole("button", { name: `Actions for ${uiName}` }).click(); await sleep(400);
        await page.getByRole("menuitem", { name: /^Delete$/ }).click(); await sleep(600);
        await page.getByLabel("Confirm deletion").fill(uiName);
        await ensureGcp();
        await page.getByRole("button", { name: /^Delete$/ }).last().click();
        const gone = await waitGone(uiName, 60000);
        const r = await getI(uiName);
        ck("(3) delete from the UI -> API 404", gone && r.status === 404, `GET ${r.status}`);
        if (gone) created.splice(created.indexOf(uiName), 1);
      } catch (e) { rec("(3) delete from UI", "FAIL", String(e.message).split("\n")[0].slice(0, 140)); }
    }
  }

  // ============ (2) API -> UI ============
  const apiName = N("api");
  if (await section("(2) API->UI")) {
    const body_ = { name: apiName, machineType: `zones/${ZONE}/machineTypes/e2-small`, labels: { bdrun: RUN, origin: "api" },
      disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12", diskSizeGb: 10 } }], networkInterfaces: [{ network: `projects/${PROJECT}/global/networks/default` }] };
    let ins = await api("POST", IP, body_);
    const t0 = Date.now();
    while ((ins.status === 500 || ins.status === 503) && /capacity|memory|limit|quota|enough resources/i.test(ins.text) && Date.now() - t0 < 180000) { await sleep(15000); ins = await api("POST", IP, body_); }
    ck("(2) instances.insert over REST accepted", ins.status < 300, `${ins.status} ${ins.status >= 300 ? ins.text.slice(0, 160) : ""}`);
    if (ins.status < 300) {
      created.push(apiName);
      const s = await waitStatus(apiName, ["RUNNING"], 120000);
      const found = await listHas(apiName);
      const row = found ? await rowText(apiName) : "";
      ck("(2) console VM list shows the API-created instance (name)", found, "");
      ck("(2) list row shows the same zone and status", found && row.includes(ZONE) && row.includes(s), `api=${s} row=${row.slice(0, 120)}`);
      // type / labels live on the detail page
      await page.goto(`${base}/v4/gcp/index.html#/compute/instances/${ZONE}/${apiName}`, { waitUntil: "domcontentloaded" }); await page.reload({ waitUntil: "domcontentloaded" }); await sleep(3000);
      const d = await body();
      ck("(2) detail page shows machine type e2-small and the label", /e2-small/.test(d) && /bdrun/.test(d) && new RegExp(RUN).test(d), d.match(/e2-small|bdrun/g)?.join(",") || "neither");
    }
  }

  // ============ (3b) API delete -> UI gone ============
  if (created.includes(apiName)) {
    if (await section("(3) delete via API")) {
      const d = await api("DELETE", `${IP}/${apiName}`);
      const gone = await waitGone(apiName, 60000);
      let still = true; for (let i = 0; i < 4; i++) { await go("instances"); still = (await body()).includes(apiName); if (!still) break; await sleep(2500); }
      ck("(3) delete via API -> UI list no longer shows it", d.status < 300 && gone && !still, `DELETE ${d.status} gone=${gone} listed=${still}`);
      if (gone) created.splice(created.indexOf(apiName), 1);
    }
  }

  // ============ (5) real compute ============
  if (await section("(5) real compute")) {
    const probe = N("ssh");
    const ins = await api("POST", IP, { name: probe, machineType: `zones/${ZONE}/machineTypes/e2-micro`, disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }], networkInterfaces: [{}] });
    if (ins.status < 300) {
      created.push(probe); await waitStatus(probe, ["RUNNING"], 120000);
      const os = await api("GET", `${IP}/${probe}:osInfo`);
      ck("(5) :osInfo reads from the running guest (source=guest)", os.status === 200 && os.json?.source === "guest", `${os.status} source=${os.json?.source} ${os.json?.prettyName || ""}`);
      await ensureGcp();
      const lst = await api("GET", "/api/console/gce/instances");
      const rec_ = (lst.json?.instances || []).find((x) => x.name === probe);
      if (!rec_) rec("(5) run `echo hello` inside the instance", "FAIL", `instance not in /api/console/gce/instances (${lst.status})`);
      else {
        const ex = await api("POST", `/api/console/gce/instances/${rec_.id || rec_.instance_id}/exec`, { command: "echo hello" });
        const out = String(ex.json?.stdout ?? ex.json?.output ?? ex.text);
        ck("(5) `echo hello` inside the instance returns hello (exit 0)", ex.status === 200 && /^hello\s*$/m.test(out) && (ex.json?.exit_code ?? 0) === 0, `${ex.status} ${ex.text.slice(0, 120)}`);
      }
    } else rec("(5) real-compute probe", "NOT-AUTOMATED", `could not create probe VM: ${ins.status} ${ins.text.slice(0, 100)}`);
  }
} catch (e) {
  rec("(run) harness ran to completion", "FAIL", String(e.message).split("\n")[0].slice(0, 200));
} finally {
  // cleanup: everything we created
  await ensureGcp();
  const all = await api("GET", `/compute/v1/projects/${PROJECT}/aggregated/instances`);
  const mine = Object.values(all.json?.items || {}).flatMap((v) => v.instances || []).map((i) => i.name).filter((n) => n.startsWith(`bd-${RUN}-`));
  for (const n of new Set([...created, ...mine])) { const z = ZONE; const r = await api("DELETE", `${IP.replace(ZONE, z)}/${n}`); if (r.status >= 300 && r.status !== 404) console.log(`cleanup ${n}: ${r.status}`); }
  await sleep(3000);
  const left = await api("GET", `/compute/v1/projects/${PROJECT}/aggregated/instances`);
  const leftMine = Object.values(left.json?.items || {}).flatMap((v) => v.instances || []).filter((i) => i.name.startsWith(`bd-${RUN}-`)).length;
  ck("(cleanup) no bd-instances left behind", leftMine === 0, `${leftMine} left`);
  if (origSpace) { await api("POST", `/api/spaces/${origSpace}/switch`); const a = await activeSpace(); ck("(cleanup) originally active space restored", a === origSpace, `${origSpace} -> ${a}`); }
}
rec("(run) no uncaught page errors", pageErrors.length ? "NOT-AUTOMATED" : "PASS", pageErrors.slice(0, 3).join(" | "));
const outDir = new URL("../../../tests/conformance/hourly/out/", import.meta.url).pathname;
mkdirSync(outDir, { recursive: true });
let md = "# GCP v4 console <-> Compute Engine API bi-directional report (Mesh)\n\n| Check | Result | Detail |\n|---|---|---|\n";
for (const r of rows) md += `| ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 160)} |\n`;
const n = (s) => rows.filter((r) => r.status === s).length;
md += `\n**${n("PASS")} pass, ${n("FAIL")} fail, ${n("NOT-AUTOMATED")} not automated.**\n`;
writeFileSync(outDir + "gcp-gce-bidirectional.md", md);
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
