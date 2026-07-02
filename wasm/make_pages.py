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
    "/console/aws": "aws-console.html",
    "/console/gcp": "gcp-console.html",
    "/console/azure": "azure-console.html",
    '"/ui#spaces"': '"clouds.html#spaces"',  # console "back to spaces" -> dashboard, Spaces view (must precede "/ui")
    '"/ui"': '"clouds.html"',      # "back to spaces/dashboard" -> the workspaces dashboard
    '"/clouds"': '"clouds.html"',   # Nano: launch = index.html, dashboard = clouds.html
}

# Relative src so the boot loader resolves under any mount point.
BOOT = '  <script type="module" src="./nano-boot.js"></script>\n</head>'  # consoles: Pyodide + SW
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
 #nano-docs{{position:fixed;right:16px;bottom:52px;z-index:99998;font:13px system-ui,-apple-system,sans-serif}}
 #nano-docs .pill{{background:#0d1030;color:#e4e4e7;border:1px solid #2a2f55;border-radius:999px;padding:8px 14px;cursor:pointer;box-shadow:0 6px 18px rgba(0,0,0,.35);user-select:none}}
 #nano-docs .pop{{position:absolute;right:0;bottom:42px;background:#0d1030;border:1px solid #2a2f55;border-radius:12px;padding:6px;min-width:218px;display:none;box-shadow:0 12px 34px rgba(0,0,0,.45)}}
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
</style>
<div id="nano-logs"><div class="h">Relay endpoint — runs in a shared worker, stays connected across views. Logs:</div><pre id="nano-foot-log"><span class="dim">tunnel off — click “Start tunnel”.</span></pre></div>
<div id="nano-foot" title="Relay tunnel — lets an external SDK/CLI reach this in-browser sim">
 <span class="dot"></span><span class="lbl">Relay tunnel: off</span>
 <span class="ep" id="nano-foot-ep"></span>
 <span class="sp"></span>
 <button id="nano-foot-logs">Logs ▴</button>
 <button id="nano-foot-toggle">Start tunnel</button>
