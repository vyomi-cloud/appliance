"""Wrap the REAL Pro/Max front-end (splash/launch dashboard + the three SPA
consoles) for the Nano in-browser substrate. We DON'T fork these pages — we
take the shipped HTML verbatim and add one <script> + rewrite the inter-page
links so the exact same UI runs against the in-browser backend.

Pro/Max flow            ->  Nano (static, in-browser)
  /clouds (clouds.html) ->  /  (index.html)        launch dashboard / splash
  /console/aws          ->  /aws-console.html       SPA console
  /console/gcp          ->  /gcp-console.html
  /console/azure        ->  /azure-console.html

Run:  python3 wasm/make_pages.py   (after build_fixtures.py)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "static")

# Pro/Max console URLs -> the static files we serve them as. RELATIVE targets so
# inter-page nav works whether the bundle is served at the web root or under a
# subpath (the portal's /nano/).
LINKS = {
    # Nano opens the v4 native-fidelity consoles from the launcher (cloud cards + space clicks);
    # the v3 consoles stay reachable as each v4 lens's "classic console" link. Must precede
    # the "/console/<cloud>" rewrites below.
    "const PROVIDER_PATHS = { aws: '/console/aws', gcp: '/console/gcp', azure: '/console/azure' };":
        "const PROVIDER_PATHS = { aws: 'v4/aws/', gcp: 'v4/gcp/', azure: 'v4/azure/' };",
    "/console/aws": "aws-console.html",
    "/console/gcp": "gcp-console.html",
    "/console/azure": "azure-console.html",
    '"/ui#spaces"': '"clouds.html#spaces"',  # console "back to spaces" -> dashboard, Spaces view (must precede "/ui")
    '"/ui#usage"': '"clouds.html#usage"',    # console dev-tools -> dashboard SDK & CLI usage view
    '"/ui#api"': '"clouds.html#api"',        # console dev-tools -> dashboard API (Swagger) view
    '"/ui"': '"clouds.html"',      # "back to spaces/dashboard" -> the workspaces dashboard
    '"/clouds"': '"clouds.html"',   # Nano: launch = index.html, dashboard = clouds.html
}

# Relative src so the boot loader resolves under any mount point.
BOOT = '  <script type="module" src="./nano-boot.js?v=4"></script>\n</head>'  # consoles: Pyodide + SW
# Dashboard: SW only + hide the appliance host-health panel (CPU/RAM/Disk are
# the host VM's stats — there is no VM in a browser tab, so it's N/A for Nano).
# Nano shows the full UI (sidebar + Dashboard + Spaces + Knowledge Center, dark
# theme, curved graphs — all inherited from clouds.html). The Service-status card
# IS shown (readiness-strip.js is kept — see the rewrite in _process): it renders
# per-service CPU/RAM tiles fed by the Nano SW's /api/runtime/readiness +
# /api/runtime/service-metrics (derived from the live census + WASM heap), just
# like Lite/Pro/Max. Only the Host-utilization card stays hidden (host CPU/RAM/Disk
# are meaningless in-browser). Host distribution pies run off the Nano SW.
SW = ('  <style>#host-util-card{display:none!important}</style>\n'
      '  <script src="./nano-sw.js" defer></script>\n</head>')

# Launch page (pricing.html) → the Nano landing (index.html), identical to the
# Lite/Max/Pro launch page (SDK strip + local-fidelity services). The "Activate
# appliance" + "GitHub community" top-bar buttons ARE shown and fully wired: the
# Nano SW proxies the REAL portal device-flow (start-activation → portal /activate
# → poll /api/oauth/token) and holds the resulting license JWT in IndexedDB, so
# /api/runtime/tier + /api/license/status flip the top bar to the green pill just
# like Lite/Pro/Max. Only the retired inline activate-section and the "Continue to
# console" primary button stay hidden.
LAUNCH = ('  <style>#activate-section,.tb-btn-primary{display:none!important}</style>\n'
          '  <script src="./nano-sw.js" defer></script>\n</head>')

# Base-path fetch shim — injected FIRST in <head> so it patches window.fetch
# before the page's inline boot() fires its /api reads. Rewrites the console's
# absolute /api/* (and other bundle-internal absolute fetches) to the bundle's
# mount path, so the service worker (scoped to that path) intercepts them. No-op
# at the web root (base==""). Static asset/link refs are made relative below.
SHIM = r"""  <script>
  (function(){
    var base = location.pathname.replace(/\/[^\/]*$/, "");
    window.__NANO_BASE = base;
    if (!base) return;
    var of = window.fetch.bind(window);
    var origin = location.origin;
    function rw(u){
      if (typeof u!=="string") return u;
      if (u.indexOf(origin+"/")===0){                     // same-origin ABSOLUTE url (e.g. ORIGIN + "/api/..")
        var pth = u.slice(origin.length);
        return (pth===base || pth.indexOf(base+"/")===0) ? u : origin+base+pth;
      }
      if (u.charAt(0)==="/" && u.charAt(1)!=="/"){         // root-relative path (e.g. "/api/..")
        return (u===base || u.indexOf(base+"/")===0) ? u : base+u;
      }
      return u;                                            // relative or cross-origin -> leave alone
    }
    window.fetch = function(input, init){
      if (typeof input==="string") return of(rw(input), init);
      if (input && input.url) return of(new Request(rw(input.url), input), init);
      return of(input, init);
    };
  })();
  </script>
