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

  function mount(host, opts) {
    opts = opts || {};
    var base = opts.base || "", cloud = opts.cloud || "aws", course = null, sel = null, hasApi = false, store = {};
    var root = el("div", { className: "vl" });
    host.replaceChildren(root);
    var KEY = function () { return "vyomi.labs." + cloud; };
    var done = function (id) { return store[id]; };
    var byId = function (id) { return course.layers.filter(function (l) { return l.id === id; })[0]; };
    var nextId = function () { var l = course.layers.filter(function (x) { return !done(x.id); })[0]; return l ? l.id : null; };
    var nDone = function () { return Object.keys(store).length; };

    function load(c) {
      cloud = c; root.dataset.cloud = c; store = lsGet(KEY()); sel = null;
      return fetch(base + "data/" + c + ".json").then(function (r) { return r.json(); }).then(function (d) {
        course = d;
        return fetch("/api/health").then(function (h) { hasApi = h.ok; }).catch(function () { hasApi = false; });
      }).then(function () { render(); });
    }
    function go(id) { sel = id; render(); var s = host.closest ? host : null; window.scrollTo && window.scrollTo(0, 0); root.scrollIntoView && root.scrollIntoView({ block: "start" }); }
    function render() { root.replaceChildren(sel ? chapterView(byId(sel)) : courseView()); }
    function save() { lsSet(KEY(), store); }

    /* ---------- course view ---------- */
    function courseView() {
      var nx = nextId(), n = nDone(), tot = course.layers.length, pct = Math.round(100 * n / tot);
      var cloudTabs = opts.tabs ? el("nav", { className: "vl-clouds", "aria-label": "Cloud" }, CLOUDS.map(function (c) {
        var b = el("button", { type: "button", textContent: c[1] }); b.setAttribute("aria-current", c[0] === cloud); b.onclick = function () { if (c[0] !== cloud) load(c[0]); }; return b; })) : null;
      var cta = el("button", { type: "button", className: "vl-btn primary lg", onclick: function () { go(nx || course.layers[0].id); } },
        nx ? (n ? "Continue: " : "Start: ") + byId(nx).title : "Review the course", icon(P.arrow, 18));
      var hero = el("header", { className: "vl-hero" },
        el("div", { className: "vl-herotxt" },
          el("div", { className: "vl-eyebrow" }, "Vyomi Labs · " + course.cloud_name),
          el("h1", { textContent: course.title }),
          el("p", { textContent: "Build a complete enterprise agentic AI application layer by layer. Each chapter defines a layer the others use, every step runs on the Vyomi simulator, and anything you have not built yet runs on our reference version so the app always works." }),
          el("div", { className: "vl-stats" },
            el("span", {}, icon(P.book, 16), course.layers.length + " chapters"), el("span", {}, icon(P.clock, 16), "about " + hm(course.total_minutes) + " (estimate)"),
            el("span", {}, icon(P.flag, 16), "Beginner to Advanced")), cloudTabs),
        el("div", { className: "vl-progcard" },
          el("div", { className: "vl-ring", style: "--p:" + pct }, el("b", { textContent: pct + "%" })),
          el("div", {}, el("div", { className: "vl-progt", textContent: n + " of " + tot + " chapters complete" }), el("div", { className: "vl-muted", textContent: nx ? "Up next: chapter " + byId(nx).order + ", " + byId(nx).title : "Course complete" })), cta));

      var map = el("section", { className: "vl-map", "aria-label": "Reference architecture" },
        el("div", { className: "vl-sechead" }, el("h2", { textContent: "The reference architecture" }), el("p", { className: "vl-muted", textContent: "Native " + course.cloud_name + " services (" + course.ai_platform + "). Select any layer to open its chapter." })),
        diagram(null, true), el("ul", { className: "vl-legend" }, el("li", {}, el("i", { className: "vl-dot" }), "Not started"), el("li", {}, el("i", { className: "vl-dot done" }), "Complete"), el("li", {}, el("i", { className: "vl-dot next" }), "Up next")));

      var tiles = el("section", { className: "vl-contents", "aria-label": "Course contents" },
        el("div", { className: "vl-sechead" }, el("h2", { textContent: "Course contents" }), el("p", { className: "vl-muted", textContent: "Recommended order, one chapter at a time. You can start anywhere." })),
        el("div", { className: "vl-tiles" }, course.layers.map(function (l) { return tile(l, nx); })));
      return el("div", { className: "vl-page" }, hero, map, tiles);
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
      var svc = l.services.slice(0, 2).join(", ") + (l.services.length > 2 ? " +" + (l.services.length - 2) : "");
      var kv = function (k, v) { return el("div", { className: "vl-kv" }, el("dt", { textContent: k }), el("dd", { textContent: v })); };
      var stText = st === "done" ? (done(l.id) === "verified" ? "Verified" : done(l.id) === "deployed" ? "Deployed" : "Complete") : st === "next" ? "Up next" : "Not started";
      var t = el("button", { type: "button", className: "vl-tile " + st, style: "--c:" + l.color },
        el("span", { className: "vl-thead" }, el("span", { className: "vl-chno", textContent: pad(l.order) }), el("span", { className: "vl-ttitle", textContent: l.title }), el("span", { className: "vl-state " + st, textContent: stText })),
        el("span", { className: "vl-outcome", textContent: l.outcome }),
        el("dl", { className: "vl-kvs" }, kv("Level", l.level), kv("Duration", "~" + l.minutes + " min"), kv("Lessons", String(l.lessons)), kv("Services", svc)),
        el("span", { className: "vl-tfoot" }, el("span", { className: "vl-cta" }, st === "done" ? "Review chapter" : st === "next" ? "Continue" : "Open chapter", icon(P.arrow, 14))),
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
      var route = meshRoute(), target = route ? "the Mesh (" + route.name + ")" + (route.all ? "" : ": compute and AI calls; storage and databases stay in your browser") : "this browser (Nano)";
      var supported = cloud === "aws";
      var rows = l.lab.map(function (bk) { return { bk: bk, chip: el("span", { className: "vl-dchip", textContent: bk.run ? "waiting" : "saved on run" }), log: el("pre", { className: "vl-dlog" }) }; });
      var btn = el("button", { type: "button", className: "vl-btn primary lg" }, icon("M8 5v14l11-7z", 16), "Deploy this chapter");
      var out = el("div", { className: "vl-dout" });
      var allFiles = function () {   // every earlier chapter's files exist too (this chapter may import them); nothing is run for those
        var f = {}; for (var i = 0; i < course.layers.length; i++) { var c = course.layers[i]; (c.lab || []).forEach(function (b) { f[b.file] = b.code; }); if (c.id === l.id) break; } return f; };
      btn.onclick = function () {
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
        el("div", { className: "vl-dhead" }, el("div", {}, el("h3", { textContent: "Deploy this chapter" }), el("p", { className: "vl-muted", textContent: supported ? "Runs every block below in order against " + target + ", then shows you the resources in the console." : "In-browser deploy for " + course.cloud_name + " is not available yet. Run the blocks below in your own terminal." })), btn),
        supported ? null : el("p", { className: "vl-native", textContent: "Python SDKs for " + course.cloud_name + " have not been proven in the in-browser runner yet; use the Run commands under each block." }),
        el("ol", { className: "vl-drows" }, rows.map(function (r, i) { return el("li", {}, el("div", { className: "vl-drow" }, el("span", { className: "vl-dn", textContent: i + 1 }), el("span", { className: "vl-dt", textContent: r.bk.title }), el("code", { textContent: r.bk.run || r.bk.file }), r.chip), r.log); })), out);
      // button disabled when this cloud is not supported
    }
    function copyBtn(text) { return el("button", { type: "button", className: "vl-copy", title: "Copy", onclick: function (e) { try { navigator.clipboard.writeText(text); e.currentTarget.textContent = "Copied"; } catch (_) {} } }, "Copy"); }
    function labBlock(bk, i) {
      return el("li", { className: "vl-block" },
        el("div", { className: "vl-bhead" }, el("span", { className: "vl-s2n", textContent: i + 1 }), el("div", {}, el("h3", { textContent: bk.title }), el("p", { className: "vl-muted", textContent: bk.text }))),
        el("div", { className: "vl-file" }, el("span", { className: "vl-fname" }, icon("M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5", 14), bk.file), copyBtn(bk.code)),
        el("pre", { className: "vl-pre", textContent: bk.code }),
        bk.run ? el("div", { className: "vl-runrow" }, el("span", { className: "vl-runlbl", textContent: "Run" }), el("code", { textContent: bk.run }), copyBtn(bk.run)) : el("div", { className: "vl-runrow muted" }, el("span", { className: "vl-runlbl", textContent: "Nothing to run yet; the next step uses this file." })),
        bk.expect ? el("div", { className: "vl-expect" }, el("span", { textContent: "You should see" }), el("code", { textContent: bk.expect })) : null);
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
      var buildBody = el("div", {}, hasLab ? el("div", {}, (function () { var d = deployPanel(l); if (cloud !== "aws") d.querySelector("button").disabled = true; return d; })(),
          el("p", { className: "vl-muted", textContent: "Complete these in order. Save each file with the name shown, run the command under it and check the output matches. Point your SDK at the simulator first (open SDK & CLI usage in the bottom drawer for the exact settings)." }),
          el("ol", { className: "vl-blocks" }, l.lab.map(labBlock))) :
        el("div", { className: "vl-note" }, el("b", { textContent: "Code for this chapter is not written yet" }), el("p", { textContent: "Create the resources in the console steps below. The runnable, verified code for this chapter is still being added." }), ul(l.build)));
      var consBody = el("div", {}, el("p", { className: "vl-muted", textContent: "Open each service in the " + course.cloud_name + " console, enter the values shown and compare with the screenshot." }),
        el("ol", { className: "vl-steps2" }, (l.setup || []).map(setupStep)));
      var fitsBody = el("div", {}, el("dl", { className: "vl-contract" }, [el("dt", { textContent: "Needs" }), needs].concat(names)),
        el("div", { className: "vl-note" }, el("b", { textContent: "What the simulator simplifies" }), ul(l.simplified)), l.native ? el("p", { className: "vl-native", textContent: l.native }) : null);
      var valBody = el("div", {}, el("p", { className: "vl-muted", textContent: "Confirm the layer works before moving on. Run each check in the simulator." }), el("ol", { className: "vl-vals" }, valRows),
        el("h3", { className: "vl-h3", textContent: "What the full check covers" }), ul(l.checks), el("p", { className: "vl-muted", textContent: how }), el("div", { className: "vl-actions" }, check, statusEl), out);
      var closing = el("div", { className: "vl-finish" }, el("div", { className: "vl-actions" }, mark), next, el("p", { className: "vl-muted" }, "Reference solution (peek only after you have tried): ", el("code", { textContent: l.reference })));
      var hd = function (id, text, extra) { return el("h2", { id: "vl-" + id, className: "vl-h2" }, text, extra || null); };
      var secs = [];   // [anchor id, heading, body, minutes-badge]
      var main;
      if (cloud === "aws") {
        /* AWS hands-on tutorial: facts table, Overview, What you will accomplish, Prerequisites, Application architecture, Tasks, Clean Up Resources */
        var tasks = [["build", "Build the Code", tm.build, buildBody], ["console", "Create the Resources in the Console", tm.cons, consBody], ["fits", "Connect It to the Other Layers", 5, fitsBody], ["validate", "Validate Your Work", tm.val, valBody], ["clean", "Clean Up Resources", tm.clean, cleanup]];
        main = el("article", { className: "vl-article vl-doc aws" },
          el("h1", { textContent: l.title }),
          facts([["AWS experience", l.level], ["Minimum time to complete", "~" + N + " minutes (estimate)"], ["Cost to complete", "Free: runs on your Vyomi simulator"], ["Services used", svcList], ["Last updated", course.updated]]),
          hd("overview", "Overview"), el("p", { textContent: l.about }), ul(l.why),
          hd("accomplish", "What you will accomplish"), ul(l.learn),
          hd("prereq", "Prerequisites"), ul(l.prereq),
          hd("arch", "Application architecture"), archFig,
          hd("tasks", "Tasks"), el("p", { textContent: "This chapter is divided into " + tasks.length + " tasks. Complete each task in order before moving on." }),
          el("ol", { className: "vl-tasklist" }, tasks.map(function (t, i) { return el("li", {}, el("a", { href: "#vl-t" + i, onclick: function (e) { e.preventDefault(); var n = root.querySelector("#vl-t" + i); n && n.scrollIntoView({ behavior: "smooth", block: "start" }); } }, "Task " + (i + 1) + ": " + t[1]), " (" + t[2] + " minutes)"); })),
          tasks.map(function (t, i) { return el("section", { className: "vl-task", id: "vl-t" + i }, el("h2", { className: "vl-h2" }, "Task " + (i + 1) + ": " + t[1], el("span", { className: "vl-mins", textContent: " (" + t[2] + " minutes)" })), t[3]); }),
          closing);
      } else if (cloud === "gcp") {
        /* Google codelab: Before you begin (Prerequisites, What you'll learn, What you'll need), numbered steps with Duration, Clean up, Congratulations */
        var steps = [["Before you begin", 2, el("div", {}, el("h3", { className: "vl-h3", textContent: "Prerequisites" }), ul(l.prereq), el("h3", { className: "vl-h3", textContent: "What you'll learn" }), ul(l.learn),
            el("h3", { className: "vl-h3", textContent: "What you'll need" }), ul(["The Vyomi " + course.cloud_name + " console open in a browser tab", "Python 3 and a terminal, for the code steps", "About " + N + " minutes"]), el("h3", { className: "vl-h3", textContent: "Why this matters" }), el("p", { textContent: l.about }), ul(l.why)) ],
          ["Architecture", 1, archFig], ["Build the code", tm.build, buildBody], ["Create the resources in the console", tm.cons, consBody], ["Connect it to the other layers", 3, fitsBody], ["Validate", tm.val, valBody], ["Clean up", tm.clean, cleanup]];
        main = el("article", { className: "vl-article vl-doc gcp" },
          el("div", { className: "vl-cl-head" }, el("h1", { textContent: l.title }), el("div", { className: "vl-cl-meta" }, el("span", { textContent: "Duration: ~" + N + " min (estimate)" }), el("span", { textContent: "Level: " + l.level }), el("span", { textContent: "Last updated: " + course.updated })), el("div", { className: "vl-chips" }, l.services.map(function (x) { return el("span", { className: "vl-chip", textContent: x }); }))),
          steps.map(function (t, i) { return el("section", { className: "vl-step", id: "vl-t" + i }, el("h2", { className: "vl-h2" }, el("span", { className: "vl-stepno", textContent: i + 1 }), t[0], el("span", { className: "vl-dur", textContent: "Duration: " + t[1] + " min" })), t[2]); }),
          el("section", { className: "vl-step" }, el("h2", { className: "vl-h2" }, el("span", { className: "vl-stepno", textContent: "✓" }), "Congratulations!"), el("p", { textContent: "You have built " + l.title.toLowerCase() + ": " + l.outcome.charAt(0).toLowerCase() + l.outcome.slice(1) + "." }), closing));
      } else {
        /* Microsoft Learn: intro, In this article, Prerequisites, Sign in, numbered steps with Setting / Suggested value / Description tables, Clean up resources, Next steps */
        var items = [["prereq", "Prerequisites"], ["signin", "Sign in to the Vyomi Azure console"], ["build", "Build the code"], ["create", "Create the resources"], ["fits", "Connect it to the other layers"], ["validate", "Validate"], ["clean", "Clean up resources"], ["next", "Next steps"]];
        var azSteps = (l.setup || []).map(function (st) {
          return el("li", { className: "vl-az-step" }, el("p", {}, el("b", { textContent: st.title + ". " }), st.route ? el("a", { href: consoleUrl(st.route), target: "_blank", rel: "noopener", textContent: "Open " + (st.service || "the service") + " in the console" }) : null), ul(st.do), settingsTable(st, true),
            st.shot ? el("a", { className: "vl-shot", href: base + st.shot, target: "_blank", rel: "noopener" }, el("img", { src: base + st.shot, alt: "Screenshot: " + st.title, loading: "lazy" })) : null, st.note ? el("p", { className: "vl-native", textContent: st.note }) : null);
        });
        main = el("article", { className: "vl-article vl-doc azure" },
          el("div", { className: "vl-crumbs", textContent: "Microsoft Azure  /  Vyomi Labs  /  " + l.title }),
          el("h1", { textContent: l.title }), el("div", { className: "vl-azmeta", textContent: "Chapter " + l.order + " of " + course.layers.length + " · " + l.level + " · about " + N + " min (estimate) · Updated " + course.updated }),
          el("p", { textContent: l.about + " " + l.objective }), ul(l.why),
          el("nav", { className: "vl-inthis", "aria-label": "In this article" }, el("h4", { textContent: "In this article" }), el("ul", {}, items.map(function (t) { return el("li", {}, el("a", { href: "#vl-" + t[0], textContent: t[1], onclick: function (e) { e.preventDefault(); var n = root.querySelector("#vl-" + t[0]); n && n.scrollIntoView({ behavior: "smooth", block: "start" }); } })); }))),
          hd("prereq", "Prerequisites"), ul(l.prereq), archFig,
          hd("signin", "Sign in to the Vyomi Azure console"), el("p", {}, "Open the ", el("a", { href: base + "../v4/azure/", target: "_blank", rel: "noopener", textContent: "Vyomi Azure console" }), ". No account is needed: it runs on your simulator."),
          hd("build", "Build the code"), buildBody,
          hd("create", "Create the resources"), el("p", { textContent: "Use these steps to create the resources in the console." }), el("ol", { className: "vl-az-steps" }, azSteps),
          hd("fits", "Connect it to the other layers"), fitsBody,
          hd("validate", "Validate"), valBody,
          hd("clean", "Clean up resources"), cleanup,
          hd("next", "Next steps"), closing);
      }

      var cols = el("div", { className: "vl-cols" + (collapsed ? " oc" : "") }, side, main);
      return el("div", { className: "vl-reader" }, top, cols);
    }

    var q = parseInt(opts.layer, 10);
    return load(cloud).then(function () { if (q && byId(q)) go(q); }).catch(function (e) { root.textContent = "Could not load Vyomi Labs: " + e.message; });
  }
  window.VyomiLabs = { mount: mount };
})();
