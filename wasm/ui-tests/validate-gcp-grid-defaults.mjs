/* GCP grids: a resource created with default values (Firestore, Cloud Functions,
 * API Gateway, VPC, Eventarc, Secret Manager, Cloud KMS) must resolve every grid
 * column from the list API to a real value — never "-", blank, [object Object].
 * Nano by default; VYOMI_CONSOLE_URL drives the offline console instead. */
import { startServer, bootConsole, chromium, RAIL_SEL } from "./lib.mjs";

const offline = process.env.VYOMI_CONSOLE_URL;
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  if (offline) {
    await page.goto(offline, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else {
    const s = await startServer(); server = s.server;
    await bootConsole(page, s.base, "/gcp-console.html");
  }
  const tag = Date.now().toString(36);
  const res = await page.evaluate(async (tag) => {
    const j = (b) => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    const P = PROJECT, out = {};
    const cat = await (await fetch("/api/gcp/catalog")).json();
    const get = (o, p) => p.split(".").reduce((a, k) => (a && typeof a === "object" ? a[k] : undefined), o);
    const mk = {
      firestore: [`/api/gcp/firestore/v1/projects/${P}/databases`, { name: "db" + tag }],
      apigateway: [`/api/gcp/apigateway/v1/projects/${P}/locations/global/apis`, { name: "api" + tag }],
      vpc: [`/api/gcp/compute/v1/projects/${P}/global/networks`, { name: "net" + tag }],
      eventarc: [`/api/gcp/extras/eventarc/triggers`, { name: "trg" + tag }],
      secretmanager: [`/api/gcp/secrets`, { name: "sec" + tag }],
      kms: [`/api/gcp/kms/keys`, { name: "key" + tag }],
      functions: [`/api/gcp/cloudfunctions/v2/projects/${P}/locations/us-central1/functions`, { name: "fn" + tag, runtime: "python312", entryPoint: "hello_world" }],
    };
    for (const [k, [path, body]] of Object.entries(mk)) {
      await fetch(path, j(body));
      const l = await (await fetch(path)).json();
      const items = Array.isArray(l) ? l : (l.items || l.functions || l.databases || l.keys || l.secrets || l.apis || l.triggers || []);
      const row = items.find((i) => String(i.name || "").split("/").pop() === body.name);
      const svc = cat.services.find((x) => x.key === k);
      // the console derives some columns (VPC mode, function state) from the resource
      if (row && typeof decorateGcpItems === "function") decorateGcpItems(svc, [row]);
      out[k] = row ? svc.columns.map(([p, label]) => [label, get(row, p)]) : null;
    }
    return out;
  }, tag);
  for (const [k, cols] of Object.entries(res)) {
    check(`${k}: created resource listed`, !!cols);
    for (const [label, v] of cols || []) {
      const bad = v === undefined || v === null || v === "" || (typeof v === "object") || /^[-—]$|undefined|null|\[object/i.test(String(v));
      check(`${k}: column '${label}' filled`, !bad, JSON.stringify(v));
    }
  }
  // Every grid ends in a Created column; wherever the service already has rows, each row must carry a real timestamp.
  const created = await page.evaluate(async () => {
    const cat = await (await fetch("/api/gcp/catalog")).json(), out = {};
    for (const k of ["compute", "cloudsql", "functions", "vpc", "iam", "monitoring"]) {
      const svc = cat.services.find((x) => x.key === k);
      const col = svc && svc.columns.find((c) => c[1] === "Created");
      if (!col) { out[k] = { col: false }; continue; }
      const path = svc.collection_path.replace("{project}", cat.project).replace("{zone}", cat.zone).replace("{region}", cat.region).replace("{location}", cat.region);
      let items = [];
      try { const l = await (await fetch(path)).json(); items = Array.isArray(l) ? l : (Object.values(l).find(Array.isArray) || []); } catch (_) {}
      out[k] = { col: true, rows: items.length, bad: items.filter((i) => !i[col[0]] || Number.isNaN(Date.parse(i[col[0]]))).length };
    }
    return out;
  });
  for (const [k, r] of Object.entries(created)) {
    check(`${k}: grid has a Created column`, r.col);
    if (r.col) check(`${k}: every row (${r.rows}) has a creation time`, r.bad === 0, `${r.bad} rows without one`);
  }
  // The grid shows every field the records carry: extra property / label / date columns beside the curated ones,
  // never a credential, and resource references as names (not self-link URLs).
  for (const svcName of ["VPC Network", "Cloud Functions"]) {
    await page.locator(RAIL_SEL).filter({ hasText: svcName }).first().click({ timeout: 8000 }).catch(() => {});
    await page.waitForSelector("#main table.gc tr td", { timeout: 15000 }).catch(() => {});
    const g = await page.evaluate(() => {
      const t = document.querySelector("#main table.gc"); if (!t) return null;
      const th = [...t.querySelectorAll("th[data-label]")];
      return { total: th.length, auto: th.filter((x) => x.dataset.auto).map((x) => x.dataset.label),
               cells: [...t.querySelectorAll("td")].map((c) => c.innerText).join(" | ") };
    });
    check(`${svcName}: grid lists extra properties beyond the curated columns`, !!g && g.auto.length > 0, JSON.stringify(g && g.auto));
    check(`${svcName}: no credential-like column`, !!g && !g.auto.some((l) => /pass|secret|token|private|credential/i.test(l)), JSON.stringify(g && g.auto));
    check(`${svcName}: no raw self-link URL in a cell`, !!g && !/\/(zones|regions|machineTypes)\/[^\s|]+/.test(g.cells), (g && g.cells || "").slice(0, 160));
  }
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