"""

# The conformance docs (API/SDK/Utility) live on the public portal.
DOCS_BASE = "https://vyomi.cloud"


def _docs_widget(cloud=None):
    """A floating 'Conformance' pill linking the three distinct docs (API · SDK
    · Utility) + the Conformance Pack. On a console it deep-links that cloud; on
    the dashboard it links the pack. Docs live on the portal (vyomi.cloud)."""
    if cloud:
        head = f"{cloud.upper()} conformance"
        links = (
            f'<a href="{DOCS_BASE}/docs/{cloud}" target="_blank" rel="noopener">API doc <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/{cloud}/sdk" target="_blank" rel="noopener">SDK doc <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/{cloud}/cli" target="_blank" rel="noopener">Utility doc <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/conformance-pack" target="_blank" rel="noopener">Conformance Pack <span>↗</span></a>'
        )
    else:
        head = "Conformance"
        links = (
            f'<a href="{DOCS_BASE}/docs/conformance-pack" target="_blank" rel="noopener">Conformance Pack <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/aws" target="_blank" rel="noopener">AWS · API / SDK / Utility <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/gcp" target="_blank" rel="noopener">GCP · API / SDK / Utility <span>↗</span></a>'
            f'<a href="{DOCS_BASE}/docs/azure" target="_blank" rel="noopener">Azure · API / SDK / Utility <span>↗</span></a>'
        )
    return f"""
<style>
 #nano-docs{{position:fixed;right:14px;bottom:40px;z-index:100000;font:13px system-ui,-apple-system,sans-serif}}
 #nano-docs .pill{{display:none}}   /* trigger moved into the tunnel bar's "More" menu (#nano-menu-conf) */
 #nano-docs .pop{{position:absolute;right:0;bottom:0;background:#0d1030;border:1px solid #2a2f55;border-radius:12px;padding:6px;min-width:218px;display:none;box-shadow:0 12px 34px rgba(0,0,0,.45)}}
 #nano-docs.open .pop{{display:block}}
 #nano-docs .pop .h{{font-size:11px;color:#8b8ba7;padding:6px 10px;text-transform:uppercase;letter-spacing:1px}}
 #nano-docs .pop a{{display:flex;justify-content:space-between;gap:14px;padding:8px 10px;border-radius:8px;color:#cdd8e6;text-decoration:none}}
 #nano-docs .pop a:hover{{background:#171b3d;color:#fff}}
 #nano-docs .pop a span{{color:#7cc4ff}}
</style>
<div id="nano-docs">
 <div class="pop"><div class="h">{head}</div>{links}</div>
 <div class="pill" onclick="this.parentNode.classList.toggle('open')">📘 Conformance</div>
</div>"""


def _footer_widget():
    """FROZEN relay-tunnel footer — present on EVERY view (launch dashboard + all
    consoles), so the tunnel control + status + logs follow you everywhere with no
    extra tab. The endpoint (Pyodide + cores + relay WebSocket) lives in a SHARED
    WORKER (relay/relay-shared-worker.js) — the one browser context that survives
    full-page navigation — so moving dashboard→console keeps the tunnel connected.
    The worker mirrors status + boot/splash logs to every footer over a same-origin
    BroadcastChannel('nano-relay'); each footer drives it via a MessagePort
    (start/stop/query). Footer height is padded into <body> so nothing is covered."""
    return """
<style>
 #nano-foot{position:fixed;left:0;right:0;bottom:0;z-index:99999;height:34px;display:flex;align-items:center;gap:12px;padding:0 14px;background:#0b0e28;border-top:1px solid #2a2f55;color:#e4e4e7;font:12px system-ui,-apple-system,sans-serif;box-shadow:0 -4px 18px rgba(0,0,0,.35)}
 #nano-foot .dot{width:9px;height:9px;border-radius:50%;background:#71717a;flex:0 0 auto}
 #nano-foot.up .dot{background:#34d399;box-shadow:0 0 8px #34d39988}
 #nano-foot.connecting .dot{background:#fbbf24;box-shadow:0 0 8px #fbbf2488;animation:nano-pulse 1s ease-in-out infinite}
 @keyframes nano-pulse{0%,100%{opacity:1}50%{opacity:.35}}
 #nano-foot .lbl{white-space:nowrap}
 #nano-foot .sp{flex:1}
 #nano-foot button{background:#171b3d;color:#7cc4ff;border:1px solid #2a2f55;border-radius:6px;padding:3px 10px;cursor:pointer;font:12px system-ui,-apple-system,sans-serif}
 #nano-foot button:hover{background:#1f2550;color:#fff}
 #nano-foot .ep{font:11px ui-monospace,Menlo,monospace;color:#8b8ba7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40vw}
 #nano-logs{position:fixed;left:0;right:0;bottom:34px;z-index:99998;height:240px;background:#05071a;border-top:1px solid #2a2f55;display:none;flex-direction:column;box-shadow:0 -12px 34px rgba(0,0,0,.5)}
 #nano-logs.open{display:flex}
 #nano-logs .h{padding:5px 14px;font:11px system-ui,-apple-system,sans-serif;color:#8b8ba7;background:#0a0c24;border-bottom:1px solid #1a1f44}
 #nano-logs pre{flex:1;margin:0;padding:10px 14px;overflow:auto;font:12px ui-monospace,Menlo,monospace;color:#cdd8e6;white-space:pre-wrap}
 #nano-logs pre .ok{color:#34d399}#nano-logs pre .err{color:#f87171}#nano-logs pre .dim{color:#71717a}
 #nano-foot-menu{position:fixed;right:14px;bottom:40px;z-index:100001;background:#0d1030;border:1px solid #2a2f55;border-radius:12px;padding:6px;min-width:196px;display:none;box-shadow:0 12px 34px rgba(0,0,0,.45)}
 #nano-foot-menu.open{display:block}
 #nano-foot-menu button{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:none;border:0;color:#cdd8e6;padding:9px 11px;border-radius:8px;cursor:pointer;font:13px system-ui,-apple-system,sans-serif}
 #nano-foot-menu button:hover{background:#171b3d;color:#fff}
 #nano-foot-menu #nano-menu-star{color:#f59e0b}
 #nano-foot-menu #nano-menu-star:hover{background:rgba(245,158,11,.14);color:#f59e0b}
 #nano-star{position:fixed;right:16px;bottom:44px;z-index:100001;width:292px;background:linear-gradient(180deg,#14172e,#0d1228);border:1px solid #2a2f55;border-radius:14px;padding:15px 16px;box-shadow:0 16px 42px rgba(0,0,0,.55);display:none;font:13px system-ui,-apple-system,sans-serif;color:#cdd8e6}
 #nano-star .ns-x{position:absolute;top:7px;right:11px;background:none;border:0;color:#8b8ba7;font-size:19px;cursor:pointer;line-height:1;padding:0}
 #nano-star .ns-x:hover{color:#fff}
 #nano-star .ns-top{display:flex;align-items:center;gap:8px;font-size:14px;color:#e4e4e7;font-weight:700}
 #nano-star .ns-emoji{font-size:18px}
 #nano-star .ns-msg{margin:8px 0 13px;line-height:1.5;color:#a1a1aa;font-size:12.5px}
 #nano-star .ns-actions{display:flex;align-items:center;gap:10px}
 #nano-star .ns-go{flex:1;text-align:center;background:linear-gradient(135deg,#f59e0b,#f97316);color:#fff;text-decoration:none;border-radius:9px;padding:8px 12px;font-weight:600;font-size:12.5px}
 #nano-star .ns-go:hover{filter:brightness(1.08)}
 #nano-star .ns-later{background:none;border:0;color:#8b8ba7;cursor:pointer;font-size:12.5px}
 #nano-star .ns-later:hover{color:#cdd8e6}
