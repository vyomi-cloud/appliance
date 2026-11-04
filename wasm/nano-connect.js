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
    var bar = document.createElement("div"); bar.style.cssText = "display:flex;gap:22px;border-bottom:1px solid var(--line,#e5e7eb);margin-bottom:12px";
    var body = document.createElement("div");
    root.appendChild(bar); root.appendChild(body);
    var sel = (ls("nano_relay_mode") === "local") ? "local" : "cloud", local = false, drawn = "";
    function pill(id, label, on, dot) {   // classic cloud-console tab: text + underline, same as the CLI tabs below
      var b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(on));
      b.style.cssText = "display:inline-flex;align-items:center;gap:6px;border:none;background:none;padding:8px 2px 9px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;color:" + (on ? o.accent : "var(--sub,#5f6b7a)") + ";box-shadow:" + (on ? "inset 0 -3px 0 " + o.accent : "none");
      if (dot) { var d = document.createElement("span"); d.style.cssText = "width:7px;height:7px;border-radius:50%;background:#22c55e"; b.appendChild(d); }
      b.appendChild(document.createTextNode(label));
      b.onclick = function () { sel = id; paint(); };
      return b;
    }
    function paint() {
      if (sel === "local" && !local) sel = "cloud";
      var key = sel + "|" + local + "|" + cloudEp();
      if (key === drawn) return; drawn = key;
      bar.innerHTML = "";
      bar.appendChild(pill("cloud", "Cloudflare tunnel", sel === "cloud", false));
      if (local) bar.appendChild(pill("local", "Local tunnel", sel === "local", true));
      body.innerHTML = "";
      var ep = sel === "local" ? LOCAL_EP().replace(/\/$/, "") : cloudEp();
      var note = sel === "local"
        ? "Local tunnel detected on this machine: fastest, and traffic stays private. Keep this Nano tab open."
        : (o.note || "Start the tunnel (bottom bar) to reach this browser tab from your CLI or SDK. Works from anywhere.");
      body.appendChild(window.vyCodeTabs({ note: note, accent: o.accent, tabs: o.build(ep) }));
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
