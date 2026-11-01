/* Nano: Eventarc fires on a console upload (in-browser function runs with a CloudEvent); the Azure ARM side still boots. (The /gcf, Event Grid publish and function-app data planes are wire paths: covered at router level by tests/conformance/test_nano_triggers.py.)
 * Run: NODE_PATH=.../portal-OLD/node_modules NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-nano-gcp-azure-triggers.mjs */
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
  await sleep(2500);
  const api = (m, p, b, raw) => page.evaluate(async ([m, p, b, raw]) => {
    const r = await fetch(p, { method: m, headers: raw ? {} : { "content-type": "application/json" }, body: b == null ? undefined : (raw ? Uint8Array.from(atob(b), c => c.charCodeAt(0)) : JSON.stringify(b)) });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (_) {}
    return { status: r.status, j, t };
  }, [m, p, b, raw]);
  const P = "nano-project", L = "us-central1";
  let r = await api("POST", "/api/gcp/storage/v1/b", { name: "evb" });
  check("create bucket", r.status < 300, r.t.slice(0, 200));
  const http = "import functions_framework\nfrom flask import jsonify\n@functions_framework.http\ndef h(request):\n    if request.method == 'GET':\n        return 'hi ' + request.args.get('who', '?')\n    return jsonify({'echo': request.get_json()}), 202\n";
  const evt = "import functions_framework\n@functions_framework.cloud_event\ndef e(ce):\n    return {'type': ce['type'], 'name': (ce.data or {}).get('name')}\n";
  for (const [n, code, entry] of [["fnh", http, "h"], ["fne", evt, "e"]]) {
    r = await api("POST", `/api/gcp/cloudfunctions/v2/projects/${P}/locations/${L}/functions`, { name: n, runtime: "python312", entryPoint: entry, code });
    check("create function " + n, r.status < 300, r.t.slice(0, 200));
  }
  r = await api("POST", "/api/gcp/extras/eventarc/triggers", { name: "evt1", eventType: "google.cloud.storage.object.v1.finalized",
    eventFilters: [{ attribute: "type", value: "google.cloud.storage.object.v1.finalized" }, { attribute: "bucket", value: "evb" }],
    destinationSpec: { type: "cloud-function", service: "fne" } });
  check("create Eventarc trigger", r.status < 300, r.t.slice(0, 200));
  r = await page.evaluate(async () => { const fd = new FormData(); fd.append("file", new File(["hello"], "dir/a.txt", { type: "text/plain" }));
    const x = await fetch("/api/gcp/storage/v1/b/evb/upload", { method: "POST", body: fd }); return { status: x.status, t: await x.text() }; });
  check("upload object", r.status < 300, r.t.slice(0, 200));
  await sleep(500);
  r = await api("GET", `/api/gcp/cloudfunctions/v2/projects/${P}/locations/${L}/functions/fne`);
  const inv = (r.j && r.j.invocations) || [];
  check("upload fired the storage-finalized CloudEvent at the in-browser function",
    inv.length === 1 && /dir\/a\.txt/.test(inv[0].response || ""), JSON.stringify(inv).slice(0, 300));
} catch (e) { check("boot/gcp", false, String(e).split("\n")[0]); }
try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  const api = (m, p, b, h) => page.evaluate(async ([m, p, b, h]) => {
    const r = await fetch(p, { method: m, headers: h || { "content-type": "application/json" }, body: b == null ? undefined : (typeof b === "string" ? b : JSON.stringify(b)) });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (_) {}
    return { status: r.status, j, t };
  }, [m, p, b, h]);
  const S = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers";
  await api("PUT", "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourcegroups/rg1?api-version=2021-04-01", { location: "eastus" });
  let r = await api("PUT", `${S}/Microsoft.EventGrid/topics/t1?api-version=2024-06-01-preview`, { location: "eastus", properties: {} });
  check("create Event Grid topic", r.status < 300, r.t.slice(0, 200));
} catch (e) { check("boot/azure", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
