/* Vyomi Global Mesh widget for the AWS / GCP / Azure Nano consoles: an in-page card on the console HOME page (beside the "How Nano ... works" video banner).
 *   Pro / Max (or active trial) with mesh enabled -> Start / Leave the Mesh button
 *   Pro / Max entitled but switched off              -> "Turn on the Mesh"
 *   Free, trial never used                           -> "Start 30-day trial" (one per account; same trial as the appliance)
 *   Trial ended / not entitled                       -> "Upgrade to Pro / Max"
 * Uses window.VyomiBooster (booster-link.js) and /api/account/booster. Cloud = data-cloud on this script tag. */
(function () {
  "use strict";
  var me = document.currentScript, CLOUD = (me && me.getAttribute("data-cloud")) || "";
  var PRICING = "https://vyomi.cloud/pricing";
  var card, busy = false, msg = "", view = "main", collapsed = false;

  function B() { return window.VyomiBooster; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  // Errors are shown as a 5-second toast (shared implementation in booster-link.js), never inside the Mesh card.
  function toast(text) { var b = B(); if (b && b.toast) b.toast(text); }
  function css() {
    var st = document.createElement("style");
    st.textContent = "#vy-bw{position:relative;z-index:2;box-sizing:border-box;margin:14px 0 18px;padding:14px 18px;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#fff;color:#16191f;border:1px solid #d5dbdb;border-radius:8px;font-size:14px;line-height:1.45;display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px}"
      + ".vy-nano-video{display:flex;flex-wrap:wrap;gap:16px;align-items:stretch}.vy-nano-video>.vy-video-banner{order:1;flex:1 1 340px;min-width:0;margin:0 0 16px!important}.vy-nano-video>#vy-bw{order:2;flex:1 1 340px;min-width:0;margin:0 0 16px}"
      + "#vy-bw .main{flex:1 1 200px;min-width:0}"
      + "#vy-bw h4{margin:0 0 3px;font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px}"
      + "#vy-bw .tag{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:999px;background:#e8f0fe;color:#1a56c4}"
      + "#vy-bw .tag.free{background:#eceff3;color:#4b5563}"
      + "#vy-bw p{margin:0 0 6px;color:#4b5563}#vy-bw p:last-child{margin:0}"
      + "#vy-bw .fine{font-size:12px;color:#6b7280}#vy-bw a{color:#1a56c4}"
      + "#vy-bw .act{display:flex;flex-direction:column;align-items:stretch;gap:4px;min-width:170px}"
      + "#vy-bw .go{display:block;box-sizing:border-box;text-align:center;text-decoration:none;padding:9px 16px;border-radius:8px;border:0;background:#2f6fdc;color:#fff!important;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}"
      + "#vy-bw .go.stop{background:#b42318}#vy-bw .go[disabled]{opacity:.6;cursor:default}"
      + "#vy-bw .sub{font-size:12px;color:#6b7280;text-align:center}"
      + "#vy-bw .cd{margin-top:6px;text-align:center;font:600 22px/1.1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.04em;font-variant-numeric:tabular-nums}#vy-bw .cdl{text-align:center;font-size:11px;color:#6b7280;margin-top:-2px}"
      + "#vy-bw .err{color:#b42318;font-size:13px;margin-top:4px}"
      // ── native look per cloud ──
      // AWS · Cloudscape: Open Sans / Amazon Ember, 1px #c6c6cd-ish container, orange primary pill (as "Add widgets"), outlined blue pill for normal actions
      + "#vy-bw[data-cloud=aws]{font-family:'Amazon Ember','Open Sans','Helvetica Neue',Roboto,Arial,sans-serif;border:1px solid #e9ebed;border-radius:8px;box-shadow:0 1px 1px 0 rgba(0,28,36,.3),1px 1px 1px 0 rgba(0,28,36,.15),-1px 1px 1px 0 rgba(0,28,36,.15);color:#0f141a;font-size:14px}"
      + "#vy-bw[data-cloud=aws] h4{font-size:16px;font-weight:700;letter-spacing:.005em}#vy-bw[data-cloud=aws] p{color:#414d5c}"
      + "#vy-bw[data-cloud=aws] .tag{border-radius:4px;background:#0972d3;color:#fff;letter-spacing:.02em}#vy-bw[data-cloud=aws] .tag.free{background:#5f6b7a;color:#fff}"
      + "#vy-bw[data-cloud=aws] .go{border-radius:20px;background:#ff9900;color:#0f141a!important;font-weight:700;padding:6px 20px;border:2px solid #ff9900}"
      + "#vy-bw[data-cloud=aws] .go.stop{background:#fff;color:#d91515!important;border:2px solid #d91515}"
      + "#vy-bw[data-cloud=aws] a{color:#0972d3}"
      // GCP · Material 3: Google Sans / Roboto, 12px radius #dadce0 outline, filled blue pill
      + "#vy-bw[data-cloud=gcp]{font-family:'Google Sans',Roboto,Arial,sans-serif;border:1px solid #dadce0;border-radius:12px;color:#202124;font-size:14px}"
      + "#vy-bw[data-cloud=gcp] h4{font-size:16px;font-weight:500}#vy-bw[data-cloud=gcp] p{color:#5f6368}"
      + "#vy-bw[data-cloud=gcp] .tag{border-radius:8px;background:#e8f0fe;color:#1967d2;letter-spacing:.03em}#vy-bw[data-cloud=gcp] .tag.free{background:#f1f3f4;color:#5f6368}"
      + "#vy-bw[data-cloud=gcp] .go{border-radius:20px;background:#0b57d0;font-weight:500;padding:9px 24px;letter-spacing:.01em}"
      + "#vy-bw[data-cloud=gcp] .go.stop{background:#fff;color:#b3261e!important;border:1px solid #dadce0}"
      + "#vy-bw[data-cloud=gcp] a{color:#0b57d0}"
      // Azure · Fluent 2: Segoe UI, 4px radius, #e0e0e0 stroke, brand #0f6cbd, subtle buttons
      + "#vy-bw[data-cloud=azure]{font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,sans-serif;border:1px solid #e0e0e0;border-radius:4px;box-shadow:0 2px 4px rgba(0,0,0,.14),0 0 2px rgba(0,0,0,.12);color:#242424;font-size:14px}"
      + "#vy-bw[data-cloud=azure] h4{font-size:16px;font-weight:600}#vy-bw[data-cloud=azure] p{color:#616161}"
      + "#vy-bw[data-cloud=azure] .tag{border-radius:2px;background:#ebf3fc;color:#0f6cbd;font-weight:600}#vy-bw[data-cloud=azure] .tag.free{background:#f0f0f0;color:#424242}"
      + "#vy-bw[data-cloud=azure] .go{border-radius:4px;background:#0f6cbd;font-weight:600;padding:7px 14px}"
      + "#vy-bw[data-cloud=azure] .go.stop{background:#fff;color:#b10e1c!important;border:1px solid #d1d1d1}"
      + "#vy-bw[data-cloud=azure] a{color:#0f6cbd}";
    document.head.appendChild(st);
  }
  function api(path, body) {
    return fetch("/api/account/booster" + path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function refresh() { var b = B(); return b ? Promise.all([b.loadAccount(), b.loadSession()]).then(paint, paint) : Promise.resolve(); }
  function run(fn) { if (busy) return; busy = true; msg = ""; paint(); Promise.resolve().then(fn).catch(function () { toast("Something went wrong. Try again."); }).then(function () { busy = false; return refresh(); }); }

  // Agreement is stored per GitHub account and per terms version (bump TERMS_V when the wording changes: everyone sees it again).
  var TERMS_V = "v2";
  function termsKey() { var x = B() && B().session && B().session(); return "vy_booster_terms_" + TERMS_V + ":" + ((x && x.github && x.github.login) || ""); }
  function agreed() { try { return localStorage.getItem(termsKey()) === "1"; } catch (_) { return false; } }
  function show(v) { view = v; collapsed = false; try { localStorage.setItem("vy_bw_collapsed", "0"); } catch (_) {} paint(); }
  function doStart() {
    var b = B();
    run(function () {
      return b.sessionStart().then(function (r) {
        if (!r || r.cancelled) return;
        var er = !r.ok && r.j; if (!er) return;
        if (er.action === "reconnect") view = "connect"; else toast(er.message || er.error || "Could not start the mesh.");
      });
    });
  }
  function startStop() {
    var b = B(), x = b.session();
    if (!x || !x.github || !x.github.connected) { show("connect"); return; }
    if (x.active) { run(function () { return b.sessionStop(); }); return; }
    b.confirmTerms().then(function (ok) { if (ok) { b.termsAccept(); doStart(); } });     // terms: modal dialog
  }
  function enable(trial) {
    run(function () {
      return api(trial ? "/enable?trial=1" : "/enable").then(function (r) {
        if (!r.ok) { toast(r.j.message || "Could not turn on the mesh."); return; }
        // Pro = ONE cloud: a fresh trial pins the cloud of the console it was started from
        if (trial && r.j.clouds === "one" && !r.j.primary_cloud && CLOUD) return api("/primary-cloud", { cloud: CLOUD });
      });
    });
  }

  function paint() {
    if (!card) return;
    var b = B(), a = b && b.account && b.account(), x = b && b.session && b.session(), main, act = "";
    card.className = "";
    if (!a) {                                                       // not signed in / account unavailable
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag free">Free</span></h4><p>Your Free plan runs everything in the browser. Pro and Max add the Vyomi Global Mesh: real compute and AI on your own free GitHub quota.</p>';
      act = '<a class="go" href="' + PRICING + '" target="_blank" rel="noopener">See plans</a>';
    } else if (view === "connect") {                                // inline GitHub connect
      main = '<h4>\u26A1 Connect your GitHub account</h4><p>The Mesh runs on the free quota of <b>your own GitHub account</b>. Your Vyomi sign-in (Google, LinkedIn or any other) stays the same; we just link GitHub to it.</p><p class="fine">No GitHub account? <a href="https://github.com/signup" target="_blank" rel="noopener">Create a free one</a> (about 2 minutes), then come back and click Connect GitHub.</p>';
      act = '<button class="go" data-gh>Connect GitHub</button><div class="sub"><a href="#" data-back>Cancel</a></div>';
    } else if (a.effective) {                                       // Pro / Max / active trial, switched on
      var ss = x && x.session, stt = ss && ss.state, conn = !!(x && x.github && x.github.connected);
      var starting = stt === "pending" || stt === "starting", running = stt === "running", stopping = stt === "stopping";
      var tierName = (a.tier || "pro").charAt(0).toUpperCase() + (a.tier || "pro").slice(1);
      var cloudName = a.clouds === "one" && a.primary_cloud ? ({ aws: "AWS", gcp: "GCP", azure: "Azure" }[a.primary_cloud] || a.primary_cloud) : "";
      var sub = a.source === "trial" && a.days_left != null ? tierName + " trial: " + a.days_left + " day" + (a.days_left === 1 ? "" : "s") + " left" + (cloudName ? " \u00b7 " + cloudName + " only" : "") : (cloudName ? tierName + " \u00b7 " + cloudName + " only" : "");
      var hrs = x && x.hours_remaining != null ? x.hours_remaining + " h left this cycle" : "";
      var line, btn;
      if (starting) { line = "Starting\u2026 about 2 minutes."; btn = '<button class="go" disabled>Starting\u2026</button>'; }
      else if (stopping) { line = "Stopping\u2026"; btn = '<button class="go" disabled>Stopping\u2026</button>'; }
      else if (running) {
        var sec = Math.max(0, ss.countdown_seconds | 0), p2 = function (n) { return String(n).padStart(2, "0"); };
        line = "Running on your own GitHub Codespace.";
        btn = '<button class="go stop" data-ss ' + (busy ? "disabled" : "") + '>Leave the Mesh</button>'
          + '<div class="cd" aria-live="off" title="Time left in this session">' + p2(Math.floor(sec / 3600)) + ':' + p2(Math.floor(sec % 3600 / 60)) + ':' + p2(sec % 60) + '</div><div class="cdl">session time left</div>';
      }
      else {
        line = (x && x.ended_note) || (conn ? "Runs on the free quota of your own GitHub account." : "Connect your GitHub account to start.");
        btn = '<button class="go" data-ss ' + (busy ? "disabled" : "") + '>' + (conn ? "Join the Mesh" : "Connect GitHub & join") + '</button>';
      }
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag">' + esc(a.source === "trial" ? tierName + " trial" : tierName) + '</span></h4><p>' + esc(line) + '</p>';
      act = btn + '<div class="sub">' + esc([sub, hrs].filter(Boolean).join(" \u00b7 ")) + '</div>';
    } else if (a.status === "active" || a.status === "trial") {      // entitled but switched off
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag">' + esc(a.tier || "pro") + '</span></h4><p>Your plan includes the Mesh. It is switched off.</p>';
      act = '<button class="go" data-en ' + (busy ? "disabled" : "") + '>' + (busy ? "Turning on\u2026" : "Turn on the Mesh") + '</button>';
    } else if (!a.trial_used) {                                     // Free, the account's one 30-day trial not started yet
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag free">Free</span></h4><p>Try the Mesh with a free 30-day Pro trial (one cloud): real compute and AI on your own free GitHub quota. One trial per account.</p>';
      act = '<button class="go" data-tr ' + (busy ? "disabled" : "") + '>' + (busy ? "Starting trial\u2026" : "Start 30-day Pro trial") + '</button><div class="sub">or <a href="' + PRICING + '" target="_blank" rel="noopener">compare plans</a></div>';
    } else {                                                        // trial used / expired
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag free">Free</span></h4><p>The Mesh is included with Pro and Max. Upgrade to use it.</p>';
      act = '<a class="go" href="' + PRICING + '" target="_blank" rel="noopener">Upgrade to Pro / Max</a>';
    }
    card.innerHTML = '<div class="main">' + main + (msg ? '<div class="err">' + esc(msg) + '</div>' : "") + '</div><div class="act">' + act + '</div>';
  }

  // Mount as an in-page card on the console HOME page: directly beside the "How Nano ... works" video banner; if that banner was dismissed,
  // before the Home heading. Not on other pages (the mesh status chip covers those).
  var HEADINGS = { aws: "Console Home", azure: "Azure services", gcp: "Welcome" };
  function findHeading() {
    var want = HEADINGS[CLOUD], els = document.querySelectorAll("h1,h2,h3"), i;
    for (i = 0; i < els.length; i++) if (els[i].textContent.trim() === want) return els[i];
    return null;
  }
  function place() {
    var vid = document.querySelector(".vy-nano-video"), h = vid ? null : findHeading();
    if (!vid && !h) { if (card.isConnected) card.remove(); return; }
    // The banner wrapper is a React-owned empty div whose children are script-injected: the card joins it, side by side with the video banner.
    if (vid) { if (card.parentElement !== vid) vid.appendChild(card); }
    if (vid && CLOUD === "aws") {          // AWS: the "Welcome to the Vyomi AWS console" alert goes first, above the video + Mesh row
      var row = vid.closest('[class*="awsui_child"]'), kids = row && row.parentElement ? row.parentElement.children : [], i;
      for (i = 0; i < kids.length; i++) if (kids[i] !== row && /^\s*Welcome to the/.test(kids[i].textContent) && kids[i].style.order !== "-1") kids[i].style.order = "-1";
    }
    else { var tgt = h.closest('[class*="awsui_child"]') || h.parentElement; if (card.nextElementSibling !== tgt || !card.isConnected) tgt.parentElement.insertBefore(card, tgt); }
  }

  function boot() {
    if (document.getElementById("vy-bw")) return;
    css(); card = document.createElement("div"); card.id = "vy-bw"; card.setAttribute("data-cloud", CLOUD); card.setAttribute("data-vyb-keep", "1");
    card.addEventListener("click", function (e) {
      var t = e.target;
      if (t.closest("[data-ss]")) startStop();
      else if (t.closest("[data-gh]")) { location.href = "/api/mesh/github/connect"; }
      else if (t.closest("[data-back]")) { e.preventDefault(); view = "main"; paint(); }
      else if (t.closest("[data-en]")) enable(false);
      else if (t.closest("[data-tr]")) enable(true);
    });
    var pending = false;
    new MutationObserver(function () { if (pending) return; pending = true; requestAnimationFrame(function () { pending = false; place(); }); })
      .observe(document.body, { childList: true, subtree: true });
    place(); paint();
    window.addEventListener("vyomi-booster-session", paint); window.addEventListener("vyomi-booster-account", paint);
    window.VyomiBoosterWidget = { agreed: agreed, accept: function () { try { localStorage.setItem(termsKey(), "1"); } catch (_) {} }, show: function (v) { view = v; paint(); place(); if (card.scrollIntoView) card.scrollIntoView({ block: "center", behavior: "smooth" }); } };
    setInterval(function () { var x = B() && B().session && B().session(); if (x && x.session && x.session.state === "running" && view === "main") paint(); }, 1000);
    var tries = 0; (function wait() { if (B() && B().loadAccount) { refresh(); setInterval(refresh, 60000); } else if (tries++ < 40) setTimeout(wait, 250); })();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
