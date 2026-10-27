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
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