</div>
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
  var foot = document.getElementById("nano-foot"), lbl = foot.querySelector(".lbl");
  var epEl = document.getElementById("nano-foot-ep"), logsPane = document.getElementById("nano-logs"), logEl = document.getElementById("nano-foot-log");
  var toggleBtn = document.getElementById("nano-foot-toggle"), logsBtn = document.getElementById("nano-foot-logs");
  var phase = "off", lastSeen = 0, mode = null, external = null, noteText = null;
  document.body.style.paddingBottom = "40px";   // never cover page content

  function render(state, served){
    phase = state || "off";
    foot.classList.remove("up","connecting");
    var via = mode ? (mode==="local" ? " · local (fast · private)" : " · cloud (Cloudflare)") : "";
    if(phase==="connected"){ foot.classList.add("up"); lbl.textContent = "Relay tunnel: connected" + via + (served!=null?(" · "+served+" served"):""); toggleBtn.textContent="Stop"; }
    // A `note` from the worker (e.g. "no local tunnel — run `vyomi-tunnel`") means
    // the tunnel can't connect — show it in the label instead of a forever spinner.
    else if(phase==="connecting"){ foot.classList.add("connecting"); lbl.textContent = noteText ? ("Relay tunnel: " + noteText) : ("Relay tunnel: connecting…" + via); toggleBtn.textContent="Stop"; }
    else { lbl.textContent = "Relay tunnel: off"; toggleBtn.textContent="Start tunnel"; }
    epEl.textContent = (phase==="connected" && external) ? ("apps → " + external) : "";
    epEl.title = external || "";
  }
  function appendLog(line, cls){ var d=document.createElement("div"); d.innerHTML = cls ? ('<span class="'+cls+'">'+(line||"")+'</span>') : (line||""); logEl.appendChild(d); logEl.scrollTop=logEl.scrollHeight; }
  function renderLogs(lines){ logEl.textContent=""; if(!lines||!lines.length){ appendLog("tunnel off — click “Start tunnel”.","dim"); return; } lines.forEach(function(l){ appendLog(l.line,l.cls); }); }
  logsBtn.onclick = function(){ logsPane.classList.toggle("open"); logsBtn.textContent = logsPane.classList.contains("open") ? "Logs ▾" : "Logs ▴"; };

  var ch = ("BroadcastChannel" in window) ? new BroadcastChannel("nano-relay") : null;
  if(ch) ch.onmessage = function(ev){ var m=ev.data||{}; if(m.type==="status"){ lastSeen=performance.now(); if(m.mode!==undefined) mode=m.mode; if(m.external!==undefined) external=m.external; if(m.note!==undefined) noteText=m.note; render(m.state,m.served); } else if(m.type==="log"){ appendLog(m.line,m.cls); } else if(m.type==="logs"){ renderLogs(m.lines); } };

  // The shared worker hosts the endpoint; the port carries start/stop/query.
  var worker=null, port=null, ok=false;
  try {
    worker = new SharedWorker(base + "/relay/relay-shared-worker.js", { type:"module", name:"nano-relay" });
    port = worker.port; port.start();
    port.onmessage = function(ev){ var m=ev.data||{}; if(m.type==="logs") renderLogs(m.lines); else if(m.type==="status"){ if(m.mode!==undefined) mode=m.mode; if(m.external!==undefined) external=m.external; if(m.note!==undefined) noteText=m.note; render(m.state,m.served); } };
    ok = true;
  } catch(e){ ok = false; }

  function setIntent(on){ try{ on ? localStorage.setItem("nano_tunnel_on","1") : localStorage.removeItem("nano_tunnel_on"); }catch(_){} }
  function intentOn(){ try{ return localStorage.getItem("nano_tunnel_on")==="1"; }catch(_){ return false; } }
  toggleBtn.onclick = function(){
    if(!ok){ window.open(base + "/relay/nano-endpoint.html", "nano-relay-endpoint"); return; }   // fallback: standalone tab
    if(phase==="off"){ setIntent(true); render("connecting"); port.postMessage({type:"start", session:SESSION, config:CFG}); logsPane.classList.add("open"); logsBtn.textContent="Logs ▾"; }
    else { setIntent(false); port.postMessage({type:"stop"}); render("off"); }
  };
  if(ok){
    // The shared worker is RECREATED on same-tab navigation, so AUTO-RESUME: if the
    // user left the tunnel on, every view reconnects it automatically (it briefly
    // re-handshakes during the nav). Open the dashboard + a console in SEPARATE tabs
    // and the worker has overlapping clients → it stays continuously connected.
    if(intentOn()){ render("connecting"); port.postMessage({type:"start", session:SESSION, config:CFG}); }
    port.postMessage({type:"query"});
    setInterval(function(){
      if(phase!=="off" && performance.now()-lastSeen>8000){ render("off"); if(intentOn()) port.postMessage({type:"start", session:SESSION, config:CFG}); }
      port.postMessage({type:"query"});
    }, 3000);
  } else { toggleBtn.textContent = "Open relay endpoint ↗"; }
})();
</script>"""


def _process(src_name, dst_name, inject, cloud=None):
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
    dst = os.path.join(HERE, dst_name)
    with open(dst, "w") as f:
        f.write(html)
    print(f"{dst_name:24} <- {src_name:22} ({len(html)} bytes)")


def main():
    # Launch page -> the Nano landing (/nano/ = index.html), identical to Lite/Max/Pro.
    _process("pricing.html", "index.html", LAUNCH)
    # Workspaces dashboard (Appliance health / Host util / Spaces / KC) -> clouds.html.
    _process("clouds.html", "clouds.html", SW)
    # The three SPA consoles, verbatim + Pyodide boot loader + per-cloud docs.
    _process("aws-console.html", "aws-console.html", BOOT, cloud="aws")
    _process("gcp-console.html", "gcp-console.html", BOOT, cloud="gcp")
    _process("azure-console.html", "azure-console.html", BOOT, cloud="azure")
    # Ship the readiness strip verbatim (kept in the Nano dashboard, see SW/_process).
    import shutil
    shutil.copyfile(os.path.join(STATIC, "readiness-strip.js"),
                    os.path.join(HERE, "readiness-strip.js"))
    print(f"{'readiness-strip.js':24} <- static/readiness-strip.js (copied)")


if __name__ == "__main__":
    main()
