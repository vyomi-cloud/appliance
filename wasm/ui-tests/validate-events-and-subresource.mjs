/* SHARED backbone validation (second-level UI pass):
 *   (a) after a create/update op, /api/cloudsim/events?resource=<name> returns a
 *       matching cloudsim event (recorded by providers/registry on dispatch);
 *   (b) the generic /api/{cloud}/sub/{service}/{op}(/{name}) route dispatches to
 *       [provider, "_resource", <Op>] and reaches the core adapter;
 *   (c) events survive a reload (DURABLE tier via nano_persist → IndexedDB).
 */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
let page = await ctx.newPage();
const results = [];
const ok = (label, pass, detail) => { results.push([label, !!pass, detail]); };

try {
  await bootConsole(page, base, "/gcp-console.html");

  const out = await page.evaluate(async () => {
    const J = async (m, p, b) => {
      const o = { method: m, headers: {} };
      if (b !== undefined) { o.headers["content-type"] = "application/json"; o.body = JSON.stringify(b); }
      const r = await fetch(p, o); let j = null; try { j = await r.json(); } catch (_) {}
      return { status: r.status, json: j };
    };
    const res = {};

    // ── (a) create a resource → an event must be recorded ──────────────
    // GCP compute is a generic ResourceStore service → goes through _resource Create.
    await J("POST", `/api/gcp/compute/v1/projects/demo/zones/us-central1/instances`, { name: "vm-evt-1" });
    const ev = await J("GET", `/api/cloudsim/events?resource=vm-evt-1`);
    res.eventsShape = ev.json && Array.isArray(ev.json.events);
    res.eventsForResource = (ev.json && ev.json.events) || [];

    // provider filter + global feed
    const evGcp = await J("GET", `/api/cloudsim/events?provider=gcp`);
    res.gcpFeed = ((evGcp.json && evGcp.json.events) || []).length;
    const evAll = await J("GET", `/api/cloudsim/events`);
    res.globalFeed = ((evAll.json && evAll.json.events) || []).length;

    // ── (b) generic sub-resource route → [gcp,_resource,ListSubscriptions] ──
    // First create a pubsub topic the normal way, then drive subscriptions via the
    // NEW generic /api/gcp/sub/{service}/{op}/{name} family (op lower→Upper-cased).
    await J("POST", `/api/gcp/pubsub/v1/projects/demo/topics`, { name: "orders-sub-test" });
    const subCreate = await J("POST", `/api/gcp/sub/pubsub/createSubscription/orders-sub-test`, { name: "sub-A" });
    const subList = await J("GET", `/api/gcp/sub/pubsub/listSubscriptions/orders-sub-test`);
    res.subCreateOk = subCreate.json && subCreate.json.ok !== false;
    res.subCreateStatus = subCreate.status;
    res.subListItems = (subList.json && subList.json.items) || [];
    res.subListed = res.subListItems.some((s) => JSON.stringify(s).includes("sub-A"));

    // creating the subscription via the generic route must ALSO log an event for it
    const evSub = await J("GET", `/api/cloudsim/events?resource=sub-A`);
    res.subEventLogged = ((evSub.json && evSub.json.events) || []).some((e) => e.action === "CreateSubscription");

    return res;
  });

  const matchEvt = out.eventsForResource.find((e) => e.resource === "vm-evt-1" && e.action === "Create");
  ok("(a) events API shape {events:[…]}", out.eventsShape, { shape: out.eventsShape });
  ok("(a) create op recorded a cloudsim event", !!matchEvt, { event: matchEvt, all: out.eventsForResource });
  ok("(a) event has provider/service/action/ts/seq",
     matchEvt && matchEvt.provider === "gcp" && matchEvt.service && matchEvt.ts && typeof matchEvt.seq === "number",
     matchEvt);
  ok("(a) provider-filtered feed non-empty", out.gcpFeed >= 1, { gcpFeed: out.gcpFeed });
  ok("(a) global feed non-empty", out.globalFeed >= 1, { globalFeed: out.globalFeed });
  ok("(b) generic sub route create dispatched", out.subCreateOk, { status: out.subCreateStatus });
  ok("(b) generic sub route list returns the sub-resource", out.subListed, { items: out.subListItems });
  ok("(b) sub-resource create logged an event", out.subEventLogged, {});

  // ── (c) DURABLE: events survive a reload (nano_persist → IndexedDB) ──
  // Give the debounced store-save time to flush, then reload and re-query.
  await sleep(1200);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller,
    { timeout: 180000, polling: 500 });
  // the console rail may still be mid-boot; wait for the backend to be serving
  await sleep(2500);
  const after = await page.evaluate(async () => {
    const r = await fetch(`/api/cloudsim/events?resource=vm-evt-1`);
    let j = null; try { j = await r.json(); } catch (_) {}
    return (j && j.events) || [];
  });
  ok("(c) events survive reload (DURABLE tier)",
     after.some((e) => e.resource === "vm-evt-1" && e.action === "Create"),
     { afterReload: after });
} catch (e) {
  ok("(err)", false, String(e).split("\n")[0]);
}
await browser.close(); server.close();

console.log("===== SHARED backbone: cloudsim events + generic sub-resource route =====");
let allPass = true;
for (const [label, pass, detail] of results) {
  if (!pass) allPass = false;
  console.log(`  [${pass ? "PASS" : "FAIL"}] ${label}`);
  if (!pass) console.log("        ", JSON.stringify(detail));
}
console.log("\nRESULT:", allPass ? "PASS" : "FAIL");
process.exit(allPass ? 0 : 1);
