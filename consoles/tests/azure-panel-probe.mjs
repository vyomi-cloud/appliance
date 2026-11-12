#!/usr/bin/env node
/* Fast Azure panel probe: seeds every service's fixtures, then opens EVERY resource-blade menu panel (ids read from the
 * Blade source MENU) and records whether a "Not simulated" / "Limited" / "Config only" marker renders.
 *   BASE=http://127.0.0.1:9081 PW=<playwright> [UI_PATH=/v4/azure/ NANO=1] node consoles/tests/azure-panel-probe.mjs [out.json] */
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9081";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "azure", "services");
const T = [ // [service dir, blade file, route prefix]
  ["acr", "RegistryBlade", "acr/uic-rg/uicacr"], ["aks", "ClusterBlade", "aks/uic-rg/uicaks"], ["apim", "ApimBlade", "apim/uic-rg/uicapim"],
  ["appconfiguration", "ConfigStoreBlade", "appconfiguration/uic-rg/uicappconfig"], ["appservices", "WebAppBlade", "appservices/uic-rg/uicapp"],
  ["cognitiveservices", "CognitiveServicesAccountBlade", "cognitiveservices/uic-rg/uiccogsvc"], ["containerapps", "ContainerAppBlade", "containerapps/uic-rg/uicapp"],
  ["containerapps", "EnvironmentBlade", "containerapps/environments/uic-rg/uiccae"], ["containerapps", "JobBlade", "containerapps/jobs/uic-rg/uicjob"],
  ["cosmos", "CosmosAccountBlade", "cosmos/uic-rg/uiccosmos"], ["dns", "ZoneBlade", "dns/uic-rg/uic"], ["functionapp", "FunctionAppBlade", "functionapp/uic-rg/uicfn"],
  ["keyvaults", "KeyVaultBlade", "keyvaults/uic-rg/uickv"], ["loganalytics", "WorkspaceBlade", "loganalytics/uic-rg/uiclaw"], ["nsgs", "NsgBlade", "nsgs/uic-rg/uicnsg"],
  ["servicebus", "NamespaceBlade", "servicebus/uic-rg/uicsbns"], ["sql", "SqlDatabaseBlade", "sql/uic-rg/uicsqlsrv/uicsqldb"], ["storage", "StorageAccountBlade", "storage/uic-rg/uicstorage"],
  ["vms", "VmBlade", "vms/uic-rg/uicvm"], ["vnets", "VnetBlade", "vnets/uic-rg/uicvnet"], ["resourcegroups", "ResourceGroupBlade", "resourcegroups/uic-rg"],
];
const fx = {};
for (const d of readdirSync(ROOT)) { const f = join(ROOT, d, "fixtures.mjs"); if (existsSync(f)) fx[d] = (await import(pathToFileURL(f))).default; }
const b = await pw.chromium.launch(); const pg = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage(); pg.setDefaultTimeout(4000); pg.on("pageerror", () => {});
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "load" });
if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await pg.waitForTimeout(1500);
const wire = async (method, path, { body } = {}) => {
  const r = await pg.evaluate(async ([u, m, bd]) => { const x = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: bd }); return { ok: x.ok, status: x.status, text: await x.text() }; }, [WIRE + path, method, body === undefined ? undefined : (typeof body === "string" ? body : JSON.stringify(body))]);
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${r.text.slice(0, 100)}`);
  try { return JSON.parse(r.text); } catch { return r.text; }
};
const settle = async () => {
  let last = -1, same = 0;
  for (let i = 0; i < 18; i++) {
    await pg.waitForTimeout(200);
    const st = await pg.evaluate(() => ({ n: document.body.innerText.length, load: /Loading\.\.\.|Loading$/m.test(document.body.innerText) }));
    if (!st.load && st.n === last) { if (++same >= 3) return; } else same = 0;
    last = st.n;
  }
};
const fxLog = [];
for (const [svc, m] of Object.entries(fx)) for (const [k, fn] of Object.entries(m)) if (k.startsWith("az-")) { try { await fn(wire, "u" + Date.now() % 100000); } catch (e) { fxLog.push(`${svc}/${k}: ${e.message.slice(0, 100)}`); } }
const out = [];
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;
for (const [svc, blade, prefix] of T) {
  if (ONLY && !ONLY.has(svc)) continue;
  await pg.goto(UI, { waitUntil: "load" }); await pg.waitForTimeout(800);   // fresh page per blade: an error boundary survives hash navigation
  const src = readFileSync(join(ROOT, svc, blade + ".jsx"), "utf8");
  const ids = [...new Set([...src.matchAll(/\{ id: "([\w-]+)", label: "([^"]+)"/g)].map((m) => m[1] + "|" + m[2]))];
  for (const e of ids) {
    const [id, label] = e.split("|");
    await pg.goto(`${UI}#/`); await pg.goto(`${UI}#/${prefix}/${id}`); await settle();
    if (await pg.evaluate(() => /Something went wrong/.test(document.body.innerText))) { await pg.goto(UI, { waitUntil: "load" }); }
    const r = await pg.evaluate(() => ({
      ns: [...document.querySelectorAll("[data-vyomi-not-simulated]")].map((x) => (x.innerText || "").replace(/\s+/g, " ").slice(0, 140)),
      txt: /isn't backed by a Vyomi backend|Not simulated in Vyomi/.test(document.body.innerText),
      body: document.body.innerText.length,
      err: /Failed to load|Something went wrong/.test(document.body.innerText),
    }));
    out.push({ svc, blade, id, label, ns: r.ns.length || (r.txt ? 1 : 0), note: r.ns[0] || "", err: r.err });
  }
}
// Static list/overview/create routes: every parameter-free pattern in the services' route tables
for (const d of readdirSync(ROOT)) {
  if (ONLY && !ONLY.has(d)) continue;
  const ix = join(ROOT, d, "index.jsx"); if (!existsSync(ix)) continue;
  for (const m of readFileSync(ix, "utf8").matchAll(/pattern: "(\/[^":]*)"/g)) {
    const route = m[1].replace(/^\//, "");
    await pg.goto(`${UI}#/`); await pg.goto(`${UI}#/${route}`); await settle();
    const r = await pg.evaluate(() => ({
      ns: [...document.querySelectorAll("[data-vyomi-not-simulated]")].map((x) => (x.innerText || "").replace(/\s+/g, " ").slice(0, 140)),
      txt: /isn't backed by a Vyomi backend|Not simulated in Vyomi/.test(document.body.innerText),
      err: /Failed to load|Something went wrong/.test(document.body.innerText),
    }));
    out.push({ svc: d, blade: "(route)", id: route, label: route, ns: r.ns.length || (r.txt ? 1 : 0), note: r.ns[0] || "", err: r.err });
  }
}
const f = process.argv[2] || "azure-panel-probe.json";
writeFileSync(f, JSON.stringify({ fxLog, out }, null, 1));
const ns = out.filter((x) => x.ns);
console.log(`panels ${out.length}, not-simulated ${ns.length}, errors ${out.filter((x) => x.err).length}, fixture failures ${fxLog.length}`);
for (const x of ns) console.log(`NS ${x.blade}/${x.id} (${x.label}) ${x.note.slice(0, 90)}`);
await b.close();
