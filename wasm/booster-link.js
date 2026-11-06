/* Vyomi Nano <-> booster link (booster pack, phase 1; spec: docs/architecture/v4.0/V4-BOOSTER-DESIGN-DISCUSSION.md).
 *
 * A "booster" is a paired Pro/Max appliance that hosts booster-homed spaces. This plain script (no deps) is
 * loaded by clouds.html and by every v4 Nano console (BEFORE nano-boot.js, so its fetch hook is in place).
 *
 *  - registry   : paired boosters in localStorage "vyomi.boosters" [{id,name,token,local_url,relay_url,port,...}]
 *  - connect    : <id>.local.vyomi.cloud (HTTPS) -> relay URL -> loopback http://127.0.0.1:<port> (dev); first that answers wins
 *  - pairing    : POST {base}/booster/pair/complete {code} -> {token}; then GET /booster/status (Authorization: Bearer)
 *  - health     : GET /booster/status every 5 s -> state "connected" | "unreachable" (| "unauthorized"); events on window
 *  - per-space  : space.home = {type:"booster", booster_id, booster_name} | absent (= this browser), fixed at creation
 *  - routing    : for a booster-homed ACTIVE space, same-origin <base>/_wire/* fetches are redirected to the booster
 *                 (browser-homed spaces are never touched)
 *  - blocking   : booster unreachable -> "Datacenter unreachable" banner, wire calls refused, controls disabled,
 *                 auto-retry; trial_days_left <= 7 -> banner; <= 0 -> lock screen. Browser-homed spaces: no effect.
 *
 * Wire auth: the console's SigV4 `authorization` header is the routing signal and must stay intact, so on /_wire
 * the booster token travels in `x-vyomi-booster-token` (+ `Authorization: Bearer` only when the call has none).
 * Public API: window.VyomiBooster. Events (on window): "vyomi-booster-state", "vyomi-booster-registry".
 */
