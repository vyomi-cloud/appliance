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
      var aws = o.theme === "aws";   // classic AWS console look: 30px button-group, #687078 outline, AWS orange (.btn.primary) when selected
      var gcp = o.theme === "gcp";   // Google Cloud console (Material 3): outlined pill group, selected segment = filled blue-tint with a check
      if (gcp) {
        b.style.cssText = "display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 16px;font-family:'Google Sans',Roboto,Arial,sans-serif;font-size:14px;font-weight:500;letter-spacing:.1px;margin:0;border:1px solid var(--m3-outline,#747775);" +
          "border-radius:" + (id === "cloud" ? "16px 0 0 16px" : "0 16px 16px 0") + ";" + (id === "local" ? "margin-left:-1px;" : "") + "position:relative;" +
          "cursor:" + (disabled ? "not-allowed" : "pointer") + ";opacity:" + (disabled ? ".5" : "1") + ";background:" + (on ? "#d3e3fd" : "transparent") + ";color:" + (on ? "#041e49" : "#1f1f1f");
        if (on) { var ck = document.createElement("span"); ck.textContent = "\u2713"; ck.style.cssText = "font-size:15px;line-height:1"; b.appendChild(ck); }
      } else if (o.theme === "azure") {   // Azure portal (Fluent): 32px, 2px radius, Segoe UI; selected = primary Azure blue, white text
        b.style.cssText = "display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 16px;font-family:'Segoe UI',Roboto,Arial,sans-serif;font-size:14px;font-weight:600;margin:0;border:1px solid " + (on ? "#0078d4" : "#8a8886") +
          ";border-radius:" + (id === "cloud" ? "2px 0 0 2px" : "0 2px 2px 0") + ";" + (id === "local" ? "margin-left:-1px;" : "") + "position:relative;z-index:" + (on ? 1 : 0) +
          ";cursor:" + (disabled ? "not-allowed" : "pointer") + ";opacity:" + (disabled ? ".5" : "1") + ";background:" + (on ? "#0078d4" : "#fff") + ";color:" + (on ? "#fff" : "#201f1e");
      } else if (aws) {
        b.style.cssText = "display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 14px;font:inherit;font-size:13px;font-weight:600;margin:0;border:1px solid " + (on ? "var(--orange-d,#ec7211)" : "#687078") +
          ";border-radius:" + (id === "cloud" ? "6px 0 0 6px" : "0 6px 6px 0") + ";" + (id === "local" ? "margin-left:-1px;" : "") + "position:relative;z-index:" + (on ? 1 : 0) +
          ";cursor:" + (disabled ? "not-allowed" : "pointer") + ";opacity:" + (disabled ? ".5" : "1") + ";background:" + (on ? "var(--orange,#ff9900)" : "#fff") + ";color:" + (on ? "#000" : "var(--ink,#16191f)");
      } else
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
      track.style.cssText = (o.theme === "aws" || o.theme === "gcp" || o.theme === "azure") ? "display:inline-flex" : "display:inline-flex;gap:2px;padding:3px;border-radius:9px;background:var(--hover,#eef0f3);border:1px solid var(--line,#e5e7eb)";
      track.appendChild(pill("cloud", "Cloudflare tunnel", sel === "cloud", false, false));
      track.appendChild(pill("local", "Local tunnel", sel === "local", local, !local));
      bar.appendChild(track);
      body.innerHTML = "";
      var ep = sel === "local" ? LOCAL_EP().replace(/\/$/, "") : cloudEp();
      var note = sel === "local"
        ? "Local tunnel detected on this machine: fastest, and traffic stays private. Keep this Nano tab open."
        : (o.note || "Start the tunnel (bottom bar) to reach this browser tab from your CLI or SDK. Works from anywhere.");
      body.appendChild(window.vyCodeTabs({ note: note, accent: o.accent, tabs: o.build(ep) }));
      // Only the endpoint for the selected tunnel is shown (the toggle above chooses which).
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
      if (sel === "local") eps.appendChild(epRow("Local tunnel", LOCAL_EP().replace(/\/$/, ""), true, "Fastest, private, this machine only"));
      else eps.appendChild(epRow("Cloudflare", cloudEp(), true, "Works from anywhere: other machines, CI, containers"));
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

/* Models panel: the mesh's AI model pool (10 open models). Feeds on GET /api/mesh/models
 *   {models:[{id,name,role,tag,state,tokens_per_s_indicative,endpoints:{bedrock,vertex,azure}}], window_deadline | window:{deadline,left_s,label}}
 * 404 / no Mesh -> clearly labelled sample data and the test-chat box is hidden. Development and accuracy checks only; no benchmark claims. */
