/* Connect-your-SDK/CLI card: Cloudflare relay snippet always, plus the local vyomi-tunnel snippet once a local tunnel is detected.
 * Needs the console's own vyCodeTabs(). Loaded as a classic script before the console's code runs. */
(function () {
  var ls = function (k) { try { return localStorage.getItem(k); } catch (_) { return null; } };
  var LOCAL_EP = function () { return ls("nano_local_ext") || "http://127.0.0.1:8090"; };
  var HEALTH = function () { return ls("nano_local_health") || (LOCAL_EP().replace(/\/$/, "") + "/health"); };
  var cloudEp = function () {
    var c = ls("nano_relay_cloud_ext"); if (c) return c;
    return "https://relay.vyomi.cloud/" + encodeURIComponent(ls("nano_session") || "nano");
  };
  function detectLocal() {
    return new Promise(function (res) {
      var done = false, t = setTimeout(function () { if (!done) { done = true; res(false); } }, 1500);
      try {
        fetch(HEALTH(), { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (j) {
          if (!done) { done = true; clearTimeout(t); res(!!(j && j.ok !== false)); }
        }).catch(function () { if (!done) { done = true; clearTimeout(t); res(false); } });
      } catch (_) { res(false); }
    });
  }
  /* o: {note, accent, build(ep) -> tabs} */
  window.vyConnectSwitch = function (o) {
    var root = document.createElement("div");
    var bar = document.createElement("div");
    var body = document.createElement("div");
    if (o.slot) {   // the toggle lives in the card header, right aligned (before the Info link when there is one)
      bar.style.cssText = "display:flex;align-items:center;margin-left:auto;margin-right:10px;font-weight:400";
      var info = o.slot.querySelector(".info");
      if (info) o.slot.insertBefore(bar, info); else o.slot.appendChild(bar);
    } else {
      bar.style.cssText = "display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-bottom:12px";
      root.appendChild(bar);
    }
    root.appendChild(body);
    var sel = (ls("nano_relay_mode") === "local") ? "local" : "cloud", local = false, drawn = "";
    function pill(id, label, on, dot, disabled) {   // segmented toggle switch: one rounded track, active segment filled
      var b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "switch"); b.setAttribute("aria-checked", String(on));
      b.disabled = !!disabled; if (disabled) b.title = "Not detected. Run vyomi-tunnel on this machine and keep this tab open.";
      b.style.cssText = "display:inline-flex;align-items:center;gap:6px;border:none;border-radius:6px;padding:5px 14px;font:inherit;font-size:12.5px;font-weight:600;transition:background .15s,color .15s;cursor:" + (disabled ? "not-allowed" : "pointer") + ";opacity:" + (disabled ? ".5" : "1") + ";background:" + (on ? o.accent : "transparent") + ";color:" + (on ? "#fff" : "var(--sub,#5f6b7a)") + ";box-shadow:" + (on ? "0 1px 2px rgba(0,0,0,.2)" : "none");
      if (dot) { var d = document.createElement("span"); d.style.cssText = "width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 2px " + (on ? "rgba(255,255,255,.35)" : "transparent"); b.appendChild(d); }
      b.appendChild(document.createTextNode(label));
      b.onclick = function () { if (disabled) return; sel = id; paint(); };
      return b;
    }
    function paint() {
      if (sel === "local" && !local) sel = "cloud";
      var key = sel + "|" + local + "|" + cloudEp();
      if (key === drawn) return; drawn = key;
      bar.innerHTML = "";
      var track = document.createElement("div"); track.setAttribute("role", "group");
      track.style.cssText = "display:inline-flex;gap:2px;padding:3px;border-radius:9px;background:var(--hover,#eef0f3);border:1px solid var(--line,#e5e7eb)";
      track.appendChild(pill("cloud", "Cloudflare tunnel", sel === "cloud", false, false));
      track.appendChild(pill("local", "Local tunnel", sel === "local", local, !local));
      bar.appendChild(track);
      body.innerHTML = "";
      var ep = sel === "local" ? LOCAL_EP().replace(/\/$/, "") : cloudEp();
      var note = sel === "local"
        ? "Local tunnel detected on this machine: fastest, and traffic stays private. Keep this Nano tab open."
        : (o.note || "Start the tunnel (bottom bar) to reach this browser tab from your CLI or SDK. Works from anywhere.");
      body.appendChild(window.vyCodeTabs({ note: note, accent: o.accent, tabs: o.build(ep) }));
      // Both endpoints, always visible: the local URL alone is not enough (other machines, CI, containers need the Cloudflare one).
      var eps = document.createElement("div"); eps.style.cssText = "margin-top:10px;display:flex;flex-direction:column;gap:6px";
      function epRow(label, url, active, hint) {
        var r = document.createElement("div");
        r.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid var(--line,#e5e7eb);border-radius:6px;font-size:12px;background:" + (active ? "var(--hover,#f4f6f8)" : "transparent");
        var l = document.createElement("span"); l.style.cssText = "min-width:96px;font-weight:600;color:var(--sub,#5f6b7a)"; l.textContent = label;
        var u = document.createElement("code"); u.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px"; u.textContent = url; u.title = hint;
        var c = document.createElement("button"); c.type = "button"; c.textContent = "Copy"; c.style.cssText = "border:1px solid var(--line,#e5e7eb);border-radius:5px;background:#fff;padding:2px 10px;font:inherit;font-size:11.5px;cursor:pointer";
        c.onclick = function () { try { navigator.clipboard.writeText(url); c.textContent = "Copied"; setTimeout(function () { c.textContent = "Copy"; }, 1200); } catch (_) {} };
        r.appendChild(l); r.appendChild(u); r.appendChild(c); return r;
      }
      eps.appendChild(epRow("Cloudflare", cloudEp(), sel === "cloud", "Works from anywhere: other machines, CI, containers"));
      eps.appendChild(epRow("Local tunnel", LOCAL_EP().replace(/\/$/, ""), sel === "local", local ? "Fastest, private, this machine only" : "Not detected: run vyomi-tunnel on this machine"));
      body.appendChild(eps);
    }
    function tick() {
      if (!root.isConnected && drawn) { return; }
      detectLocal().then(function (ok) { local = ok; paint(); });
    }
    paint(); tick();
    var iv = setInterval(function () { if (!root.isConnected) { clearInterval(iv); return; } tick(); }, 4000);
    return root;
  };
})();