</style>
<div id="nano-logs"><div class="h">Relay endpoint — runs in a shared worker, stays connected across views. Logs:</div><pre id="nano-foot-log"><span class="dim">tunnel off — click “Start tunnel”.</span></pre></div>
<div id="nano-star">
 <button class="ns-x" type="button" title="Dismiss">&times;</button>
 <div class="ns-top"><span class="ns-emoji">⭐</span><span>Enjoying Nano?</span></div>
 <p class="ns-msg">It's free &amp; open-source. A GitHub star genuinely helps more developers find it — thank you!</p>
 <div class="ns-actions">
  <a class="ns-go" href="https://github.com/vyomi-cloud/appliance" target="_blank" rel="noopener">Star on GitHub ⭐</a>
  <button class="ns-later" type="button">Maybe later</button>
 </div>
</div>
<div id="nano-foot" title="Relay tunnel — lets an external SDK/CLI reach this in-browser sim">
 <span class="dot"></span><span class="lbl">Relay tunnel: off</span>
 <span class="ep" id="nano-foot-ep"></span>
 <span class="sp"></span>
 <button id="nano-foot-logs">Logs ▴</button>
 <button id="nano-foot-toggle">Start tunnel</button>
 <button id="nano-foot-more" title="More">⋯</button>
</div>
<div id="nano-foot-menu">
 <button id="nano-menu-star">⭐ Star on GitHub</button>
 <button id="nano-menu-connect" style="display:none">🔌 Connect apps</button>
 <button id="nano-menu-conf">📘 Conformance</button>
