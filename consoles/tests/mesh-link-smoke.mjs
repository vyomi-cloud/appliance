/* Mesh link smoke (phase 1 Nano side): pair -> connected -> per-space home badge -> unreachable banner + /_wire
 * routing -> recovery -> trial warning -> lock -> browser-homed spaces unaffected. Self-contained: starts the Nano
 * preview (consoles/nano_preview.mjs) and a tiny fake mesh implementing the mesh HTTP contract.
 *
 *   node consoles/tests/mesh-link-smoke.mjs        (env PW=<playwright module path>, PORT=8791 FAKE_PORT=8792)
 * Not picked up by run-nano-smokes.mjs (name doesn't start with smoke-). Exit 1 on any FAIL. */
import http from "node:http";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { try { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); } }
const here = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8791), FAKE = Number(process.env.FAKE_PORT || 8792);
const NANO = `http://127.0.0.1:${PORT}/nano`, MESH = `http://127.0.0.1:${FAKE}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };

// ── fake mesh (contract: GET /mesh/status, POST /mesh/pair/complete {code} -> {token}; Bearer tokens) ──
const fake = { trial_days_left: 14, wire: [], token: "tok-" + Date.now(), code: "482913" };
const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*", "access-control-allow-private-network": "true" };
const fakeSrv = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (req.method === "OPTIONS") { res.writeHead(204, cors); return res.end(); }
  let body = ""; req.on("data", (d) => (body += d)); req.on("end", () => {
    const send = (st, o) => { res.writeHead(st, { ...cors, "content-type": "application/json" }); res.end(JSON.stringify(o)); };
    if (u.pathname === "/mesh/pair/complete" && req.method === "POST") {
      let code = ""; try { code = JSON.parse(body).code; } catch {}
      return code === fake.code ? send(200, { token: fake.token, relay_url: MESH + "/", local_url: "http://127.0.0.1:1" }) : send(403, { detail: "bad code" });
    }
    if (u.pathname === "/mesh/status") {
      if (req.headers.authorization !== "Bearer " + fake.token) return send(401, { detail: "unauthorized" });
      return send(200, { version: "4.0.0-dev", tier: "trial", trial_days_left: fake.trial_days_left, hostname: "lab-mesh", cap: { memory_mb: 8192, cpu: 4, disk_gb: 50 }, healthy: true });
    }
    if (u.pathname.startsWith("/_wire/")) { fake.wire.push({ path: u.pathname, token: req.headers["x-vyomi-mesh-token"] }); return send(200, { ok: true, from: "mesh" }); }
    send(404, {});
  });
});
const listen = () => new Promise((r) => fakeSrv.listen(FAKE, "127.0.0.1", r));
const unlisten = () => new Promise((r) => { fakeSrv.closeAllConnections?.(); fakeSrv.close(r); });
await listen();

const preview = spawn("node", [join(here, "..", "nano_preview.mjs"), "--port", String(PORT)], { stdio: "ignore" });
for (let i = 0; i < 40; i++) { try { if ((await fetch(`${NANO}/`, { redirect: "manual" })).status < 500) break; } catch {} await new Promise((r) => setTimeout(r, 250)); }

const browser = await pw.chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("vyomi.mesh_poll_ms", "250"); } catch {} });
const page = await ctx.newPage();
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const wait = (fn, arg, t = 15000) => page.waitForFunction(fn, arg, { timeout: t }).then(() => true, () => false);

try {
  // 1. launcher, SW controlling
  await page.goto(`${NANO}/clouds.html`);
  await wait(() => !!window.VyomiMesh && !!navigator.serviceWorker.controller, null, 30000);
  await page.waitForTimeout(1500);   // nano-sw may reload once to become controlled
  await wait(() => !!window.VyomiMesh && !!navigator.serviceWorker.controller, null, 30000);
  check("mesh-link loaded on launcher", await page.evaluate(() => !!window.VyomiMesh));
  check("no mesh home option before pairing (no Create Space modal in the portal-Nano flow)", await page.evaluate(() => VyomiMesh.homeOptions().length === 0));

  // 2. pairing: wrong code refused, right code -> token stored, connected
  const wrong = await page.evaluate((b) => VyomiMesh.pair(b, "000000").then(() => "paired", (e) => String(e.message)), MESH);
  check("wrong pairing code refused", /refused/i.test(wrong), wrong);
  const paired = await page.evaluate(([b, c]) => VyomiMesh.pair(b, c).then((x) => x, (e) => ({ err: String(e.message) })), [MESH, fake.code]);
  check("pair with code returns mesh record", !!paired.id && !paired.err && paired.name === "lab-mesh", JSON.stringify(paired));
  const id = paired.id;
  check("token stored in registry (not exposed via list)", await page.evaluate((i) => { const raw = JSON.parse(localStorage.getItem("vyomi.meshes"))[0]; return !!raw.token && VyomiMesh.list()[0].token === undefined; }, id));
  check("state connected", await wait((i) => VyomiMesh.state(i) === "connected", id));
  const reg = await page.evaluate(() => JSON.parse(localStorage.getItem("vyomi.meshes"))[0]);
  check("pair response relay_url/local_url stored in registry entry", reg.relay_url === MESH && reg.local_url === "http://127.0.0.1:1", JSON.stringify([reg.relay_url, reg.local_url]));
  const cands = await page.evaluate((i) => VyomiMesh.candidates(i), id);
  check("candidates() uses stored local_url + relay_url", cands.includes("http://127.0.0.1:1") && cands.includes(MESH), cands.join(","));

  // 3. Home picker visible; create mesh-homed + browser-homed spaces
  const opts = await page.evaluate(() => ({ vis: VyomiMesh.homeOptions().length > 0, opts: ["This browser"].concat(VyomiMesh.homeOptions().map((x) => "Mesh: " + x.name)) }));
  check("Home picker shown with mesh option once paired", opts.vis && opts.opts.length === 2 && /Mesh: lab-mesh/.test(opts.opts[1]), opts.opts.join("|"));
  const mk = (name, home, provider = "aws") => page.evaluate(async ([n, h, p]) => { const r = await fetch("/api/spaces", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ provider: p, name: n, home: VyomiMesh.homePayload(h) }) }); return (await r.json()).space; }, [name, home, provider]);
  const bs = await mk("boost-space", id), ws = await mk("web-space", "browser");
  const spaces = { aws: [bs, ws] };
  for (const cl of ["gcp", "azure"]) spaces[cl] = [await mk("boost-" + cl, id, cl), await mk("web-" + cl, "browser", cl)];
  check("mesh-homed space record carries home", bs && bs.home && bs.home.type === "mesh" && bs.home.mesh_id === id, JSON.stringify(bs && bs.home));
  check("browser-homed space has no home", ws && !ws.home);
  await page.reload(); await wait(() => !!document.querySelector("#spaces-grid .space-card[data-space-id]"), null, 30000);
  const badges = await page.evaluate(([a, b]) => ({ b: document.querySelector(`[data-space-id="${a}"] .vyb-badge`)?.dataset.home, w: document.querySelector(`[data-space-id="${b}"] .vyb-badge`)?.dataset.home }), [bs.space_id, ws.space_id]);
  check("space list shows mesh home badge", badges.b === "mesh", JSON.stringify(badges));
  check("space list shows browser home badge", badges.w === "browser", JSON.stringify(badges));

  for (const cloud of ["aws", "gcp", "azure"]) {
    const [bs, ws] = spaces[cloud];
    // 4. console of the mesh-homed space: wire routed to mesh, then outage -> banner + refusal
    await page.evaluate((s) => VyomiMesh.setActive(s), bs);
    await page.goto(`${NANO}/v4/${cloud}/`);
    await wait(() => !!window.VyomiMesh && VyomiMesh.state && VyomiMesh.activeHome(), null);
    await wait((i) => VyomiMesh.state(i) === "connected", id);
    const viaMesh = await page.evaluate(() => fetch(location.pathname.split("/v4/")[0] + "/_wire/probe-1").then((r) => r.json(), (e) => ({ err: String(e) })));
    check(`[${cloud}] mesh-homed /_wire call goes to the mesh`, viaMesh.from === "mesh" && fake.wire.some((w) => w.path === "/_wire/probe-1" && w.token === fake.token), JSON.stringify(viaMesh));
    check(`[${cloud}] no banner while connected`, !(await page.$("#vyb-banner")));

    await unlisten();
    check(`[${cloud}] unreachable banner appears`, await wait(() => /Datacenter unreachable/.test(document.getElementById("vyb-banner")?.textContent || ""), null, 10000));
    const refused = await page.evaluate(() => fetch(location.pathname.split("/v4/")[0] + "/_wire/probe-2", { method: "POST", body: "x" }).then(async (r) => ({ s: r.status, j: await r.json() })));
    check(`[${cloud}] actions refused while unreachable (503 DatacenterUnreachable)`, refused.s === 503 && refused.j.error.code === "DatacenterUnreachable", JSON.stringify(refused));
    check(`[${cloud}] console controls disabled (body class)`, await page.evaluate(() => document.body.classList.contains("vy-mesh-down")));

    await listen();
    check(`[${cloud}] auto-retry recovers: banner clears`, await wait(() => !document.getElementById("vyb-banner") && VyomiMesh.state(JSON.parse(localStorage.getItem("vyomi.meshes"))[0].id) === "connected", null, 10000));
    const again = await page.evaluate(() => fetch(location.pathname.split("/v4/")[0] + "/_wire/probe-3").then((r) => r.json()));
    check(`[${cloud}] wire works again after recovery`, again.from === "mesh");

    // 5. trial warning (<=7 days) then lock (day 15 -> trial_days_left 0)
    fake.trial_days_left = 5;
    check(`[${cloud}] trial banner at 5 days left`, await wait(() => /trial ends in 5 days/i.test(document.getElementById("vyb-banner")?.textContent || ""), null, 8000));
    fake.trial_days_left = 0;
    check(`[${cloud}] lock screen when trial over`, await wait(() => !!document.getElementById("vyb-lock"), null, 8000));
    const locked = await page.evaluate(() => fetch(location.pathname.split("/v4/")[0] + "/_wire/probe-4").then(async (r) => ({ s: r.status, j: await r.json() })));
    check(`[${cloud}] wire refused while locked`, locked.s === 503 && locked.j.error.code === "MeshTrialExpired", JSON.stringify(locked));
    fake.trial_days_left = 14;
    check(`[${cloud}] lock clears on valid entitlement`, await wait(() => !document.getElementById("vyb-lock"), null, 8000));

    // 6. browser-homed space is never affected by an outage / lock
    fake.trial_days_left = 0; await unlisten();
    await page.evaluate((s) => VyomiMesh.setActive(s), ws);
    await page.reload();
    await page.waitForTimeout(2500);
    check(`[${cloud}] browser-homed space: no banner/lock during outage+lock`, await page.evaluate(() => !document.getElementById("vyb-banner") && !document.getElementById("vyb-lock") && !document.body.classList.contains("vy-mesh-down")));
    check(`[${cloud}] browser-homed /_wire not redirected`, await page.evaluate(() => VyomiMesh.activeHome() === null));
    await listen(); fake.trial_days_left = 14;
    await wait((i) => VyomiMesh.state(i) === "connected", id, 15000);
  }

  // 7. legacy wasm/<cloud>-console.html pages carry the same hook (mesh taken down first)
  await unlisten();
  for (const cloud of ["aws", "gcp", "azure"]) {
    await page.evaluate(([s, base]) => fetch(base + "/api/spaces/" + s.space_id + "/switch", { method: "POST" }).then(() => VyomiMesh.setActive(s)), [spaces[cloud][0], "/nano"]);   // like the Spaces list: make it the SW active space
    await page.goto(`${NANO}/${cloud}-console.html`);
    check(`[legacy ${cloud}] mesh-link loaded`, await wait(() => !!window.VyomiMesh, null, 30000));
    check(`[legacy ${cloud}] unreachable banner for mesh-homed space`, await wait(() => /Datacenter unreachable/.test(document.getElementById("vyb-banner")?.textContent || ""), null, 15000));
  }
} catch (e) { check("harness error", false, e && e.stack || e); }

console.log(errors.length ? `page errors (informational): ${errors.slice(0, 3).join(" | ")}` : "no page errors");
console.log(bad ? `\n${bad} FAILED` : "\nall mesh-link checks passed");
await browser.close(); preview.kill(); fakeSrv.closeAllConnections?.(); fakeSrv.close();
process.exit(bad ? 1 : 0);
