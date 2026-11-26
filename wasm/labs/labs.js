"use strict";
/* Vyomi Labs. VyomiLabs.mount(container, {cloud, base, tabs, layer}) renders the guided layered build for one cloud.
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
    /* the layer count is whatever the course data has, never a typed number: adding a chapter must not leave a stale "13" behind */
    function nLayers() { return course ? course.layers.length : 0; }
    function nWord(cap) { var w = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"][nLayers()] || String(nLayers()); return cap ? w.charAt(0).toUpperCase() + w.slice(1) : w; }
    var base = opts.base || "", cloud = opts.cloud || "aws", course = null, sel = null, inCourse = false, hasApi = false, edition = "mesh", store = {};
    /* Several courses can share one cloud. "facilities" is the original course (data/<cloud>[-nano].json); any other id is listed in data/courses.json and has its own data file, progress and project. */
    var courseId = opts.course || ((location.search.match(/[?&]course=([\w-]+)/) || [])[1]) || "facilities", listing = null;
    var suffix = function () { return courseId === "facilities" ? "" : "." + courseId; };
    var listed = function (id) { return listing && listing.courses.filter(function (c) { return c.id === id && c.cloud === cloud; })[0]; };
    var root = el("div", { className: "vl" });
    host.replaceChildren(root);
    var KEY = function () { return "vyomi.labs." + cloud + suffix(); };
    var done = function (id) { return store[id]; };
    var byId = function (id) { return course.layers.filter(function (l) { return l.id === id; })[0]; };
    var nextId = function () { var l = course.layers.filter(function (x) { return !done(x.id); })[0]; return l ? l.id : null; };
    var nDone = function () { return Object.keys(store).length; };

    function load(c) {
      cloud = c; root.dataset.cloud = c; store = lsGet(KEY()); sel = null; inCourse = false;
      /* This course is the Pro/Max Mesh course: one data file per cloud, deployed only through a Mesh or the Vyomi runner. */
      return fetch("/api/health").then(function (h) { hasApi = h.ok; }).catch(function () { hasApi = false; }).then(function () {
        edition = "mesh";
        return (listing ? Promise.resolve() : fetch(base + "data/courses.json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { listing = j; }, function () { listing = null; })).then(function () {
        if (courseId !== "facilities" && !listed(courseId)) { courseId = "facilities"; store = lsGet(KEY()); }
        if (courseId !== "facilities") return fetch(base + "data/" + listed(courseId).file, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("no course"); return r.json(); });
        return fetch(base + "data/" + c + ".json", { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("no course data"); return r.json(); });
        });
      }).then(function (d) { course = d; }).then(function () { render(); });
    }
    function go(id) { sel = id; render(); var s = host.closest ? host : null; window.scrollTo && window.scrollTo(0, 0); root.scrollIntoView && root.scrollIntoView({ block: "start" }); }
    function render() { root.replaceChildren(sel === "intro" ? introView() : sel ? chapterView(byId(sel)) : inCourse ? courseView() : catalogView()); }
    function save() { lsSet(KEY(), store); }

    /* ---------- landing: every hands-on course as a card ---------- */
    /* Plan tag: which plans include this course (course.plan comes from the course data). */
    function planTag() { var p = course.plan || []; return p.length ? el("span", { className: "vl-ribbon", title: "This course needs a " + p.join(" or ") + " plan", "aria-label": "Plan: " + p.join(" or ") }, el("span", { textContent: p.join(" · ") })) : null; }
    function catalogView() {
      var nx = nextId(), n = nDone(), tot = course.layers.length, pct = Math.round(100 * n / tot);
      var labN = course.layers.reduce(function (a, l) { return a + (l.lab ? l.lab.length : 0); }, 0);
      var cloudTabs = opts.tabs ? el("nav", { className: "vl-clouds", "aria-label": "Cloud" }, CLOUDS.map(function (c) {
        var b = el("button", { type: "button", textContent: c[1] }); b.setAttribute("aria-current", c[0] === cloud); b.onclick = function () { if (c[0] !== cloud) load(c[0]); }; return b; })) : null;
      var stat = function (ic, v, k) { return el("div", { className: "vl-stat" }, el("span", { className: "vl-stati" }, icon(ic, 18)), el("div", {}, el("b", { textContent: v }), el("small", { textContent: k }))); };
      var start = function () { inCourse = true; render(); window.scrollTo && window.scrollTo(0, 0); root.scrollIntoView && root.scrollIntoView({ block: "start" }); };
      var card = el("article", { className: "vl-ccard" + ((course.plan || []).length ? " has-ribbon" : "") }, planTag(),
        el("div", { className: "vl-herotxt" },
          el("div", { className: "vl-eyebrow" }, (otherCards().length ? "Enterprise course · Advanced · " : "Hands-on course · ") + course.cloud_name + " · " + course.ai_platform),
          el("h2", { textContent: course.title }),
          el("p", { textContent: "Build a complete enterprise agentic AI application layer by layer. Every chapter gives you the code, deploys it to your simulator and verifies it, so the app always works." }),
          el("div", { className: "vl-statrow" }, stat(P.book, String(tot), "chapters"), stat(P.clock, hm(course.total_minutes), "estimated"), stat("M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12", String(labN), "code steps"), stat(P.flag, "Beginner to Advanced", nLayers() + " layers")), archLink()),
        el("div", { className: "vl-progcard" },
          el("div", { className: "vl-ring", style: "--p:" + pct }, el("b", { textContent: pct + "%" })),
          el("div", {}, el("div", { className: "vl-progt", textContent: n + " of " + tot + " complete" }), el("div", { className: "vl-muted", textContent: nx ? "Up next: " + byId(nx).title : "Course complete" })),
          el("button", { type: "button", className: "vl-btn primary lg", onclick: start }, n ? "Continue course" : "Start course", icon(P.arrow, 18))));
      return el("div", { className: "vl-page" },
        el("header", { className: "vl-cathead" }, el("div", {}, el("h1", { textContent: "Vyomi Labs" }), el("p", { className: "vl-muted", textContent: "Hands-on courses. Build real applications on " + course.cloud_name + " services running in your simulator." })), cloudTabs,
          (course.plan || []).length ? el("p", { className: "vl-disclaimer" }, icon("M12 8v5M12 16.500v.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", 16),
            el("span", {}, el("b", { textContent: "Deploying needs a Mesh. " }), ("Courses that deploy code run it inside a Mesh, which is included with the "), el("span", { className: "vl-planchip", textContent: course.plan.join(" \u00b7 ").toUpperCase() }), " plans. You can always read every lesson, browse and edit the code, and download the project.")) : null),
        el("div", { className: "vl-cgrid" }, otherCards(), card, otherCards().length ? null : el("div", { className: "vl-ccard soon" }, el("b", { textContent: "More hands-on courses are on the way" }), el("span", { className: "vl-muted", textContent: "New courses appear here as they are published." }))));
    }
    /* The other courses listed in data/courses.json for this cloud, as cards of their own (Nano edition only). Each has its own data, progress and project. */
    function otherCards() {
      if (!listing || cloud !== "aws") return [];
      return listing.courses.filter(function (c) { return c.cloud === cloud && c.id !== courseId; }).map(function (c) {
        var st = lsGet(c.key), n = Object.keys(st).length, pct = Math.round(100 * n / c.chapters);
        var stat = function (ic, v, k) { return el("div", { className: "vl-stat" }, el("span", { className: "vl-stati" }, icon(ic, 18)), el("div", {}, el("b", { textContent: v }), el("small", { textContent: k }))); };
        var open = function () { courseId = c.id; load(cloud).then(function () { inCourse = true; render(); window.scrollTo && window.scrollTo(0, 0); }); };
        return el("article", { className: "vl-ccard", "data-course": c.id },
          el("div", { className: "vl-herotxt" }, el("div", { className: "vl-eyebrow" }, c.kicker + " \u00b7 " + c.level + " \u00b7 " + c.badge), el("h2", { textContent: c.title }), el("p", { textContent: c.blurb }),
            el("div", { className: "vl-statrow" }, stat(P.book, String(c.chapters), "chapters"), stat(P.clock, hm(c.minutes), "estimated"), stat(P.flag, c.level, "level"))),
          el("div", { className: "vl-progcard" }, el("div", { className: "vl-ring", style: "--p:" + pct }, el("b", { textContent: pct + "%" })),
            el("div", {}, el("div", { className: "vl-progt", textContent: n + " of " + c.chapters + " complete" }), el("div", { className: "vl-muted", textContent: c.kicker === "Start here" ? "New to agents? Begin here." : "Continue when you are ready." })),
            el("button", { type: "button", className: "vl-btn primary lg", onclick: open }, n ? "Continue course" : "Start course", icon(P.arrow, 18))));
      });
    }

    /* ---------- Start here: the premise (why this many layers) ---------- */
    var WHY = { 10: ["Platform lead", "Can we change the model without rewriting the app?", "Every part hard-wires a model; one change breaks them all."],
      3: ["Engineering manager", "What stops it running away, or mixing up two users?", "One giant agent that loops, leaks between users and cannot be tested."],
      7: ["Security", "What exactly is the agent allowed to do?", "Functions with no contract: the model can call anything with any argument."],
      12: ["Knowledge owner", "How does our latest documentation get in, and stay current?", "Documents go stale the first busy week; nobody re-imports them."],
      6: ["Domain expert", "Does it find the right passage before it answers?", "Confident answers built on the wrong page."],
      11: ["Legal and risk", "Can every statement be traced to a source, with private data kept out?", "Invented answers with no source, and private data repeated back."],
      9: ["Privacy officer", "What does it remember, and can one user's data reach another?", "Every chat starts from zero, or one user's details reach another."],
      4: ["CISO", "Who may call which tool, and where is that decided?", "Permissions scattered across eight codebases; nobody can answer an auditor."],
      5: ["Business owner", "Who signs off before something real changes?", "The agent writes first and apologises later; a restart loses the request."],
      1: ["IT operations", "Who is calling, and who is flooding us?", "Anonymous callers and one noisy client burning the whole model budget."],
      2: ["Security", "What if the message itself is an attack?", "A single clever sentence rewrites the agent's rules."],
      8: ["Operations", "Why was it slow or wrong last night?", "A chain of calls and a log line that just says error."],
      13: ["Auditor", "Can we prove what happened, and that nobody altered it?", "Plain-text records and a trail nobody can trust."],
      14: ["Knowledge architect", "Was the search designed and tested on real questions, or are these just defaults?", "Chunk sizes and search settings guessed once and never measured against the questions people ask."] };
    /* Scroll spy: highlight the "On this page" link of the section being read. */
    function tocSpy(rootEl) {
      var links = [].slice.call(rootEl.querySelectorAll(".vl-toc a")), secs = links.map(function (a) { return rootEl.querySelector("#" + (a.getAttribute("href") || "").slice(1)); }), vis = {};
      if (!links.length || !window.IntersectionObserver) return;
      function paint() {
        var cur = -1; for (var i = 0; i < secs.length; i++) if (vis[i]) { cur = i; break; }
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 6) cur = secs.length - 1;
        if (cur < 0) { for (var k = secs.length - 1; k >= 0; k--) if (secs[k] && secs[k].getBoundingClientRect().top < window.innerHeight * 0.3) { cur = k; break; } }
        links.forEach(function (a, i) { a.classList.toggle("on", i === cur); if (i === cur) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); });
      }
      var io = new IntersectionObserver(function (es) { es.forEach(function (e) { vis[secs.indexOf(e.target)] = e.isIntersecting; }); paint(); }, { rootMargin: "-12% 0px -72% 0px", threshold: 0 });
      secs.forEach(function (x) { x && io.observe(x); }); window.addEventListener("scroll", paint, { passive: true }); setTimeout(paint, 60);
    }
    function quizBlock(qs) {
      var res = []; var score = el("span", { className: "vl-score", textContent: "Pick an answer" });
      var cards = qs.map(function (q, qi) {
        var box = el("div", { className: "vl-q" }, el("p", { className: "vl-qt" }, el("span", { className: "vl-qn", textContent: "Q" + (qi + 1) }), q[0])), fb = el("div", { className: "vl-qfb", hidden: true }), answered = false;
        q[1].forEach(function (opt, oi) {
          var bt = el("button", { type: "button", className: "vl-qo", textContent: opt });
          bt.onclick = function () { if (answered) return; answered = true; var ok = oi === q[2]; res[qi] = ok;
            box.querySelectorAll(".vl-qo").forEach(function (x, k) { x.disabled = true; if (k === q[2]) x.classList.add("right"); else if (k === oi) x.classList.add("wrong"); });
            fb.hidden = false; fb.className = "vl-qfb " + (ok ? "ok" : "no"); fb.replaceChildren(el("b", { textContent: ok ? "Correct. " : "Not quite. " }), q[3]);
            score.textContent = res.filter(Boolean).length + " of " + qs.length + " correct" + (res.filter(function (x) { return x !== undefined; }).length < qs.length ? " so far" : ""); };
          box.append(bt);
        });
        box.append(fb); return box;
      });
      return el("div", {}, cards, el("div", { className: "vl-scorebar" }, score));
    }
    function demoSvg() {   // the "before": a forty-line demo, cloud-neutral
      var box = function (x, y, w, t, sub, hot) { return '<g><rect x="' + x + '" y="' + y + '" width="' + w + '" height="86" rx="12" fill="' + (hot ? "#1a6e66" : "#fff") + '" stroke="' + (hot ? "#1a6e66" : "#9aa7b4") + '" stroke-width="2"/><text x="' + (x + w / 2) + '" y="' + (y + 38) + '" text-anchor="middle" font-size="17" font-weight="700" fill="' + (hot ? "#fff" : "#1b2733") + '">' + t + '</text><text x="' + (x + w / 2) + '" y="' + (y + 62) + '" text-anchor="middle" font-size="13" fill="' + (hot ? "#d6ece9" : "#5d6b78") + '">' + sub + '</text></g>'; };
      var arrow = function (x1, x2) { return '<path d="M' + x1 + ' 83 H' + (x2 - 8) + '" stroke="#5d6b78" stroke-width="2.5" fill="none"/><path d="M' + (x2 - 8) + ' 76 L' + x2 + ' 83 L' + (x2 - 8) + ' 90Z" fill="#5d6b78"/>'; };
      var gaps = ["No sign-in", "No limits", "No guardrails", "No memory", "No approvals", "No logs", "No audit"], g = gaps.map(function (t, i) { return '<g><rect x="' + (28 + i * 126) + '" y="186" width="116" height="34" rx="17" fill="#fdecea" stroke="#e0a39b" stroke-dasharray="4 3"/><text x="' + (86 + i * 126) + '" y="208" text-anchor="middle" font-size="13" fill="#a3382c" font-weight="600">' + t + '</text></g>'; }).join("");
      var d = document.createElement("div"); d.className = "vl-archfig";
      d.innerHTML = '<svg viewBox="0 0 910 240" role="img" aria-label="A demo architecture: a chat box calls a model, which calls one function" style="width:100%;height:auto;font-family:inherit">' +
        box(28, 40, 170, "Chat box", "one user, one tab") + arrow(198, 268) + box(268, 40, 170, "Model", "one hard-coded name", 1) + arrow(438, 508) + box(508, 40, 170, "One function", "any input, any caller") + arrow(678, 748) + box(748, 40, 134, "Data", "plain text") + g + '</svg>';
      return d;
    }
    function archFigure(kind) {
      if (kind === "before") return demoSvg();
      var a = el("a", { className: "vl-archfig", href: base + course.image, target: "_blank", rel: "noopener", title: "Open full size" });
      a.append(el("img", { src: base + course.image, alt: "The enterprise reference architecture, " + course.cloud_name, style: "width:100%;height:auto;display:block" })); return a;
    }
    function introView() {
      var L = course.layers, first = L[0], sc = function (id, t, b, c) { return el("section", { className: "vl-lsec " + (c || ""), id: "vl-i-" + id }, el("h3", { textContent: t }), b); };
      
      var main = el("div", { className: "vl-lmain" },
        sc("story", "The problem", el("blockquote", { className: "vl-scene" }, el("p", { textContent: "The facilities team at the Northwind campus answers thousands of questions a week: boiler limits, service history, which air handler is drifting. They want an assistant that answers from the company's own documents and can open a work order. Priya, a night technician, will be one of its first users." }))),
        sc("simple", "The simplest architecture", el("div", {}, el("p", { textContent: "The quickest way to build it is four boxes and about forty lines of code: a chat box, a model, one function, and some data." }), archFigure("before"),
          el("div", { className: "vl-gn" }, el("div", { className: "vl-got" }, el("h4", { textContent: "What it achieves" }), el("ul", {}, ["Answers questions in plain language", "Looks up an asset and returns its status", "Opens a work order when asked", "Runs in an afternoon"].map(function (t) { return el("li", { textContent: t }); }))),
            el("div", { className: "vl-miss" }, el("h4", { textContent: "What it does not" }), el("ul", {}, ["Who is asking, and how many people may ask", "Limits on what the agent is allowed to do", "Answers grounded in the company's documents, with sources", "A human decision before anything changes", "A way to see what happened, or to prove it later"].map(function (t) { return el("li", { textContent: t }); })))))),
        sc("beyond", "Why an enterprise goes beyond the functional scope", el("div", {}, el("p", { textContent: "The simple version meets the functional requirement: it does the task. An enterprise is also accountable for how the task is done, and each of those concerns arrives as a question from someone who has to sign off." }),
          el("div", { className: "vl-reasons" }, [["Risk", "An agent acts, it does not only answer. One bad action can cost more than the system saves."], ["Scale", "Thousands of users share one model budget and must never see each other's data."], ["Accountability", "Auditors and regulators ask who did what, when and why, and expect proof."], ["Change", "Models, documents and people change every week. The system has to absorb it without breaking."]].map(function (r) { return el("div", { className: "vl-reason" }, el("b", { textContent: r[0] }), el("p", { textContent: r[1] })); })))),
        sc("questions", nWord(1) + " questions an enterprise asks before going live", el("div", {}, el("p", { textContent: "Before an enterprise lets an agent near real work, " + nWord() + " different people ask " + nWord() + " different questions. The simple design answers none of them. Each question below is answered by exactly one layer, which is why the architecture has " + nWord() + " of them. Select a question to open its chapter." }),
          el("ol", { className: "vl-why" }, L.map(function (l) { var w = WHY[l.id] || ["", "", ""];
            var li = el("li", { style: "--c:" + l.color }, el("span", { className: "vl-wn", textContent: l.order }), el("div", {}, el("span", { className: "vl-wwho", textContent: w[0] + " asks" }), el("span", { className: "vl-wq", textContent: w[1] }), el("small", { textContent: "Without an answer: " + w[2] }), el("span", { className: "vl-wans" }, "Answered by ", el("b", { textContent: "Layer " + l.order + ": " + l.title }))), icon(P.arrow, 14));
            li.onclick = function () { go(l.id); }; return li; })))),
        sc("arch", "The resulting architecture", el("div", {}, el("p", { textContent: "Answer all " + nWord() + " questions and this is the architecture you end up with. It is not a bigger version of the simple design: every part exists because one of those questions needed an answer." }), archFigure("after"),
          el("p", { className: "vl-bacap", textContent: "Select the diagram to open it full size." }))),
        sc("how", "How this course works", el("ol", { className: "vl-tl" }, [["You build the same app all the way through", "One facilities agent, one layer at a time. Chapter 1 gives it a brain; chapter " + nLayers() + " makes it auditable."], ["Every chapter gives you the code and runs it", "Press Deploy and the code goes into your simulator as it is, then a check confirms it works."], ["Nothing is left half-built", "Each chapter ends with a working app, so you can stop anywhere and still have something real."], ["The same story on every cloud", "AWS, Google Cloud and Azure follow the same " + nLayers() + " layers with each cloud's own services."]].map(function (w, i) { return el("li", {}, el("span", { className: "vl-tn", textContent: i + 1 }), el("div", {}, el("b", { textContent: w[0] }), el("p", { textContent: w[1] }))); }))),
        sc("recap", "Recap", el("div", {}, el("ul", { className: "vl-recap" }, ["The simple design meets the functional need; an enterprise is also accountable for how it is met.", "Each of the " + nLayers() + " layers closes one specific gap and prevents one failure.", "You build one working app, a layer at a time, and every chapter is deployed and checked."].map(function (t) { return el("li", {}, icon(P.check, 16), t); })),
          el("button", { type: "button", className: "vl-btn primary lg", onclick: function () { go(first.id); } }, "Start Chapter 1: " + first.title, icon(P.arrow, 16)))));
      var side = el("aside", { className: "vl-lside" }, el("nav", { className: "vl-toc" }, el("h4", { textContent: "On this page" }), [["story", "The problem"], ["simple", "The simplest architecture"], ["beyond", "Beyond the functional scope"], ["questions", nWord(1) + " questions"], ["arch", "The resulting architecture"], ["how", "How this course works"], ["recap", "Recap"]].map(function (t) { var a = el("a", { href: "#vl-i-" + t[0], textContent: t[1] }); a.onclick = function (e) { e.preventDefault(); var x = root.querySelector("#vl-i-" + t[0]); x && x.scrollIntoView({ behavior: "smooth", block: "start" }); }; return a; })));
      var chip = function (ic, t) { return el("span", { className: "vl-hchip" }, icon(ic, 14), t); };
      var back = el("button", { type: "button", className: "vl-back", onclick: function () { sel = null; render(); } }, icon(P.back, 16), "Course contents");
      var top = el("div", { className: "vl-topbar" }, back, el("span", { className: "vl-crumb", textContent: course.cloud_name + " · Start here" }),
        el("span", { className: "vl-topprog" }, el("span", { textContent: nDone() + " of " + course.layers.length + " complete" }), el("span", { className: "vl-bar" }, el("i", { style: "width:" + (100 * nDone() / course.layers.length) + "%" }))));
      var hero = el("header", { className: "vl-chero", style: "--c:#1a6e66" },
        el("div", { className: "vl-cicon" }, icon(P.book, 30)),
        el("div", { className: "vl-ctext" },
          el("div", { className: "vl-crumbs2", textContent: course.cloud_name + "  /  Vyomi Labs  /  Start here" }),
          el("h1", { textContent: "Why an enterprise agent needs " + nLayers() + " layers" }),
          el("p", { textContent: "The problem, the simplest design that solves it, what that design cannot do, and the " + nLayers() + " questions that lead to the full architecture." }),
          el("div", { className: "vl-cchips" }, chip(P.flag, "Beginner"), chip(P.clock, "~5 min"), chip("M4 6h16M4 12h16M4 18h10", "Lesson and quiz"))),
        el("div", { className: "vl-cside" }, el("span", { className: "vl-status", textContent: "Read first" })));
      var article = el("article", { className: "vl-article vl-ws " + cloud }, hero, el("div", { className: "vl-wsbody single" }, el("div", { className: "vl-lesson", style: "--c:#1a6e66" }, main, side)));
      var pageEl = el("div", { className: "vl-reader vl-intropage" }, top, el("div", { className: "vl-cols" }, article));
      tocSpy(pageEl); return pageEl;
    }
    /* ---------- course view ---------- */
    /* ---------- In-course code editor: the project's files in a Monaco editor (plain textarea if the CDN is unreachable); edits stay in this browser ---------- */
    var PROJ = null, monacoP = null;
    function loadProject() { return PROJ ? Promise.resolve(PROJ) : fetch(base + "project/" + cloud + (courseId === "facilities" ? "" : "-" + courseId) + ".json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (j) { PROJ = j; return j; }); }
    function loadMonaco() {
      if (monacoP) return monacoP;
      var CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min";
      monacoP = new Promise(function (ok, bad) {
        var sc = document.createElement("script"); sc.src = CDN + "/vs/loader.js"; sc.onerror = function () { bad(new Error("offline")); };
        sc.onload = function () {
          window.MonacoEnvironment = { getWorkerUrl: function () { return "data:text/javascript;charset=utf-8," + encodeURIComponent("self.MonacoEnvironment={baseUrl:'" + CDN + "/'};importScripts('" + CDN + "/vs/base/worker/workerMain.js');"); } };
          window.require.config({ paths: { vs: CDN + "/vs" } }); window.require(["vs/editor/editor.main"], function () { ok(window.monaco); }, bad);
        };
        document.head.appendChild(sc); setTimeout(function () { bad(new Error("timeout")); }, 15000);
      });
      return monacoP;
    }
    function crc32(u8) { var t = crc32.t || (crc32.t = (function () { var a = [], c, n, k; for (n = 0; n < 256; n++) { c = n; for (k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; a[n] = c >>> 0; } return a; })()), c2 = 0xFFFFFFFF; for (var i = 0; i < u8.length; i++) c2 = t[(c2 ^ u8[i]) & 255] ^ (c2 >>> 8); return (c2 ^ 0xFFFFFFFF) >>> 0; }
    function zipOf(files) {   // store-only zip, no library
      var enc = new TextEncoder(), parts = [], cen = [], off = 0, n = 0;
      function u16(v) { return [v & 255, (v >> 8) & 255]; } function u32(v) { return [v & 255, (v >> 8) & 255, (v >> 16) & 255, (v >>> 24) & 255]; }
      Object.keys(files).forEach(function (path) {
        var nm = enc.encode(path), d = enc.encode(files[path]), crc = crc32(d);
        var lh = new Uint8Array([].concat(u32(0x04034b50), u16(20), u16(0x800), u16(0), u16(0), u16(0x21), u32(crc), u32(d.length), u32(d.length), u16(nm.length), u16(0)));
        parts.push(lh, nm, d);
        cen.push(new Uint8Array([].concat(u32(0x02014b50), u16(20), u16(20), u16(0x800), u16(0), u16(0), u16(0x21), u32(crc), u32(d.length), u32(d.length), u16(nm.length), u16(0), u16(0), u16(0), u16(0), u32(0), u32(off))), nm);
        off += lh.length + nm.length + d.length; n++;
      });
      var cl = cen.reduce(function (a, x) { return a + x.length; }, 0);
      return new Blob(parts.concat(cen, [new Uint8Array([].concat(u32(0x06054b50), u16(0), u16(0), u16(n), u16(n), u32(cl), u32(off), u16(0)))]), { type: "application/zip" });
    }
    function openEditor(startPath) {
      var ov = el("div", { className: "vl-ed", role: "dialog", "aria-label": "Code editor" }, el("div", { className: "vl-edload", textContent: "Opening the project..." }));
      root.appendChild(ov); var closeEd = function () { try { ed && ed.dispose(); } catch (_) {} ov.remove(); document.removeEventListener("keydown", onKey); }, ed = null;
      var onKey = function (e) { if (e.key === "Escape") closeEd(); }; document.addEventListener("keydown", onKey);
      Promise.all([loadProject(), loadMonaco().catch(function () { return null; })]).then(function (r) {
        var proj = r[0], mon = r[1], KEYE = "vyomi.labs.edit." + cloud + suffix(), edits = {}; try { edits = JSON.parse(localStorage.getItem(KEYE) || "{}"); } catch (_) {}
        var paths = Object.keys(proj.files), models = {}, cur = null, treeEl = el("div", { className: "vl-edtree" }), tabsEl = el("div", { className: "vl-edtabs" }), host = el("div", { className: "vl-edhost" }), ta = null, open = [];
        var text = function (p) { return edits[p] !== undefined ? edits[p] : proj.files[p]; };
        var persist = function () { try { localStorage.setItem(KEYE, JSON.stringify(edits)); } catch (_) {} };
        var lang = function (p) { return /\.py$/.test(p) ? "python" : /\.md$/.test(p) ? "markdown" : /\.json$/.test(p) ? "json" : /\.sh$/.test(p) ? "shell" : "plaintext"; };
        if (mon) ed = mon.editor.create(host, { value: "", language: "python", theme: "vs", automaticLayout: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false });
        else { ta = el("textarea", { className: "vl-edta", spellcheck: false }); host.append(ta); }
        function setVal(p) {
          if (mon) { if (!models[p]) { models[p] = mon.editor.createModel(text(p), lang(p)); models[p].onDidChangeContent(function () { var v = models[p].getValue(); if (v === proj.files[p]) delete edits[p]; else edits[p] = v; persist(); paint(); }); } ed.setModel(models[p]); }
          else { ta.value = text(p); ta.oninput = function () { if (ta.value === proj.files[p]) delete edits[p]; else edits[p] = ta.value; persist(); paint(); }; }
        }
        function show(p) { cur = p; if (open.indexOf(p) < 0) open.push(p); setVal(p); paint(); }
        function paint() {
          tabsEl.replaceChildren.apply(tabsEl, open.map(function (p) { var t = el("button", { type: "button", className: "vl-edtab" + (p === cur ? " on" : "") }, p.split("/").pop(), edits[p] !== undefined ? el("i", { className: "vl-eddot", title: "Edited" }) : null,
            el("span", { className: "vl-edx", textContent: "×", onclick: function (e) { e.stopPropagation(); open.splice(open.indexOf(p), 1); if (cur === p) { if (open.length) show(open[open.length - 1]); else { cur = null; if (mon) ed.setModel(null); else ta.value = ""; paint(); } } else paint(); } })); t.onclick = function () { show(p); }; return t; }));
          [].forEach.call(treeEl.querySelectorAll(".vl-edf"), function (b) { b.classList.toggle("on", b.getAttribute("data-p") === cur); });
          reset.hidden = !(cur && edits[cur] !== undefined);
        }
        var groups = {}; paths.forEach(function (p) { var d = p.indexOf("/") < 0 ? "" : p.slice(0, p.lastIndexOf("/")); (groups[d] = groups[d] || []).push(p); });
        Object.keys(groups).sort(function (a, b) { var r = function (d) { return d === "" ? 0 : /^\d\d-/.test(d) ? 1 : 2; }; return r(a) - r(b) || (a < b ? -1 : 1); }).forEach(function (d) {
          if (d) treeEl.append(el("div", { className: "vl-edd", textContent: d + "/" }));
          groups[d].forEach(function (p) { var b = el("button", { type: "button", className: "vl-edf", "data-p": p, textContent: p.split("/").pop() }); b.onclick = function () { show(p); }; treeEl.append(b); });
        });
        var reset = el("button", { type: "button", className: "vl-btn sm", textContent: "Reset file", hidden: true, onclick: function () { if (!cur) return; delete edits[cur]; persist(); if (mon) models[cur].setValue(proj.files[cur]); else ta.value = proj.files[cur]; paint(); } });
        var dl = el("button", { type: "button", className: "vl-btn sm primary", textContent: "Download project (zip)", onclick: function () { var all = {}; paths.forEach(function (p) { all[proj.name + "/" + p] = text(p); }); var a = el("a", { href: URL.createObjectURL(zipOf(all)), download: proj.name + ".zip" }); document.body.append(a); a.click(); a.remove(); } });
        ov.replaceChildren(el("div", { className: "vl-edbar" }, el("b", { textContent: proj.name }), el("span", { className: "vl-muted", textContent: mon ? "Your edits are kept in this browser." : "Basic editor (the full editor could not be loaded). Your edits are kept in this browser." }), el("span", { className: "vl-edsp" }), reset, dl, el("button", { type: "button", className: "vl-btn sm", textContent: "Close", onclick: closeEd })),
          el("div", { className: "vl-edmain" }, treeEl, el("div", { className: "vl-edright" }, tabsEl, host)));
        show(startPath && proj.files[startPath] !== undefined ? startPath : (paths.indexOf("README.md") >= 0 ? "README.md" : paths[0]));
      }).catch(function (e) { ov.replaceChildren(el("div", { className: "vl-edload", textContent: "Could not open the project: " + e.message }), el("button", { type: "button", className: "vl-btn", textContent: "Close", onclick: function () { ov.remove(); } })); });
    }
    /* The finished code is a real GitHub project (projects/vyomi-labs-facilities-agent/<cloud>); every block here is a file in it. */
    function ghUrl(path) { return "https://github.com/" + course.repo + (path || ""); }
    function ghBase() { return (course.repo_path ? course.repo_path + "/" : "") + cloud; }
    var slugOf = function (t) { return t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); };
    function layerDir(l) { return String(l.order).padStart(2, "0") + "-" + slugOf(l.title); }
    function projFile(file) { for (var i = 0; i < course.layers.length; i++) { var c = course.layers[i]; if ((c.lab || []).some(function (b) { return b.file === file; })) return layerDir(c) + "/" + file; } return file; }
    function downloadProject() { loadProject().then(function (p) { var all = {}; Object.keys(p.files).forEach(function (f) { all[p.name + "/" + f] = p.files[f]; }); var a = el("a", { href: URL.createObjectURL(zipOf(all)), download: p.name + ".zip" }); document.body.append(a); a.click(); a.remove(); }); }
    function projectCard() {
      var btn = function (txt, primary, fn) { return el("button", { type: "button", className: "vl-btn" + (primary ? " primary" : ""), onclick: fn, textContent: txt }); };
      return el("section", { className: "vl-projcard" },
        el("div", { className: "vl-projtxt" }, el("small", { textContent: "The finished project" }), el("h3", { textContent: "Take the full code with you" }),
          el("p", { textContent: "Everything you build here is one runnable " + course.cloud_name + " project: every file is the exact code from the chapters, in order, with a README per chapter and a script that runs them all. Open it in the editor right here, or download it." })),
        el("div", { className: "vl-projbtns" }, btn("Open in editor", true, function () { openEditor("README.md"); }), btn("Download project (zip)", false, downloadProject)));
    }
    /* The chapter's code is part of the project: open it in the editor right here. */
    function chapterCode(l) {
      var first = (l.lab || [])[0], dir = layerDir(l);
      return el("div", { className: "vl-codelinks" }, el("b", { textContent: "The full code for this chapter" }), el("span", { className: "vl-muted", textContent: "It is part of the project; open it in the editor." }),
        el("div", { className: "vl-projbtns" }, el("button", { type: "button", className: "vl-btn primary", textContent: "Open in editor", onclick: function () { openEditor(first ? dir + "/" + first.file : dir + "/README.md"); } }),
          el("button", { type: "button", className: "vl-btn", textContent: "Layer guide", onclick: function () { openEditor(dir + "/README.md"); } })));
    }
    function archLink() {   // the full architecture this course teaches you to build, opened full size in its own tab
      if (!course.image) return null;
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
      var hero = el("header", { className: "vl-hero" + ((course.plan || []).length ? " has-ribbon" : "") }, planTag(),
        el("div", { className: "vl-herotxt" },
          el("button", { type: "button", className: "vl-backlink", onclick: function () { inCourse = false; if (courseId !== "facilities") { courseId = "facilities"; load(cloud); } else render(); } }, icon(P.back, 14), "All courses"),
          el("div", { className: "vl-eyebrow" }, "Vyomi Labs · " + course.cloud_name + " · " + course.ai_platform),
          el("h1", { textContent: course.title }),
          el("p", { textContent: course.blurb || "Build a complete enterprise agentic AI application layer by layer. Every chapter gives you the code, deploys it to your simulator and verifies it, so the app always works." }),
          el("div", { className: "vl-statrow" }, stat(P.book, String(tot), "chapters"), stat(P.clock, hm(course.total_minutes), "estimated"), stat("M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12", String(labN), "code steps to copy and run"), stat(P.flag, "Beginner to Advanced", nLayers() + " layers")), archLink(), cloudTabs),
        el("div", { className: "vl-progcard" },
          el("div", { className: "vl-ring", style: "--p:" + pct }, el("b", { textContent: pct + "%" })),
          el("div", {}, el("div", { className: "vl-progt", textContent: n + " of " + tot + " complete" }), el("div", { className: "vl-muted", textContent: nx ? "Up next: " + byId(nx).title : "Course complete" })), cta));

      var map = !course.image ? null : el("section", { className: "vl-map", "aria-label": "Reference architecture" },
        el("div", { className: "vl-sechead" }, el("h2", { textContent: "Reference architecture" }), el("p", { className: "vl-muted", textContent: "Native " + course.cloud_name + " services. Select any layer to open its chapter." }), archLink()),
        diagram(null, true), el("ul", { className: "vl-legend" }, el("li", {}, el("i", { className: "vl-dot" }), "Not started"), el("li", {}, el("i", { className: "vl-dot done" }), "Complete"), el("li", {}, el("i", { className: "vl-dot next" }), "Up next")));

      var tiles = el("section", { className: "vl-contents", "aria-label": "Course contents" },
        el("div", { className: "vl-sechead" }, el("h2", { textContent: "Course contents" }), el("p", { className: "vl-muted", textContent: "Recommended order. You can start anywhere." })),
        el("div", { className: "vl-tiles" }, course.intro === false ? null : introTile(), course.layers.map(function (l) { return tile(l, nx); })));
      return el("div", { className: "vl-page" }, hero, tiles, map, projectCard());
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

    function introTile() {   // "Start here": the premise lesson, the first tile of the course
      var m = function (ic, t) { return el("span", {}, icon(ic, 13), t); };
      var t = el("button", { type: "button", className: "vl-tile intro", style: "--c:#1a6e66" },
        el("span", { className: "vl-thead" }, el("span", { className: "vl-ticon" }, icon(P.book, 20)), el("span", { className: "vl-chno", textContent: "Start here" }), el("span", { className: "vl-state next", textContent: "5 min read" })),
        el("span", { className: "vl-ttitle", textContent: "Why an enterprise agent needs " + nLayers() + " layers" }),
        el("span", { className: "vl-outcome", textContent: "The problem, the simplest design that solves it, what it cannot do, and the " + nLayers() + " questions that lead to the full architecture." }),
        el("span", { className: "vl-tmeta" }, m(P.clock, "~5 min"), m("M4 6h16M4 12h16M4 18h10", "Lesson and quiz")),
        el("span", { className: "vl-tfoot" }, el("span", { className: "vl-cta" }, "Read", icon(P.arrow, 14))));
      t.onclick = function () { go("intro"); }; return t;
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
      worker = new Worker(base + "pyrun-worker.js?v=2", { type: "module" });
      worker.onmessage = function (e) { var p = pend[e.data.id]; if (!p) return; if (e.data.type === "log") p.log(e.data.text); else { delete pend[e.data.id]; p.done(e.data.ok); } };
      worker.onerror = function (e) { Object.keys(pend).forEach(function (k) { pend[k].log("Runner error: " + (e.message || "failed to load")); pend[k].done(false); delete pend[k]; }); worker = null; };
      return worker;
    }
    function runInBrowser(files, run, env, route, onLog) {
      return new Promise(function (resolve) { var id = ++seq; pend[id] = { log: onLog, done: resolve }; getWorker().postMessage({ id: id, files: files, run: run, env: env, route: route }); });
    }
    function wireEndpoint() { return location.origin + location.pathname.split("/labs/")[0] + "/_wire"; }
    function meshRoute() { try { return window.parent !== window && window.parent.VyomiMesh && window.parent.VyomiMesh.wireRouting ? window.parent.VyomiMesh.wireRouting() : null; } catch (_) { return null; } }
    /* Deploy must never hand the user a to-do list: when a chapter needs the Mesh (real functions, a model, or a cloud SDK the browser cannot run), start it and join it from here. */
    function ensureMesh(say) {
      var M = null; try { M = window.parent !== window ? window.parent.VyomiMesh : null; } catch (_) {}
      if (meshRoute()) return Promise.resolve();
      if (!M || !M.sessionStart) return Promise.reject(new Error("The Mesh is not available in this console. Sign in, then deploy again."));
      var live = M.session && M.session() && M.session().session;
      var started = live ? Promise.resolve({ ok: true }) : (say("Starting your Mesh. This takes a few minutes the first time..."), M.sessionStart(cloud));
      return started.then(function (r) {
        if (r && r.cancelled) throw new Error("Starting the Mesh was cancelled.");
        if (r && r.ok === false) throw new Error((r.j && r.j.message) || "The Mesh could not be started.");
        var t0 = Date.now(), asked = 0;
        return new Promise(function (ok, bad) {
          (function poll() {
            if (meshRoute()) return ok();
            if (Date.now() - t0 > 15 * 60 * 1000) return bad(new Error("The Mesh did not become ready in 15 minutes."));
            var s = M.session && M.session(), ss = s && s.session, c = M.checks && M.checks();
            if (!ss) say("Starting your Mesh...");
            else if (ss.state !== "running") say("Your Mesh is booting (" + Math.round((Date.now() - t0) / 1000) + " s)...");
            else if (!c || c.sid !== ss.id || c.state === "idle") { say("Running the Mesh health checks..."); if (!asked++ || asked % 8 === 0) M.runChecks(); }
            else if (c.state === "running") say("Running the Mesh health checks...");
            else if (c.state === "failed") return bad(new Error("A Mesh health check failed: " + (c.items.filter(function (i) { return i.ok === false; }).map(function (i) { return i.label; }).join(", ") || "see the Mesh card") + "."));
            else if (c.state === "passed") { say("Joining the Mesh..."); if (c.joined || M.joinMesh()) return setTimeout(poll, 500); }
            setTimeout(poll, 4000);
          })();
        });
      });
    }
    function deployPanel(l) {
      var route = meshRoute(), target = route ? "inside your Mesh (" + route.name + ")" : hasApi ? "in the Vyomi runner" : "inside a Mesh (started for you if it is not running)";
      var supported = true;
      var rows = l.lab.map(function (bk) { return { bk: bk, chip: el("span", { className: "vl-dchip", textContent: bk.run ? "waiting" : "saved on run" }), log: el("pre", { className: "vl-dlog" }) }; });
      var btn = el("button", { type: "button", className: "vl-btn primary sm vl-deploybtn" }, icon("M8 5v14l11-7z", 14), "Deploy this chapter");
      var out = el("div", { className: "vl-dout" });
      var allFiles = function () {   // every earlier chapter's files exist too (this chapter may import them); nothing is run for those
        var f = {}; for (var i = 0; i < course.layers.length; i++) { var c = course.layers[i]; (c.lab || []).forEach(function (b) { f[b.file] = b.code; }); if (c.id === l.id) break; } return f; };
      function finish(failed, blocked, needModel, endpointNote) {
        btn.disabled = false; btn.textContent = "Deploy again";
        var links = (l.setup || []).filter(function (s) { return s.route; });
        if (!failed && !blocked) { store[l.id] = store[l.id] === "verified" ? "verified" : "deployed"; save(); var st = root.querySelector(".vl-chero .vl-status"); if (st) { st.textContent = store[l.id] === "verified" ? "Verified" : "Deployed"; st.classList.add("done"); } }
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
      /* On Nano (no Mesh, no local runner) the browser runs what it can. Only non-AWS clouds (no browser SDK runner) still need a Mesh up front. */
      var needsMesh = function () { return courseId === "facilities" && !meshRoute() && !hasApi; };   /* the Nano course runs in the browser; only the Mesh course needs a Mesh */
      var meshWanted = false;
      var kernel = function () { try { if (window.parent !== window && window.parent.vyomiEnableWebLLM) return window.parent; } catch (_) {} return window.vyomiEnableWebLLM ? window : null; };
      /* Why a failed step cannot run in the browser: {kind:"model"} (load a model) or {kind:"mesh", why} (genuinely Mesh-only). */
      function classify(text) {
        if (/ModelNotReady|No in-browser model/.test(text)) return { kind: "model" };
        var m;
        if (/NotImplementedException|identity services need|not implemented on Nano/i.test(text)) return { kind: "mesh", why: "This service has no in-browser engine yet." };
        if ((m = /No module named '(langgraph|langchain[\w.]*|torch|numpy|pandas|scipy)'/.exec(text))) return { kind: "mesh", why: "The hosted agent needs the Python package '" + m[1] + "', which could not be loaded in the browser (it needs network access to PyPI, or has no browser build)." };
        if (/langgraph could not be installed/.test(text)) return { kind: "mesh", why: "langgraph could not be downloaded in this browser (offline?). Reconnect and deploy again, or run this step in a Mesh." };
        return null;
      }
      function modelPicker(note) {   // resolves true once a model is loaded, false if the learner skips
        return new Promise(function (resolve) {
          var host = kernel(), box = el("div", { className: "vl-dres warn vl-modelpick" }), list = el("div", { className: "vl-mlist" }), msg = el("p", { className: "vl-muted" });
          var rec = "qwen2.5-1.5b";
          var finishPick = function (ok) { box.remove(); resolve(ok); };
          box.append(el("b", { textContent: "This step needs a language model" }), el("p", { textContent: (note || "") + "Pick one to load into this browser. It runs on your own GPU; nothing is sent anywhere. The download happens once and is cached by the browser." }), msg, list);
          out.append(box); box.scrollIntoView && box.scrollIntoView({ block: "nearest" });
          var skip = el("button", { type: "button", className: "vl-btn sm", textContent: "Skip, continue without a model" }); skip.onclick = function () { finishPick(false); };
          if (!host) { msg.textContent = "Open Vyomi Labs from inside a Nano console (Launch a space, then Labs) so a model can be loaded; this page has no model runtime."; list.append(skip); return; }
          var gpu = navigator.gpu ? navigator.gpu.requestAdapter().then(function (a) { return !!a; }, function () { return false; }) : Promise.resolve(false);
          gpu.then(function (hasGpu) {
            if (!hasGpu) { msg.textContent = "No WebGPU in this browser, so no in-browser model can run. Use a recent desktop Chrome or Edge (WebGPU on, graphics acceleration enabled). Steps that call a model stay marked 'needs a model'; every other step still runs."; list.append(skip); return; }
            msg.textContent = "Qwen2.5 1.5B is the one that follows the course (routing, tool calls, citations). The smaller ones only prove the plumbing: they load fast, but their answers are poor. Needs about 2 GB of free disk and a GPU with enough memory.";
            (host.vyomiWebLLMModels || []).forEach(function (m) {
              var small = m.id !== rec, b = el("button", { type: "button", className: "vl-btn sm" + (small ? "" : " primary"), title: small ? "Plumbing only" : "Recommended" });
              b.append(el("b", { textContent: m.name }), " " + m.size, el("small", { textContent: small ? "  plumbing only" : "  recommended" }));
              b.onclick = function () {
                list.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
                msg.textContent = "Downloading " + m.name + " (" + m.size + "). Keep this tab open...";
                host.vyomiEnableWebLLM(m.id, function (p) { if (p && p.text) msg.textContent = m.name + ": " + p.text; }).then(function () { finishPick(true); }, function (e) {
                  var t = String(e && e.message || e), low = /Cache|quota|storage/i.test(t);
                  msg.textContent = "Could not load " + m.name + ": " + t.slice(0, 220) + (low ? " The browser could not write the model cache; free some disk space (about 2 GB) and try again." : "");
                  list.querySelectorAll("button").forEach(function (x) { x.disabled = false; });
                });
              };
              list.append(b);
            });
            list.append(skip);
          });
        });
      }
      function modelLoaded() { try { var h = kernel(); return !!(h && h.vyomiLlmStatus && h.vyomiLlmStatus().available); } catch (_) { return false; } }
      btn.onclick = function () {
        if (needsMesh()) { btn.disabled = true; var say = function (t) { out.replaceChildren(el("div", { className: "vl-dstatus", textContent: t })); }; return ensureMesh(say).then(function () { btn.disabled = false; btn.onclick(); }, function (e) { btn.disabled = false; out.replaceChildren(el("div", { className: "vl-dres bad" }, el("b", { textContent: e.message }))); }); }
        var route = courseId === "facilities" ? meshRoute() : null;   // the Nano course never goes through a Mesh
        if (route && window.parent.VyomiMesh.apiFetch) return deployVia(function () { return window.parent.VyomiMesh.apiFetch("/mesh/labs/deploy/" + cloud + "/" + l.id, { method: "POST" }); });   // a Mesh is on: deploy INSIDE the Mesh
        if (hasApi && courseId === "facilities") return deployVia(function () { return fetch("/api/deploy/" + cloud + "/" + l.id, { method: "POST" }); });
        btn.disabled = true; btn.textContent = "Deploying..."; out.replaceChildren(); var failed = 0, meshOnly = 0, noModel = 0, passed = 0, reasons = [];
        rows.forEach(function (r) { r.chip.textContent = r.bk.run ? "waiting" : "saved on run"; r.chip.className = "vl-dchip"; r.log.textContent = ""; });
        var files = allFiles(), env = { AWS_ENDPOINT_URL: wireEndpoint(), AWS_DEFAULT_REGION: "us-east-1", AWS_ACCESS_KEY_ID: "test", AWS_SECRET_ACCESS_KEY: "test" };
        var chain = Promise.resolve();
        function runBlock(r, retried) {
          r.chip.textContent = "running"; r.chip.className = "vl-dchip run"; var text = "";
          return runInBrowser(files, r.bk.run, env, route, function (t) { text += t + "\n"; r.log.textContent = text; }).then(function (ok) {
            var pass = ok && (!r.bk.expect || text.indexOf(r.bk.expect) >= 0);
            if (pass) { passed++; r.chip.textContent = "passed"; r.chip.className = "vl-dchip ok"; return; }
            if (!ok || r.bk.expect) r.log.textContent = text + (ok ? "\nExpected to see: " + r.bk.expect : "");
            var why = classify(text);
            if (why && why.kind === "model") {
              if (!retried && !modelLoaded()) { r.chip.textContent = "needs a model"; r.chip.className = "vl-dchip warn"; return modelPicker("").then(function (loaded) { return loaded ? runBlock(r, true) : (noModel++, void 0); }); }
              noModel++; r.chip.textContent = "needs a model"; r.chip.className = "vl-dchip warn"; return;
            }
            if (why && why.kind === "mesh") { meshOnly++; reasons.push(r.bk.title + ": " + why.why); r.chip.textContent = "needs the Mesh"; r.chip.className = "vl-dchip warn"; r.log.textContent = text + "\nMesh only: " + why.why; return; }
            failed++; r.chip.textContent = "failed"; r.chip.className = "vl-dchip bad";
          });
        }
        /* Chapters this one builds on (l.requires, generated from the course) are deployed first when they are not deployed yet: their resources
           (tool functions, the hosted agent, the knowledge base ...) are what this chapter's steps look up. Their steps run silently; a failure stops here and names the chapter. */
        var prereqFailed = null, byId = {}; course.layers.forEach(function (c) { byId[c.id] = c; });
        var status = el("div", { className: "vl-dstatus" }); out.append(status);
        function runPrereq(c) {
          status.textContent = "Deploying '" + c.title + "' first (this chapter builds on it)...";
          var p = Promise.resolve(), ok = true;
          (c.lab || []).forEach(function (bk) {
            p = p.then(function () {
              if (!ok) return;
              if (!bk.run) return runInBrowser(files, "", env, route, function () {});
              var text = "";
              function attempt(retried) {
                text = "";
                return runInBrowser(files, bk.run, env, route, function (t) { text += t + "\n"; }).then(function (good) {
                  if (good && (!bk.expect || text.indexOf(bk.expect) >= 0)) return;
                  var why = classify(text);
                  if (why && why.kind === "model" && !retried && !modelLoaded()) return modelPicker("'" + c.title + "' needs a model. ").then(function (loaded) { if (loaded) return attempt(true); noModel++; });
                  if (why && why.kind === "model") { noModel++; return; }
                  if (why && why.kind === "mesh") { meshOnly++; reasons.push(c.title + ": " + bk.title + ": " + why.why); return; }   // the same as on the chapter's own page: reported, the rest still runs
                  ok = false; prereqFailed = { c: c, bk: bk, text: text + (good ? "\nExpected to see: " + bk.expect : "") };
                });
              }
              return attempt(false);
            });
          });
          return p.then(function () { if (ok) { store[c.id] = store[c.id] === "verified" ? "verified" : "deployed"; save(); } });
        }
        (l.requires || []).filter(function (id) { return byId[id] && store[id] !== "deployed" && store[id] !== "verified"; }).forEach(function (id) {
          chain = chain.then(function () { return prereqFailed ? null : runPrereq(byId[id]); });
        });
        chain = chain.then(function () { status.textContent = ""; });
        rows.forEach(function (r) {
          chain = chain.then(function () {
            if (prereqFailed) return;
            if (!r.bk.run) { r.chip.textContent = "saved"; r.chip.className = "vl-dchip ok"; return runInBrowser(files, "", env, route, function () {}); }
            return runBlock(r, false);
          });
        });
        chain.then(function () {
          btn.disabled = false; btn.textContent = "Deploy again";
          if (prereqFailed) {
            rows.forEach(function (r) { r.chip.textContent = "not run"; r.chip.className = "vl-dchip warn"; });
            out.replaceChildren(el("div", { className: "vl-dres bad" },
              el("b", { textContent: "This chapter builds on '" + prereqFailed.c.title + "', which failed to deploy, so it was not run." }),
              el("p", { className: "vl-muted", textContent: "Step '" + prereqFailed.bk.title + "' (" + prereqFailed.bk.run + ") failed:" }),
              el("pre", { className: "vl-dlog", textContent: prereqFailed.text.slice(-1500) }),
              el("p", { className: "vl-muted", textContent: "Open that chapter, fix the failing step and deploy it, then deploy this one again." })));
            return;
          }
          var links = (l.setup || []).filter(function (s) { return s.route; }), M = null; try { M = window.parent !== window ? window.parent.VyomiMesh : null; } catch (_) {}
          var allGood = !failed && !meshOnly && !noModel;
          if (allGood) { store[l.id] = store[l.id] === "verified" ? "verified" : "deployed"; save(); var st = root.querySelector(".vl-chero .vl-status"); if (st) { st.textContent = store[l.id] === "verified" ? "Verified" : "Deployed"; st.classList.add("done"); } }
          var parts = [passed + " step(s) ran in your browser"]; if (noModel) parts.push(noModel + " need a model"); if (meshOnly) parts.push(meshOnly + " need a Mesh"); if (failed) parts.push(failed + " failed");
          out.replaceChildren(el("div", { className: "vl-dres " + (failed ? "bad" : (meshOnly || noModel) ? "warn" : "ok") },
            el("b", { textContent: allGood ? "Deployed." : parts.join(", ") + "." }),
            meshOnly ? ul(reasons) : null,
            noModel ? el("p", { className: "vl-muted", textContent: "Deploy again and pick a model when asked to run the steps that call one." }) : null,
            failed ? el("p", { className: "vl-muted", textContent: "Open the step log below, fix the cause and deploy again." }) : null,
            (meshOnly && M && M.sessionStart) ? el("button", { type: "button", className: "vl-btn sm", textContent: "Run this chapter in a Mesh", onclick: function () { meshWanted = true; btn.onclick(); } }) : null,
            (!failed && links.length) ? el("div", { className: "vl-dlinks" }, el("span", { textContent: "See it running in the space: " }), links.map(function (s) { return el("a", { className: "vl-btn", href: consoleUrl(s.route), target: "_blank", rel: "noopener", textContent: s.service || s.title }); })) : null));
        });
      };
      var panel = el("div", { className: "vl-deploy vl-deploystrip", hidden: true },
        el("div", { className: "vl-dhead" }, el("div", {}, el("h3", { textContent: "Deployment" }), el("p", { className: "vl-muted", textContent: supported ? "Runs every block below in order, exactly as written, " + target + ", then shows you the resources in the console." : "Deploying " + course.cloud_name + " chapters needs the Vyomi Labs runner (the offline appliance or a Mesh); it is not available in this browser session." }))),
        supported ? null : el("p", { className: "vl-native", textContent: "The in-browser runner supports the AWS SDK only. " + course.cloud_name + " chapters deploy through the runner on the appliance or a Mesh." }),
        el("ol", { className: "vl-drows" }, rows.map(function (r, i) { return el("li", {}, el("div", { className: "vl-drow" }, el("span", { className: "vl-dn", textContent: i + 1 }), el("span", { className: "vl-dt", textContent: r.bk.title }), el("code", { textContent: r.bk.run || r.bk.file }), r.chip), r.log); })), out);
      var runIt = btn.onclick; btn.onclick = function () { panel.hidden = false; return runIt.apply(this, arguments); };
      panel.deployBtn = btn; return panel;
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
        el("div", { className: "vl-file" }, el("span", { className: "vl-fname" }, icon("M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5", 14), projFile(bk.file)), el("button", { type: "button", className: "vl-ghlink", textContent: "Open in editor", onclick: function () { openEditor(projFile(bk.file)); } }), copyBtn(bk.code)), pre,
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
      var facts = function (rows) { return el("table", { className: "vl-facts" }, el("tbody", {}, rows.map(function (r) { return el("tr", {}, el("th", { textContent: r[0] }), el("td", {}, r[1])); }))); };
      var svcList = el("span", { className: "vl-svclist" }, l.services.map(function (x) { return el("span", {}, x); }));
      var next = nxt ? el("div", { className: "vl-nextcard" }, el("small", { textContent: "Next" }), el("button", { type: "button", className: "vl-btn primary", onclick: function () { go(nxt.id); } }, "Chapter " + nxt.order + ": " + nxt.title, icon(P.arrow, 16))) : el("p", { className: "vl-muted", textContent: "That was the last chapter. You now have the full enterprise agent." });
      var cleanup = el("div", {}, el("p", { textContent: "Vyomi is a simulator, so nothing here is billed and nothing needs deleting to avoid charges. To start this chapter again, delete the resources you created from their console pages, or reset the space from Spaces in the bottom drawer." }),
        el("p", { className: "vl-muted", textContent: "Keep the resources if you are continuing: later chapters build on them." }));
      var buildBody = el("div", {}, hasLab ? el("div", {},
          el("p", { className: "vl-muted", textContent: "Complete these in order. Save each file with the name shown, run the command under it and check the output matches. Point your SDK at the simulator first (open SDK & CLI usage in the bottom drawer for the exact settings)." }),
          (function () { var ol = el("ol", { className: "vl-blocks" }, l.lab.map(labBlock)), allOpen = false; var tg2 = el("button", { type: "button", className: "vl-btn sm", textContent: "Expand all" }); tg2.onclick = function () { allOpen = !allOpen; [].forEach.call(ol.children, function (x) { x.classList.toggle("open", allOpen); }); tg2.textContent = allOpen ? "Collapse all" : "Expand all"; }; return el("div", {}, el("div", { className: "vl-blocktools" }, tg2), ol, chapterCode(l)); })()) :
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
      var closing = el("div", { className: "vl-finish" }, el("div", { className: "vl-actions" }, mark, statusEl));
      /* ---- the chapter workspace: a hero, then ONE section at a time (compact), in each cloud's own tutorial structure ---- */
      var chk = function (arr) { return el("ul", { className: "vl-checks" }, arr.map(function (t) { return el("li", {}, icon(P.check, 15), t); })); };
      var card = function (title, body, cls) { return el("section", { className: "vl-card " + (cls || "") }, el("h3", { textContent: title }), body); };
      var X = l.explain || { lead: [l.about], concepts: [], flow: [], example: "", pitfalls: [] };
      var needs = (l.contract && l.contract.needs || []).map(byId).filter(Boolean), usedBy = course.layers.filter(function (o) { return (o.contract && o.contract.needs || []).indexOf(l.id) >= 0; });
      var chapLink = function (o) { var a = el("button", { type: "button", className: "vl-chaplink", textContent: "Chapter " + o.order + ": " + o.title }); a.onclick = function () { go(o.id); }; return a; };
      var sec = function (title, body, cls) { return el("section", { className: "vl-isec " + (cls || "") }, el("h3", { textContent: title }), body); };
      var L = { aws: ["Overview", "Task 1: Build the code", "Task 2: Create the resources", "Task 3: Connect to other layers", "Task 4: Validate your work", "Task 5: Clean up resources"],
        gcp: ["Before you begin", "Build the code", "Create the resources", "Connect the layers", "Validate", "Clean up"],
        azure: ["Prerequisites", "Build the code", "Create the resources", "Connect to other layers", "Validate", "Clean up and next steps"] }[cloud];
      var N2 = l.narr;
      var quizState = []; 
      function quizCard(q, qi) {
        var box = el("div", { className: "vl-q" }, el("p", { className: "vl-qt" }, el("span", { className: "vl-qn", textContent: "Q" + (qi + 1) }), q[0])), fb = el("div", { className: "vl-qfb", hidden: true }), answered = false;
        q[1].forEach(function (opt, oi) {
          var bt = el("button", { type: "button", className: "vl-qo", textContent: opt });
          bt.onclick = function () {
            if (answered) return; answered = true; var ok = oi === q[2]; quizState[qi] = ok;
            box.querySelectorAll(".vl-qo").forEach(function (x, k) { x.disabled = true; if (k === q[2]) x.classList.add("right"); else if (k === oi) x.classList.add("wrong"); });
            fb.hidden = false; fb.className = "vl-qfb " + (ok ? "ok" : "no"); fb.replaceChildren(el("b", { textContent: ok ? "Correct. " : "Not quite. " }), q[3]);
            var done = quizState.filter(function (x) { return x !== undefined; }).length; score.textContent = quizState.filter(Boolean).length + " of " + N2.quiz.length + " correct" + (done < N2.quiz.length ? " so far" : "");
          };
          box.append(bt);
        });
        box.append(fb); return box;
      }
      var score = el("span", { className: "vl-score", textContent: "Pick an answer" });
      var anchor = function (id, title, body, cls) { var s = el("section", { className: "vl-lsec " + (cls || ""), id: "vl-s-" + id }, el("h3", { textContent: title }), body); return s; };
      var HANDS = [["build", L[1]], ["create", L[2]], ["connect", L[3]], ["validate", L[4]], ["clean", L[5]]];
      var toc = [["story", "The problem"], ["why", "Why an enterprise goes further"], ["design", "The layer design"]].concat(HANDS, [["recap", "Recap"]]);
      var introBody = el("div", { className: "vl-lesson", style: "--c:" + l.color },
        el("div", { className: "vl-lmain" },
          anchor("story", "The problem", el("blockquote", { className: "vl-scene" }, el("p", { textContent: N2.scene })), "vl-first"),
          anchor("why", "Why an enterprise goes further", el("p", { textContent: N2.why })),
          anchor("design", "The layer design", el("div", {}, el("p", { textContent: N2.design }),
            el("div", { className: "vl-analogy" }, el("small", { textContent: "Think of it as" }), el("b", { textContent: N2.idea[0] }), el("p", { textContent: N2.idea[1] })),
            el("h4", { className: "vl-sub", textContent: "How it works" }),
            el("ol", { className: "vl-tl" }, N2.walk.map(function (w, i) { return el("li", {}, el("span", { className: "vl-tn", textContent: i + 1 }), el("div", {}, el("b", { textContent: w[0] }), el("p", { textContent: w[1] }))); })))),
          anchor("recap", "Recap", el("div", {}, el("ul", { className: "vl-recap" }, N2.recap.map(function (t) { return el("li", {}, icon(P.check, 16), t); })),
            usedBy.length ? el("p", { className: "vl-nextup" }, el("b", { textContent: "Next, in the story: " }), "this feeds ", chapLink(usedBy[0]), ".") : null,
            el("details", { className: "vl-terms" }, el("summary", { textContent: "Key terms" }), el("dl", {}, X.concepts.map(function (c) { return el("div", {}, el("dt", { textContent: c[0] }), el("dd", { textContent: c[1] })); })))))),
        el("aside", { className: "vl-lside" },
          el("nav", { className: "vl-toc", "aria-label": "On this page" }, el("h4", { textContent: "On this page" }), toc.map(function (t) { var a2 = el("a", { href: "#vl-s-" + t[0], textContent: t[1] }); a2.onclick = function (e) { e.preventDefault(); var x = introBody.querySelector("#vl-s-" + t[0]); x && x.scrollIntoView({ behavior: "smooth", block: "start" }); }; return a2; }))));
      var PANES = [
        { t: L[0], dur: 2, body: introBody },
        { t: L[1], dur: tm.build, body: buildBody, badge: hasLab ? String(l.lab.length) : "" },
        { t: L[2], dur: tm.cons, body: consBody, badge: (l.setup || []).length ? String(l.setup.length) : "" },
        { t: L[3], dur: 5, body: fitsBody },
        { t: L[4], dur: tm.val, body: valBody },
        { t: L[5], dur: tm.clean, body: el("div", {}, cleanup, closing, l.order === course.layers.length ? projectCard() : null) }];
      var bodies = [buildBody, consBody, fitsBody, valBody, el("div", {}, cleanup, closing, l.order === course.layers.length ? projectCard() : null)];
      var lmain = introBody.querySelector(".vl-lmain"), checkSec = introBody.querySelector("#vl-s-recap");
      introBody.querySelector("#vl-s-design").appendChild(el("div", { className: "vl-factrow" }, sec("By the end you will", chk(l.learn)), sec("Before you start", ul(l.prereq)),
        (needs.length || usedBy.length) ? sec("Connected chapters", el("div", { className: "vl-conn" },
          needs.length ? el("div", { className: "vl-connrow" }, el("span", { className: "vl-connlbl", textContent: "Builds on" }), el("div", { className: "vl-chaps" }, needs.map(chapLink))) : null,
          usedBy.length ? el("div", { className: "vl-connrow" }, el("span", { className: "vl-connlbl", textContent: "Used by" }), el("div", { className: "vl-chaps" }, usedBy.map(chapLink))) : null), "vl-span2") : null));
      HANDS.forEach(function (h, k) { lmain.insertBefore(anchor(h[0], h[1], bodies[k], "vl-handson"), checkSec); });
      var pager = el("div", { className: "vl-pager2" }, prev ? el("button", { type: "button", className: "vl-btn", onclick: function () { go(prev.id); } }, icon(P.back, 16), "Previous chapter: " + prev.title) : el("span"),
        nxt ? el("button", { type: "button", className: "vl-btn primary", onclick: function () { go(nxt.id); } }, "Next chapter: " + nxt.title, icon(P.arrow, 16)) : el("span", { className: "vl-muted", textContent: "That was the last chapter." }));
      lmain.append(pager);
      var dep = hasLab ? deployPanel(l) : null;
      var chipo = function (ic, t) { return el("span", { className: "vl-hchip" }, icon(ic, 14), t); };
      var hero = el("header", { className: "vl-chero", style: "--c:" + l.color },
        el("div", { className: "vl-cicon" }, icon(l.icon, 30)),
        el("div", { className: "vl-ctext" },
          el("div", { className: "vl-crumbs2", textContent: course.cloud_name + "  /  Vyomi Labs  /  Chapter " + l.order + " of " + course.layers.length }),
          el("h1", { textContent: l.title }), el("p", { textContent: l.outcome }),
          el("div", { className: "vl-cchips" }, chipo(P.flag, l.level), chipo(P.clock, "~" + N + " min"), hasLab ? chipo("M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12", l.lab.length + " code steps") : null, l.services.slice(0, 3).map(function (x) { return el("span", { className: "vl-hchip svc", textContent: x }); }))),
        el("div", { className: "vl-cside" }, dep ? dep.deployBtn : null, el("span", { className: "vl-status" + (done(l.id) ? " done" : ""), textContent: done(l.id) ? (done(l.id) === "verified" ? "Verified" : done(l.id) === "deployed" ? "Deployed" : "Complete") : "Not started" })));
      var article = el("article", { className: "vl-article vl-ws " + cloud }, hero, dep, el("div", { className: "vl-wsbody single" }, introBody));
      tocSpy(article);
      var main = article;

      var cols = el("div", { className: "vl-cols" + (collapsed ? " oc" : "") }, side, main);
      return el("div", { className: "vl-reader" }, top, cols);
    }

    var q = parseInt(opts.layer, 10);
    return load(cloud).then(function () { if (q && byId(q)) { inCourse = true; go(q); } }).catch(function (e) { root.textContent = "Could not load Vyomi Labs: " + e.message; });
  }
  window.VyomiLabs = { mount: mount };
})();
