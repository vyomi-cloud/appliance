"use strict";
/* Vyomi Labs. VyomiLabs.mount(container, {cloud, base, tabs, layer}) renders the guided 13-layer build for one cloud.
 * Course view: a hero with progress, the full-width reference diagram (click a layer), and the course contents as LMS tiles.
 * Chapter view (a tile or a diagram layer is clicked): the chapter opens full view with a course outline on the left, the lesson in the
 * middle and "where it fits" + page outline on the right. Progress lives in this browser. With the optional local Labs server
 * (python -m vyomilabs serve) the Check button verifies a layer against the simulator.
 * base = URL prefix of the labs folder (data/, img/). tabs = show the cloud switcher (standalone page only). */
(function () {
  var CLOUDS = [["aws", "AWS"], ["gcp", "Google Cloud"], ["azure", "Azure"]];
  var el = function (t, p) { var n = document.createElement(t); Object.assign(n, p || {}); for (var i = 2; i < arguments.length; i++) [].concat(arguments[i]).forEach(function (x) { if (x != null && x !== false) n.append(x); }); return n; };
  var lsGet = function (k) { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch (_) { return {}; } };
  var lsSet = function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} };
  var ul = function (items, tag) { return el(tag || "ul", {}, items.map(function (t) { return el("li", { textContent: t }); })); };
  var hm = function (m) { return m >= 60 ? Math.floor(m / 60) + " h" + (m % 60 ? " " + (m % 60) + " min" : "") : m + " min"; };
  var pad = function (n) { return (n < 10 ? "0" : "") + n; };
  var LEVEL = { Beginner: 1, Intermediate: 2, Advanced: 3 };
  var SVG = "http://www.w3.org/2000/svg";
  function icon(path, size) { var s = document.createElementNS(SVG, "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", size || 16); s.setAttribute("height", size || 16); s.setAttribute("aria-hidden", "true");
    var p = document.createElementNS(SVG, "path"); p.setAttribute("d", path); p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", "2"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); s.append(p); return s; }
  var P = { clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2", book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
    check: "M5 12l5 5 9-10", arrow: "M5 12h14M13 6l6 6-6 6", back: "M19 12H5M11 18l-6-6 6-6", flag: "M5 21V4M5 4h11l-2 4 2 4H5", copy: "M9 9h11v11H9zM5 15V4h11" };

  var KW = "def|class|import|from|return|if|else|elif|for|while|in|not|and|or|try|except|finally|with|as|raise|lambda|None|True|False|pass|yield|async|await|is|echo|export|pip|install";
  var D3 = String.fromCharCode(34, 34, 34), S3 = String.fromCharCode(39, 39, 39);
  var TOK = new RegExp("(#[^\\n]*)|(" + D3 + "[\\s\\S]*?" + D3 + "|" + S3 + "[\\s\\S]*?" + S3 + "|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*')|\\b(" + KW + ")\\b|\\b(\\d+(?:\\.\\d+)?)\\b|(\\b[A-Za-z_]\\w*(?=\\())", "g");
  function hl(code) {   // tiny Python/bash highlighter: comments, strings, keywords, numbers, calls
    var f = document.createDocumentFragment(), last = 0, m; TOK.lastIndex = 0;
    while ((m = TOK.exec(code))) {
      if (m.index > last) f.append(code.slice(last, m.index));
      var c = m[1] ? "c" : m[2] ? "s" : m[3] ? "k" : m[4] ? "n" : "f"; f.append(el("span", { className: "t" + c, textContent: m[0] })); last = m.index + m[0].length;
    }
    if (last < code.length) f.append(code.slice(last)); return f;
  }

  function mount(host, opts) {
    opts = opts || {};
    var base = opts.base || "", cloud = opts.cloud || "aws", course = null, sel = null, inCourse = false, hasApi = false, store = {};
    var root = el("div", { className: "vl" });
    host.replaceChildren(root);
    var KEY = function () { return "vyomi.labs." + cloud; };
    var done = function (id) { return store[id]; };
    var byId = function (id) { return course.layers.filter(function (l) { return l.id === id; })[0]; };
    var nextId = function () { var l = course.layers.filter(function (x) { return !done(x.id); })[0]; return l ? l.id : null; };
    var nDone = function () { return Object.keys(store).length; };

    function load(c) {
      cloud = c; root.dataset.cloud = c; store = lsGet(KEY()); sel = null; inCourse = false;
      return fetch(base + "data/" + c + ".json", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
        course = d;
        return fetch("/api/health").then(function (h) { hasApi = h.ok; }).catch(function () { hasApi = false; });
      }).then(function () { render(); });
    }
    function go(id) { sel = id; render(); var s = host.closest ? host : null; window.scrollTo && window.scrollTo(0, 0); root.scrollIntoView && root.scrollIntoView({ block: "start" }); }
    function render() { root.replaceChildren(sel ? chapterView(byId(sel)) : inCourse ? courseView() : catalogView()); }
    function save() { lsSet(KEY(), store); }

    /* ---------- landing: every hands-on course as a card ---------- */
    function catalogView() {
      var nx = nextId(), n = nDone(), tot = course.layers.length, pct = Math.round(100 * n / tot);
      var labN = course.layers.reduce(function (a, l) { return a + (l.lab ? l.lab.length : 0); }, 0);
      var cloudTabs = opts.tabs ? el("nav", { className: "vl-clouds", "aria-label": "Cloud" }, CLOUDS.map(function (c) {
        var b = el("button", { type: "button", textContent: c[1] }); b.setAttribute("aria-current", c[0] === cloud); b.onclick = function () { if (c[0] !== cloud) load(c[0]); }; return b; })) : null;
      var stat = function (ic, v, k) { return el("div", { className: "vl-stat" }, el("span", { className: "vl-stati" }, icon(ic, 18)), el("div", {}, el("b", { textContent: v }), el("small", { textContent: k }))); };
      var start = function () { inCourse = true; render(); window.scrollTo && window.scrollTo(0, 0); root.scrollIntoView && root.scrollIntoView({ block: "start" }); };
      var card = el("article", { className: "vl-ccard" },
        el("div", { className: "vl-herotxt" },
          el("div", { className: "vl-eyebrow" }, "Hands-on course · " + course.cloud_name + " · " + course.ai_platform),
          el("h2", { textContent: course.title }),
          el("p", { textContent: "Build a complete enterprise agentic AI application layer by layer. Every chapter gives you the code, deploys it to your simulator and verifies it, so the app always works." }),
          el("div", { className: "vl-statrow" }, stat(P.book, String(tot), "chapters"), stat(P.clock, hm(course.total_minutes), "estimated"), stat("M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12", String(labN), "code steps"), stat(P.flag, "Beginner to Advanced", "13 layers"))),
        el("div", { className: "vl-progcard" },
          el("div", { className: "vl-ring", style: "--p:" + pct }, el("b", { textContent: pct + "%" })),
          el("div", {}, el("div", { className: "vl-progt", textContent: n + " of " + tot + " complete" }), el("div", { className: "vl-muted", textContent: nx ? "Up next: " + byId(nx).title : "Course complete" })),
          el("button", { type: "button", className: "vl-btn primary lg", onclick: start }, n ? "Continue course" : "Start course", icon(P.arrow, 18))));
      return el("div", { className: "vl-page" },
        el("header", { className: "vl-cathead" }, el("div", {}, el("h1", { textContent: "Vyomi Labs" }), el("p", { className: "vl-muted", textContent: "Hands-on courses. Build real applications on " + course.cloud_name + " services running in your simulator." })), cloudTabs),
        el("div", { className: "vl-cgrid" }, card, el("div", { className: "vl-ccard soon" }, el("b", { textContent: "More hands-on courses are on the way" }), el("span", { className: "vl-muted", textContent: "New courses appear here as they are published." }))));
    }

    /* ---------- course view ---------- */
    function archLink() {   // the full architecture this course teaches you to build, opened full size in its own tab
      return el("a", { className: "vl-archlink", href: base + course.image, target: "_blank", rel: "noopener" }, icon("M4 5h16v14H4zM4 10h16M10 10v9", 15), "View the full reference architecture you will build", icon("M7 17L17 7M9 7h8v8", 14));
    }
    function courseView() {
      var nx = nextId(), n = nDone(), tot = course.layers.length, pct = Math.round(100 * n / tot);
      var cloudTabs = opts.tabs ? el("nav", { className: "vl-clouds", "aria-label": "Cloud" }, CLOUDS.map(function (c) {
        var b = el("button", { type: "button", textContent: c[1] }); b.setAttribute("aria-current", c[0] === cloud); b.onclick = function () { if (c[0] !== cloud) load(c[0]); }; return b; })) : null;
      var cta = el("button", { type: "button", className: "vl-btn primary lg", onclick: function () { go(nx || course.layers[0].id); } },
        nx ? (n ? "Continue: " : "Start: ") + byId(nx).title : "Review the course", icon(P.arrow, 18));
      var labN = course.layers.reduce(function (a, l) { return a + (l.lab ? l.lab.length : 0); }, 0);
      var stat = function (ic, v, k) { return el("div", { className: "vl-stat" }, el("span", { className: "vl-stati" }, icon(ic, 18)), el("div", {}, el("b", { textContent: v }), el("small", { textContent: k }))); };
      var hero = el("header", { className: "vl-hero" },
        el("div", { className: "vl-herotxt" },
          el("button", { type: "button", className: "vl-backlink", onclick: function () { inCourse = false; render(); } }, icon(P.back, 14), "All courses"),
          el("div", { className: "vl-eyebrow" }, "Vyomi Labs · " + course.cloud_name + " · " + course.ai_platform),
          el("h1", { textContent: course.title }),
          el("p", { textContent: "Build a complete enterprise agentic AI application layer by layer. Every chapter gives you the code, deploys it to your simulator and verifies it, so the app always works." }),
          el("div", { className: "vl-statrow" }, stat(P.book, String(tot), "chapters"), stat(P.clock, hm(course.total_minutes), "estimated"), stat("M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12", String(labN), "code steps to copy and run"), stat(P.flag, "Beginner to Advanced", "13 layers")), archLink(), cloudTabs),
        el("div", { className: "vl-progcard" },
          el("div", { className: "vl-ring", style: "--p:" + pct }, el("b", { textContent: pct + "%" })),
          el("div", {}, el("div", { className: "vl-progt", textContent: n + " of " + tot + " complete" }), el("div", { className: "vl-muted", textContent: nx ? "Up next: " + byId(nx).title : "Course complete" })), cta));

      var map = el("section", { className: "vl-map", "aria-label": "Reference architecture" },
        el("div", { className: "vl-sechead" }, el("h2", { textContent: "Reference architecture" }), el("p", { className: "vl-muted", textContent: "Native " + course.cloud_name + " services. Select any layer to open its chapter." }), archLink()),
        diagram(null, true), el("ul", { className: "vl-legend" }, el("li", {}, el("i", { className: "vl-dot" }), "Not started"), el("li", {}, el("i", { className: "vl-dot done" }), "Complete"), el("li", {}, el("i", { className: "vl-dot next" }), "Up next")));

      var tiles = el("section", { className: "vl-contents", "aria-label": "Course contents" },
        el("div", { className: "vl-sechead" }, el("h2", { textContent: "Course contents" }), el("p", { className: "vl-muted", textContent: "Recommended order. You can start anywhere." })),
        el("div", { className: "vl-tiles" }, course.layers.map(function (l) { return tile(l, nx); })));
      return el("div", { className: "vl-page" }, hero, tiles, map);
    }

    function diagram(highlight, clickable) {
      var wrap = el("div", { className: "vl-imgwrap" }), img = el("img", { src: base + course.image, alt: course.title + ": reference architecture" });
      img.addEventListener("error", function () { wrap.append(el("p", { className: "vl-muted", textContent: "The diagram could not be loaded." })); });
      wrap.append(img);
      var W = course.image_size[0], H = course.image_size[1], nx = nextId();
      course.layers.forEach(function (l) {
        if (highlight != null && l.id !== highlight) return;
        var h = l.hotspot, b = el(clickable ? "button" : "span", { className: "vl-hs" + (done(l.id) ? " done" : "") + (l.id === nx && clickable ? " next" : "") + (highlight === l.id ? " cur" : "") });
        b.style.cssText = "left:" + 100 * h[0] / W + "%;top:" + 100 * h[1] / H + "%;width:" + 100 * (h[2] - h[0]) / W + "%;height:" + 100 * (h[3] - h[1]) / H + "%";
        if (clickable) { b.type = "button"; b.title = l.order + ". " + l.title; b.setAttribute("aria-label", "Chapter " + l.order + ": " + l.title + (done(l.id) ? ", complete" : "")); b.onclick = function () { go(l.id); }; }
        wrap.append(b);
      });
      return wrap;
    }

    function tile(l, nx) {
      var st = done(l.id) ? "done" : l.id === nx ? "next" : "todo";
      var stText = st === "done" ? (done(l.id) === "verified" ? "Verified" : done(l.id) === "deployed" ? "Deployed" : "Complete") : st === "next" ? "Up next" : "Not started";
      var m = function (ic, t) { return el("span", {}, icon(ic, 13), t); };
      var steps = (l.lab || []).length;
      var t = el("button", { type: "button", className: "vl-tile " + st, style: "--c:" + l.color },
        el("span", { className: "vl-thead" }, el("span", { className: "vl-ticon" }, icon(l.icon, 20)), el("span", { className: "vl-chno", textContent: "Chapter " + pad(l.order) }), el("span", { className: "vl-state " + st, textContent: stText })),
        el("span", { className: "vl-ttitle", textContent: l.title }),
        el("span", { className: "vl-outcome", textContent: l.outcome }),
        el("span", { className: "vl-tmeta" }, m(P.clock, "~" + l.minutes + " min"), m("M4 6h16M4 12h16M4 18h10", (steps || l.lessons) + (steps ? " code steps" : " lessons")), m(P.flag, l.level)),
        el("span", { className: "vl-tsvc" }, l.services.slice(0, 2).map(function (x) { return el("i", { textContent: x }); }), l.services.length > 2 ? el("i", { textContent: "+" + (l.services.length - 2) }) : null),
        el("span", { className: "vl-tfoot" }, el("span", { className: "vl-cta" }, st === "done" ? "Review" : st === "next" ? "Continue" : "Open", icon(P.arrow, 14))),
        el("span", { className: "vl-pbar" }, el("i", { style: "width:" + (st === "done" ? 100 : 0) + "%" })));
      t.onclick = function () { go(l.id); };
      return t;
    }

    /* ---------- Deploy: run the chapter's blocks in the browser (Nano) or, when a Mesh is on, against the Mesh ---------- */
    var worker = null, seq = 0, pend = {};
    function getWorker() {
      if (worker) return worker;
      worker = new Worker(base + "pyrun-worker.js", { type: "module" });
      worker.onmessage = function (e) { var p = pend[e.data.id]; if (!p) return; if (e.data.type === "log") p.log(e.data.text); else { delete pend[e.data.id]; p.done(e.data.ok); } };
      worker.onerror = function (e) { Object.keys(pend).forEach(function (k) { pend[k].log("Runner error: " + (e.message || "failed to load")); pend[k].done(false); delete pend[k]; }); worker = null; };
      return worker;
    }
    function runInBrowser(files, run, env, route, onLog) {
      return new Promise(function (resolve) { var id = ++seq; pend[id] = { log: onLog, done: resolve }; getWorker().postMessage({ id: id, files: files, run: run, env: env, route: route }); });
    }
    function wireEndpoint() { return location.origin + location.pathname.split("/labs/")[0] + "/_wire"; }
    function meshRoute() { try { return window.parent !== window && window.parent.VyomiMesh && window.parent.VyomiMesh.wireRouting ? window.parent.VyomiMesh.wireRouting() : null; } catch (_) { return null; } }
    function deployPanel(l) {
      var route = meshRoute(), target = route ? "inside your Mesh (" + route.name + ")" : hasApi ? "in the Vyomi runner" : "in this browser (Nano)";
      var supported = cloud === "aws" || hasApi || !!route;
      var rows = l.lab.map(function (bk) { return { bk: bk, chip: el("span", { className: "vl-dchip", textContent: bk.run ? "waiting" : "saved on run" }), log: el("pre", { className: "vl-dlog" }) }; });
      var btn = el("button", { type: "button", className: "vl-btn primary lg" }, icon("M8 5v14l11-7z", 16), "Deploy this chapter");
      var out = el("div", { className: "vl-dout" });
      var allFiles = function () {   // every earlier chapter's files exist too (this chapter may import them); nothing is run for those
        var f = {}; for (var i = 0; i < course.layers.length; i++) { var c = course.layers[i]; (c.lab || []).forEach(function (b) { f[b.file] = b.code; }); if (c.id === l.id) break; } return f; };
      function finish(failed, blocked, needModel, endpointNote) {
        btn.disabled = false; btn.textContent = "Deploy again";
        var links = (l.setup || []).filter(function (s) { return s.route; });
        if (!failed && !blocked) { store[l.id] = store[l.id] === "verified" ? "verified" : "deployed"; save(); }
        out.replaceChildren(el("div", { className: "vl-dres " + (failed ? "bad" : blocked ? "warn" : "ok") },
          el("b", { textContent: failed ? failed + " step(s) failed. Open the step log below, fix the cause and deploy again." : blocked ? "Deployed, except steps that need a runtime (appliance or Mesh)." : "Deployed." + (endpointNote || "") }),
          (!failed && links.length) ? el("div", { className: "vl-dlinks" }, el("span", { textContent: "See it running in the space: " }), links.map(function (s) { return el("a", { className: "vl-btn", href: consoleUrl(s.route), target: "_blank", rel: "noopener", textContent: s.service || s.title }); })) : null));
      }
      function deployVia(startFetch) {   // the Labs runner (local server, offline appliance or Mesh): runs the blocks exactly as written
        btn.disabled = true; btn.textContent = "Deploying..."; out.replaceChildren(); var failed = 0, blocked = 0, status = el("div", { className: "vl-dstatus" });
        out.append(status);
        rows.forEach(function (r) { r.chip.textContent = r.bk.run ? "waiting" : "saved on run"; r.chip.className = "vl-dchip"; r.log.textContent = ""; });
        startFetch().then(function (resp) {
          if (!resp.ok) return resp.json().then(function (j) { throw new Error((j.error && j.error.message) || ("HTTP " + resp.status)); });
          var rd = resp.body.getReader(), dec = new TextDecoder(), buf = "", endp = "";
          function handle(ev) {
            if (ev.t === "status") status.textContent = ev.text;
            else if (ev.t === "block") { var r = rows[ev.i]; if (!r) return;
              r.chip.textContent = { running: "running", passed: "passed", failed: "failed", saved: "saved", blocked: "needs a runtime" }[ev.status];
              r.chip.className = "vl-dchip " + ({ passed: "ok", saved: "ok", failed: "bad", blocked: "warn", running: "run" }[ev.status]);
              if (ev.out) r.log.textContent = ev.out; if (ev.status === "failed") failed++; if (ev.status === "blocked") blocked++; }
            else if (ev.t === "done") { if (!ev.ok && ev.error) { failed++; status.textContent = ev.error; } endp = ev.endpoint ? " Simulator at " + ev.endpoint + "." : ""; }
            return endp;
          }
          function pump() { return rd.read().then(function (c) {
            if (c.done) { finish(failed, blocked, false, endp); return; }
            buf += dec.decode(c.value, { stream: true }); var lines = buf.split("\n"); buf = lines.pop();
            lines.forEach(function (ln) { if (ln.trim()) { var x = handle(JSON.parse(ln)); if (x) endp = x; } }); return pump(); }); }
          return pump();
        }).catch(function (e) { out.replaceChildren(el("div", { className: "vl-dres bad" }, el("b", { textContent: "Could not run the deploy: " + e.message }))); btn.disabled = false; btn.textContent = "Deploy again"; });
      }
      btn.onclick = function () {
        if (route && window.parent.VyomiMesh.apiFetch) return deployVia(function () { return window.parent.VyomiMesh.apiFetch("/mesh/labs/deploy/" + cloud + "/" + l.id, { method: "POST" }); });   // a Mesh is on: deploy INSIDE the Mesh
        if (hasApi) return deployVia(function () { return fetch("/api/deploy/" + cloud + "/" + l.id, { method: "POST" }); });
        btn.disabled = true; btn.textContent = "Deploying..."; out.replaceChildren(); var failed = 0, blocked = 0, needModel = false;
        var files = allFiles(), env = { AWS_ENDPOINT_URL: wireEndpoint(), AWS_DEFAULT_REGION: "us-east-1", AWS_ACCESS_KEY_ID: "test", AWS_SECRET_ACCESS_KEY: "test" };
        var chain = Promise.resolve();
        rows.forEach(function (r) {
          chain = chain.then(function () {
            if (!r.bk.run) { r.chip.textContent = "saved"; r.chip.className = "vl-dchip ok"; return runInBrowser(files, "", env, route, function () {}); }
            if (r.bk.needs_runtime && !route) { blocked++; r.chip.textContent = "needs the Mesh"; r.chip.className = "vl-dchip warn"; r.log.textContent = "This step runs real function code, which the in-browser simulator does not execute. Turn on a Mesh and deploy again."; return; }
            r.chip.textContent = "running"; r.chip.className = "vl-dchip run"; var text = "";
            return runInBrowser(files, r.bk.run, env, route, function (t) { text += t + "\n"; r.log.textContent = text; }).then(function (ok) {
              var pass = ok && (!r.bk.expect || text.indexOf(r.bk.expect) >= 0);
              if (!pass) failed++; r.chip.textContent = pass ? "passed" : "failed"; r.chip.className = "vl-dchip " + (pass ? "ok" : "bad");
              if (!pass && ok) r.log.textContent = text + "\nExpected to see: " + r.bk.expect;
              if (!pass && /ModelNotReady|No in-browser model/.test(text)) { needModel = true; r.chip.textContent = "needs a model"; r.chip.className = "vl-dchip warn"; }
            });
          });
        });
        chain.then(function () {
          btn.disabled = false; btn.textContent = failed ? "Deploy again" : "Deploy again";
          var links = (l.setup || []).filter(function (s) { return s.route; });
          if (!failed && !blocked) { store[l.id] = store[l.id] === "verified" ? "verified" : "deployed"; save(); }
          out.replaceChildren(el("div", { className: "vl-dres " + (failed ? "bad" : blocked ? "warn" : "ok") },
            needModel ? el("b", { textContent: "A step needs a model. Load one (Amazon Bedrock, Overview, Local model: choose a small model and Load in-browser model) or turn on a Mesh, then deploy again." }) : el("b", { textContent: failed ? failed + " step(s) failed. Open the step log below, fix the cause and deploy again." : blocked ? "Deployed, except steps that need the Mesh." : "Deployed." }),
            (!failed && links.length) ? el("div", { className: "vl-dlinks" }, el("span", { textContent: "See it running in the space: " }), links.map(function (s) { return el("a", { className: "vl-btn", href: consoleUrl(s.route), target: "_blank", rel: "noopener", textContent: s.service || s.title }); })) : null));
        });
      };
      return el("div", { className: "vl-deploy" },
        el("div", { className: "vl-dhead" }, el("div", {}, el("h3", { textContent: "Deploy this chapter" }), el("p", { className: "vl-muted", textContent: supported ? "Runs every block below in order, exactly as written, " + target + ", then shows you the resources in the console." : "Deploying " + course.cloud_name + " chapters needs the Vyomi Labs runner (the offline appliance or a Mesh); it is not available in this browser session." })), btn),
        supported ? null : el("p", { className: "vl-native", textContent: "The in-browser runner supports the AWS SDK only. " + course.cloud_name + " chapters deploy through the runner on the appliance or a Mesh." }),
        el("ol", { className: "vl-drows" }, rows.map(function (r, i) { return el("li", {}, el("div", { className: "vl-drow" }, el("span", { className: "vl-dn", textContent: i + 1 }), el("span", { className: "vl-dt", textContent: r.bk.title }), el("code", { textContent: r.bk.run || r.bk.file }), r.chip), r.log); })), out);
      // button disabled when this cloud is not supported
    }
    function copyBtn(text) { return el("button", { type: "button", className: "vl-copy", title: "Copy", onclick: function (e) { try { navigator.clipboard.writeText(text); e.currentTarget.textContent = "Copied"; } catch (_) {} } }, "Copy"); }
    function labBlock(bk, i) {
      var li = el("li", { className: "vl-block" + (i === 0 ? " open" : "") });
      var head = el("button", { type: "button", className: "vl-bhead", "aria-expanded": String(i === 0) },
        el("span", { className: "vl-s2n", textContent: i + 1 }), el("span", { className: "vl-btitle" }, el("b", { textContent: bk.title }), el("small", { textContent: bk.text })),
        el("code", { className: "vl-bfile", textContent: bk.run || bk.file }), el("span", { className: "vl-chev" }, icon("M6 9l6 6 6-6", 16)));
      head.onclick = function () { var o = li.classList.toggle("open"); head.setAttribute("aria-expanded", String(o)); };
      var pre = el("pre", { className: "vl-pre" }); pre.append(hl(bk.code));
      li.append(head, el("div", { className: "vl-bbody" },
        el("div", { className: "vl-file" }, el("span", { className: "vl-fname" }, icon("M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5", 14), "Save as " + bk.file), copyBtn(bk.code)), pre,
        bk.run ? el("div", { className: "vl-runrow" }, el("span", { className: "vl-runlbl", textContent: "Run" }), el("code", { textContent: bk.run }), copyBtn(bk.run)) : el("div", { className: "vl-runrow muted" }, el("span", { className: "vl-runlbl", textContent: "Nothing to run yet; the next step uses this file." })),
        bk.expect ? el("div", { className: "vl-expect" }, el("span", { textContent: "You should see" }), el("code", { textContent: bk.expect })) : null));
      return li;
    }
    function consoleUrl(route) { return base + "../v4/" + cloud + "/#" + route; }
    function settingsTable(st, withDesc) {
        var keys = Object.keys(st.fill || {}); if (!keys.length) return null;
        return el("table", { className: "vl-vtab" }, el("thead", {}, el("tr", {}, el("th", { textContent: "Setting" }), el("th", { textContent: "Suggested value" }), withDesc ? el("th", { textContent: "Description" }) : null)),
          el("tbody", {}, keys.map(function (k) { return el("tr", {}, el("td", {}, el("b", { textContent: k })), el("td", {}, el("code", { textContent: st.fill[k] })), withDesc ? el("td", { textContent: "Use exactly this name: later chapters look the resource up by it." }) : null); })));
      }
    function setupStep(st) {
      var vals = Object.keys(st.fill || {});
      var open = st.route ? el("a", { className: "vl-btn primary", href: consoleUrl(st.route), target: "_blank", rel: "noopener" }, "Open in " + course.cloud_name + " console", icon("M7 17L17 7M9 7h8v8", 16)) : null;
      var shot = st.shot ? el("a", { className: "vl-shot", href: base + st.shot, target: "_blank", rel: "noopener", title: "Open the full-size screenshot" },
        el("img", { src: base + st.shot, alt: "Screenshot: " + st.title, loading: "lazy" }), el("span", { className: "vl-shotcap", textContent: "Real screenshot from the Vyomi " + course.cloud_name + " console" })) : null;
      return el("li", { className: "vl-step2" },
        el("div", { className: "vl-s2head" }, el("span", { className: "vl-s2n", textContent: st.n }), el("div", {}, el("h3", { textContent: st.title }), st.service ? el("span", { className: "vl-chip", textContent: st.service }) : null), open),
        el("div", { className: "vl-s2body" + (shot ? "" : " noshot") },
          el("div", {}, ul(st.do), settingsTable(st, false),
            st.note ? el("p", { className: "vl-native", textContent: st.note }) : null),
          shot));
    }

    /* ---------- chapter view (full view) ---------- */
    function chapterView(l) {
      var i = course.layers.indexOf(l), prev = course.layers[i - 1], nxt = course.layers[i + 1], out = el("div", { className: "vl-result" });
      var nx = nextId();
      var back = el("button", { type: "button", className: "vl-back", onclick: function () { sel = null; render(); } }, icon(P.back, 16), "Course contents");
      var top = el("div", { className: "vl-topbar" }, back, el("span", { className: "vl-crumb", textContent: course.cloud_name + " · Chapter " + l.order + " of " + course.layers.length }),
        el("span", { className: "vl-topprog" }, el("span", { textContent: nDone() + " of " + course.layers.length + " complete" }), el("span", { className: "vl-bar" }, el("i", { style: "width:" + (100 * nDone() / course.layers.length) + "%" }))));

      var collapsed = lsGet("vyomi.labs.ui").outline === 0;
      var side = el("nav", { className: "vl-outline" + (collapsed ? " collapsed" : ""), "aria-label": "Course outline" });
      var tg = el("button", { type: "button", className: "vl-collapse", title: collapsed ? "Expand outline" : "Collapse outline", "aria-expanded": String(!collapsed) }, icon("M15 6l-6 6 6 6", 16));
      tg.onclick = function () { var c = !side.classList.contains("collapsed"); side.classList.toggle("collapsed", c); tg.setAttribute("aria-expanded", String(!c)); tg.title = c ? "Expand outline" : "Collapse outline"; cols.classList.toggle("oc", c); var u = lsGet("vyomi.labs.ui"); u.outline = c ? 0 : 1; lsSet("vyomi.labs.ui", u); };
      side.append(el("div", { className: "vl-ohead" }, el("h4", { textContent: "Course outline" }), tg),
        el("ol", {}, course.layers.map(function (x) {
          var b = el("button", { type: "button", title: x.order + ". " + x.title, className: (x.id === l.id ? "cur " : "") + (done(x.id) ? "done" : ""), onclick: function () { go(x.id); } },
            el("span", { className: "vl-oi", style: "--c:" + x.color }, icon(x.icon, 17), done(x.id) ? el("i", { className: "vl-tick" }, icon(P.check, 9)) : null), el("span", { className: "vl-ol", textContent: x.order + ". " + x.short }));
          if (x.id === l.id) b.setAttribute("aria-current", "true"); return el("li", {}, b); })));

      var needs = l.contract.needs.length ? el("dd", { className: "vl-needs" }, l.contract.needs.map(function (id) { return el("button", { type: "button", textContent: byId(id).short, onclick: function () { go(id); } }); }),
        el("span", { className: "vl-muted", textContent: "until you build it, the reference version is used" })) : el("dd", { textContent: "nothing from other layers" });
      var names = []; Object.keys(l.contract.names).forEach(function (k) { names.push(el("dt", { textContent: k.replace(/_/g, " ") }), el("dd", {}, el("code", { textContent: l.contract.names[k] }))); });

      var canCheck = hasApi && l.checker, check = el("button", { type: "button", className: "vl-btn", textContent: "Check my layer" }); check.disabled = !canCheck;
      var how = canCheck ? "Press Check: Labs runs the checks below against your simulator." : l.checker
        ? "Run the checker yourself: python -m vyomilabs check " + l.id + " (start python -m vyomilabs serve to get the button here)."
        : "An automatic checker for this chapter is coming. Until then, compare with the reference solution: it shows what a passing build creates.";
      var statusEl = el("span", { className: "vl-status" + (done(l.id) ? " done" : ""), textContent: done(l.id) ? (done(l.id) === "verified" ? "Verified by the checker" : "Marked complete") : "" });
      check.onclick = function () {
        check.disabled = true; check.textContent = "Checking...";
        fetch("/api/layers/" + l.id + "/check", { method: "POST" }).then(function (r) { return r.json(); }).then(function (r) {
          out.replaceChildren(el("ul", { className: "vl-steps" }, r.steps.map(function (s) { return el("li", {}, el("span", { className: "vl-st " + s.status, textContent: s.status }), el("span", {}, s.name, s.detail ? el("span", { className: "vl-d", textContent: s.detail }) : "")); })));
          if (r.status === "PASS") { store[l.id] = "verified"; save(); statusEl.textContent = "Verified by the checker"; statusEl.className = "vl-status done"; }
        }).catch(function (e) { out.replaceChildren(el("p", { className: "vl-status FAIL", textContent: "Could not run the check: " + e.message })); })
          .then(function () { check.disabled = false; check.textContent = "Check my layer"; });
      };
      var mark = el("button", { type: "button", className: "vl-btn primary", onclick: function () { if (store[l.id]) delete store[l.id]; else store[l.id] = "self"; save(); render(); } }, done(l.id) ? "Mark as not complete" : [icon(P.check, 16), "Mark chapter complete"]);

      function sec(id, no, title, body) { return el("section", { className: "vl-sec", id: "vl-" + id }, el("h2", {}, el("span", { className: "vl-no", textContent: no }), title), body); }
      var code = l.code ? el("div", { className: "vl-code" }, el("button", { type: "button", className: "vl-copy", title: "Copy", onclick: function (e) { try { navigator.clipboard.writeText(l.code.text); e.currentTarget.textContent = "Copied"; } catch (_) {} } }, "Copy"), el("pre", { textContent: l.code.text })) : null;
      var valRows = l.validate.map(function (v) {
        return el("li", { className: "vl-val" }, el("div", { className: "vl-valhead" }, el("span", { className: "vl-kind " + v.kind.toLowerCase(), textContent: v.kind }), el("b", { textContent: v.what })),
          v.kind === "Console" ? el("div", { className: "vl-path" }, v.how) : el("div", { className: "vl-code sm" }, el("button", { type: "button", className: "vl-copy", title: "Copy", onclick: function (e) { try { navigator.clipboard.writeText(v.how); e.currentTarget.textContent = "Copied"; } catch (_) {} } }, "Copy"), el("pre", { textContent: v.how })),
          el("div", { className: "vl-expect" }, el("span", { textContent: "You should see" }), v.expect));
      });
      /* ---- the chapter as a native tutorial: AWS hands-on, Google codelab or Microsoft Learn layout ---- */
      var N = l.minutes, tm = { build: Math.max(5, Math.round(N * 0.5)), cons: Math.max(5, Math.round(N * 0.25)), val: Math.max(5, Math.round(N * 0.2)), clean: 5 };
      var hasLab = l.lab && l.lab.length;
      var archFig = el("figure", { className: "vl-fig" }, diagram(l.id, false), el("figcaption", { textContent: "Highlighted: where this chapter's layer sits in the " + course.cloud_name + " architecture." }));
      var facts = function (rows) { return el("table", { className: "vl-facts" }, el("tbody", {}, rows.map(function (r) { return el("tr", {}, el("th", { textContent: r[0] }), el("td", {}, r[1])); }))); };
      var svcList = el("span", { className: "vl-svclist" }, l.services.map(function (x) { return el("span", {}, x); }));
      var next = nxt ? el("div", { className: "vl-nextcard" }, el("small", { textContent: "Next" }), el("button", { type: "button", className: "vl-btn primary", onclick: function () { go(nxt.id); } }, "Chapter " + nxt.order + ": " + nxt.title, icon(P.arrow, 16))) : el("p", { className: "vl-muted", textContent: "That was the last chapter. You now have the full enterprise agent." });
      var cleanup = el("div", {}, el("p", { textContent: "Vyomi is a simulator, so nothing here is billed and nothing needs deleting to avoid charges. To start this chapter again, delete the resources you created from their console pages, or reset the space from Spaces in the bottom drawer." }),
        el("p", { className: "vl-muted", textContent: "Keep the resources if you are continuing: later chapters build on them." }));
      var buildBody = el("div", {}, hasLab ? el("div", {}, (function () { var d = deployPanel(l); if (cloud !== "aws" && !hasApi && !meshRoute()) d.querySelector("button").disabled = true; return d; })(),
          el("p", { className: "vl-muted", textContent: "Complete these in order. Save each file with the name shown, run the command under it and check the output matches. Point your SDK at the simulator first (open SDK & CLI usage in the bottom drawer for the exact settings)." }),
          (function () { var ol = el("ol", { className: "vl-blocks" }, l.lab.map(labBlock)), allOpen = false; var tg2 = el("button", { type: "button", className: "vl-btn sm", textContent: "Expand all" }); tg2.onclick = function () { allOpen = !allOpen; [].forEach.call(ol.children, function (x) { x.classList.toggle("open", allOpen); }); tg2.textContent = allOpen ? "Collapse all" : "Expand all"; }; return el("div", {}, el("div", { className: "vl-blocktools" }, tg2), ol); })()) :
        el("div", { className: "vl-note" }, el("b", { textContent: "Code for this chapter is not written yet" }), el("p", { textContent: "Create the resources in the console steps below. The runnable, verified code for this chapter is still being added." }), ul(l.build)));
      var consBody = el("div", {}, el("p", { className: "vl-muted", textContent: "Open each service in the " + course.cloud_name + " console, enter the values shown and compare with the screenshot." }),
        el("ol", { className: "vl-steps2" }, (l.setup || []).map(setupStep)));
      var fitsBody = el("div", {}, el("dl", { className: "vl-contract" }, [el("dt", { textContent: "Needs" }), needs].concat(names)),
        el("div", { className: "vl-note" }, el("b", { textContent: "What the simulator simplifies" }), ul(l.simplified)), l.native ? el("p", { className: "vl-native", textContent: l.native }) : null);
      /* Validate: the chapter's services' SDK & CLI usage + API reference, embedded live from the generated docs (one source of truth), with Try it that runs the calls in this browser. */
      var docIds = (l.docs || []).map(function (d) { return d.id; });
      var docsUrl = function (view) { return base + "../clouds.html?embed=1&only=" + cloud + "&svc=" + encodeURIComponent(docIds.join(",")) + "&ops=" + encodeURIComponent(JSON.stringify((l.ops || []).map(function (o) { return { f: o.f, n: o.n }; }))) + "#" + view; };
      var docsBlock = function () {
        if (!docIds.length) return el("p", { className: "vl-muted", textContent: "This chapter's services have no generated API docs yet; use the console steps above to check them." });
        var frame = el("iframe", { className: "vl-docframe", title: "SDK & CLI usage and API reference for this chapter", loading: "lazy", src: docsUrl("api") });
        window.addEventListener("message", function (e) { if (e.source === frame.contentWindow && e.data && e.data.vylabs === "h") frame.style.height = Math.min(Math.max(e.data.h + 8, 160), 12000) + "px"; });
        return el("div", { className: "vl-docs" }, el("div", { className: "vl-dtabs" }, el("span", { className: "vl-muted vl-dsvc", textContent: (l.docs || []).map(function (d) { return d.title; }).join(" · ") })), frame);
      };
      var consoleVals = l.validate.filter(function (v) { return v.kind === "Console"; }).map(function (v) {
        return el("li", { className: "vl-val" }, el("div", { className: "vl-valhead" }, el("span", { className: "vl-kind console", textContent: "Console" }), el("b", { textContent: v.what })), el("div", { className: "vl-path" }, v.how), el("div", { className: "vl-expect" }, el("span", { textContent: "You should see" }), v.expect)); });
      var valBody = el("div", {}, el("p", { className: "vl-muted", textContent: "These are the exact operations this chapter uses, straight from the live API reference. Press Try it on any operation to make the call from this browser against your simulator: no tunnel needed." }),
        docsBlock(), consoleVals.length ? el("ol", { className: "vl-vals" }, consoleVals) : null,
        el("h3", { className: "vl-h3", textContent: "What the full check covers" }), ul(l.checks), canCheck ? el("div", { className: "vl-actions" }, check, statusEl) : null, out);
      var closing = el("div", { className: "vl-finish" }, el("div", { className: "vl-actions" }, mark, statusEl), el("p", { className: "vl-muted" }, "Reference solution (peek only after you have tried): ", el("code", { textContent: l.reference })));
      /* ---- the chapter workspace: a hero, then ONE section at a time (compact), in each cloud's own tutorial structure ---- */
      var chk = function (arr) { return el("ul", { className: "vl-checks" }, arr.map(function (t) { return el("li", {}, icon(P.check, 15), t); })); };
      var card = function (title, body, cls) { return el("section", { className: "vl-card " + (cls || "") }, el("h3", { textContent: title }), body); };
      var introBody = el("div", { className: "vl-intro" },
        el("div", { className: "vl-grid2" }, card(cloud === "aws" ? "What you will accomplish" : "What you'll learn", chk(l.learn)), card("Why it matters in the enterprise", el("div", {}, el("p", { textContent: l.about }), ul(l.why)))),
        el("div", { className: "vl-grid2" }, card("Prerequisites", ul(l.prereq)),
          card(cloud === "aws" ? "Tutorial details" : "At a glance", facts([[cloud === "aws" ? "AWS experience" : "Level", l.level], ["Time", "~" + N + " minutes (estimate)"], ["Cost", "Free: runs on your Vyomi simulator"], ["Services", svcList], ["Updated", course.updated]]))),
        card("Where this layer sits", archFig, "vl-wide"));
      var L = { aws: ["Overview", "Task 1: Build the code", "Task 2: Create the resources", "Task 3: Connect to other layers", "Task 4: Validate your work", "Task 5: Clean up resources"],
        gcp: ["Before you begin", "Build the code", "Create the resources", "Connect the layers", "Validate", "Clean up"],
        azure: ["Prerequisites", "Build the code", "Create the resources", "Connect to other layers", "Validate", "Clean up and next steps"] }[cloud];
      var PANES = [
        { t: L[0], dur: 2, body: introBody },
        { t: L[1], dur: tm.build, body: buildBody, badge: hasLab ? String(l.lab.length) : "" },
        { t: L[2], dur: tm.cons, body: consBody, badge: (l.setup || []).length ? String(l.setup.length) : "" },
        { t: L[3], dur: 5, body: fitsBody },
        { t: L[4], dur: tm.val, body: valBody },
        { t: L[5], dur: tm.clean, body: el("div", {}, cleanup, closing) }];
      var curPane = 0, content = el("div", { className: "vl-pane" }), nav = el("nav", { className: "vl-pnav", "aria-label": cloud === "azure" ? "In this article" : cloud === "gcp" ? "Codelab steps" : "Tasks" });
      nav.append(el("h4", { textContent: cloud === "azure" ? "In this article" : cloud === "gcp" ? "Steps" : "Tasks" }));
      var pbtn = PANES.map(function (p, i) {
        var b = el("button", { type: "button", className: "vl-pb" }, el("span", { className: "vl-pn", textContent: i + 1 }), el("span", { className: "vl-pt", textContent: p.t }), p.badge ? el("em", { className: "vl-pbadge", textContent: p.badge }) : null, el("small", { className: "vl-pd", textContent: p.dur + " min" }));
        b.onclick = function () { showPane(i, true); }; nav.append(b); return b;
      });
      function showPane(i, scroll) {
        curPane = i; pbtn.forEach(function (b, k) { b.classList.toggle("cur", k === i); b.classList.toggle("past", k < i); if (k === i) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current"); });
        var p = PANES[i];
        var pager = el("div", { className: "vl-pager2" }, i ? el("button", { type: "button", className: "vl-btn", onclick: function () { showPane(i - 1, true); } }, icon(P.back, 16), PANES[i - 1].t) : el("span"),
          i < PANES.length - 1 ? el("button", { type: "button", className: "vl-btn primary", onclick: function () { showPane(i + 1, true); } }, PANES[i + 1].t, icon(P.arrow, 16)) : (nxt ? el("button", { type: "button", className: "vl-btn primary", onclick: function () { go(nxt.id); } }, "Next chapter: " + nxt.title, icon(P.arrow, 16)) : el("span", { className: "vl-muted", textContent: "That was the last chapter." })));
        content.replaceChildren(el("div", { className: "vl-phead" }, el("h2", { textContent: p.t }), el("span", { className: "vl-dur", textContent: p.dur + " min" })), p.body, pager);
        if (scroll) { window.scrollTo(0, 0); }
      }
      function gotoDeploy() { showPane(1, false); var d = content.querySelector(".vl-deploy"); d && d.scrollIntoView({ behavior: "smooth", block: "start" }); }
      var chipo = function (ic, t) { return el("span", { className: "vl-hchip" }, icon(ic, 14), t); };
      var hero = el("header", { className: "vl-chero", style: "--c:" + l.color },
        el("div", { className: "vl-cicon" }, icon(l.icon, 30)),
        el("div", { className: "vl-ctext" },
          el("div", { className: "vl-crumbs2", textContent: course.cloud_name + "  /  Vyomi Labs  /  Chapter " + l.order + " of " + course.layers.length }),
          el("h1", { textContent: l.title }), el("p", { textContent: l.outcome }),
          el("div", { className: "vl-cchips" }, chipo(P.flag, l.level), chipo(P.clock, "~" + N + " min"), hasLab ? chipo("M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12", l.lab.length + " code steps") : null, l.services.slice(0, 3).map(function (x) { return el("span", { className: "vl-hchip svc", textContent: x }); }))),
        el("div", { className: "vl-cside" }, hasLab ? el("button", { type: "button", className: "vl-btn primary lg", onclick: gotoDeploy }, icon("M8 5v14l11-7z", 16), "Deploy this chapter") : null,
          el("span", { className: "vl-status" + (done(l.id) ? " done" : ""), textContent: done(l.id) ? (done(l.id) === "verified" ? "Verified" : done(l.id) === "deployed" ? "Deployed" : "Complete") : "Not started" })));
      var article = el("article", { className: "vl-article vl-ws " + cloud }, hero, el("div", { className: "vl-wsbody" }, nav, content));
      showPane(0, false);
      var main = article;

      var cols = el("div", { className: "vl-cols" + (collapsed ? " oc" : "") }, side, main);
      return el("div", { className: "vl-reader" }, top, cols);
    }

    var q = parseInt(opts.layer, 10);
    return load(cloud).then(function () { if (q && byId(q)) { inCourse = true; go(q); } }).catch(function (e) { root.textContent = "Could not load Vyomi Labs: " + e.message; });
  }
  window.VyomiLabs = { mount: mount };
})();