</div>
<script>
// The tunnel bar starts right of the left side menu (never over it: the account menu /
// Sign out lives at the side menu's foot) and follows it as it collapses or expands.
(function(){
  var foot = document.getElementById("nano-foot"); if(!foot) return;
  function fit(){
    var sb = document.getElementById("app-sidebar");
    var r = (sb && sb.getClientRects().length) ? sb.getBoundingClientRect() : null;
    foot.style.left = (r && r.width && r.left < 1 ? Math.round(r.right) : 0) + "px";
  }
  fit(); addEventListener("resize", fit); addEventListener("load", fit);
  var sb = document.getElementById("app-sidebar");
  if(sb && window.ResizeObserver) new ResizeObserver(fit).observe(sb);
  new MutationObserver(fit).observe(document.body, { attributes: true, attributeFilter: ["class"] });
})();
</script>
<script>
(function(){
  var base = window.__NANO_BASE || "";
  // Tunnel config + cloud session live in localStorage (the worker can't read it);
  // the footer resolves them and hands them to the shared worker on start. Defaults
  // point at the local tunnel (auto-detected) with the Cloudflare relay as fallback.
  function ls(k, d){ try { return localStorage.getItem(k) || d; } catch(_){ return d; } }
  function sessionId(){
    var s = ls("nano_session", null);
    if(!s){ s = "nano-" + Math.random().toString(36).slice(2,10); try{ localStorage.setItem("nano_session", s); }catch(_){} }
    return s;
  }
  var SESSION = sessionId();
  var CFG = {
    localHealth:   ls("nano_local_health", "http://127.0.0.1:8090/health"),
    localWs:       ls("nano_local_ws",     "ws://127.0.0.1:8090/register"),
    localExternal: ls("nano_local_ext",    "http://127.0.0.1:8090"),
    cloudWsBase:   ls("nano_cloud_ws",     "wss://relay.vyomi.cloud/register"),
    cloudExternal: ls("nano_cloud_ext",    "https://relay.vyomi.cloud"),
  };
  // Sign-in perks (from /api/license/status): a STABLE relay URL — the session is
  // derived from the account, so it's the same across devices/browsers — plus no
  // idle-pause. Refreshed on load + periodically so a mid-session sign-in applies.
  var _signedIn = false, _acctSession = null;
  function effSession(){ return (_signedIn && _acctSession) ? _acctSession : SESSION; }
  function refreshLicense(){
    fetch("/api/license/status").then(function(r){ return r.json(); }).then(function(d){
      var was = _signedIn;
      _signedIn = !!(d && d.active);
      var acct = (d && (d.issued_to || (d.license && d.license.sub))) || "";
      if(_signedIn && acct){
        try { crypto.subtle.digest("SHA-256", new TextEncoder().encode(acct)).then(function(buf){
          _acctSession = "nano-u-" + Array.from(new Uint8Array(buf)).map(function(b){ return b.toString(16).padStart(2,"0"); }).join("").slice(0,14);
        }); } catch(_){ _acctSession = null; }
      } else { _acctSession = null; }
      if(_signedIn && !was && ok && port) port.postMessage({type:"noidle", on:true});   // mid-session sign-in → cancel idle-pause
    }).catch(function(){});
  }
  var foot = document.getElementById("nano-foot"), lbl = foot.querySelector(".lbl");
  var epEl = document.getElementById("nano-foot-ep"), logsPane = document.getElementById("nano-logs"), logEl = document.getElementById("nano-foot-log");
  var toggleBtn = document.getElementById("nano-foot-toggle"), logsBtn = document.getElementById("nano-foot-logs");
  var phase = "off", lastSeen = 0, mode = null, external = null, noteText = null, _prevServed = 0, _prevPhase = null;
  document.body.style.paddingBottom = "40px";   // never cover page content

  function render(state, served){
    phase = state || "off";
    foot.classList.remove("up","connecting");
    var via = mode ? (mode==="local" ? " · local (fast · private)" : " · cloud (Cloudflare)") : "";
    if(phase==="connected"){ foot.classList.add("up"); lbl.textContent = "Relay tunnel: connected" + via + (served!=null?(" · "+served+" served"):""); toggleBtn.textContent="Stop"; }
    // A `note` from the worker (e.g. "no local tunnel — run `vyomi-tunnel`") means
    // the tunnel can't connect — show it in the label instead of a forever spinner.
    else if(phase==="connecting"){ foot.classList.add("connecting"); lbl.textContent = noteText ? ("Relay tunnel: " + noteText) : ("Relay tunnel: connecting…" + via); toggleBtn.textContent="Stop"; }
    else if(phase==="idle"){ lbl.textContent = "Relay tunnel: paused (30 min idle)"; toggleBtn.textContent="Reconnect"; }
    else { lbl.textContent = "Relay tunnel: off"; toggleBtn.textContent="Start tunnel"; }
    epEl.textContent = (phase==="connected" && external) ? ("apps → " + external) : "";
    epEl.title = external || "";
    // Persist the live endpoint so other views (e.g. the /docs/*/usage per-service
    // samples) can show the SAME relay URL even before their own channel connects.
    if(phase==="connected" && external){ try{ localStorage.setItem("nano_relay_external", external); if(mode) localStorage.setItem("nano_relay_mode", mode); }catch(_){} }
    // Gentle GitHub-star nudge at natural moments: the first relayed request (a
    // "win") or the 30-min idle pause. Once per browser, dismissable, never blocks.
    if(served!=null && served>=1 && _prevServed<1) maybeNudge();
    if(phase==="idle" && _prevPhase!=="idle") maybeNudge();
    if(served!=null) _prevServed = served;
    _prevPhase = phase;
  }
  function appendLog(line, cls){ var d=document.createElement("div"); d.innerHTML = cls ? ('<span class="'+cls+'">'+(line||"")+'</span>') : (line||""); logEl.appendChild(d); logEl.scrollTop=logEl.scrollHeight; }
  function renderLogs(lines){ logEl.textContent=""; if(!lines||!lines.length){ appendLog("tunnel off — click “Start tunnel”.","dim"); return; } lines.forEach(function(l){ appendLog(l.line,l.cls); }); }
  logsBtn.onclick = function(){ logsPane.classList.toggle("open"); logsBtn.textContent = logsPane.classList.contains("open") ? "Logs ▾" : "Logs ▴"; };

  var ch = ("BroadcastChannel" in window) ? new BroadcastChannel("nano-relay") : null;
  if(ch) ch.onmessage = function(ev){ var m=ev.data||{}; if(m.type==="status"){ lastSeen=performance.now(); if(m.mode!==undefined) mode=m.mode; if(m.external!==undefined) external=m.external; if(m.note!==undefined) noteText=m.note; render(m.state,m.served); } else if(m.type==="log"){ appendLog(m.line,m.cls); } else if(m.type==="logs"){ renderLogs(m.lines); } };

  // The shared worker hosts the endpoint; the port carries start/stop/query.
  var worker=null, port=null, ok=false;
  try {
    worker = new SharedWorker(base + "/relay/relay-shared-worker.js?v=3", { type:"module", name:"nano-relay-v3" });
    port = worker.port; port.start();
    port.onmessage = function(ev){ var m=ev.data||{}; if(m.type==="logs") renderLogs(m.lines); else if(m.type==="status"){ if(m.mode!==undefined) mode=m.mode; if(m.external!==undefined) external=m.external; if(m.note!==undefined) noteText=m.note; render(m.state,m.served); } };
    ok = true;
  } catch(e){ ok = false; }

  function setIntent(on){ try{ on ? localStorage.setItem("nano_tunnel_on","1") : localStorage.removeItem("nano_tunnel_on"); }catch(_){} }
  function intentOn(){ try{ return localStorage.getItem("nano_tunnel_on")==="1"; }catch(_){ return false; } }
  toggleBtn.onclick = function(){
    if(!ok){ window.open(base + "/relay/nano-endpoint.html", "nano-relay-endpoint"); return; }   // fallback: standalone tab
    if(phase==="off" || phase==="idle"){ setIntent(true); render("connecting"); port.postMessage({type:"start", session:effSession(), config:CFG, noIdle:_signedIn}); logsPane.classList.add("open"); logsBtn.textContent="Logs ▾"; }
    else { setIntent(false); port.postMessage({type:"stop"}); render("off"); }
  };

  // ── GitHub-star nudge (gentle, one-time, never blocks) + persistent Star ────
  function starNudged(){ try{ return localStorage.getItem("nano_star_nudged")==="1" || localStorage.getItem("nano_starred")==="1"; }catch(_){ return false; } }
  function maybeNudge(){ if(starNudged()) return; var c=document.getElementById("nano-star"); if(c) c.style.display="block"; }
  function hideNudge(remember){ var c=document.getElementById("nano-star"); if(c) c.style.display="none"; if(remember){ try{ localStorage.setItem("nano_star_nudged","1"); }catch(_){} } }
  function markStarred(){ try{ localStorage.setItem("nano_starred","1"); }catch(_){} hideNudge(false); }
  // "More" in the tunnel bar → popup menu (Star / Connect apps / Conformance).
  var moreBtn = document.getElementById("nano-foot-more"), footMenu = document.getElementById("nano-foot-menu");
  function closeFootMenu(){ if(footMenu) footMenu.classList.remove("open"); }
  if(moreBtn && footMenu){
    moreBtn.addEventListener("click", function(e){ e.stopPropagation(); footMenu.classList.toggle("open"); });
    document.addEventListener("click", function(e){ if(footMenu.classList.contains("open") && !footMenu.contains(e.target) && !moreBtn.contains(e.target)) closeFootMenu(); });
    document.addEventListener("keydown", function(e){ if(e.key==="Escape") closeFootMenu(); });
  }
  var starBtn = document.getElementById("nano-menu-star");
  if(starBtn) starBtn.onclick = function(){ closeFootMenu(); window.open("https://github.com/vyomi-cloud/appliance","_blank","noopener"); markStarred(); };
  var nsGo = document.querySelector("#nano-star .ns-go"), nsLater = document.querySelector("#nano-star .ns-later"), nsX = document.querySelector("#nano-star .ns-x");
  if(nsGo) nsGo.addEventListener("click", markStarred);                       // the <a> opens the repo; we optimistically mark + hide
  if(nsLater) nsLater.addEventListener("click", function(){ hideNudge(true); });
  if(nsX) nsX.addEventListener("click", function(){ hideNudge(true); });
  refreshLicense(); setInterval(refreshLicense, 20000);   // sign-in perks: stable URL + no idle-pause
  if(ok){
    // The shared worker is RECREATED on same-tab navigation, so AUTO-RESUME: if the
    // user left the tunnel on, every view reconnects it automatically (it briefly
    // re-handshakes during the nav). Open the dashboard + a console in SEPARATE tabs
    // and the worker has overlapping clients → it stays continuously connected.
    if(intentOn()){ render("connecting"); port.postMessage({type:"start", session:effSession(), config:CFG, noIdle:_signedIn}); }
    port.postMessage({type:"query"});
    setInterval(function(){
      if(phase!=="off" && performance.now()-lastSeen>8000){ render("off"); if(intentOn()) port.postMessage({type:"start", session:effSession(), config:CFG, noIdle:_signedIn}); }
      port.postMessage({type:"query"});
    }, 3000);
  } else { toggleBtn.textContent = "Open relay endpoint ↗"; }

  // Conformance button lives in this bar (next to Logs) → toggles the docs pop-up.
  var confBtn = document.getElementById("nano-menu-conf"), docs = document.getElementById("nano-docs");
  if(confBtn && docs){
    confBtn.addEventListener("click", function(e){ e.stopPropagation(); closeFootMenu();
      var cd = document.getElementById("connect-dock"); if(cd) cd.classList.remove("open");   // one pop-up at a time
      docs.classList.toggle("open"); });
    document.addEventListener("click", function(e){ if(docs.classList.contains("open") && !docs.contains(e.target) && !confBtn.contains(e.target)) docs.classList.remove("open"); });
    document.addEventListener("keydown", function(e){ if(e.key==="Escape") docs.classList.remove("open"); });
  }
})();
</script>"""


# ── Nano-only chrome the portal's live Nano carries (back-ported from portal
# app/nano commits 7b9af7f, e5ba309, ca22cde, 1d8d434, 4359f3f) ──────────────
# Kept HERE (not in static/) because it's portal-context behaviour: the signed-in
# account comes from the portal's /api/auth/me and Sign out calls the portal's
# /api/auth/logout. The offline appliance pages stay untouched.

def _swap(html, old, new, page):
    """Exact, single-occurrence replace — fail the build loudly if static/ moved
    on, instead of silently shipping a page without the Nano chrome."""
    n = html.count(old)
    if n != 1:
        raise SystemExit(f"make_pages: expected 1 occurrence in {page}, found {n}: {old[:70]!r}")
    return html.replace(old, new, 1)


# Side menu: thin-stroke line icons (no icon font), chevron collapse toggle ON the
# sidebar/main separator, account menu at the foot. Overrides the appliance CSS.
_DASH_CSS = """  <style>
    /* Nano side menu (portal parity): line icons, separator chevron, account foot. */
    #app-body { position: relative; }
    #app-sidebar { overflow: visible; }
    .side-collapse {
      position: absolute; top: 16px; left: calc(216px - 13px); z-index: 60;
      width: 26px; height: 26px; border-radius: 50%; padding: 0; margin: 0;
      background: #121524; border: 1px solid #2b3350; color: #a7b0c4; cursor: pointer;
      display: grid; place-items: center; box-shadow: 0 2px 10px rgba(0,0,0,.5);
      transition: left .2s ease, color .12s, border-color .12s;
    }
    .side-collapse:hover { color: #fff; border-color: #6366f1; background: #161a2b; }
    .side-collapse .material-icons { font-size: 18px; transition: transform .16s; }
    body.side-collapsed .side-collapse .material-icons { transform: rotate(180deg); }
    body.side-collapsed .side-collapse { left: calc(68px - 13px); padding: 0; }
    .side-nav { flex: 1; overflow: hidden; }
    .side-item .side-ic { width: 18px; height: 18px; flex: none; display: grid; place-items: center; color: #6b7488; }
    .side-item:hover .side-ic { color: #e8ecf5; }
    .side-item.active .side-ic { color: #818cf8; }
    .side-item .side-ic svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    #app-sidebar .side-foot { margin-top: auto; padding-top: 10px; border-top: 1px solid #20263a; }
    .side-user-menu { position: relative; }
    .side-user { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border-radius: 9px; background: #121524; border: 1px solid #20263a; cursor: pointer; text-align: left; color: inherit; font-family: inherit; }
    .side-user:hover { border-color: #6366f1; }
    .side-user .av { width: 30px; height: 30px; border-radius: 50%; flex: none; overflow: hidden; background: #161a2b; display: grid; place-items: center; color: #e8ecf5; font-weight: 700; font-size: 12px; }
    .side-user .av img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .side-user .who { min-width: 0; flex: 1; }
    .side-user .who b { display: block; font-size: 12.5px; color: #e8ecf5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .side-user .who span { display: block; font-size: 11px; color: #6b7488; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .side-user .chev { width: 15px; height: 15px; flex: none; color: #6b7488; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; transition: transform .16s; }
    .side-user-menu.open .chev { transform: rotate(180deg); }
    .side-user-dd { position: absolute; left: 0; right: 0; bottom: calc(100% + 8px); background: #0f121c; border: 1px solid #2b3350; border-radius: 10px; box-shadow: 0 20px 45px -25px rgba(0,0,0,.8); padding: 6px; display: none; z-index: 1000; }
    .side-user-menu.open .side-user-dd { display: block; }
    .side-user-dd a, .side-user-dd button { display: flex; align-items: center; gap: 9px; width: 100%; text-align: left; padding: 9px 11px; border-radius: 7px; font-size: 13px; color: #a7b0c4; background: none; border: 0; cursor: pointer; font-weight: 500; font-family: inherit; text-decoration: none; }
    .side-user-dd a:hover, .side-user-dd button:hover { background: #121524; color: #e8ecf5; }
    .side-user-dd .signout { color: #fca5a5; }
    #app-sidebar .side-foot[hidden], .side-user-dd [hidden] { display: none !important; }
    .side-user-dd svg { width: 15px; height: 15px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    body.side-collapsed .side-user .who, body.side-collapsed .side-user .chev { display: none; }
    body.side-collapsed .side-user { width: 56px; height: 56px; padding: 0; margin: 0 auto; justify-content: center; background: transparent; border-color: transparent; }
    body.side-collapsed .side-user:hover { background: #121524; border-color: #6366f1; }
    body.side-collapsed .side-user-dd { left: 8px; right: auto; width: 208px; }
    /* SDK & CLI usage: exactly 2 cards per row (1 on phones). */
    #view-usage .u-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    @media (max-width: 600px) { #view-usage .u-grid { grid-template-columns: 1fr; } }
    /* The Spaces hero already carries "Activate appliance" — no second save CTA. */
    #save-chip { display: none !important; }
  </style>
</head>"""

_SIDE_ICONS = (
    # (old icon+label, new icon+label, old title, new title)
    ('<span class="material-icons">home</span><span class="side-label">Home</span>',
     '<span class="side-ic"><svg viewBox="0 0 24 24"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg></span><span class="side-label">Spaces</span>',
     'title="Home"', 'title="Spaces — your active spaces (home)"'),
    ('<span class="material-icons">dashboard</span><span class="side-label">Dashboard</span>',
     '<span class="side-ic"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6"/><rect x="12" y="8" width="3" height="10"/><rect x="17" y="4" width="3" height="14"/></svg></span><span class="side-label">Health</span>',
     'title="Dashboard"', 'title="Health — appliance at a glance"'),
    ('<span class="material-icons">menu_book</span><span class="side-label">Knowledge Center</span>',
     '<span class="side-ic"><svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></span><span class="side-label">Knowledge Center</span>',
     None, None),
    ('<span class="material-icons">terminal</span><span class="side-label">SDK &amp; CLI usage</span>',
     '<span class="side-ic"><svg viewBox="0 0 24 24"><path d="M4 17l6-6-6-6M12 19h8"/></svg></span><span class="side-label">SDK &amp; CLI usage</span>',
     None, None),
    ('<span class="material-icons">api</span><span class="side-label">API (Swagger)</span>',
     '<span class="side-ic"><svg viewBox="0 0 24 24"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/></svg></span><span class="side-label">API (Swagger)</span>',
     None, None),
)

_OLD_COLLAPSE = """    <button class="side-collapse" type="button" onclick="toggleSidebar()" aria-label="Collapse menu" title="Collapse / expand">
      <span class="material-icons">menu</span>
    </button>
"""

# Account menu at the side menu's foot. Starts hidden: it only appears once the
# portal answers /api/auth/me, so a bundle served without a portal (local dev,
# a plain static server) shows no dead button.
_SIDE_FOOT = """    <div class="side-foot" id="nanoSideFoot" hidden>
      <div class="side-user-menu" id="nanoUsrMenu">
        <div class="side-user-dd" id="nanoUsrDd">
          <button class="signout" id="nanoSignout" type="button" onclick="nanoLogout()"><svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>Sign out</button>
          <a class="signin" id="nanoSignin" href="/dashboard?next=%2Fnano%2F" hidden><svg viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3"/></svg>Sign in</a>
        </div>
        <button class="side-user" id="nanoUsrBtn" type="button" aria-label="Account menu">
          <div class="av" id="nanoAv">?</div>
          <div class="who"><b id="nanoName">Account</b><span id="nanoRole">Personal account</span></div>
          <svg class="chev" viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg>
        </button>
      </div>
    </div>
  </aside>
  <button class="side-collapse" type="button" onclick="toggleSidebar()" aria-label="Collapse / expand menu" title="Collapse / expand">
    <span class="material-icons">chevron_left</span>
  </button>"""

_DASH_JS = r"""<script>
/* Nano account menu (side-menu foot). XHR, not fetch: the base-path fetch shim
   rewrites window.fetch('/api/*') into /nano/api/*, which the in-tab service
   worker answers — so /api/auth/* would never reach the portal. XHR isn't
   shimmed, and /api/auth/* is outside the SW's /nano/ scope.
   - portal session  -> name + provider avatar, Sign out
   - portal, signed out (session expired) -> "Guest", Sign in
   - no portal (local dev / static server / non-JSON) -> the menu stays hidden */
(function(){
  var foot=document.getElementById('nanoSideFoot');
  function paintAccount(d){
    if(!d || typeof d.authenticated!=='boolean' || !foot) return;   // not the portal's /api/auth/me
    var out=document.getElementById('nanoSignout'), inn=document.getElementById('nanoSignin');
    var nm=document.getElementById('nanoName'), rl=document.getElementById('nanoRole'), av=document.getElementById('nanoAv');
    if(!d.authenticated){
      if(nm) nm.textContent='Guest'; if(rl) rl.textContent='Not signed in';
      if(out) out.hidden=true;
      if(inn){ inn.hidden=false; inn.href='/dashboard?next='+encodeURIComponent(location.pathname); }
      foot.hidden=false; return;
    }
    var email=d.email||''; var handle=email.split('@')[0]||'account';
    if(nm) nm.textContent=handle;
    if(rl) rl.textContent=d.is_admin?'Admin':'Personal account';
    if(av){
      if(d.avatar_url){
        av.textContent='';
        var im=new Image(); im.src=d.avatar_url; im.alt=handle; im.referrerPolicy='no-referrer';
        im.style.cssText='width:100%;height:100%;border-radius:inherit;object-fit:cover;display:block';
        im.onerror=function(){ av.textContent=(email[0]||'?').toUpperCase(); };
        av.appendChild(im);
      } else { av.textContent=(email[0]||'?').toUpperCase(); }
    }
    foot.hidden=false;
  }
  try {
    var _x=new XMLHttpRequest(); _x.open('GET','/api/auth/me',true); _x.withCredentials=true;
    _x.onload=function(){ if(_x.status!==200) return; try{ paintAccount(JSON.parse(_x.responseText)); }catch(e){} };
    _x.send();
  } catch(e){}
  var btn=document.getElementById('nanoUsrBtn'), menu=document.getElementById('nanoUsrMenu');
  if(btn&&menu){
    btn.addEventListener('click',function(e){ e.stopPropagation(); menu.classList.toggle('open'); });
    document.addEventListener('click',function(){ menu.classList.remove('open'); });
    menu.addEventListener('click',function(e){ e.stopPropagation(); });
  }
})();
function nanoLogout(){
  /* XHR (see above) so this reaches the portal and truly clears the cookie. */
  try {
    var l = new XMLHttpRequest();
    l.open('POST', '/api/auth/logout', true); l.withCredentials = true;
    l.onloadend = function(){ location.href = '/dashboard'; };
    l.send();
  } catch (e) { location.href = '/dashboard'; }
}
</script>
<script>
/* Nano install ping — RESILIENT. The launch page (/nano/ = index.html) redirects
   here before it renders, and the ping needs the service worker controlling to
   reach the portal (the SW forwards /api/install/register out of the /nano scope).
   So fire it here and retry until the SW controls. Same device fingerprint as
   index.html's nanoDeviceFp → the portal's idempotent upsert keeps one row per
   machine; the once-per-browser guard latches only on success. */
(function(){
  function done(){ try{ return localStorage.getItem("nano_install_recorded")==="1"; }catch(_){ return true; } }
  if(done()) return;
  async function nanoFp(){
    var gpu="";
    try{ var c=document.createElement("canvas"); var gl=c.getContext("webgl")||c.getContext("experimental-webgl");
      if(gl){ var e=gl.getExtension("WEBGL_debug_renderer_info"); if(e) gpu=gl.getParameter(e.UNMASKED_RENDERER_WEBGL)||""; } }catch(_){}
    var parts=[navigator.platform||"", navigator.hardwareConcurrency||"", navigator.deviceMemory||"",
      screen.width+"x"+screen.height+"x"+screen.colorDepth,
      (Intl.DateTimeFormat().resolvedOptions().timeZone)||"", navigator.language||"", gpu];
    try{ var buf=await crypto.subtle.digest("SHA-256", new TextEncoder().encode(parts.join("|")));
      return "nano-fp-"+Array.from(new Uint8Array(buf)).map(function(b){return b.toString(16).padStart(2,"0");}).join("").slice(0,24); }
    catch(_){ return null; }
  }
  var tries=0;
  async function attempt(){
    if(done()) return;
    tries++;
    try{
      var id=await nanoFp(); if(!id) return;
      var r=await fetch("/api/install/register",{method:"POST",keepalive:true,headers:{"Content-Type":"application/json"},
        body:JSON.stringify({install_id:id,channel:"nano",state:"DOWNLOADED",host_os:(navigator.platform||"").slice(0,32),webdriver:!!navigator.webdriver})});
      if(r&&r.ok){ try{ localStorage.setItem("nano_install_recorded","1"); }catch(_){} return; }
    }catch(_){}
    if(tries<6) setTimeout(attempt, 3000);
  }
  try{ if(navigator.serviceWorker) navigator.serviceWorker.addEventListener("controllerchange", attempt); }catch(_){}
  attempt();
})();
</script>
"""


def _nano_dashboard(html, page):
    """clouds.html → the portal's live Nano dashboard chrome (see block comment)."""
    html = _swap(html, "</head>", _DASH_CSS, page)
    html = _swap(html, _OLD_COLLAPSE, "", page)
    for old, new, t_old, t_new in _SIDE_ICONS:
        html = _swap(html, old, new, page)
        if t_old:   # the item's tooltip sits right before its (now swapped) icon
            html = _swap(html, f'{t_old}>{new}', f'{t_new}>{new}', page)
    html = _swap(html, "    </nav>\n  </aside>", "    </nav>\n" + _SIDE_FOOT, page)
    html = _swap(html, '<div class="hero-eyebrow">Dashboard</div>', '<div class="hero-eyebrow">Health</div>', page)
    html = _swap(html, "if (!APP_VIEWS[view]) view = 'workspace';", "if (!APP_VIEWS[view]) view = 'spaces';", page)
    i = html.rfind("</body>")
    return html[:i] + _DASH_JS + html[i:]


def _hide_console_account(btn_id):
    """aws/gcp consoles: hide the simulated header account button (it only toasts
    "Account is set by the active simulator space") — the portal's live Nano hides
    it (portal e5ba309); the signed-in account lives in the Spaces side menu."""
    def post(html, page):
        return _swap(html, '<script type="module" src="./nano-boot.js?v=4"></script>\n',
                     '<script type="module" src="./nano-boot.js?v=4"></script>\n'
                     f'<style>#{btn_id}{{display:none!important;}}</style>\n', page)
    return post


def _process(src_name, dst_name, inject, cloud=None, post=None):
    src = os.path.join(STATIC, src_name)
    with open(src) as f:
        html = f.read()
    if "</head>" not in html:
        raise SystemExit(f"no </head> in {src_name}")
    for a, b in LINKS.items():
        html = html.replace(a, b)
    # Keep the readiness strip (service-status tiles + top banner) but load it from
    # the bundle. It's fed by the Nano SW's /api/runtime/readiness + service-metrics
    # so Nano shows per-service status + live CPU/RAM identical to Lite/Pro/Max.
    html = html.replace('<script src="/assets/readiness-strip.js" defer></script>',
                        '<script src="./readiness-strip.js" defer></script>')
    # "Back to launch" → the Nano launch page (index.html); href="/" is rewritten
    # to "./" below, which resolves to the /nano/ landing (the launch page).
    # Make bundle-internal absolute refs relative so the SPA works under any mount
    # (web root OR the portal's /nano/). /api/* is handled by the runtime SHIM;
    # /docs/* + external links stay absolute (they point at the portal).
    for a, b in (
        ('src="/assets/', 'src="assets/'), ('href="/assets/', 'href="assets/'),
        ('href="/aws-console.html"', 'href="aws-console.html"'),
        ('href="/gcp-console.html"', 'href="gcp-console.html"'),
        ('href="/azure-console.html"', 'href="azure-console.html"'),
        ('href="/"', 'href="./"'),
    ):
        html = html.replace(a, b)
    # Inject the base-path fetch shim FIRST in <head> (before the page's scripts).
    if "__NANO_BASE" not in html:
        h = html.find("<head")
        end = html.find(">", h) if h != -1 else -1
        if end == -1:
            raise SystemExit(f"no <head> open tag in {src_name}")
        html = html[:end + 1] + "\n" + SHIM + html[end + 1:]
    if "nano-boot.js" not in html and "nano-sw.js" not in html:
        html = html.replace("</head>", inject, 1)
    # Floating Conformance-docs widget (API/SDK/Utility links to the portal).
    # Guard on the ELEMENT id (not a bare substring) so page markup that merely
    # references these ids (e.g. the Spaces "Connect apps" card) can't suppress it.
    if "</body>" in html and 'id="nano-docs"' not in html:
        html = html.replace("</body>", _docs_widget(cloud) + "</body>", 1)
    # Frozen relay-tunnel footer on EVERY view (dashboard + consoles), backed by
    # the shared-worker endpoint so the tunnel persists across navigation.
    if "</body>" in html and 'id="nano-foot"' not in html:
        html = html.replace("</body>", _footer_widget() + "</body>", 1)
    if post:
        html = post(html, src_name)
    dst = os.path.join(HERE, dst_name)
    with open(dst, "w") as f:
        f.write(html)
    print(f"{dst_name:24} <- {src_name:22} ({len(html)} bytes)")


def main():
    # Launch page -> the Nano landing (/nano/ = index.html), identical to Lite/Max/Pro.
    _process("pricing.html", "index.html", LAUNCH)
    # Workspaces dashboard (Appliance health / Host util / Spaces / KC) -> clouds.html.
    # + the portal's Nano chrome: side-menu account / Sign out, line icons, install ping.
    _process("clouds.html", "clouds.html", SW, post=_nano_dashboard)
    # The three SPA consoles, verbatim + Pyodide boot loader + per-cloud docs.
    _process("aws-console.html", "aws-console.html", BOOT, cloud="aws", post=_hide_console_account("acctBtn"))
    _process("gcp-console.html", "gcp-console.html", BOOT, cloud="gcp", post=_hide_console_account("avatarBtn"))
    _process("azure-console.html", "azure-console.html", BOOT, cloud="azure")
    # Ship the readiness strip verbatim (kept in the Nano dashboard, see SW/_process).
    import shutil
    shutil.copyfile(os.path.join(STATIC, "readiness-strip.js"),
                    os.path.join(HERE, "readiness-strip.js"))
    print(f"{'readiness-strip.js':24} <- static/readiness-strip.js (copied)")


if __name__ == "__main__":
    main()
