/* GCP detail Metrics tabs: a freshly created VPC network / API Gateway API / Eventarc
 * trigger has 0 subnets / API configs / event filters — the tab must show the number
 * 0 (the resource loaded), not "-". Drives the console's own count fetchers in Nano. */
import { startServer, bootConsole, chromium } from "./lib.mjs";

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  const s = await startServer(); server = s.server;
  await bootConsole(page, s.base, "/gcp-console.html");
  const tag = Date.now().toString(36);
  const r = await page.evaluate(async (tag) => {
    const j = (b) => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    const out = {};
    const cases = {
      vpc: [`/api/gcp/compute/v1/projects/${PROJECT}/global/networks`, "net" + tag, ["subnetworks", "firewalls", "routes"]],
      apigateway: [`/api/gcp/apigateway/v1/projects/${PROJECT}/locations/global/apis`, "api" + tag, ["apiConfigs", "routes"]],
      eventarc: [`/api/gcp/extras/eventarc/triggers`, "trg" + tag, ["eventFilters"]],
    };
    for (const [svc, [path, name, fields]] of Object.entries(cases)) {
      await fetch(path, j({ name }));
      STATE.service = svc;
      out[svc] = [];
      for (const f of fields) out[svc].push(await _recordFieldCount(f)(name));
    }
    return out;
  }, tag);
  for (const [svc, counts] of Object.entries(r))
    check(`${svc}: every metrics count is a number`, counts.every((n) => typeof n === "number"), JSON.stringify(counts));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
