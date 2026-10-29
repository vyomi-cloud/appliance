/* Vyomi Nano — boot screen ("nano kernel").
 *
 * Shown on EVERY launch of the dashboard and the consoles, drawn by the first
 * script in <body> so nothing can hide it, and closed the moment the page is
 * ready. It prints the REAL boot steps with their real timings (the callers in
 * clouds.html and nano-boot.js report them); there is no scripted animation of
 * fake work. Carries its log across the one automatic reload Nano does when a
 * page first loads without its service worker.
 *
 * Off: ?nokernel=1, localStorage["vyomi.nano.kernel"]="off", or an automated
 * browser (navigator.webdriver; force with ?kernel=1). Esc / click skips it.
 *
 *   const k = NanoKernel.start("AWS console");
 *   const s = k.step("kernel", "loading Pyodide"); …; s.ok("CPython 3.12 → WebAssembly");
 *   k.carry();            // before a reload
 *   k.ready("console ready");
 */
(function () {
  "use strict";
  var KEY = "nano-kernel-log", MIN_MS = 1200;
  var noop = { step: function () { return { ok: function () {}, fail: function () {} }; },
               info: function () {}, carry: function () {}, ready: function () {}, fail: function () {} };
  var params = new URLSearchParams(location.search);
  var off = params.get("nokernel") === "1";
  try { off = off || localStorage.getItem("vyomi.nano.kernel") === "off"; } catch (_) {}
  if (navigator.webdriver && params.get("kernel") !== "1") off = true;   // never in the way of UI tests
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 5x7 dot-matrix font for the wordmark.
  var FONT = {
    V: ["10001", "10001", "10001", "10001", "01010", "01010", "00100"],
    Y: ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    O: ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    M: ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    I: ["111", "010", "010", "010", "010", "010", "111"]
  };

  var CSS =
    "#nano-kernel{position:fixed;inset:0;z-index:2147483000;background:#05071a;color:#cbd5e1;" +
    "display:flex;align-items:center;justify-content:center;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;" +
    "transition:opacity .32s ease;cursor:pointer}" +
    "#nano-kernel.nk-out{opacity:0;pointer-events:none}" +
    "#nano-kernel .nk-wrap{width:min(760px,92vw)}" +
    "#nano-kernel .nk-matrix{display:flex;gap:14px;justify-content:center;margin-bottom:14px}" +
    "#nano-kernel .nk-letter{display:grid;gap:4px}" +
    "#nano-kernel .nk-dot{width:9px;height:9px;border-radius:50%;background:#111a33}" +
    "#nano-kernel .nk-dot.on{background:#22d3ee;box-shadow:0 0 6px #22d3ee,0 0 14px rgba(34,211,238,.45)}" +
    "#nano-kernel.nk-anim .nk-dot.on{animation:nk-lit .5s ease-out both}" +
    "@keyframes nk-lit{from{background:#111a33;box-shadow:none}to{}}" +
    "#nano-kernel .nk-sub{text-align:center;color:#64748b;letter-spacing:.08em;font-size:11.5px;margin-bottom:22px;text-transform:uppercase}" +
    "#nano-kernel .nk-log{background:#0a0f25;border:1px solid #1e293b;border-radius:8px;padding:14px 16px;min-height:150px;max-height:46vh;overflow:auto;white-space:pre-wrap;margin:0}" +
    "#nano-kernel .nk-l{display:flex;gap:10px}" +
    "#nano-kernel .nk-t{color:#475569;flex:0 0 auto}" +
    "#nano-kernel .nk-m{flex:0 0 1.2em;text-align:center}" +
    "#nano-kernel .nk-k{color:#7dd3fc;flex:0 0 7.5em}" +
    "#nano-kernel .nk-x{flex:1;color:#e2e8f0}" +
    "#nano-kernel .nk-d{color:#64748b;flex:0 0 auto}" +
    "#nano-kernel .nk-ok .nk-m{color:#4ade80}#nano-kernel .nk-err .nk-m,#nano-kernel .nk-err .nk-x{color:#f87171}" +
    "#nano-kernel .nk-run .nk-m{color:#fbbf24}#nano-kernel.nk-anim .nk-run .nk-m{animation:nk-blink 1s steps(2) infinite}" +
    "@keyframes nk-blink{50%{opacity:.25}}" +
    "#nano-kernel .nk-hint{margin-top:10px;text-align:right;color:#334155;font-size:11px}";

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function secs(ms) { return (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + " s"; }

  function start(title) {
    if (off || !document.body) return noop;
    var t0 = performance.now(), log, root, done = false;
    var carried = null;
    try { carried = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (_) {}
    if (carried && Date.now() - carried.at > 20000) carried = null;
    var offset = carried ? carried.elapsed : 0;   // keep the clock running across the reload

    var style = el("style"); style.textContent = CSS; document.head.appendChild(style);
    root = el("div"); root.id = "nano-kernel"; root.setAttribute("role", "status"); root.setAttribute("aria-live", "polite");
    if (!reduced) root.className = "nk-anim";
    var wrap = el("div", "nk-wrap"), matrix = el("div", "nk-matrix");
    var col = 0;
    "VYOMI".split("").forEach(function (ch) {
      var rows = FONT[ch], w = rows[0].length, letter = el("div", "nk-letter");
      letter.style.gridTemplateColumns = "repeat(" + w + ",9px)";
      for (var r = 0; r < 7; r++) for (var c = 0; c < w; c++) {
        var d = el("span", "nk-dot" + (rows[r][c] === "1" ? " on" : ""));
        if (!reduced) d.style.animationDelay = ((col + c) * 35 + r * 12) + "ms";
        letter.appendChild(d);
      }
      col += w + 1; matrix.appendChild(letter);
    });
    wrap.appendChild(matrix);
    wrap.appendChild(el("div", "nk-sub", "nano kernel · " + (title || "Vyomi") + " · local AWS, GCP and Azure, in your browser"));
    log = el("pre", "nk-log"); wrap.appendChild(log);
    wrap.appendChild(el("div", "nk-hint", "Esc or click to skip"));
    root.appendChild(wrap); document.body.appendChild(root);

    function now() { return offset + performance.now() - t0; }
    function stamp(ms) { var s = (ms / 1000).toFixed(3); return "[" + "       ".slice(s.length + 1) + s + "]"; }
    function line(cls, mark, key, text, detail, at) {
      var l = el("div", "nk-l " + cls);
      l.appendChild(el("span", "nk-t", at || stamp(now())));
      l.appendChild(el("span", "nk-m", mark));
      l.appendChild(el("span", "nk-k", key));
      l.appendChild(el("span", "nk-x", text));
      l.appendChild(el("span", "nk-d", detail || ""));
      log.appendChild(l); log.scrollTop = log.scrollHeight;
      return l;
    }
    if (carried) {
      carried.lines.forEach(function (x) { line(x.cls, x.mark, x.key, x.text, x.detail, x.at); });
    }
    function skip() { close(true); }
    function onKey(e) { if (e.key === "Escape") skip(); }
    root.addEventListener("click", skip);
    document.addEventListener("keydown", onKey);
    var guard = setTimeout(function () {                // never trap the user behind it
      if (!done) line("nk-run", "…", "kernel", "taking longer than usual; the page keeps loading underneath", "Esc to continue");
    }, 30000);
    function close(now_) {
      if (done) return; done = true; clearTimeout(guard);
      document.removeEventListener("keydown", onKey);
      try { sessionStorage.removeItem(KEY); } catch (_) {}
      // A fast boot (the dashboard is ~0.2 s) would flash past: keep it up at least
      // MIN_MS from launch so the wordmark and the log can be read. Skipping is instant.
      var wait = now_ ? 0 : Math.max(550, MIN_MS - (performance.now() - t0));
      setTimeout(function () { root.classList.add("nk-out"); setTimeout(function () { root.remove(); style.remove(); }, 360); }, wait);
    }
    return {
      step: function (key, text) {
        var t = now(), l = line("nk-run", "▸", key, text, "");
        return {
          ok: function (detail) { l.className = "nk-l nk-ok"; l.children[1].textContent = "✓"; l.children[4].textContent = (detail ? detail + "  " : "") + secs(now() - t); },
          fail: function (err) { l.className = "nk-l nk-err"; l.children[1].textContent = "✗"; l.children[4].textContent = String(err && err.message || err).slice(0, 120); }
        };
      },
      info: function (key, text, detail) { line("nk-ok", "·", key, text, detail); },
      carry: function () {
        var lines = [].map.call(log.children, function (l) {
          return { cls: l.className.replace("nk-l ", ""), mark: l.children[1].textContent, key: l.children[2].textContent,
                   text: l.children[3].textContent, detail: l.children[4].textContent, at: l.children[0].textContent };
        });
        try { sessionStorage.setItem(KEY, JSON.stringify({ at: Date.now(), elapsed: now(), lines: lines })); } catch (_) {}
      },
      ready: function (text) { line("nk-ok", "✓", "ready", text || "ready", secs(now())); close(false); },
      fail: function (err) { line("nk-err", "✗", "kernel", "boot failed: " + String(err && err.message || err), "Esc to continue"); }
    };
  }

  window.NanoKernel = { start: start, enabled: !off };
})();
