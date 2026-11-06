/* "Share feedback" — floating button in every Vyomi v4 cloud console (Nano + offline appliance).
 * A text field and a Submit button; nothing else is collected beyond what is listed in `ctx()` below (no account data, no email).
 * Sends POST {origin}/api/feedback ({text, cloud, substrate, page, version, ua}). If the endpoint is unreachable (offline, local preview)
 * the note is kept in localStorage `vyomi.feedback.queue` and re-sent on the next page load — the user is told which happened. */
(function () {
  if (window.__vyFeedback) return; window.__vyFeedback = true;
  var QUEUE = "vyomi.feedback.queue", MAX = 2000;
  var cloud = (location.pathname.match(/\/v4\/(aws|gcp|azure)\b/) || [])[1] || (location.pathname.match(/(aws|gcp|azure)/) || [])[1] || "";
  function substrate() { var m = document.querySelector('meta[name="vyomi-substrate"]'); return (m && m.content) || "unknown"; }
  function ctx(text) { return { text: text, cloud: cloud, substrate: substrate(), page: (location.hash || "").slice(0, 200), ua: navigator.userAgent.slice(0, 200) }; }
  function readQ() { try { return JSON.parse(localStorage.getItem(QUEUE) || "[]"); } catch (_) { return []; } }
  function writeQ(q) { try { localStorage.setItem(QUEUE, JSON.stringify(q.slice(-20))); } catch (_) {} }
  function post(body) {
    return fetch("/api/feedback", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return true; });
  }
  function flush() { var q = readQ(); if (!q.length) return; writeQ([]); q.forEach(function (b) { post(b).catch(function () { writeQ(readQ().concat([b])); }); }); }

  var css = document.createElement("style");
  css.textContent =
    ".vyfb-btn{position:fixed;right:16px;bottom:64px;z-index:2147483000;display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border:1px solid rgba(127,127,127,.35);border-radius:999px;background:#111827;color:#fff;font:600 13px/1 system-ui,-apple-system,Segoe UI,sans-serif;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25)}" +
    ".vyfb-btn:hover{background:#1f2937}.vyfb-btn:focus-visible,.vyfb-x:focus-visible,.vyfb-send:focus-visible,.vyfb-ta:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}" +
    ".vyfb-pop{position:fixed;right:16px;bottom:110px;z-index:2147483001;width:min(340px,calc(100vw - 32px));padding:14px;border:1px solid rgba(127,127,127,.35);border-radius:12px;background:#fff;color:#111827;font:14px/1.4 system-ui,-apple-system,Segoe UI,sans-serif;box-shadow:0 12px 32px rgba(0,0,0,.28)}" +
    ".vyfb-pop[hidden]{display:none}.vyfb-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-weight:700}" +
    ".vyfb-x{border:0;background:none;font-size:20px;line-height:1;cursor:pointer;color:inherit;padding:2px 6px}" +
    ".vyfb-ta{box-sizing:border-box;width:100%;min-height:96px;resize:vertical;padding:8px;border:1px solid rgba(127,127,127,.5);border-radius:8px;font:inherit;background:#fff;color:#111827}" +
    ".vyfb-row{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:8px}.vyfb-msg{font-size:12px;opacity:.85;flex:1}" +
    ".vyfb-send{padding:7px 14px;border:0;border-radius:8px;background:#2563eb;color:#fff;font:600 13px system-ui;cursor:pointer}.vyfb-send:disabled{opacity:.5;cursor:default}" +
    "@media (prefers-color-scheme:dark){.vyfb-pop{background:#1f2937;color:#f3f4f6}.vyfb-ta{background:#111827;color:#f3f4f6}}";
  document.head.appendChild(css);

  var btn = document.createElement("button"); btn.type = "button"; btn.className = "vyfb-btn"; btn.setAttribute("aria-haspopup", "dialog"); btn.textContent = "💬 Share feedback";
  var pop = document.createElement("div"); pop.className = "vyfb-pop"; pop.hidden = true; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Share feedback");
  pop.innerHTML = '<div class="vyfb-h"><span>Share feedback</span><button type="button" class="vyfb-x" aria-label="Close">×</button></div>' +
    '<textarea class="vyfb-ta" maxlength="' + MAX + '" placeholder="What is working, what is missing, what is broken?" aria-label="Your feedback"></textarea>' +
    '<div class="vyfb-row"><span class="vyfb-msg" role="status"></span><button type="button" class="vyfb-send" disabled>Submit</button></div>';
  document.body.appendChild(btn); document.body.appendChild(pop);
  var ta = pop.querySelector(".vyfb-ta"), send = pop.querySelector(".vyfb-send"), msg = pop.querySelector(".vyfb-msg"), x = pop.querySelector(".vyfb-x");

  function open() { pop.hidden = false; ta.focus(); }
  function close() { pop.hidden = true; btn.focus(); }
  btn.onclick = function () { pop.hidden ? open() : close(); };
  x.onclick = close;
  pop.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  ta.addEventListener("input", function () { send.disabled = !ta.value.trim(); msg.textContent = ""; });
  send.onclick = function () {
    var text = ta.value.trim(); if (!text) return;
    var body = ctx(text); send.disabled = true; msg.textContent = "Sending…";
    post(body).then(function () { ta.value = ""; msg.textContent = "Thanks — sent."; setTimeout(close, 1200); },
      function () { writeQ(readQ().concat([body])); ta.value = ""; msg.textContent = "Saved on this device; it will be sent when the service is reachable."; setTimeout(close, 2200); });
  };
  flush();
})();
