/* Vyomi Nano <-> mesh link (mesh pack, phase 1; spec: docs/architecture/v4.0/V4-MESH-DESIGN-DISCUSSION.md).
 *
 * A "mesh" is a paired Pro/Max appliance that hosts mesh-homed spaces. This plain script (no deps) is
 * loaded by clouds.html and by every v4 Nano console (BEFORE nano-boot.js, so its fetch hook is in place).
 *
 *  - registry   : paired meshs in localStorage "vyomi.meshes" [{id,name,token,local_url,relay_url,port,...}]
 *  - connect    : <id>.local.vyomi.cloud (HTTPS) -> relay URL -> loopback http://127.0.0.1:<port> (dev); first that answers wins
 *  - pairing    : POST {base}/mesh/pair/complete {code} -> {token}; then GET /mesh/status (Authorization: Bearer)
 *  - health     : GET /mesh/status every 5 s -> state "connected" | "unreachable" (| "unauthorized"); events on window
 *  - per-space  : space.home = {type:"mesh", mesh_id, mesh_name} | absent (= this browser), fixed at creation
 *  - routing    : for a mesh-homed ACTIVE space, same-origin <base>/_wire/* fetches are redirected to the mesh
 *                 (browser-homed spaces are never touched)
 *  - blocking   : mesh unreachable -> "Datacenter unreachable" banner, wire calls refused, controls disabled,
 *                 auto-retry; trial_days_left <= 7 -> banner; <= 0 -> lock screen. Browser-homed spaces: no effect.
 *
 * Wire auth: the console's SigV4 `authorization` header is the routing signal and must stay intact, so on /_wire
 * the mesh token travels in `x-vyomi-mesh-token` (+ `Authorization: Bearer` only when the call has none).
 * Public API: window.VyomiMesh. Events (on window): "vyomi-mesh-state", "vyomi-mesh-registry".
 */
