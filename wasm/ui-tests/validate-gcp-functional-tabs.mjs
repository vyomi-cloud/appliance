// Capped validation: GCP detail-tab functional backend through the live SW.
// Boots the GCP console (SW + Pyodide + cores), then drives the EXACT endpoints
// the new detail tabs call: cloudsim events + the generic /api/gcp/sub/ route for
// core-backed sub-resources. Runs the whole thing INSIDE the page (SW-intercepted
// fetch), so it proves the real in-browser path the UI uses. Self-kills at 90s.
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000); _k.unref && _k.unref();

import { chromium, startServer, bootConsole } from "./lib.mjs";

const out = (k, v) => console.log("RESULT " + k + " = " + JSON.stringify(v));

(async () => {
  const { server, base } = await startServer();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  try {
    const { errors } = await bootConsole(page, base, "/gcp-console.html");
    out("boot_errors", errors.slice(0, 5));

    // Drive the real endpoints from the page (same-origin, SW-intercepted) exactly
    // as the UI's api()/fetch do. One async sequence, returns a summary object.
    const res = await page.evaluate(async () => {
      const O = location.origin;
      const J = async (m, p, b) => {
        const o = { method: m, headers: {} };
        if (b !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(b); }
        const r = await fetch(O + p, o); let j = null; try { j = await r.json(); } catch (_) {}
        return { status: r.status, j };
      };
      const sub = (op, parent) => `/api/gcp/sub/cloudsql/${op}/${encodeURIComponent(parent)}`;
      const r = {};

      // 1) create a Cloud SQL instance via the catalog collection path (same route
      //    the console list/create uses → generic _resource Create {service:cloudsql}).
      const inst = "func-inst-" + Math.random().toString(36).slice(2, 7);
      r.createInstance = (await J("POST", "/api/gcp/rds/databases", { name: inst })).status;

      // 2) core-backed sub-resource: users (durable adapter store) via /sub/ route
      r.createUser = (await J("POST", sub("createUser", inst), { name: "appuser", host: "%" })).status;
      const lu = await J("GET", sub("listUsers", inst));
      r.listUsers = (lu.j && lu.j.items || []).map(x => x.name);
      r.deleteUser = (await J("POST", sub("deleteUser", inst), { name: "appuser" })).status;
      const lu2 = await J("GET", sub("listUsers", inst));
      r.listUsersAfterDelete = (lu2.j && lu2.j.items || []).length;

      // 3) core-backed sub-resource: databases (native cloud SQL core) via /sub/
      r.createDb = (await J("POST", sub("createDatabase", inst), { name: "appdb" })).status;
      const ld = await J("GET", sub("listDatabases", inst));
      r.listDatabases = (ld.j && ld.j.items || []).map(x => x.name);

      // 4) backups (auto-named adapter store)
      r.createBackup = (await J("POST", sub("createBackup", inst), {})).status;
      const lb = await J("GET", sub("listBackups", inst));
      r.listBackups = (lb.j && lb.j.items || []).length;

      // 5) cloudsim events for THIS resource — must contain the mutating ops above
      const ev = await J("GET", "/api/cloudsim/events?resource=" + encodeURIComponent(inst) + "&provider=gcp&service=cloudsql&limit=200");
      r.eventsOk = !!(ev.j && ev.j.ok);
      r.eventActions = (ev.j && ev.j.events || []).map(e => e.action);
      return r;
    });
    for (const [k, v] of Object.entries(res)) out(k, v);
    const checks = [
      ["console boots without page errors", errors.length === 0],
      ["create Cloud SQL instance", res.createInstance === 200],
      ["create user", res.createUser === 200],
      ["list users shows the new user", (res.listUsers || []).includes("appuser")],
      ["delete user", res.deleteUser === 200 && res.listUsersAfterDelete === 0],
      ["create database and list it", res.createDb === 200 && (res.listDatabases || []).includes("appdb")],
      ["create backup and list it", res.createBackup === 200 && res.listBackups >= 1],
      ["cloudsim events record the Create", res.eventsOk && (res.eventActions || []).includes("Create")],
    ];
    for (const [name, ok] of checks) console.log(`[${ok ? "PASS" : "FAIL"}] ${name}`);
    out("PASS", checks.every(([, ok]) => ok));
    if (!checks.every(([, ok]) => ok)) process.exitCode = 1;
  } catch (e) {
    out("ERROR", String(e && e.message || e));
    console.log("[FAIL] run: " + String(e && e.message || e).split("\n")[0]);
    process.exitCode = 1;
  } finally {
    await browser.close().catch(() => {});
    server.close();
    clearTimeout(_k);
    process.exit(process.exitCode || 0);
  }
})();