(function () {
  var MOCK = [
    ["qwen2.5-3b", "Qwen2.5 3B", "Fast chat", "qwen2.5:3b"], ["nomic-embed-text", "Nomic Embed Text", "Embeddings", "nomic-embed-text"],
    ["qwen2.5-7b", "Qwen2.5 7B", "General", "qwen2.5:7b"], ["qwen2.5-coder-7b", "Qwen2.5 Coder 7B", "Code", "qwen2.5-coder:7b"],
    ["llama3.1-8b", "Llama 3.1 8B", "Tool use / agents", "llama3.1:8b"], ["gemma2-9b", "Gemma 2 9B", "Second family", "gemma2:9b"],
    ["qwen3-8b", "Qwen3 8B", "Newer general", "qwen3:8b"], ["deepseek-r1-8b", "DeepSeek R1 8B", "Reasoning", "deepseek-r1:8b"],
    ["mistral-7b", "Mistral 7B", "Another family", "mistral:7b"], ["qwen3-30b", "Qwen3 30B MoE", "Pooled over 2 machines", "qwen3:30b"]
  ];
  var COLORS = { starting: "#d97706", ready: "#16a34a", rotating: "#2563eb", draining: "#9a6700", stopped: "#71717a" };
  function mockData() {
    var states = ["ready", "ready", "ready", "ready", "ready", "ready", "starting", "rotating", "ready", "starting"];
    return { sample: true, window_deadline: Date.now() / 1000 + 28 * 3600 + 40 * 60, models: MOCK.map(function (m, i) {
      return { id: m[0], name: m[1], role: m[2], tag: m[3], state: states[i], tokens_per_s_indicative: null, endpoints: {} };
    }) };
  }
  function esc(x) { return String(x == null ? "" : x).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function deadlineOf(j) {
    var d = j.window_deadline != null ? j.window_deadline : (j.window && (j.window.deadline != null ? j.window.deadline : null));
    if (d == null && j.window && j.window.left_s != null) return Date.now() / 1000 + Number(j.window.left_s);
    if (typeof d === "string") { var t = Date.parse(d); return isFinite(t) ? t / 1000 : null; }
    return d == null ? null : Number(d);
  }
  function fmt(sec) { if (sec <= 0) return "ended"; var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60); return h + "h " + (m < 10 ? "0" : "") + m + "m left"; }
  function getModels() {
    var B = window.VyomiMesh;
    var viaMesh = B && B.apiFetch ? B.apiFetch("/api/mesh/models", { cache: "no-store" }).catch(function () { return null; }) : Promise.resolve(null);
    return viaMesh.then(function (r) { if (r && r.ok) return r; return fetch("/api/mesh/models", { credentials: "same-origin", cache: "no-store" }).catch(function () { return null; }); })
      .then(function (r) { if (r && r.ok) return r.json().then(function (j) { return Array.isArray(j) ? { models: j } : j; }); return mockData(); })
      .catch(function () { return mockData(); });
  }
  window.vyModelsPanel = function (opts) {
    opts = opts || {};
    var root = document.createElement("div"); root.className = "vy-models";
    root.style.cssText = "font:13px/1.45 system-ui,sans-serif;color:var(--vm-ink,#16191f)"; if (opts.dark) { root.style.setProperty("--vm-ink", "#e6e8ee"); root.style.setProperty("--vm-sub", "#9aa3b5"); root.style.setProperty("--vm-line", "rgba(255,255,255,.16)"); root.style.setProperty("--vm-bg", "transparent"); }
    var data = null, open = {}, timer = null, tick = null;
    function chip(st) { var c = COLORS[st] || COLORS.stopped; return '<span style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;color:' + c + '"><span style="width:8px;height:8px;border-radius:50%;background:' + c + '"></span>' + esc(st) + "</span>"; }
    function paint() {
      if (!data) { root.textContent = "Loading models..."; return; }
      var dl = deadlineOf(data), sample = !!data.sample;
      var h = '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px"><strong>Model pool</strong><span class="vm-left" style="color:var(--vm-sub,#5f6b7a)">' + (dl ? fmt(dl - Date.now() / 1000) : "") + "</span></div>";
      if (sample) h += '<div style="padding:6px 10px;border:1px dashed var(--vm-line,#e5e7eb);border-radius:6px;margin-bottom:8px;color:var(--vm-sub,#5f6b7a);font-size:12px">Sample data: the model pool is not attached. Start the Mesh (Pro or Max) to see live models.</div>';
      h += '<div style="border:1px solid var(--vm-line,#e5e7eb);border-radius:8px;overflow:hidden">';
      (data.models || []).forEach(function (m, i) {
        var ready = m.state === "ready" && !sample && m.tag !== "nomic-embed-text";
        h += '<div style="padding:8px 12px;' + (i ? "border-top:1px solid var(--vm-line,#e5e7eb);" : "") + '"><div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
          + '<div style="flex:1;min-width:150px"><div style="font-weight:600">' + esc(m.name || m.id) + '</div><div style="color:var(--vm-sub,#5f6b7a);font-size:12px">' + esc(m.role || "") + (m.tag ? " &middot; <code>" + esc(m.tag) + "</code>" : "") + "</div></div>"
          + chip(m.state || "stopped")
          + (m.tokens_per_s_indicative ? '<span title="Indicative only, not a benchmark" style="font-size:11.5px;color:var(--vm-sub,#5f6b7a)">~' + Number(m.tokens_per_s_indicative).toFixed(0) + " tok/s</span>" : "")
          + (ready ? '<button type="button" data-chat="' + esc(m.id) + '" style="border:1px solid var(--vm-line,#e5e7eb);border-radius:5px;background:var(--vm-bg,#fff);color:inherit;padding:2px 10px;font:inherit;font-size:12px;cursor:pointer">' + (open[m.id] ? "Close" : "Test chat") + "</button>" : "")
          + "</div>";
        if (ready && open[m.id]) h += '<div data-box="' + esc(m.id) + '" style="margin-top:8px"><div class="vm-out" style="min-height:20px;max-height:140px;overflow:auto;white-space:pre-wrap;color:var(--vm-sub,#5f6b7a);margin-bottom:6px"></div><div style="display:flex;gap:6px"><input type="text" placeholder="Ask this model something" style="flex:1;min-width:0;border:1px solid var(--vm-line,#e5e7eb);border-radius:5px;padding:5px 8px;font:inherit"><button type="button" data-send="' + esc(m.id) + '" style="border:1px solid var(--vm-line,#e5e7eb);border-radius:5px;background:var(--vm-bg,#fff);color:inherit;padding:4px 12px;font:inherit;cursor:pointer">Send</button></div></div>';
        h += "</div>";
      });
      h += '</div><div style="margin-top:8px;color:var(--vm-sub,#5f6b7a);font-size:11.5px">For development and accuracy checks. Speed is indicative only, not a benchmark.</div>';
      var keep = {}; root.querySelectorAll("input").forEach(function (inp) { var b = inp.closest("[data-box]"); if (b) keep[b.getAttribute("data-box")] = inp.value; });
      root.innerHTML = h;
      root.querySelectorAll("input").forEach(function (inp) { var b = inp.closest("[data-box]"); if (b && keep[b.getAttribute("data-box")]) inp.value = keep[b.getAttribute("data-box")]; });
    }
    root.addEventListener("click", function (e) {
      var t = e.target.closest("button"); if (!t) return;
      var id = t.getAttribute("data-chat");
      if (id) { open[id] = !open[id]; paint(); return; }
      id = t.getAttribute("data-send");
      if (id) {
        var box = root.querySelector('[data-box="' + id + '"]'), inp = box.querySelector("input"), out = box.querySelector(".vm-out"), q = inp.value.trim();
        if (!q) return; out.textContent = "..."; inp.value = "";
        window.VyomiMesh.apiFetch("/v1/chat/completions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ model: id, messages: [{ role: "user", content: q }], stream: false }) })
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (r) { out.textContent = r.ok && r.j.choices ? r.j.choices[0].message.content : ((r.j && r.j.error && (r.j.error.message || r.j.error.code)) || "The model is not ready yet. Try again shortly."); })
          .catch(function () { out.textContent = "Could not reach the Mesh."; });
      }
    });
    function load() { if (!root.isConnected && data) { clearInterval(timer); clearInterval(tick); return; } getModels().then(function (j) { data = j; if (!root.querySelector("input:focus")) paint(); }); }
    paint(); load();
    timer = setInterval(load, 5000);
    tick = setInterval(function () { var el = root.querySelector(".vm-left"); if (el && data) { var dl = deadlineOf(data); if (dl) el.textContent = fmt(dl - Date.now() / 1000); } }, 30000);
    return root;
  };
})();