(function () {
  if (window.VyomiBooster) return;
  var LS_REG = "vyomi.boosters", LS_ACTIVE = "vyomi.active_space";
  var SESSION_ID = "vyomi-session", vboost = null;   // the portal-started Codespace booster: in-memory only (its token expires with the session)
  var POLL_MS = (function () { try { var v = Number(localStorage.getItem("vyomi.booster_poll_ms")); if (v >= 100) return v; } catch (_) {} return 5000; })();
  var PROBE_TIMEOUT = 2500, FAILS_TO_DOWN = 2, TRIAL_WARN_DAYS = 7;
  var realFetch = window.fetch.bind(window);
  // Mount path of the Nano bundle (page at <BASE>/clouds.html or <BASE>/v4/<cloud>/).
  var NANO_BASE = location.pathname.replace(/\/v4\/[^/]*\/?[^/]*$/, "").replace(/\/[^/]*$/, "");
  var IS_CONSOLE = /\/v4\/|-console\.html/.test(location.pathname);

  // ── registry ────────────────────────────────────────────────────────
  function stored() { try { var a = JSON.parse(localStorage.getItem(LS_REG) || "[]"); return Array.isArray(a) ? a.filter(function (b) { return b.id !== SESSION_ID; }) : []; } catch (_) { return []; } }
  function load() { var a = stored(); if (vboost) a.push(vboost); return a; }
  function save(a) { a = a.filter(function (b) { return b.id !== SESSION_ID; }); try { localStorage.setItem(LS_REG, JSON.stringify(a)); } catch (_) {} emit("vyomi-booster-registry", { boosters: list() }); }
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
      return timed(base + "/booster/status", { headers: b.session ? { "x-vyomi-session-token": b.token } : b.token ? { Authorization: "Bearer " + b.token } : {} }).then(function (r) {
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
    if (prev.state !== next.state || patch.status) emit("vyomi-booster-state", { id: id, state: next.state, previous: prev.state, status: next.status || null });
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
  // ── account: the portal's per-user booster subscription record (portal DB) ──────────────────────
  // enabled booster -> spaces default to the booster (backend); not enabled -> everything stays in the browser.
  // `null` = the portal can't say (preview / offline / signed out): behave as before (paired boosters stay usable).
  var account = null, accTimer = null;
  var _origFetch = window.fetch.bind(window);
  function accountFetch(method, path) {
    return _origFetch("/api/account/booster" + (path || ""), { method: method || "GET", credentials: "same-origin", headers: { accept: "application/json" } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); });
  }
  function loadAccount() {
    return accountFetch("GET").then(function (r) {
      var was = JSON.stringify(account);
      account = (r.ok && r.body && typeof r.body.enabled === "boolean") ? r.body : null;
      if (JSON.stringify(account) !== was) { try { window.dispatchEvent(new CustomEvent("vyomi-booster-account", { detail: account })); } catch (_) {} render(); }
      return account;
    }, function () { account = null; return null; });
  }
  function setBooster(on) {
    return accountFetch("POST", on ? "/enable" : "/disable").then(function (r) {
      if (r.ok) { account = r.body; try { window.dispatchEvent(new CustomEvent("vyomi-booster-account", { detail: account })); } catch (_) {} render(); return account; }
      var e = new Error((r.body && r.body.message) || "Could not change the booster setting."); e.account = r.body; throw e;
    });
  }
  // Pro = ONE cloud (all services on it); Max / Enterprise = all three. The portal's account record says which applies and
  // (once chosen) which cloud. No record (not signed in / Free) -> not gated here.
  function planCloud() { return account && account.clouds === "one" ? String(account.primary_cloud || "").toLowerCase() : null; }
  function cloudAllowed(c) { if (!account || account.clouds !== "one") return true; var pc = planCloud(); return !pc || String(c).toLowerCase() === pc; }
  function pinCloud(c) {   // first use of a cloud on a Pro plan chooses it; refused once another is chosen
    if (!account || account.clouds !== "one" || planCloud()) return Promise.resolve(cloudAllowed(c));
    return _origFetch("/api/account/booster/primary-cloud", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify({ cloud: c }) })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (r) { if (r.ok) { account = r.body; try { window.dispatchEvent(new CustomEvent("vyomi-booster-account", { detail: account })); } catch (_) {} return true; } if (r.body && r.body.primary_cloud) { account = Object.assign({}, account, { primary_cloud: r.body.primary_cloud }); } return false; }, function () { return true; });
  }
  function boosterOn() { return account === null || account.effective === true; }   // unknown -> don't hide anything
  function start() { if (timer) return; loadSession(); sessTimer = setInterval(loadSession, POLL_MS); setInterval(sessionTick, 1000); loadAccount(); accTimer = setInterval(loadAccount, 60000); pollAll(); timer = setInterval(pollAll, POLL_MS); }


  // ── portal session (the portal-Nano flow: Start/Stop live on the vyomi.cloud dashboard; Nano only shows + uses it) ──────────
  // /api/booster/status -> {session:{state,countdown_seconds,session_token,error},relay_url,error,ended_note,hours_remaining,...}.
  // While the session is running the relay is registered as an in-memory booster and compute/AI wire calls are routed to it.
  var sess = null, sessTimer = null;
  var COMPUTE_SCOPE = /Credential=[^/]+\/[^/]+\/[^/]+\/(ec2|lambda|ecs|eks|batch|lightsail|autoscaling|apprunner|bedrock|bedrock-runtime|bedrock-agent|bedrock-agent-runtime|sagemaker|sagemaker-runtime)\//i;
  var COMPUTE_PATH = /^\/(compute\/v1\/|v1\/projects\/[^/]+\/locations\/[^/]+\/(publishers|endpoints|models)\b|.*\/aiplatform\/)|\/providers\/Microsoft\.(Compute|ContainerService|CognitiveServices|MachineLearningServices|Batch|ContainerInstance)\//i;
  // Heuristic classifier for native-wire calls: EC2/VMs, languages (Lambda/functions), AI. Everything else stays in the browser.
  function isComputeCall(wirePath, authorization) { return COMPUTE_SCOPE.test(authorization || "") || COMPUTE_PATH.test(wirePath || ""); }
  function httpBase(u) { try { var x = new URL(u); x.protocol = x.protocol === "wss:" ? "https:" : x.protocol === "ws:" ? "http:" : x.protocol; x.pathname = ""; x.search = ""; return x.toString().replace(/\/+$/, ""); } catch (_) { return ""; } }
  function applySession(st) {
    var prev = JSON.stringify(sess && { s: sess.session && sess.session.state, e: sess.error && sess.error.code, n: sess.ended_note });
    sess = st;
    var live = st && st.session && st.session.state === "running" && st.relay_url && st.session.session_token;
    if (live) {
      var base = httpBase(st.relay_url);
      if (!vboost || vboost.token !== st.session.session_token || vboost.relay_url !== base) {
        vboost = { id: SESSION_ID, name: "Codespace booster", session: true, relay_url: base, token: st.session.session_token, base: base };
        delete state[SESSION_ID]; pollOne(vboost);
      }
    } else if (vboost) { vboost = null; delete state[SESSION_ID]; }
    var now = JSON.stringify(sess && { s: sess.session && sess.session.state, e: sess.error && sess.error.code, n: sess.ended_note });
    if (prev !== now) emit("vyomi-booster-session", { session: sess });
    render();
  }
  function loadSession() {
    return realFetch("/api/booster/status", { credentials: "same-origin", headers: { accept: "application/json" }, cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { applySession(j && typeof j.entitled === "boolean" && j.entitled ? j : null); }, function () { applySession(null); });
  }
  function sessionTick() { if (sess && sess.session && sess.session.countdown_seconds > 0) { sess.session.countdown_seconds -= 1; renderChip(); } }
  function fmtLeft(s) { s = Math.max(0, s | 0); return Math.floor(s / 3600) + "h " + String(Math.floor(s % 3600 / 60)).padStart(2, "0") + "m"; }
  var ACTION_TEXT = { reconnect: "Reconnect GitHub", copy_repo: "Fix on dashboard", choose_cloud: "Choose your cloud", upgrade: "See plans", wait: "Open dashboard", retry: "Open dashboard", contact: "Contact support", restart: "Open dashboard" };
  function renderChip() {
    if (!document.body) return;
    if (!sess) { kill("vyb-chip"); return; }
    var x = sess.session, st = x && x.state, err = (st === "failed" && x.error) ? x.error : sess.error, link = stateOf(SESSION_ID);
    var text, cls = "vyb-c-off", action = "";
    if (st === "running") {
      cls = link === "connected" ? "vyb-c-ok" : "vyb-c-warn";
      text = "Booster " + (link === "connected" ? "connected" : "linking…") + " · ends in " + fmtLeft(x.countdown_seconds) + (x.warning ? " · " + x.warning : "");
    } else if (st === "pending" || st === "starting") { cls = "vyb-c-warn"; text = "Booster starting… (about 2 minutes)"; }
    else if (st === "stopping") { cls = "vyb-c-warn"; text = "Booster stopping…"; }
    else if (err) { cls = "vyb-c-err"; text = "Booster: " + err.message; action = err.action || "retry"; }
    else if (st === "ended" && sess.ended_note) { text = sess.ended_note; action = "restart"; }
    else { text = "Booster off · " + (sess.hours_remaining != null ? sess.hours_remaining + " h left this month" : "start it from your dashboard"); action = "restart"; }
    var c = el("vyb-chip", "vyb-chip " + cls); c.className = "vyb-chip " + cls; c.setAttribute("role", "status"); c.setAttribute("data-state", st || "off"); c.setAttribute("data-link", link);
    c.innerHTML = "<span>" + esc(text) + "</span>" + (action ? "<a data-vyb-keep href='/dashboard#booster-session' target='_blank' rel='noopener'>" + esc(ACTION_TEXT[action] || "Open dashboard") + "</a>" : "");
  }

  // ── pairing ─────────────────────────────────────────────────────────
  // addr: a booster id ("bst-ab12"), or an https/http URL (relay / LAN / loopback). code: from `vyomi booster pair`.
  function pair(addr, code) {
    addr = String(addr || "").trim(); code = String(code || "").trim();
    if (!code) return Promise.reject(new Error("Enter the pairing code."));
    var b = { id: "", name: "", paired_at: Date.now() };
    if (/^https?:\/\//i.test(addr)) { b.relay_url = addr.replace(/\/+$/, ""); b.id = addr.replace(/^https?:\/\//i, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 40); try { var u = new URL(addr); if (/^(127\.0\.0\.1|localhost)$/.test(u.hostname)) { b.port = u.port || "80"; delete b.relay_url; } } catch (_) {} }
    else if (addr) b.id = addr.toLowerCase();
    else return Promise.reject(new Error("Enter the booster id or address."));
    var cs = candidates(b), i = 0, lastErr = "no candidate reachable";
    function next() {
      if (i >= cs.length) return Promise.reject(new Error("Could not reach the booster (" + lastErr + ")."));
      var base = cs[i++];
      return timed(base + "/booster/pair/complete", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code: code }) }).then(function (r) {
        if (r.status === 400 || r.status === 401 || r.status === 403 || r.status === 404 || r.status === 410) return r.text().then(function (t) { throw new Error("Pairing refused (" + r.status + "): check the code. " + t.slice(0, 120)); });
        if (!r.ok) { lastErr = "HTTP " + r.status; return next(); }
        return r.json().then(function (j) { if (!j || !j.token) throw new Error("Booster returned no token."); return { base: base, token: j.token, relay_url: j.relay_url || null, local_url: j.local_url || null }; });
      }, function (e) { if (e && /refused/.test(e.message || "")) throw e; lastErr = String((e && e.message) || e); return next(); });
    }
    return next().then(function (res) {
      b.token = res.token; b.base = res.base;
      if (res.local_url) b.local_url = String(res.local_url).replace(/\/+$/, "");
      if (res.relay_url) b.relay_url = String(res.relay_url).replace(/\/+$/, "");
      return timed(res.base + "/booster/status", { headers: { Authorization: "Bearer " + res.token } }).then(function (r) { return r.ok ? r.json() : {}; }, function () { return {}; }).then(function (st) {
        b.name = st.hostname || b.id; if (!b.id) b.id = String(st.hostname || "booster").toLowerCase();
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
  function homeOf(space) { return space && space.home && space.home.type === "booster" ? space.home : null; }
  function activeHome() { return homeOf(active); }
  function refreshActive() {
    return realFetch(NANO_BASE + "/api/spaces/active").then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { if (d && d.space) setActive(d.space); }).catch(function () {});
  }

  // ── fetch hook: route booster-homed /_wire, block when down/locked ──
  function blocked() {   // -> reason string | null, for the active booster-homed space
    var h = activeHome(); if (!h) return null;
    var st = stateOf(h.booster_id);
    if (st === "unreachable" || st === "unauthorized") return "unreachable";
    if (isLocked(h.booster_id)) return "locked";
    return null;
  }
  function daysLeft(id) { var s = (state[id] || {}).status; return s && typeof s.trial_days_left === "number" ? s.trial_days_left : null; }
  function isLocked(id) { if (account && account.locked) return true; var s = (state[id] || {}).status; var d = daysLeft(id); return !!(s && (s.locked === true || (d !== null && d <= 0))); }
  function refuse(reason) {
    var code = reason === "locked" ? "BoosterTrialExpired" : "DatacenterUnreachable";
    return new Response(JSON.stringify({ error: { code: code, message: reason === "locked" ? "The booster trial has ended; booster-homed spaces are locked." : "Datacenter unreachable: this space lives on a booster that cannot be reached right now." } }),
      { status: 503, headers: { "content-type": "application/json", "retry-after": "5" } });
  }
  window.fetch = function (input, init) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || String(input);
      var u = new URL(url, location.href), wi = u.pathname.indexOf("/_wire/");
      var isWire = u.origin === location.origin && (wi >= 0 || /\/_wire$/.test(u.pathname));
      var sh = null;   // portal session: compute/AI calls of ANY space go to the running Codespace booster; emulators stay in the browser
      if (isWire && !activeHome() && vboost) {
        var hd = new Headers((init && init.headers) || (typeof input !== "string" && input && input.headers) || {});
        if (isComputeCall(u.pathname.slice(wi >= 0 ? wi + 6 : 0), hd.get("authorization") || "")) sh = { booster_id: SESSION_ID, booster_name: vboost.name };
      }
      if (isWire && (activeHome() || sh)) {
        var h = sh || activeHome(), b = get(h.booster_id), why = sh ? (/^(unreachable|unauthorized)$/.test(stateOf(SESSION_ID)) ? "unreachable" : null) : blocked();
        if (why) return Promise.resolve(refuse(why));
        if (!b) return Promise.resolve(refuse("unreachable"));
        var base = (state[b.id] || {}).base || b.base || candidates(b)[0];
        var req = typeof input === "string" ? null : input;
        var headers = new Headers((init && init.headers) || (req && req.headers) || {});
        if (b.session) headers.set("x-vyomi-session-token", b.token || "");   // relay plane: the SAME signed token the booster re-verifies
        else { headers.set("x-vyomi-booster-token", b.token || ""); if (!headers.has("authorization")) headers.set("authorization", "Bearer " + (b.token || "")); }
        var target = base + u.pathname.slice(wi >= 0 ? wi : u.pathname.indexOf("/_wire")) + u.search;
        var ni = Object.assign({}, init || {}, { headers: headers });
        if (req && !(init && init.method)) { ni.method = req.method; if (!/^(GET|HEAD)$/i.test(req.method)) ni.body = req.body; }
        return realFetch(target, ni).catch(function (e) { setState(b.id, { state: "unreachable", fails: FAILS_TO_DOWN }); return refuse("unreachable"); });
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
    "body.vy-booster-down #root button:not([data-vyb-keep]),body.vy-booster-down #root input,body.vy-booster-down #root select,body.vy-booster-down #root textarea,body.vy-booster-down #root [role=button]{pointer-events:none!important;opacity:.55}" +
    "body.vyb-legacy.vy-booster-down>*:not(.vyb-bar):not(.vyb-lock):not(script):not(style){pointer-events:none!important;opacity:.55}" +
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
    var h = IS_CONSOLE ? activeHome() : null, why = h ? blocked() : null, name = h ? (h.booster_name || h.booster_id) : "";
    document.body.classList.toggle("vy-booster-down", !!why);
    document.body.classList.toggle("vyb-legacy", !document.getElementById("root"));
    if (why === "unreachable") {
      var st = stateOf(h.booster_id), bar = el("vyb-banner", "vyb-bar vyb-down");
      bar.setAttribute("role", "alert"); bar.setAttribute("data-state", st);
      bar.innerHTML = "<span>Datacenter unreachable</span><span style='font-weight:400'>" + esc(name) + (st === "unauthorized" ? " rejected this browser's pairing; pair it again." : " is not responding. Read-only until it reconnects; retrying automatically.") + "</span><button data-vyb-keep type='button' id='vyb-retry'>Retry now</button>";
      var rb = document.getElementById("vyb-retry"); if (rb) rb.onclick = function () { pollAll(); };
    } else if (h && !why) {
      var d = daysLeft(h.booster_id);
      if (d !== null && d > 0 && d <= TRIAL_WARN_DAYS) {
        var w = el("vyb-banner", "vyb-bar vyb-warn"); w.setAttribute("data-state", "trial-warning");
        w.textContent = "Booster trial ends in " + d + (d === 1 ? " day" : " days") + ". Booster-homed spaces lock after that; upgrade to Pro/Max to keep them.";
      } else kill("vyb-banner");
    } else kill("vyb-banner");
    if (why === "locked") {
      var l = el("vyb-lock", "vyb-lock"); l.setAttribute("role", "alertdialog");
      l.innerHTML = "<div><h2>Booster trial ended</h2><div>This space lives on <b>" + esc(name) + "</b> and is locked. Your data is kept and unlocks with a valid Pro or Max entitlement.<br>Browser-homed spaces keep working.</div><a data-vyb-keep href='" + NANO_BASE + "/clouds.html'>Back to spaces</a></div>";
    } else kill("vyb-lock");
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  // ── UI: home badge (space cards), home picker, pairing dialog ───────
  function badgeHtml(space) {
    var h = homeOf(space);
    if (!h) return '<span class="vyb-badge" data-home="browser" title="Runs in this browser">This browser</span>';
    var down = stateOf(h.booster_id) !== "connected" && stateOf(h.booster_id) !== "unknown";
    return '<span class="vyb-badge' + (down ? " vyb-b-down" : "") + '" data-home="booster" data-booster="' + esc(h.booster_id) + '" title="' + (down ? "Datacenter unreachable" : "Runs on the booster") + '">Booster: ' + esc(h.booster_name || h.booster_id) + (down ? " (unreachable)" : "") + "</span>";
  }
  function homeOptions() { return boosterOn() ? load().map(function (b) { return { id: b.id, name: b.name || b.id }; }) : []; }
  // The id the create-space picker should preselect: the booster when the account has it enabled (backend), else the browser.
  function defaultHome() { var o = homeOptions(); return (account && account.effective && o.length) ? o[0].id : "browser"; }
  function homePayload(selectValue) {   // select value "" | "browser" -> undefined, else booster id -> home record
    if (!selectValue || selectValue === "browser") return undefined;
    var b = get(selectValue); return b ? { type: "booster", booster_id: b.id, booster_name: b.name || b.id } : undefined;
  }
  function openPairDialog() {
    ensureStyle();
    var m = document.createElement("div"); m.className = "vyb-modal"; m.id = "vyb-pair";
    function paint(err) {
      var acc = account, accLine = acc ? ("<div id='vyb-acc' style='margin:8px 0;padding:8px;border:1px solid #d1d5db;border-radius:8px'>Booster: <b>" + (acc.effective ? "on" : acc.locked ? "locked (trial ended)" : "off") + "</b>" + (acc.status === "trial" && acc.days_left != null ? " &middot; trial, " + acc.days_left + " day(s) left" : acc.status === "active" ? " &middot; " + esc(acc.tier || "plan") : "") + " <button type='button' id='vyb-acc-btn'>" + (acc.enabled ? "Turn off" : "Turn on") + "</button></div>") : "";
      m.innerHTML = "<div class='vyb-card' role='dialog' aria-labelledby='vyb-t'><h3 id='vyb-t'>Boosters</h3>" + accLine + "<div style='color:#4b5563'>Pair a booster (a Pro/Max appliance) to host spaces on your own machine. Run <code>vyomi booster pair</code> there to get a code.</div>" +
        "<ul>" + load().map(function (b) { return "<li><span>" + esc(b.name || b.id) + " <span class='vyb-badge' data-vyb-state='" + esc(b.id) + "'>" + esc(stateOf(b.id)) + "</span></span><button type='button' data-unpair='" + esc(b.id) + "'>Unpair</button></li>"; }).join("") + "</ul>" +
        "<label for='vyb-addr'>Booster id or address</label><input id='vyb-addr' placeholder='bst-ab12 or http://127.0.0.1:8765' autocomplete='off'>" +
        "<label for='vyb-code'>Pairing code</label><input id='vyb-code' placeholder='e.g. 482913' autocomplete='off'>" +
        "<div class='vyb-err' id='vyb-err'>" + esc(err || "") + "</div><div class='vyb-row'><button type='button' id='vyb-close'>Close</button><button type='button' class='vyb-primary' id='vyb-go'>Pair</button></div></div>";
      m.querySelector("#vyb-close").onclick = function () { m.remove(); };
      var ab = m.querySelector("#vyb-acc-btn");
      if (ab) ab.onclick = function () { ab.disabled = true; setBooster(!(account && account.enabled)).then(function () { paint(""); }, function (e) { paint(String(e.message || e)); }); };
      m.querySelector("#vyb-go").onclick = function () {
        var btn = this; btn.disabled = true; btn.textContent = "Pairing...";
        pair(m.querySelector("#vyb-addr").value, m.querySelector("#vyb-code").value).then(function () { paint(""); }, function (e) { paint(String(e.message || e)); });
      };
      Array.prototype.forEach.call(m.querySelectorAll("[data-unpair]"), function (b) { b.onclick = function () { unpair(b.getAttribute("data-unpair")); paint(""); }; });
    }
    paint(""); (document.body || document.documentElement).appendChild(m);
    return m;
  }

  window.VyomiBooster = {
    list: list, get: function (id) { var b = get(id); return b && Object.assign({}, b, { token: undefined }); }, pair: pair, unpair: unpair,
    state: function (id) { return stateOf(id); }, status: function (id) { return (state[id] || {}).status || null; },
    pollNow: pollAll, setActive: setActive, refreshActive: refreshActive, activeHome: activeHome,
    homeOptions: homeOptions, defaultHome: defaultHome, cloudAllowed: cloudAllowed, planCloud: planCloud, pinCloud: pinCloud, homePayload: homePayload, account: function () { return account; }, loadAccount: loadAccount, setBooster: setBooster, badgeHtml: badgeHtml, openPairDialog: openPairDialog,
    session: function () { return sess; }, sessionBooster: function () { return vboost && Object.assign({}, vboost, { token: undefined }); }, loadSession: loadSession, isComputeCall: isComputeCall,
    isBlocked: blocked, candidates: function (id) { var b = get(id); return b ? candidates(b) : []; },
  };

  function boot() { render(); refreshActive(); start(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