(function () {
  if (window.VyomiMesh) return;
  var LS_REG = "vyomi.meshes", LS_ACTIVE = "vyomi.active_space";
  var SESSION_ID = "vyomi-session", vboost = null;   // the portal-started Codespace mesh: in-memory only (its token expires with the session)
  var POLL_MS = (function () { try { var v = Number(localStorage.getItem("vyomi.mesh_poll_ms")); if (v >= 100) return v; } catch (_) {} return 5000; })();
  var PROBE_TIMEOUT = 2500, FAILS_TO_DOWN = 2, TRIAL_WARN_DAYS = 7;
  var realFetch = window.fetch.bind(window);
  // Mount path of the Nano bundle (page at <BASE>/clouds.html or <BASE>/v4/<cloud>/).
  var NANO_BASE = location.pathname.replace(/\/v4\/[^/]*\/?[^/]*$/, "").replace(/\/[^/]*$/, "");
  var IS_CONSOLE = /\/v4\/|-console\.html/.test(location.pathname);

  // ── registry ────────────────────────────────────────────────────────
  function stored() { try { var a = JSON.parse(localStorage.getItem(LS_REG) || "[]"); return Array.isArray(a) ? a.filter(function (b) { return b.id !== SESSION_ID; }) : []; } catch (_) { return []; } }
  function load() { var a = stored(); if (vboost) a.push(vboost); return a; }
  function save(a) { a = a.filter(function (b) { return b.id !== SESSION_ID; }); try { localStorage.setItem(LS_REG, JSON.stringify(a)); } catch (_) {} emit("vyomi-mesh-registry", { meshes: list() }); }
  function list() { return load().map(function (b) { return Object.assign({}, b, { token: undefined, has_token: !!b.token }); }); }
  function get(id) { return load().find(function (b) { return b.id === id; }) || null; }
  function emit(name, detail) { try { window.dispatchEvent(new CustomEvent(name, { detail: detail })); } catch (_) {} }

  // ── connection ──────────────────────────────────────────────────────
  function candidates(b) {
    if (b.session) return b.relay_url ? [b.relay_url] : [];
    var c = [];
    if (b.local_url) c.push(b.local_url);
    else if (b.id) c.push("https://" + b.id + ".local.vyomi.cloud" + (b.local_port ? ":" + b.local_port : ""));
    if (b.relay_url) c.push(b.relay_url);
    if (b.port) c.push("http://127.0.0.1:" + b.port);
    if (b.loopback_url) c.push(b.loopback_url);
    var seen = {}; c = c.map(function (u) { return u.replace(/\/+$/, ""); }).filter(function (u) { return u && !seen[u] && (seen[u] = 1); });
    if (b.base) { c = c.filter(function (u) { return u !== b.base; }); c.unshift(b.base); }   // last good first
    return c;
  }
  function timed(url, init) {
    var ctl = new AbortController(), t = setTimeout(function () { ctl.abort(); }, PROBE_TIMEOUT);
    return realFetch(url, Object.assign({}, init, { signal: ctl.signal, cache: "no-store" })).finally(function () { clearTimeout(t); });
  }
  function probeStatus(b) {   // -> {base, status} | {unauthorized:true, base} | null
    var cs = candidates(b), i = 0;
    function next() {
      if (i >= cs.length) return Promise.resolve(null);
      var base = cs[i++];
      return timed(base + "/mesh/status", { headers: b.session ? { "x-vyomi-session-token": b.token } : b.token ? { Authorization: "Bearer " + b.token } : {} }).then(function (r) {
        if (r.status === 401 || r.status === 403) return { unauthorized: true, base: base };
        if (!r.ok) return next();
        return r.json().then(function (j) { return { base: base, status: j }; });
      }, next);
    }
    return next();
  }

  // ── health state machine ────────────────────────────────────────────
  var state = {};   // id -> {state, status, base, fails, at}
  function stateOf(id) { return (state[id] && state[id].state) || "unknown"; }
  function setState(id, patch) {
    var prev = state[id] || { state: "unknown", fails: 0 }, next = Object.assign({}, prev, patch, { at: Date.now() });
    state[id] = next;
    if (prev.state !== next.state || patch.status) emit("vyomi-mesh-state", { id: id, state: next.state, previous: prev.state, status: next.status || null });
    if (prev.state !== next.state || patch.status) render();
  }
  function pollOne(b) {
    return probeStatus(b).then(function (r) {
      if (r && r.status) {
        var all = load(), me = all.find(function (x) { return x.id === b.id; });
        if (me && me.base !== r.base) { me.base = r.base; save(all); }
        setState(b.id, { state: "connected", status: r.status, base: r.base, fails: 0 });
      } else if (r && r.unauthorized) {
        setState(b.id, { state: "unauthorized", fails: 0 });
      } else {
        var f = ((state[b.id] || {}).fails || 0) + 1;
        setState(b.id, { fails: f, state: f >= FAILS_TO_DOWN || stateOf(b.id) === "unreachable" ? "unreachable" : stateOf(b.id) });
      }
    });
  }
  var timer = null;
  function pollAll() { return Promise.all(load().map(pollOne)).then(render, render); }   // re-render each cycle: legacy pages rebuild <body> after load and would drop the banner
  // ── account: the portal's per-user mesh subscription record (portal DB) ──────────────────────
  // enabled mesh -> spaces default to the mesh (backend); not enabled -> everything stays in the browser.
  // `null` = the portal can't say (preview / offline / signed out): behave as before (paired meshs stay usable).
  var account = null, accTimer = null;
  var _origFetch = window.fetch.bind(window);
  function accountFetch(method, path) {
    return _origFetch("/api/account/mesh" + (path || ""), { method: method || "GET", credentials: "same-origin", headers: { accept: "application/json" } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); });
  }
  function loadAccount() {
    return accountFetch("GET").then(function (r) {
      var was = JSON.stringify(account);
      account = (r.ok && r.body && typeof r.body.enabled === "boolean") ? r.body : null;
      if (JSON.stringify(account) !== was) { try { window.dispatchEvent(new CustomEvent("vyomi-mesh-account", { detail: account })); } catch (_) {} render(); }
      enforcePlanCloud();
      return account;
    }, function () { account = null; return null; });
  }
  // Pro = ONE cloud: a console of any other cloud does not open. Blocks the page at once (no way to keep working there), then sends the
  // user to the Spaces page after a moment. Only on a console page and only once the portal's account record is known.
  var planGated = false;
  function pageCloud() { var m = location.pathname.match(/\/v4\/(aws|azure|gcp)(\/|$)/) || location.pathname.match(/(aws|azure|gcp)-console\.html/); return m ? m[1] : ""; }
  function enforcePlanCloud() {
    if (planGated || !IS_CONSOLE || !account) return;
    var c = pageCloud(), pc = planCloud();
    if (!c || !pc || cloudAllowed(c)) return;
    planGated = true;
    var N = { aws: "AWS", gcp: "GCP", azure: "Azure" }, home = location.pathname.replace(/\/(v4\/.*|[^/]*-console\.html)$/, "") + "/clouds.html";   // the Spaces page next to the bundle (NANO_BASE is empty on /nano/v4/<cloud>/)
    var o = document.createElement("div"); o.id = "vyb-plan-gate"; o.setAttribute("role", "alertdialog"); o.setAttribute("aria-modal", "true");
    o.style.cssText = "position:fixed;inset:0;z-index:2147483600;background:rgba(15,23,42,.72);display:flex;align-items:center;justify-content:center;padding:16px;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif";
    o.innerHTML = '<div style="max-width:440px;background:#fff;color:#0f172a;border-radius:12px;padding:24px 26px;box-shadow:0 20px 50px rgba(0,0,0,.35)">'
      + '<h2 style="margin:0 0 8px;font-size:18px">Your plan covers ' + (N[pc] || pc) + ' only</h2>'
      + '<p style="margin:0 0 18px;color:#475467">The ' + (N[c] || c) + ' console is part of Max. Taking you back to your spaces.</p>'
      + '<a href="' + home + '" style="display:inline-block;background:#0f172a;color:#fff;text-decoration:none;border-radius:8px;padding:9px 16px;font-weight:600">Go to my spaces</a>'
      + ' <a href="/pricing" target="_blank" rel="noopener" style="margin-left:10px;color:#2563eb">See plans</a></div>';
    document.body.appendChild(o);
    setTimeout(function () { location.replace(home); }, 3500);
  }
  function setMesh(on) {
    return accountFetch("POST", on ? "/enable" : "/disable").then(function (r) {
      if (r.ok) { account = r.body; try { window.dispatchEvent(new CustomEvent("vyomi-mesh-account", { detail: account })); } catch (_) {} render(); return account; }
      var e = new Error((r.body && r.body.message) || "Could not change the mesh setting."); e.account = r.body; throw e;
    });
  }
  // Pro = ONE cloud (all services on it); Max / Enterprise = all three. The portal's account record says which applies and
  // (once chosen) which cloud. No record (not signed in / Free) -> not gated here.
  function planCloud() { return account && account.clouds === "one" ? String(account.primary_cloud || "").toLowerCase() : null; }
  function cloudAllowed(c) { if (!account || account.clouds !== "one") return true; var pc = planCloud(); return !pc || String(c).toLowerCase() === pc; }
  function pinCloud(c) {   // first use of a cloud on a Pro plan chooses it; refused once another is chosen
    if (!account || account.clouds !== "one" || planCloud()) return Promise.resolve(cloudAllowed(c));
    return _origFetch("/api/account/mesh/primary-cloud", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify({ cloud: c }) })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (r) { if (r.ok) { account = r.body; try { window.dispatchEvent(new CustomEvent("vyomi-mesh-account", { detail: account })); } catch (_) {} return true; } if (r.body && r.body.primary_cloud) { account = Object.assign({}, account, { primary_cloud: r.body.primary_cloud }); } return false; }, function () { return true; });
  }
  function meshOn() { return account === null || account.effective === true; }   // unknown -> don't hide anything
  function start() { if (timer) return; checkTunnel(); setInterval(checkTunnel, 3000); setInterval(lockTunnelStop, 1000); loadSession(); sessTimer = setInterval(loadSession, POLL_MS); setInterval(sessionTick, 1000); loadAccount(); accTimer = setInterval(loadAccount, 60000); pollAll(); timer = setInterval(pollAll, POLL_MS); }


  // ── portal session (the portal-Nano flow: Start/Stop live on the vyomi.cloud dashboard; Nano only shows + uses it) ──────────
  // /api/mesh/status -> {session:{state,countdown_seconds,session_token,error},relay_url,error,ended_note,hours_remaining,...}.
  // While the session is running the relay is registered as an in-memory mesh and compute/AI wire calls are routed to it.
  var sess = null, sessTimer = null;
  var COMPUTE_SCOPE = /Credential=[^/]+\/[^/]+\/[^/]+\/(ec2|lambda|ecs|eks|batch|lightsail|autoscaling|apprunner|bedrock|bedrock-runtime|bedrock-agent|bedrock-agent-runtime|sagemaker|sagemaker-runtime)\//i;
  // AI data planes: Vertex publishers/endpoints (v1 AND v1beta1 - the router accepts both), Azure OpenAI (/openai/..., offline /azure-data/openai/...).
  var COMPUTE_PATH = /^\/(compute\/v1\/|v1(beta1)?\/projects\/[^/]+\/locations\/[^/]+\/(publishers|endpoints|models)\b|openai\/|azure-data\/openai\/|.*\/aiplatform\/)|\/providers\/Microsoft\.(Compute|ContainerService|CognitiveServices|MachineLearningServices|Batch|ContainerInstance)\//i;
  // Heuristic classifier for native-wire calls: EC2/VMs, languages (Lambda/functions), AI. Everything else stays in the browser.
  function isComputeCall(wirePath, authorization) { return COMPUTE_SCOPE.test(authorization || "") || COMPUTE_PATH.test(wirePath || ""); }
  var LOCAL_TUNNEL = "http://127.0.0.1:8090";   // vyomi-tunnel's local relay (RELAY_PORT default)
  function httpBase(u) { try { var x = new URL(u); x.protocol = x.protocol === "wss:" ? "https:" : x.protocol === "ws:" ? "http:" : x.protocol; x.pathname = ""; x.search = ""; return x.toString().replace(/\/+$/, ""); } catch (_) { return ""; } }
  // ── local tunnel health ──────────────────────────────────────────────────────────────────────────────────────────────────────
  // The Mesh's control AND data plane (EC2 / VMs / Bedrock / Lambda / every compute+AI call) travel through the user's own `vyomi-tunnel`
  // (127.0.0.1:8090). Without it the Codespace can say "running" while nothing works, so Join is refused until the tunnel is up.
  //   unknown (not probed yet) | down (nothing answers: not installed / not running) | notab (running, but no Nano tab connected) | up
  var T0 = Date.now(), tun = { state: "unknown", version: "", at: 0 }, tunBusy = null;      // tunBusy = the in-flight probe (callers share it, never a stale state)
  function tunnel() { return { state: tun.state, version: tun.version, up: tun.state === "up" }; }
  function checkTunnel() {
    if (tunBusy) return tunBusy;
    tunBusy = timed(LOCAL_TUNNEL + "/health").then(function (r) { return r.ok ? r.json() : null; }, function () { return null; }).then(function (j) {
      var next = j && j.ok ? (j.tab ? "up" : "notab") : "down";
      // After a reload the strip resumes the tunnel by itself within seconds: not "go click Start tunnel" yet.
      try { if (next === "notab" && localStorage.getItem("nano_tunnel_on") === "1" && Date.now() - T0 < 20000) next = "connecting"; } catch (_) {}
      var changed = next !== tun.state;
      tun = { state: next, version: (j && j.version) || "", at: Date.now() };
      tunBusy = null;
      if (changed) emit("vyomi-tunnel", tunnel());
      return tunnel();
    });
    return tunBusy;
  }
  function meshActive() { return !!(sess && sess.active); }
  // While a Mesh session is live the tunnel carries it: the strip's Stop must not drop it (Leave the Mesh first).
  function lockTunnelStop() {
    var b = document.getElementById("nano-foot-toggle"); if (!b) return;
    var lock = meshActive() && /^stop$/i.test((b.getAttribute("data-vy-label") || b.textContent).trim());
    if (lock) { b.style.opacity = ".45"; b.style.cursor = "not-allowed"; b.title = "The Mesh is using this tunnel. Leave the Mesh first."; b.setAttribute("aria-disabled", "true"); }
    else if (b.getAttribute("aria-disabled") === "true") { b.style.opacity = ""; b.style.cursor = ""; b.title = ""; b.removeAttribute("aria-disabled"); }
  }
  document.addEventListener("click", function (e) {
    var b = e.target && e.target.closest && e.target.closest("#nano-foot-toggle");
    if (b && b.getAttribute("aria-disabled") === "true") { e.preventDefault(); e.stopImmediatePropagation(); toast("The Mesh is using this tunnel. Leave the Mesh first, then stop the tunnel."); }
  }, true);
  function tunnelBlockMessage() {
    return tun.state === "connecting" ? "Your tunnel is still connecting. Try again in a few seconds." : tun.state === "notab" ? "The tunnel is running but this console is not connected to it. Click Start tunnel in the bar at the bottom, then join the Mesh."
      : "The Mesh needs the Vyomi tunnel running on this computer (EC2, VMs and AI all go through it). Install and run vyomi-tunnel, click Start tunnel in the bar at the bottom, then join the Mesh.";
  }

  // ── pre-join health checks ──────────────────────────────────────────────────────────────────────────────────────────────────
  // A Codespace can report "running" and still be unusable (DNS broken so apt-get fails, no egress, services down). Once the session is
  // running the console verifies the Mesh THROUGH the tunnel (tunnel + reachability here, then the Mesh's own GET /mesh/selfcheck for DNS,
  // apt, egress, disk, memory, appliance, AI). Only when every check is green can the user Join; compute/AI calls are routed to the Mesh
  // only after Join, so an unhealthy Mesh is never silently used.
  var CHECK_ORDER = [["tunnel", "Tunnel connected to this console"], ["reach", "Mesh reachable through the tunnel"], ["dns", "DNS resolution"], ["apt", "Package mirror (apt)"],
    ["egress", "Outbound HTTPS"], ["disk", "Disk space"], ["memory", "Memory"], ["appliance", "Appliance healthy"], ["ai", "AI runtime"]];
  var chk = { sid: 0, state: "idle", items: [], at: 0 }, chkRun = 0, lastFail = null;     // lastFail: the attempt that was stopped because a check failed       // state: idle | running | passed | failed
  function sessId() { return sess && sess.session && sess.session.id || 0; }
  function isJoined() { var id = sessId(); if (!id) return false; try { return sessionStorage.getItem("vy_mesh_joined:" + id) === "1"; } catch (_) { return false; } }
  function setJoined(on) { var id = sessId(); if (!id) return; try { on ? sessionStorage.setItem("vy_mesh_joined:" + id, "1") : sessionStorage.removeItem("vy_mesh_joined:" + id); } catch (_) {} }
  function checks() { return { sid: chk.sid, state: chk.state, items: chk.items.map(function (i) { return Object.assign({}, i); }), at: chk.at, joined: isJoined() }; }
  function meshBase() { return sess && sess.relay_url ? httpBase(sess.relay_url) : LOCAL_TUNNEL; }
  function runChecks() {
    var ss = sess && sess.session; if (!ss || ss.state !== "running" || !ss.session_token) return Promise.resolve(checks());
    var my = ++chkRun, hdr = { "x-vyomi-session-token": ss.session_token }, base = meshBase();
    chk = { sid: ss.id, state: "running", items: CHECK_ORDER.map(function (c) { return { id: c[0], label: c[1], ok: null, detail: "", hint: "" }; }), at: Date.now() };
    emit("vyomi-mesh-checks", checks());
    function put(it) { if (my !== chkRun) return; var i = chk.items.findIndex(function (x) { return x.id === it.id; }); if (i < 0) chk.items.push(it); else chk.items[i] = Object.assign({}, chk.items[i], it); emit("vyomi-mesh-checks", checks()); }
    function finish() { if (my !== chkRun) return checks(); chk.items.forEach(function (i) { if (i.ok === null) { i.ok = false; i.skipped = true; i.detail = "not checked (an earlier check failed)"; } }); chk.state = chk.items.every(function (i) { return i.ok; }) ? "passed" : "failed"; chk.at = Date.now();
      if (chk.state === "passed") { joinMesh(); }                                          // the user already asked to join: all green means they are in
      else {                                                                               // a buggy Mesh is never kept: remember why, stop the Codespace, the widget offers Join again
        lastFail = { sid: chk.sid, at: Date.now(), items: chk.items.map(function (i) { return Object.assign({}, i); }) };
        sessionStop();
      }
      emit("vyomi-mesh-checks", checks()); return checks(); }
    function portalReport() {
      var t0 = Date.now(), wait = (function () { try { var v = Number(localStorage.getItem("vyomi.mesh_report_wait_ms")); if (v >= 500) return v; } catch (_) {} return 150000; })();
      return new Promise(function (res) {
        (function poll() {
          if (my !== chkRun) return res();
          var sc = sess && sess.session && sess.session.selfcheck;
          if (sc && sc.items && sc.items.length) { sc.items.forEach(function (it) { put(it); }); return res(); }
          if (Date.now() - t0 > wait) { put({ id: "selfcheck", label: "Health checks", ok: false, detail: "the Codespace did not report its health checks", hint: "Stop the Mesh and start it again." }); return res(); }
          loadSession().then(function () { setTimeout(poll, 3000); }, function () { setTimeout(poll, 3000); });
        })();
      });
    }
    return checkTunnel().then(function (t) {
      if (!t.up) { put({ id: "tunnel", ok: false, detail: t.state === "notab" ? "running, but this console is not connected" : "not reachable on this computer", hint: tunnelBlockMessage() }); return finish(); }
      put({ id: "tunnel", ok: true, detail: "vyomi-tunnel " + (t.version || "") });
      // Right after the Codespace reports ready, the tunnel can still be attaching to it, so one 2.5 s probe is not a verdict:
      // keep asking (8 s per try, 3 s apart) for up to 90 s, showing the wait in the dialog, and only then call it failed.
      function reachMesh() {
        var r0 = Date.now(), win = (function () { try { var v = Number(localStorage.getItem("vyomi.mesh_reach_wait_ms")); if (v >= 500) return v; } catch (_) {} return 90000; })(), tryMs = 8000;
        return new Promise(function (res, rej) {
          function again(why) {
            var el = Date.now() - r0;
            if (my !== chkRun) return res();
            if (el > win) return rej(new Error(why === "timeout" ? "no answer from the Mesh through the tunnel after " + Math.round(el / 1000) + " seconds" : why));
            put({ id: "reach", detail: "waiting for the tunnel to reach the Mesh (" + Math.round(el / 1000) + " s)" });
            setTimeout(go, 3000);
          }
          function go() {
            if (my !== chkRun) return res();
            var ctl = new AbortController(), tm = setTimeout(function () { ctl.abort(); }, tryMs);
            realFetch(base + "/mesh/status", { headers: hdr, cache: "no-store", signal: ctl.signal }).then(function (r) {
              clearTimeout(tm);
              if (r.ok) return res();
              if (r.status >= 500) return again("HTTP " + r.status);          // the Mesh is not serving yet
              rej(new Error("HTTP " + r.status));                              // 401/403/404: retrying will not help
            }, function (e) { clearTimeout(tm); again(e && e.name === "AbortError" ? "timeout" : String(e && e.message || e)); });
          }
          go();
        });
      }
      return reachMesh().then(function () {
        put({ id: "reach", ok: true, detail: "answered through the tunnel" });
      }).then(function () {
        var ctl = new AbortController(), tm = setTimeout(function () { ctl.abort(); }, 25000);
        return realFetch(base + "/mesh/selfcheck", { headers: hdr, cache: "no-store", signal: ctl.signal }).finally(function () { clearTimeout(tm); }).then(function (r) {
          if (r.status === 404) return portalReport();          // this image has no /mesh/selfcheck: use the report boot-mesh.sh posted to the portal
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json().then(function (j) { (j.items || []).forEach(put); });
        });
      }, function (e) { put({ id: "reach", ok: false, detail: String(e && e.message || e), hint: "The tunnel is up but the Mesh does not answer through it. Wait a minute and re-run the checks." }); }).then(finish, function (e) { put({ id: "selfcheck", label: "Health checks", ok: false, detail: String(e && e.message || e), hint: "The Mesh did not answer its health checks." }); return finish(); });
    });
  }
  function joinMesh() {
    if (chk.state !== "passed" || chk.sid !== sessId()) return false;
    setJoined(true); applySession(sess); emit("vyomi-mesh-checks", checks());
    portalApi("joined", "POST").then(function () {}, function () {});      // tell the portal this person is IN (counts once, server-side) — never blocks the join
    return true;
  }
  // ── one diagnostic dialog: startup progress + health checks (no buttons: Join / Leave / Re-run live on the widget) ───────────────
  var BOOT = [[0, "Requesting your Codespace from GitHub"], [25, "Creating the Codespace"], [90, "Booting the Vyomi appliance"], [200, "Starting services and loading models"], [330, "Waiting for the appliance to report ready"]];
  function progress() {
    var ss = sess && sess.session; if (!ss || !sess.active || lastFail) return null;
    var t0 = ss.started_at ? Date.parse(ss.started_at) : NaN, el = isNaN(t0) ? 0 : Math.max(0, (Date.now() - t0) / 1000), up = ss.state === "running", cur = 0, i, steps = [];
    for (i = 0; i < BOOT.length; i++) if (el >= BOOT[i][0]) cur = i;
    steps.push({ label: "Tunnel connected to this console", st: tun.state === "up" ? "done" : "bad" });
    for (i = 0; i < BOOT.length; i++) steps.push({ label: BOOT[i][1], st: up || i < cur ? "done" : i === cur ? "now" : "todo" });
    var ck = up && chk.sid === ss.id ? chk : { state: "idle", items: [] };
    steps.push({ label: "Health checks", st: !up ? "todo" : ck.state === "passed" ? "done" : ck.state === "failed" ? "bad" : "now", items: up ? ck.items.filter(function (i) { return i.id !== "tunnel"; }) : [] });          // the tunnel is step 1 already
    steps.push({ label: "Join the Mesh", st: up && ck.state === "passed" && !isJoined() ? "now" : isJoined() ? "done" : "todo", note: "use the Join button on the Mesh card" });
    var n = steps.length, done = steps.filter(function (x) { return x.st === "done"; }).length, now = -1;
    for (i = 0; i < n; i++) if (steps[i].st === "now" || steps[i].st === "bad") { now = i; break; }
    return { steps: steps, el: el, n: n, done: done, now: now, bad: now >= 0 && steps[now].st === "bad", pct: Math.round((done + (now >= 0 && steps[now].st === "now" ? 0.5 : 0)) / n * 100) };
  }
  var chkCss = false, detTimer = 0;
  function openDetails() {
    if (document.getElementById("vyb-chk")) return;
    dialogCss(); var c = cloudOf();
    if (!chkCss) { chkCss = true; var st = document.createElement("style"); st.textContent = "#vyb-chk .vyb-tm{display:flex;flex-direction:column;width:min(860px,94vw);max-width:none;max-height:min(92vh,900px)}#vyb-chk .tm-h h3{font-size:24px}#vyb-chk .ck>li{font-size:15.5px;padding:8px 0}#vyb-chk .sub li{font-size:14.5px}#vyb-chk .dt{font-size:13px}#vyb-chk .hn{font-size:13.5px}#vyb-chk .errc{font-size:15px}#vyb-chk .tm-b{overflow:auto;min-height:0;padding-bottom:18px}"
      + "#vyb-chk .errc{border:1px solid #f3b5ae;background:#fef3f2;color:#912018;border-radius:8px;padding:10px 12px;margin:0 0 12px;font-size:13.5px;line-height:1.45}#vyb-chk .errc ul{margin:6px 0 6px;padding-left:18px}#vyb-chk .errc p{margin:6px 0 0;color:#7a271a}#vyb-chk .ck{list-style:none;margin:0;padding:0}#vyb-chk .ck>li{display:grid;grid-template-columns:22px 1fr;gap:1px 8px;padding:6px 0;border-bottom:1px solid rgba(128,128,128,.14);font-size:14px}"
      + "#vyb-chk .ic{font-weight:700;text-align:center}#vyb-chk .ok{color:#067647}#vyb-chk .bad{color:#b42318}#vyb-chk .wait{color:#9ca3af}#vyb-chk .now{color:#1a56c4}#vyb-chk .lb.todo{color:#9ca3af}#vyb-chk .dt{grid-column:2;font-size:12px;color:#6b7280}#vyb-chk .hn{grid-column:2;font-size:12.5px;color:#b42318}"
      + "#vyb-chk .sub{grid-column:2;list-style:none;margin:4px 0 0;padding:0 0 0 2px}#vyb-chk .sub li{display:grid;grid-template-columns:20px 1fr;gap:0 6px;padding:2px 0;font-size:13px}#vyb-chk .sub .dt,#vyb-chk .sub .hn{grid-column:2}"
      + "@keyframes vychk{to{transform:rotate(360deg)}}#vyb-chk .sp{display:inline-block;animation:vychk 1s linear infinite}"; document.head.appendChild(st); }
    function esc2(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (ch) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]; }); }
    function mark(st) { return st === "done" || st === true ? '<span class="ic ok">✓</span>' : st === "bad" || st === false ? '<span class="ic bad">✗</span>' : st === "now" || st === null ? '<span class="ic now"><span class="sp">◠</span></span>' : '<span class="ic wait">○</span>'; }
    var o = document.createElement("div"); o.id = "vyb-chk"; o.className = "vyb-tm-o"; o.setAttribute("data-cloud", c); o.setAttribute("data-vyb-keep", "1");
    function mm(sec) { sec = Math.max(0, sec | 0); return Math.floor(sec / 60) + "m " + String(sec % 60).padStart(2, "0") + "s"; }
    function failSteps() {                // the stopped attempt: everything booted, the checks are where it went wrong
      var st = [{ label: "Tunnel connected to this console", st: "done" }].concat(BOOT.map(function (b) { return { label: b[1], st: "done" }; }));
      st.push({ label: "Health checks", st: "bad", items: lastFail.items.filter(function (i) { return i.id !== "tunnel"; }) });
      st.push({ label: "Join the Mesh", st: "todo" }); return st;
    }
    function errCard() {                  // why the last attempt was stopped: only the checks that really failed
      var errs = lastFail.items.filter(function (i) { return i.ok === false && !i.skipped; });
      return '<div class="errc"><b>Health check failed</b><ul>' + errs.map(function (i) { return "<li><b>" + esc2(i.label) + "</b>" + (i.detail ? ": " + esc2(i.detail) : "") + (i.hint ? "<br>" + esc2(i.hint) : "") + "</li>"; }).join("")
        + "</ul><p>The Codespace was stopped, so nothing is left running or counting against your quota. Close this and click Join the Mesh to try again.</p></div>";
    }
    function paintM() {
      var p = progress(), failed = !p && lastFail;
      if (!p && !failed) { close(); return; }
      var joined = isJoined(), head = failed ? "Health check failed. The Mesh was stopped" : joined ? "You are in the Mesh" : p.bad ? "Your Mesh is not healthy" : chk.state === "passed" ? "Your Mesh is healthy" : sess.session.state === "running" ? "Checking your Mesh…" : "Starting your Mesh…";
      var steps = failed ? failSteps() : p.steps;
      var li = steps.map(function (x) {
        var sub = (x.items && x.items.length) ? '<ul class="sub">' + x.items.map(function (i) {
          return "<li>" + mark(i.skipped ? "todo" : i.ok) + "<span>" + esc2(i.label) + "</span>" + (i.ok !== true && i.detail ? '<span class="dt">' + esc2(i.detail) + "</span>" : "") + (i.ok === false && !i.skipped && i.hint ? '<span class="hn">' + esc2(i.hint) + "</span>" : "") + "</li>"; }).join("") + "</ul>" : "";
        return "<li>" + (x.note && x.st === "now" ? '<span class="ic now">\u25B6</span>' : mark(x.st)) + '<span class="lb ' + x.st + '">' + esc2(x.label) + (x.st === "now" && !x.items ? "…" : "") + "</span>" + (x.st === "now" && x.note ? '<span class="dt">' + esc2(x.note) + "</span>" : "") + sub + "</li>";
      }).join("");
      var sc = o.querySelector(".tm-b"), top = sc ? sc.scrollTop : 0;
      o.innerHTML = '<div class="vyb-tm" data-cloud="' + c + '" role="dialog" aria-modal="true" aria-labelledby="vyb-chk-t"><button type="button" class="tm-x" data-no aria-label="Close">✕</button>'
        + '<div class="tm-h"><h3 id="vyb-chk-t">' + head + '</h3></div><div class="tm-b">' + (failed ? errCard() : "") + '<p>' + (failed ? "" : "Step " + (p.now >= 0 ? p.now + 1 : p.n) + " of " + p.n + " · " + mm(p.el) + " elapsed · " + p.pct + "%. First starts commonly take 4 to 8 minutes.") + "</p>"
        + '<ul class="ck">' + li + "</ul></div></div>";
      var nb = o.querySelector(".tm-b"); if (nb) nb.scrollTop = top;
    }
    function close() { window.removeEventListener("vyomi-mesh-checks", paintM); window.removeEventListener("vyomi-mesh-session", paintM); clearInterval(detTimer); document.removeEventListener("keydown", key, true); o.remove(); }
    function key(e) { if (e.key === "Escape") { e.stopPropagation(); close(); } }
    o.addEventListener("click", function (e) { var t = e.target; if (t === o || (t.closest && t.closest("[data-no]"))) close(); });
    window.addEventListener("vyomi-mesh-checks", paintM); window.addEventListener("vyomi-mesh-session", paintM); document.addEventListener("keydown", key, true);
    paintM(); document.body.appendChild(o); detTimer = setInterval(paintM, 1000);
  }

  function applySession(st) {
    var prev = JSON.stringify(sess && { s: sess.session && sess.session.state, e: sess.error && sess.error.code, n: sess.ended_note });
    sess = st;
    // No hosted relay (decision 2026-11-10: the link runs on the laptop): with no relay_url from the portal the console talks to the
    // user's own `vyomi-tunnel`, which holds the ssh session to the Codespace. A hosted relay_url, when set, still wins.
    var live = st && st.session && st.session.state === "running" && st.session.session_token && isJoined();   // routed to only after the health checks passed and the user joined
    if (live) {
      var base = st.relay_url ? httpBase(st.relay_url) : LOCAL_TUNNEL;
      if (!vboost || vboost.token !== st.session.session_token || vboost.relay_url !== base) {
        vboost = { id: SESSION_ID, name: "Codespace mesh", session: true, relay_url: base, token: st.session.session_token, base: base };
        delete state[SESSION_ID]; pollOne(vboost);
      }
    } else if (vboost) { vboost = null; delete state[SESSION_ID]; }
    var now = JSON.stringify(sess && { s: sess.session && sess.session.state, e: sess.error && sess.error.code, n: sess.ended_note });
    if (prev !== now) emit("vyomi-mesh-session", { session: sess });
    var rs = st && st.session && st.session.state === "running" && st.session.session_token;
    if (rs && !isJoined() && canReattach(st.session)) {                   // already joined earlier + keep-alive: reattach quietly, no health-check dialog
      reattach();
    } else if (rs && chk.sid !== st.session.id && !isJoined()) {                  // Mesh just came up: verify it, and show the user
      runChecks();
    } else if (!rs && chk.state !== "idle") { chkRun++; chk = { sid: 0, state: "idle", items: [], at: 0 }; var m = document.getElementById("vyb-chk"); if (m && !lastFail) m.remove(); emit("vyomi-mesh-checks", checks()); }
    ensureHeartbeat();
    render();
  }
  // ── Keep-alive reattach: the Mesh outlives the tab (portal keeps it for the whole 8 h). A refresh, reopened tab or another device has no
  // sessionStorage "joined" flag, but the portal remembers the session was joined. Reattaching = tunnel up + Mesh answers through it; that is all,
  // never the full health-check run (which stops a Mesh whose tunnel is merely down). Retries every 5 s until it works or the TTL ends it.
  var reBusy = false, reTimer = null;
  function canReattach(ss) { return !!(ss && ss.joined && ss.keep_alive !== false && ss.state === "running" && ss.session_token); }
  function reattach() {
    if (reBusy) return; reBusy = true;
    var ss = sess && sess.session, sid = ss && ss.id;
    function done(ok) {
      reBusy = false;
      if (ok) { setJoined(true); applySession(sess); emit("vyomi-mesh-checks", checks()); return; }
      clearTimeout(reTimer); reTimer = setTimeout(function () { var cur = sess && sess.session; if (cur && cur.id === sid && !isJoined() && canReattach(cur)) reattach(); }, 5000);
    }
    checkTunnel().then(function (t) {
      if (!t.up) return done(false);
      var ctl = new AbortController(), tm = setTimeout(function () { ctl.abort(); }, 8000);
      return realFetch(meshBase() + "/mesh/status", { headers: { "x-vyomi-session-token": ss.session_token }, cache: "no-store", signal: ctl.signal })
        .then(function (r) { clearTimeout(tm); done(r.ok); }, function () { clearTimeout(tm); done(false); });
    }).catch(function () { done(false); });
  }
  function setKeepAlive(on) { return portalApi("keep-alive", "POST", { enabled: !!on }).then(function (r) { return loadSession().then(function () { return r; }); }); }
  // Back in the tab (or the laptop woke): refresh the timer and heartbeat now instead of waiting for the next throttled tick.
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible" && sess && sess.active) { loadSession(); portalApi("heartbeat", "POST"); } });
  function loadSession() {
    return realFetch("/api/mesh/status", { credentials: "same-origin", headers: { accept: "application/json" }, cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { applySession(j && typeof j.entitled === "boolean" && j.entitled ? j : null); }, function () { applySession(null); });
  }
  function sessionTick() { if (sess && sess.session && sess.session.countdown_seconds > 0) { sess.session.countdown_seconds -= 1; renderChip(); } }
  function fmtLeft(s) { s = Math.max(0, s | 0); return Math.floor(s / 3600) + "h " + String(Math.floor(s % 3600 / 60)).padStart(2, "0") + "m"; }
  var ACTION_TEXT = { reconnect: "Reconnect GitHub", copy_repo: "Fix on dashboard", choose_cloud: "Choose your cloud", upgrade: "See plans", wait: "Open dashboard", retry: "Open dashboard", contact: "Contact support", restart: "Open dashboard" };
  // The mesh's own status carries ai:{state, chip, usage:{totals}}: show the model state + this session's request/token tally.
  function aiChip(st) {
    var ai = st && st.ai; if (!ai) return "";
    if (typeof ai.chip === "string" && ai.chip) return ai.chip;
    var t = ai.usage && ai.usage.totals; return t ? "AI: " + t.requests + " req · " + t.total_tokens + " tok" : "";
  }
  function renderChip() {
    if (!document.body) return;
    if (!sess || document.querySelector('script[src*="mesh-widget"]')) { kill("vyb-chip"); return; }   // the console widget shows this state
    var x = sess.session, st = x && x.state, err = (st === "failed" && x.error) ? x.error : sess.error, link = stateOf(SESSION_ID);
    var text, cls = "vyb-c-off", action = "";
    if (st === "running") {
      cls = link === "connected" ? "vyb-c-ok" : "vyb-c-warn";
      text = "Mesh " + (link === "connected" ? "connected" : "linking…") + " · ends in " + fmtLeft(x.countdown_seconds) + (x.warning ? " · " + x.warning : "");
      var aiText = aiChip(link === "connected" ? (state[SESSION_ID] || {}).status : null); if (aiText) text += " · " + aiText;
    } else if (st === "pending" || st === "starting") { cls = "vyb-c-warn"; text = "Mesh starting… (about 2 minutes)"; }
    else if (st === "stopping") { cls = "vyb-c-warn"; text = "Mesh stopping…"; }
    else if (err) { cls = "vyb-c-err"; text = "Mesh: could not start"; action = err.action || "retry"; }
    else if (st === "ended" && sess.ended_note) { text = sess.ended_note; action = "restart"; }
    else { text = "Mesh off · " + (sess.hours_remaining != null ? sess.hours_remaining + " h left this month" : "start it from your dashboard"); action = "restart"; }
    var dismissible = !!action && st !== "running" && st !== "pending" && st !== "starting" && st !== "stopping", dkey = "vyb-dismissed";
    try { if (dismissible && sessionStorage.getItem(dkey) === text) { kill("vyb-chip"); return; } if (!dismissible) sessionStorage.removeItem(dkey); } catch (_) {}
    var c = el("vyb-chip", "vyb-chip " + cls); c.className = "vyb-chip " + cls; c.setAttribute("role", "status"); c.setAttribute("data-state", st || "off"); c.setAttribute("data-link", link);
    c.innerHTML = "<span>" + esc(text) + "</span>" + (action ? "<a data-vyb-keep href='/dashboard#mesh-session' target='_blank' rel='noopener'>" + esc(ACTION_TEXT[action] || "Open dashboard") + "</a>" : "") + (dismissible ? "<button type='button' data-vyb-keep data-vyb-close aria-label='Dismiss' style='margin-left:10px;background:none;border:0;color:inherit;font-size:16px;cursor:pointer;line-height:1'>\u00d7</button>" : "");
    var xb = c.querySelector("[data-vyb-close]"); if (xb) xb.onclick = function (ev) { ev.preventDefault(); ev.stopPropagation(); try { sessionStorage.setItem(dkey, text); } catch (_) {} kill("vyb-chip"); };
  }

  // ── pairing ─────────────────────────────────────────────────────────
  // addr: a mesh id ("bst-ab12"), or an https/http URL (relay / LAN / loopback). code: from `vyomi mesh pair`.
  function pair(addr, code) {
    addr = String(addr || "").trim(); code = String(code || "").trim();
    if (!code) return Promise.reject(new Error("Enter the pairing code."));
    var b = { id: "", name: "", paired_at: Date.now() };
    if (/^https?:\/\//i.test(addr)) { b.relay_url = addr.replace(/\/+$/, ""); b.id = addr.replace(/^https?:\/\//i, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 40); try { var u = new URL(addr); if (/^(127\.0\.0\.1|localhost)$/.test(u.hostname)) { b.port = u.port || "80"; delete b.relay_url; } } catch (_) {} }
    else if (addr) b.id = addr.toLowerCase();
    else return Promise.reject(new Error("Enter the mesh id or address."));
    var cs = candidates(b), i = 0, lastErr = "no candidate reachable";
    function next() {
      if (i >= cs.length) return Promise.reject(new Error("Could not reach the mesh (" + lastErr + ")."));
      var base = cs[i++];
      return timed(base + "/mesh/pair/complete", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code: code }) }).then(function (r) {
        if (r.status === 400 || r.status === 401 || r.status === 403 || r.status === 404 || r.status === 410) return r.text().then(function (t) { throw new Error("Pairing refused (" + r.status + "): check the code. " + t.slice(0, 120)); });
        if (!r.ok) { lastErr = "HTTP " + r.status; return next(); }
        return r.json().then(function (j) { if (!j || !j.token) throw new Error("Mesh returned no token."); return { base: base, token: j.token, relay_url: j.relay_url || null, local_url: j.local_url || null }; });
      }, function (e) { if (e && /refused/.test(e.message || "")) throw e; lastErr = String((e && e.message) || e); return next(); });
    }
    return next().then(function (res) {
      b.token = res.token; b.base = res.base;
      if (res.local_url) b.local_url = String(res.local_url).replace(/\/+$/, "");
      if (res.relay_url) b.relay_url = String(res.relay_url).replace(/\/+$/, "");
      return timed(res.base + "/mesh/status", { headers: { Authorization: "Bearer " + res.token } }).then(function (r) { return r.ok ? r.json() : {}; }, function () { return {}; }).then(function (st) {
        b.name = st.hostname || b.id; if (!b.id) b.id = String(st.hostname || "mesh").toLowerCase();
        var all = load().filter(function (x) { return x.id !== b.id; }); all.push(b); save(all);
        setState(b.id, { state: "connected", status: st, base: res.base, fails: 0 });
        return Object.assign({}, b, { token: undefined });
      });
    });
  }
  function unpair(id) { save(load().filter(function (b) { return b.id !== id; })); delete state[id]; render(); }

  // ── active space + home ─────────────────────────────────────────────
  var active = (function () { try { return JSON.parse(localStorage.getItem(LS_ACTIVE) || "null"); } catch (_) { return null; } })();
  function setActive(space) {
    if (!space || !space.space_id) return;
    active = { space_id: space.space_id, home: space.home || null };
    try { localStorage.setItem(LS_ACTIVE, JSON.stringify(active)); } catch (_) {}
    render();
  }
  function homeOf(space) { return space && space.home && space.home.type === "mesh" ? space.home : null; }
  function activeHome() { return homeOf(active); }
  function refreshActive() {
    return realFetch(NANO_BASE + "/api/spaces/active").then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { if (d && d.space) setActive(d.space); }).catch(function () {});
  }

  // ── fetch hook: route mesh-homed /_wire, block when down/locked ──
  function blocked() {   // -> reason string | null, for the active mesh-homed space
    var h = activeHome(); if (!h) return null;
    var st = stateOf(h.mesh_id);
    if (st === "unreachable" || st === "unauthorized") return "unreachable";
    if (isLocked(h.mesh_id)) return "locked";
    return null;
  }
  function daysLeft(id) { var s = (state[id] || {}).status; return s && typeof s.trial_days_left === "number" ? s.trial_days_left : null; }
  function isLocked(id) { if (account && account.locked) return true; var s = (state[id] || {}).status; var d = daysLeft(id); return !!(s && (s.locked === true || (d !== null && d <= 0))); }
  function refuse(reason) {
    var code = reason === "locked" ? "MeshTrialExpired" : "DatacenterUnreachable";
    return new Response(JSON.stringify({ error: { code: code, message: reason === "locked" ? "The mesh trial has ended; mesh-homed spaces are locked." : "Datacenter unreachable: this space lives on a mesh that cannot be reached right now." } }),
      { status: 503, headers: { "content-type": "application/json", "retry-after": "5" } });
  }
  window.fetch = function (input, init) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || String(input);
      var u = new URL(url, location.href), wi = u.pathname.indexOf("/_wire/");
      var isWire = u.origin === location.origin && (wi >= 0 || /\/_wire$/.test(u.pathname));
      var sh = null;   // portal session: compute/AI calls of ANY space go to the running Codespace mesh; emulators stay in the browser
      if (isWire && !activeHome() && vboost) {
        var hd = new Headers((init && init.headers) || (typeof input !== "string" && input && input.headers) || {});
        if (isComputeCall(u.pathname.slice(wi >= 0 ? wi + 6 : 0), hd.get("authorization") || "")) sh = { mesh_id: SESSION_ID, mesh_name: vboost.name };
      }
      if (isWire && (activeHome() || sh)) {
        // Portal-session (Mesh) calls: only refuse on a rejected token. "unreachable" must NOT short-circuit, otherwise one slow
        // start-up answer (> the 2.5 s probe) leaves every later call (card refresh, retry) refused until a hard refresh.
        var h = sh || activeHome(), b = get(h.mesh_id), why = sh ? (stateOf(SESSION_ID) === "unauthorized" ? "unreachable" : null) : blocked();
        if (why) return Promise.resolve(refuse(why));
        if (!b) return Promise.resolve(refuse("unreachable"));
        var base = (state[b.id] || {}).base || b.base || candidates(b)[0];
        var req = typeof input === "string" ? null : input;
        var headers = new Headers((init && init.headers) || (req && req.headers) || {});
        if (b.session) headers.set("x-vyomi-session-token", b.token || "");   // relay plane: the SAME signed token the mesh re-verifies
        else { headers.set("x-vyomi-mesh-token", b.token || ""); if (!headers.has("authorization")) headers.set("authorization", "Bearer " + (b.token || "")); }
        var target = base + u.pathname.slice(wi >= 0 ? wi : u.pathname.indexOf("/_wire")) + u.search;
        var ni = Object.assign({}, init || {}, { headers: headers });
        if (req && !(init && init.method)) { ni.method = req.method; if (!/^(GET|HEAD)$/i.test(req.method)) ni.body = req.body; }
        return realFetch(target, ni).then(function (r) {
          if (sh && r && r.status < 500 && stateOf(b.id) === "unreachable") setState(b.id, { state: "connected", fails: 0 });   // a real answer clears a stale "unreachable"
          return r;
        }).catch(function (e) { setState(b.id, { state: "unreachable", fails: FAILS_TO_DOWN }); return refuse("unreachable"); });
      }
      // learn the active space's home from the SW's own answers
      if (u.origin === location.origin && /\/api\/spaces(\/active)?$/.test(u.pathname)) {
        var m = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
        if (m === "POST" && /\/api\/spaces$/.test(u.pathname) || m === "GET" && /\/api\/spaces\/active$/.test(u.pathname))
          return realFetch(input, init).then(function (r) { try { r.clone().json().then(function (d) { if (d && d.space) setActive(d.space); }).catch(function () {}); } catch (_) {} return r; });
      }
    } catch (_) {}
    return realFetch(input, init);
  };

  // ── UI: banner / lock screen (consoles only) ────────────────────────
  var CSS = ".vyb-bar{position:fixed;top:0;left:0;right:0;z-index:2147483000;padding:9px 16px;font:600 13px/1.4 system-ui,sans-serif;display:flex;gap:10px;align-items:center;justify-content:center;color:#fff}" +
    ".vyb-down{background:#b91c1c}.vyb-warn{background:#b45309}.vyb-bar button{margin-left:8px;font:inherit;padding:2px 10px;border-radius:4px;border:1px solid #fff8;background:#0003;color:#fff;cursor:pointer}" +
    "body.vy-mesh-down #root button:not([data-vyb-keep]),body.vy-mesh-down #root input,body.vy-mesh-down #root select,body.vy-mesh-down #root textarea,body.vy-mesh-down #root [role=button]{pointer-events:none!important;opacity:.55}" +
    "body.vyb-legacy.vy-mesh-down>*:not(.vyb-bar):not(.vyb-lock):not(script):not(style){pointer-events:none!important;opacity:.55}" +
    ".vyb-lock{position:fixed;inset:0;z-index:2147483001;background:#0f172a;color:#e5e7eb;display:flex;align-items:center;justify-content:center;font:15px/1.5 system-ui,sans-serif;text-align:center;padding:24px}" +
    ".vyb-lock h2{margin:0 0 8px;font-size:22px}.vyb-lock a,.vyb-lock button{margin-top:14px;display:inline-block;background:#2563eb;color:#fff;padding:8px 16px;border-radius:6px;border:0;text-decoration:none;font:inherit;cursor:pointer}" +
    ".vyb-chip{position:fixed;left:12px;bottom:12px;z-index:2147482999;max-width:min(560px,92vw);padding:7px 12px;border-radius:8px;font:600 12px/1.4 system-ui,sans-serif;display:flex;gap:10px;align-items:center;color:#fff;box-shadow:0 4px 14px #0004}.vyb-chip a{color:#fff;text-decoration:underline;white-space:nowrap}" +
    ".vyb-c-ok{background:#047857}.vyb-c-warn{background:#b45309}.vyb-c-err{background:#b91c1c}.vyb-c-off{background:#334155}" +
    ".vyb-badge{display:inline-block;font:600 11px/1 system-ui,sans-serif;padding:3px 7px;border-radius:9px;background:#1e3a8a22;color:#2563eb;border:1px solid #2563eb55;margin-left:6px;vertical-align:middle}" +
    ".vyb-badge.vyb-b-down{background:#b91c1c22;color:#b91c1c;border-color:#b91c1c55}" +
    ".vyb-modal{position:fixed;inset:0;z-index:2147483002;background:#0008;display:flex;align-items:center;justify-content:center;font:14px/1.45 system-ui,sans-serif}" +
    ".vyb-card{background:#fff;color:#111827;border-radius:10px;padding:20px;width:min(460px,92vw);box-shadow:0 20px 50px #0006}.vyb-card h3{margin:0 0 4px}.vyb-card label{display:block;margin:10px 0 3px;font-weight:600}" +
    ".vyb-card input{width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid #9ca3af;border-radius:6px;font:inherit}.vyb-card .vyb-err{color:#b91c1c;margin-top:8px;min-height:1em}.vyb-card .vyb-row{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}" +
    ".vyb-card button{padding:6px 14px;border-radius:6px;border:1px solid #9ca3af;background:#f3f4f6;cursor:pointer;font:inherit}.vyb-card button.vyb-primary{background:#2563eb;color:#fff;border-color:#2563eb}.vyb-card ul{padding:0;margin:10px 0;list-style:none}.vyb-card li{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #e5e7eb}";
  function ensureStyle() { if (document.getElementById("vyb-style")) return; var s = document.createElement("style"); s.id = "vyb-style"; s.textContent = CSS; (document.head || document.documentElement).appendChild(s); }
  function el(id, cls) { var e = document.getElementById(id); if (!e) { e = document.createElement("div"); e.id = id; e.className = cls; (document.body || document.documentElement).appendChild(e); } return e; }
  function kill(id) { var e = document.getElementById(id); if (e) e.remove(); }
  function render() {
    if (!document.body) return;
    ensureStyle(); renderChip();
    var h = IS_CONSOLE ? activeHome() : null, why = h ? blocked() : null, name = h ? (h.mesh_name || h.mesh_id) : "";
    document.body.classList.toggle("vy-mesh-down", !!why);
    document.body.classList.toggle("vyb-legacy", !document.getElementById("root"));
    if (why === "unreachable") {
      var st = stateOf(h.mesh_id), bar = el("vyb-banner", "vyb-bar vyb-down");
      bar.setAttribute("role", "alert"); bar.setAttribute("data-state", st);
      bar.innerHTML = "<span>Datacenter unreachable</span><span style='font-weight:400'>" + esc(name) + (st === "unauthorized" ? " rejected this browser's pairing; pair it again." : " is not responding. Read-only until it reconnects; retrying automatically.") + "</span><button data-vyb-keep type='button' id='vyb-retry'>Retry now</button>";
      var rb = document.getElementById("vyb-retry"); if (rb) rb.onclick = function () { pollAll(); };
    } else if (h && !why) {
      var d = daysLeft(h.mesh_id);
      if (d !== null && d > 0 && d <= TRIAL_WARN_DAYS) {
        var w = el("vyb-banner", "vyb-bar vyb-warn"); w.setAttribute("data-state", "trial-warning");
        w.textContent = "Mesh trial ends in " + d + (d === 1 ? " day" : " days") + ". Mesh-homed spaces lock after that; upgrade to Pro/Max to keep them.";
      } else kill("vyb-banner");
    } else kill("vyb-banner");
    if (why === "locked") {
      var l = el("vyb-lock", "vyb-lock"); l.setAttribute("role", "alertdialog");
      l.innerHTML = "<div><h2>Mesh trial ended</h2><div>This space lives on <b>" + esc(name) + "</b> and is locked. Your data is kept and unlocks with a valid Pro or Max entitlement.<br>Browser-homed spaces keep working.</div><a data-vyb-keep href='" + NANO_BASE + "/clouds.html'>Back to spaces</a></div>";
    } else kill("vyb-lock");
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  // ── UI: home badge (space cards), home picker, pairing dialog ───────
  function badgeHtml(space) {
    var h = homeOf(space);
    if (!h) return '<span class="vyb-badge" data-home="browser" title="Runs in this browser">This browser</span>';
    var down = stateOf(h.mesh_id) !== "connected" && stateOf(h.mesh_id) !== "unknown";
    return '<span class="vyb-badge' + (down ? " vyb-b-down" : "") + '" data-home="mesh" data-mesh="' + esc(h.mesh_id) + '" title="' + (down ? "Datacenter unreachable" : "Runs on the mesh") + '">Mesh: ' + esc(h.mesh_name || h.mesh_id) + (down ? " (unreachable)" : "") + "</span>";
  }
  function homeOptions() { return meshOn() ? load().map(function (b) { return { id: b.id, name: b.name || b.id }; }) : []; }
  // The id the create-space picker should preselect: the mesh when the account has it enabled (backend), else the browser.
  function defaultHome() { var o = homeOptions(); return (account && account.effective && o.length) ? o[0].id : "browser"; }
  function homePayload(selectValue) {   // select value "" | "browser" -> undefined, else mesh id -> home record
    if (!selectValue || selectValue === "browser") return undefined;
    var b = get(selectValue); return b ? { type: "mesh", mesh_id: b.id, mesh_name: b.name || b.id } : undefined;
  }
  function openPairDialog() {
    ensureStyle();
    var m = document.createElement("div"); m.className = "vyb-modal"; m.id = "vyb-pair";
    function paint(err) {
      var acc = account, accLine = acc ? ("<div id='vyb-acc' style='margin:8px 0;padding:8px;border:1px solid #d1d5db;border-radius:8px'>Mesh: <b>" + (acc.effective ? "on" : acc.locked ? "locked (trial ended)" : "off") + "</b>" + (acc.status === "trial" && acc.days_left != null ? " &middot; trial, " + acc.days_left + " day(s) left" : acc.status === "active" ? " &middot; " + esc(acc.tier || "plan") : "") + " <button type='button' id='vyb-acc-btn'>" + (acc.enabled ? "Turn off" : "Turn on") + "</button></div>") : "";
      m.innerHTML = "<div class='vyb-card' role='dialog' aria-labelledby='vyb-t'><h3 id='vyb-t'>Meshs</h3>" + accLine + "<div style='color:#4b5563'>Pair a mesh (a Pro/Max appliance) to host spaces on your own machine. Run <code>vyomi mesh pair</code> there to get a code.</div>" +
        "<ul>" + load().map(function (b) { return "<li><span>" + esc(b.name || b.id) + " <span class='vyb-badge' data-vyb-state='" + esc(b.id) + "'>" + esc(stateOf(b.id)) + "</span></span><button type='button' data-unpair='" + esc(b.id) + "'>Unpair</button></li>"; }).join("") + "</ul>" +
        "<label for='vyb-addr'>Mesh id or address</label><input id='vyb-addr' placeholder='bst-ab12 or http://127.0.0.1:8765' autocomplete='off'>" +
        "<label for='vyb-code'>Pairing code</label><input id='vyb-code' placeholder='e.g. 482913' autocomplete='off'>" +
        "<div class='vyb-err' id='vyb-err'>" + esc(err || "") + "</div><div class='vyb-row'><button type='button' id='vyb-close'>Close</button><button type='button' class='vyb-primary' id='vyb-go'>Pair</button></div></div>";
      m.querySelector("#vyb-close").onclick = function () { m.remove(); };
      var ab = m.querySelector("#vyb-acc-btn");
      if (ab) ab.onclick = function () { ab.disabled = true; setMesh(!(account && account.enabled)).then(function () { paint(""); }, function (e) { paint(String(e.message || e)); }); };
      m.querySelector("#vyb-go").onclick = function () {
        var btn = this; btn.disabled = true; btn.textContent = "Pairing...";
        pair(m.querySelector("#vyb-addr").value, m.querySelector("#vyb-code").value).then(function () { paint(""); }, function (e) { paint(String(e.message || e)); });
      };
      Array.prototype.forEach.call(m.querySelectorAll("[data-unpair]"), function (b) { b.onclick = function () { unpair(b.getAttribute("data-unpair")); paint(""); }; });
    }
    paint(""); (document.body || document.documentElement).appendChild(m);
    return m;
  }

  // ── interactive shell into a Docker VM on the Codespace mesh (relay stream path; see wasm/relay/mesh-hub.mjs) ─────────────
  // shellTarget: is this instance a VM on the running mesh that can be shelled into?  openShell: attach a terminal to it.
  // Uses the portal-session mesh only (the relay plane); paired direct meshs have no stream path.
  function shellMesh() { return vboost && vboost.token ? vboost : null; }
  function shellTarget(cloud, ref) {   // -> Promise<{ok, container} | {ok:false, code, reason, down?, none?}>
    var b = shellMesh();
    if (!b) return Promise.resolve({ ok: false, none: true, code: "NoMesh", reason: "no mesh session is running" });
    var st = stateOf(SESSION_ID);
    if (st === "unreachable" || st === "unauthorized") return Promise.resolve({ ok: false, down: true, code: "MeshDown", reason: "The Codespace mesh is not reachable right now." });
    var base = (state[SESSION_ID] || {}).base || b.base;
    return timed(base + "/mesh/shell/target?cloud=" + encodeURIComponent(cloud) + "&ref=" + encodeURIComponent(ref), { headers: { "x-vyomi-session-token": b.token } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 502 || r.status === 504) return { ok: false, down: true, code: "MeshDown", reason: "The Codespace mesh is not reachable right now." };
        if (r.status === 404) return { ok: false, none: true, code: "NoShellSupport", reason: "this mesh has no shell support (update the mesh image)" };
        if (j && j.error) return { ok: false, down: r.status >= 500, code: j.error.code || "Error", reason: j.error.reason || j.error.message || "refused" };
        return j && typeof j.ok === "boolean" ? j : { ok: false, code: "BadAnswer", reason: "unexpected answer from the mesh" };
      }); }, function () { return { ok: false, down: true, code: "MeshDown", reason: "The Codespace mesh is not reachable right now." }; });
  }
  // opts: {cols, rows, onOpen(container), onData(Uint8Array), onClose({code, reason, message})}. Returns {send(str|Uint8Array), resize(c, r), close(), state()}.
  function openShell(cloud, ref, opts) {
    opts = opts || {};
    var b = shellMesh(), enc = new TextEncoder(), ws = null, done = false, open = false;
    function end(info) { if (done) return; done = true; try { opts.onClose && opts.onClose(info); } catch (_) {} }
    if (!b) { setTimeout(function () { end({ code: "NoMesh", message: "no mesh session is running" }); }, 0); return { send: function () {}, resize: function () {}, close: function () {}, state: function () { return "closed"; } }; }
    var url = ((state[SESSION_ID] || {}).base || b.base).replace(/^http/i, "ws") + "/shell";
    try { ws = new WebSocket(url); } catch (e) { setTimeout(function () { end({ code: "MeshDown", message: String(e && e.message || e) }); }, 0); return { send: function () {}, resize: function () {}, close: function () {}, state: function () { return "closed"; } }; }
    ws.binaryType = "arraybuffer";
    var err = null;
    ws.onopen = function () { ws.send(JSON.stringify({ type: "auth", token: b.token, cloud: cloud, ref: ref, cols: opts.cols || 110, rows: opts.rows || 22 })); };
    ws.onmessage = function (e) {
      if (typeof e.data !== "string") { try { opts.onData && opts.onData(new Uint8Array(e.data)); } catch (_) {} return; }
      var c; try { c = JSON.parse(e.data); } catch (_) { return; }
      if (c.t === "opened") { open = true; try { opts.onOpen && opts.onOpen(c.container); } catch (_) {} }
      else if (c.t === "error") err = c;
    };
    ws.onclose = function (e) { end({ code: (err && err.code) || (open ? "Closed" : "MeshDown"), message: (err && err.message) || (open ? "" : "could not reach the mesh"), wsCode: e.code, wasOpen: open }); };
    ws.onerror = function () {};
    return {
      send: function (d) { if (ws.readyState === 1 && open) ws.send(typeof d === "string" ? enc.encode(d) : d); },
      resize: function (c, r) { if (ws.readyState === 1 && open) ws.send(JSON.stringify({ t: "resize", cols: c, rows: r })); },
      close: function () { try { if (ws.readyState === 1) ws.send(JSON.stringify({ t: "close" })); ws.close(); } catch (_) {} },
      state: function () { return done ? "closed" : open ? "open" : "connecting"; },
    };
  }
  function sessionLive() { return !!shellMesh(); }

  // ── Start / Stop from the console (same portal API the legacy dashboard card used) ──────────────────────────────────────────
  var hbTimer = null;
  function portalApi(path, method, body) {
    return realFetch("/api/mesh/" + path, { method: method || "GET", credentials: "same-origin", headers: body ? { accept: "application/json", "content-type": "application/json" } : { accept: "application/json" }, body: body ? JSON.stringify(body) : undefined, cache: "no-store" })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j || {} }; }); });
  }
  function ensureHeartbeat() {            // the portal ends a session whose Vyomi tab has been closed for 5 minutes: the open console is that tab
    var on = !!(sess && sess.active);
    if (on && !hbTimer) hbTimer = setInterval(function () { if (sess && sess.active) portalApi("heartbeat", "POST"); else ensureHeartbeat(); }, 60000);
    else if (!on && hbTimer) { clearInterval(hbTimer); hbTimer = null; }
  }
  // Terms dialog, themed per console: AWS Cloudscape modal · GCP Material 3 dialog · Azure Fluent 2 dialog.
  function cloudOf() { var m = /\/v4\/(aws|gcp|azure)\b/.exec(location.pathname) || /(aws|gcp|azure)-console/.exec(location.pathname); return m ? m[1] : "aws"; }
  function dialogCss() {
    if (document.getElementById("vyb-tm-css")) return;
    var st = document.createElement("style"); st.id = "vyb-tm-css";
    st.textContent = ".vyb-tm-o{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center}"
      + ".vyb-tm{box-sizing:border-box;width:min(520px,92vw);max-height:90vh;overflow:auto;background:#fff;position:relative}"
      + ".vyb-tm h3{margin:0}.vyb-tm .tm-x{position:absolute;top:14px;right:14px;border:0;background:none;cursor:pointer;font-size:18px;line-height:1;color:#5f6b7a}"
      + ".vyb-tm p{margin:0 0 12px;line-height:1.5}.vyb-tm .tm-f{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}.vyb-tm .tm-fine{font-size:12px}"
      + ".vyb-tm button.tm{cursor:pointer;font:inherit}"
      // AWS · Cloudscape
      + ".vyb-tm-o[data-cloud=aws]{background:rgba(35,47,62,.6)}"
      + ".vyb-tm[data-cloud=aws]{font-family:'Amazon Ember','Open Sans','Helvetica Neue',Roboto,Arial,sans-serif;color:#0f141a;border-radius:8px;box-shadow:0 4px 20px 1px rgba(0,28,36,.5);padding:0;font-size:14px}"
      + ".vyb-tm[data-cloud=aws] .tm-h{padding:20px 52px 14px 24px;border-bottom:1px solid #e9ebed}.vyb-tm[data-cloud=aws] h3{font-size:22px;font-weight:700}"
      + ".vyb-tm[data-cloud=aws] .tm-b{padding:18px 24px 0}.vyb-tm[data-cloud=aws] .tm-f{margin:0;padding:16px 24px 20px;border-top:0}"
      + ".vyb-tm[data-cloud=aws] .tm-fine{color:#5f6b7a}.vyb-tm[data-cloud=aws] a{color:#0972d3}"
      + ".vyb-tm[data-cloud=aws] .tm-no{border:2px solid #0972d3;background:#fff;color:#0972d3;border-radius:20px;padding:4px 18px;font-weight:700}"
      + ".vyb-tm[data-cloud=aws] .tm-go{border:2px solid #ff9900;background:#ff9900;color:#0f141a;border-radius:20px;padding:4px 20px;font-weight:700}"
      // GCP · Material 3
      + ".vyb-tm-o[data-cloud=gcp]{background:rgba(32,33,36,.5)}"
      + ".vyb-tm[data-cloud=gcp]{font-family:'Google Sans',Roboto,Arial,sans-serif;color:#1f1f1f;border-radius:28px;box-shadow:0 8px 24px rgba(0,0,0,.28);padding:24px 24px 20px;font-size:14px}"
      + ".vyb-tm[data-cloud=gcp] h3{font-size:24px;font-weight:400;margin-bottom:16px}.vyb-tm[data-cloud=gcp] .tm-h{padding:0}.vyb-tm[data-cloud=gcp] .tm-x{display:none}"
      + ".vyb-tm[data-cloud=gcp] p{color:#444746}.vyb-tm[data-cloud=gcp] .tm-fine{color:#5f6368}.vyb-tm[data-cloud=gcp] a{color:#0b57d0}"
      + ".vyb-tm[data-cloud=gcp] .tm-no{border:0;background:none;color:#0b57d0;font-weight:500;padding:10px 16px;border-radius:20px}"
      + ".vyb-tm[data-cloud=gcp] .tm-go{border:0;background:#0b57d0;color:#fff;font-weight:500;padding:10px 24px;border-radius:20px}"
      // Azure · Fluent 2
      + ".vyb-tm-o[data-cloud=azure]{background:rgba(0,0,0,.4)}"
      + ".vyb-tm[data-cloud=azure]{font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,sans-serif;color:#242424;border-radius:8px;box-shadow:0 32px 64px rgba(0,0,0,.24),0 0 8px rgba(0,0,0,.2);padding:24px;font-size:14px}"
      + ".vyb-tm[data-cloud=azure] h3{font-size:20px;font-weight:600;margin-bottom:12px}.vyb-tm[data-cloud=azure] .tm-h{padding:0}"
      + ".vyb-tm[data-cloud=azure] p{color:#424242}.vyb-tm[data-cloud=azure] .tm-fine{color:#616161}.vyb-tm[data-cloud=azure] a{color:#0f6cbd}"
      + ".vyb-tm[data-cloud=azure] .tm-no{border:1px solid #d1d1d1;background:#fff;color:#242424;font-weight:600;padding:5px 16px;border-radius:4px}"
      + ".vyb-tm[data-cloud=azure] .tm-go{border:1px solid #0f6cbd;background:#0f6cbd;color:#fff;font-weight:600;padding:5px 16px;border-radius:4px}";
    document.head.appendChild(st);
  }
  function termsModal() {                 // JS modal; resolves true on "Agree & start"
    return new Promise(function (res) {
      dialogCss(); var c = cloudOf();
      var o = document.createElement("div"); o.className = "vyb-tm-o"; o.setAttribute("data-cloud", c); o.setAttribute("data-vyb-keep", "1");
      o.innerHTML = '<div class="vyb-tm" data-cloud="' + c + '" role="dialog" aria-modal="true" aria-labelledby="vyb-tm-t">'
        + '<button type="button" class="tm-x" data-no aria-label="Close">\u2715</button>'
        + '<div class="tm-h"><h3 id="vyb-tm-t">Join the Vyomi Global Mesh</h3></div><div class="tm-b">'
        + '<p>Vyomi Global Mesh operates on a <b>BYOC (Bring Your Own Cloud)</b> model, using the free GitHub quota associated with <b>your own account</b> at <b>no cost</b>.</p>'
        + '<p>The Mesh will <b>stop once your free quota is exhausted</b>, unless you choose to continue and your GitHub account is linked to a Pro plan or a payment method.</p>'
        + '<p class="tm-fine">Vyomi acts solely as the custodian of your free quota. All data inside the Mesh is deleted when it stops or reaches the 8-hour limit. <a href="/terms#mesh" target="_blank" rel="noopener">Mesh terms</a></p></div>'
        + '<div class="tm-f"><button type="button" class="tm tm-no" data-no>Cancel</button><button type="button" class="tm tm-go" data-go>Agree &amp; start</button></div></div>';
      function done(v) { document.removeEventListener("keydown", key, true); o.remove(); res(v); }
      function key(e) { if (e.key === "Escape") { e.stopPropagation(); done(false); } }
      o.addEventListener("click", function (e) { if (e.target === o) done(false); });
      o.querySelectorAll("[data-no]").forEach(function (n) { n.onclick = function () { done(false); }; });
      o.querySelector("[data-go]").onclick = function () { done(true); };
      document.addEventListener("keydown", key, true); document.body.appendChild(o); o.querySelector("[data-go]").focus();
    });
  }
  function connectModal(reauth) {
    if (window.VyomiMeshWidget && document.getElementById("vy-bw")) { window.VyomiMeshWidget.show("connect"); return; }         // JS modal: explain + send to GitHub (works for Google/LinkedIn logins: the link is stored against the Vyomi account)
    var o = document.createElement("div"); o.setAttribute("data-vyb-keep", "1");
    o.style.cssText = "position:fixed;inset:0;z-index:2147483000;background:rgba(10,14,25,.55);display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,Segoe UI,sans-serif";
    o.innerHTML = '<div role="dialog" aria-modal="true" style="background:#fff;color:#101828;width:min(440px,92vw);border-radius:14px;box-shadow:0 24px 60px rgba(0,0,0,.35);padding:24px">'
      + '<h3 style="margin:0 0 10px;font-size:19px">' + (reauth ? "Reconnect GitHub" : "Connect your GitHub account") + '</h3>'
      + '<p style="margin:0 0 10px;font-size:15px;line-height:1.5">The Mesh runs on the free Codespaces quota of <b>your own GitHub account</b>. Your Vyomi sign-in (Google, LinkedIn or any other) stays the same; we just link GitHub to it.</p>'
      + '<p style="margin:0 0 18px;font-size:13px;line-height:1.5;color:#475467">No GitHub account yet? <a data-new href="https://github.com/signup" target="_blank" rel="noopener" style="color:#2f6fdc">Create a free one</a> (about 2 minutes), then come back and click Connect GitHub.</p>'
      + '<div style="display:flex;gap:10px;justify-content:flex-end"><button type="button" data-no style="padding:9px 16px;border-radius:8px;border:1px solid #d0d5dd;background:#fff;color:#344054;font-size:14px;cursor:pointer">Cancel</button>'
      + '<button type="button" data-go style="padding:9px 16px;border-radius:8px;border:0;background:#2f6fdc;color:#fff;font-size:14px;font-weight:600;cursor:pointer">Connect GitHub</button></div></div>';
    function done() { document.removeEventListener("keydown", key, true); o.remove(); }
    function key(e) { if (e.key === "Escape") { e.stopPropagation(); done(); } }
    o.addEventListener("click", function (e) { if (e.target === o) done(); });
    o.querySelector("[data-no]").onclick = done;
    o.querySelector("[data-go]").onclick = function () { location.href = "/api/mesh/github/connect" + (reauth ? "?reauth=1" : ""); };
    document.addEventListener("keydown", key, true); document.body.appendChild(o); o.querySelector("[data-go]").focus();
  }
  function termsAgreed() { var W = window.VyomiMeshWidget; if (W) return W.agreed(); try { return localStorage.getItem("vy_mesh_terms") === "1"; } catch (_) { return false; } }
  function termsAccept() { var W = window.VyomiMeshWidget; if (W) W.accept(); else { try { localStorage.setItem("vy_mesh_terms", "1"); } catch (_) {} } }
  function sessionStart(cloud) {
    return checkTunnel().then(function (t) {
      if (!t.up) return { ok: false, j: { action: "tunnel", error: "tunnel_required", message: tunnelBlockMessage() } };
      return sessionStart2(cloud);
    });
  }
  function sessionStart2(cloud) {
    return (termsAgreed() ? Promise.resolve(true) : termsModal()).then(function (ok) {      // terms are a modal dialog, never inline
      if (!ok) return { cancelled: true };
      termsAccept(); lastFail = null;
      return portalApi("start" + (cloud ? "?cloud=" + encodeURIComponent(cloud) : ""), "POST").then(function (r) {
        if (r && r.ok && r.j && r.j.browser_launch) return browserLaunch(r.j.browser_launch).then(function (r2) { return loadSession().then(function () { return r2; }); });
        return loadSession().then(function () { return r; });
      });
    });
  }
  // Browser launch (portal MESH_BROWSER_LAUNCH=1): the portal hands this page the launch; GitHub's create call is made FROM THIS BROWSER (the user's
  // own network), then the codespace name goes back to the portal. The token lives only in this closure and is dropped after the call.
  function browserLaunch(bl) {
    var tries = 0;
    function create() {
      var body = { machine: bl.machine, devcontainer_path: bl.devcontainer_path, idle_timeout_minutes: bl.idle_timeout_minutes, display_name: bl.display_name };
      if (bl.ref) body.ref = bl.ref;
      return realFetch(bl.api + "/repos/" + bl.repo + "/codespaces", {
        method: "POST", headers: { accept: "application/vnd.github+json", authorization: "Bearer " + bl.token, "content-type": "application/json", "x-github-api-version": "2022-11-28" },
        body: JSON.stringify(body) })
        .then(function (g) { return g.json().catch(function () { return {}; }).then(function (j) { return { status: g.status, j: j || {} }; }); },
              function () { return { status: 599, j: { message: "network error" } }; })
        .then(function (g) {
          if (g.status === 429 && tries < 2) { tries++; return new Promise(function (res) { setTimeout(res, 15000); }).then(create); }      // a Codespaces creation throttle: retry twice
          return g;
        });
    }
    return create().then(function (g) {
      bl.token = "";
      if (g.status >= 200 && g.status < 300 && g.j && g.j.name) return portalApi("launched", "POST", { codespace_name: g.j.name });
      return portalApi("launch_failed", "POST", { status: g.status, message: (g.j && g.j.message) || "" });
    });
  }
  function sessionStop() { return portalApi("stop", "POST").then(function (r) { return loadSession().then(function () { return r; }); }); }
  // One error toast for every Mesh surface (widget, app bar, chip): fixed top-right, disappears after 5 seconds.
  var toastEl = null, toastTimer = 0;
  function toast(text) {
    if (!text || !document.body) return;
    if (!document.getElementById("vy-bw-toast-css")) {
      var st = document.createElement("style"); st.id = "vy-bw-toast-css";
      st.textContent = "#vy-bw-toast{position:fixed;top:16px;right:16px;z-index:2147483000;max-width:min(420px,calc(100vw - 32px));padding:12px 16px;border-radius:10px;"
        + "background:#fff;color:#111;border:1px solid #d0d5dd;border-left:4px solid #b42318;box-shadow:0 8px 24px rgba(0,0,0,.18);font:13px/1.45 system-ui,sans-serif;"
        + "opacity:0;transform:translateY(-6px);transition:opacity .2s,transform .2s;pointer-events:none}#vy-bw-toast.on{opacity:1;transform:none}";
      document.head.appendChild(st);
    }
    if (!toastEl) { toastEl = document.createElement("div"); toastEl.id = "vy-bw-toast"; toastEl.setAttribute("role", "alert"); document.body.appendChild(toastEl); }
    toastEl.textContent = String(text);
    toastEl.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("on"); }, 5000);
  }
  window.VyomiMesh = {
    toast: toast, connectModal: connectModal, confirmTerms: function () { return termsAgreed() ? Promise.resolve(true) : termsModal(); }, termsAccept: termsAccept, sessionStart: sessionStart, sessionStop: sessionStop,
    list: list, get: function (id) { var b = get(id); return b && Object.assign({}, b, { token: undefined }); }, pair: pair, unpair: unpair,
    state: function (id) { return stateOf(id); }, status: function (id) { return (state[id] || {}).status || null; },
    pollNow: pollAll, setActive: setActive, refreshActive: refreshActive, activeHome: activeHome,
    homeOptions: homeOptions, defaultHome: defaultHome, cloudAllowed: cloudAllowed, planCloud: planCloud, pinCloud: pinCloud, homePayload: homePayload, account: function () { return account; }, loadAccount: loadAccount, setMesh: setMesh, badgeHtml: badgeHtml, openPairDialog: openPairDialog,
    checks: checks, runChecks: runChecks, joinMesh: joinMesh, openDetails: openDetails, lastFailure: function () { return lastFail && { at: lastFail.at, failed: lastFail.items.filter(function (i) { return i.ok === false && !i.skipped; }).map(function (i) { return i.label; }) }; }, progress: progress, rerunChecks: runChecks, joined: isJoined,
    setKeepAlive: setKeepAlive, tunnel: tunnel, checkTunnel: checkTunnel, tunnelMessage: tunnelBlockMessage, meshActive: meshActive,
    session: function () { return sess; }, sessionMesh: function () { return vboost && Object.assign({}, vboost, { token: undefined }); }, loadSession: loadSession, isComputeCall: isComputeCall, aiChip: aiChip,
    shellTarget: shellTarget, openShell: openShell, sessionLive: sessionLive,
    // apiFetch(path, init): call the mesh's own API (e.g. /api/mesh/models, /v1/chat/completions) with its token. Rejects when no mesh is reachable.
    apiFetch: function (path, init) {
      var b = vboost || load().filter(function (x) { return (state[x.id] || {}).base; })[0];
      if (!b) return Promise.reject(new Error("no mesh"));
      var base = (state[b.id] || {}).base || b.base; if (!base) return Promise.reject(new Error("no mesh"));
      init = Object.assign({}, init); init.headers = Object.assign({ Authorization: "Bearer " + b.token }, init.headers || {});
      return realFetch(base.replace(/\/+$/, "") + path, init);
    },
    isBlocked: blocked, candidates: function (id) { var b = get(id); return b ? candidates(b) : []; },
  };

  function boot() { render(); refreshActive(); start(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
