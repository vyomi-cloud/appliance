/* Vyomi issue reporter — ONE shared script for the offline/sandbox consoles
 * (static/) and Nano (wasm/, byte-identical copy). Also loaded by the Nano
 * service worker via importScripts (no DOM there: only scrub/shouldReport/send).
 *
 *  - captures console JS errors, unhandled rejections and failed console actions
 *  - scrubs on the client (same rules as core/issue_report.py) before anything is sent
 *  - shows the one-time consent dialog and the Settings -> Issue reporting panel
 *
 * Offline/sandbox: POST /api/issue-reporting/report (the appliance scrubs again,
 * dedupes and forwards to the portal). Nano: POST /api/issues/report (portal, via
 * the service worker with the portal session).
 */
(function (root) {
  "use strict";
  var NANO = typeof root.__NANO_BASE === "string" || (typeof self !== "undefined" && typeof self.registration !== "undefined");
  var MAX_MSG = 300;

  function hashName(s) { // short non-reversible token, stable per name (FNV-1a x2)
    var h1 = 0x811c9dc5, h2 = 0x01000193, i, c;
    for (i = 0; i < s.length; i++) { c = s.charCodeAt(i); h1 = Math.imul(h1 ^ c, 16777619) >>> 0; h2 = Math.imul(h2 + c, 2246822519) >>> 0; }
    return "<res:" + ("00000000" + ((h1 ^ h2) >>> 0).toString(16)).slice(-8) + ">";
  }
  var RX = [
    [/-----BEGIN [A-Z ]+-----[\s\S]*?(?:-----END [A-Z ]+-----|$)/g, "<key>"],
    [/\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*/g, "<token>"],
    [/\b([a-z][a-z0-9+.\-]*:\/\/)[^\/\s:@]+:[^\/\s@]+@/gi, "$1<cred>@"],
    [/(\bhttps?:\/\/[^\s?#'"<>]+)\?[^\s#'"<>]*/g, "$1?<q>"],
    [/\b([a-z0-9_.\-]*(?:secret|token|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential|authorization|signature|sig|sas)[a-z0-9_.\-]*)\s*([=:])\s*(?:bearer\s+|basic\s+)?("[^"]*"|'[^']*'|[^\s,;&"')]+)/gi, "$1$2<redacted>"],
    [/\b(bearer|basic)\s+[A-Za-z0-9._~+\/=\-]{8,}/gi, "$1 <token>"],
    [/\b(?:AKIA|ASIA|AIDA|AROA|AGPA|ANPA)[A-Z0-9]{12,}\b/g, "<key>"],
    [/\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/g, "<token>"],
    [/\b(?:AIza[0-9A-Za-z_\-]{30,}|ya29\.[0-9A-Za-z_\-]{20,})/g, "<token>"]
  ];
  function scrub(input, limit) {
    if (input === null || input === undefined) return "";
    var t = String(input), i;
    for (i = 0; i < RX.length; i++) t = t.replace(RX[i][0], RX[i][1]);
    t = t.replace(/[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+/g, "<email>");
    t = t.replace(/\barn:(aws[a-z\-]*):([a-z0-9\-]*):([a-z0-9\-]*):(\d{12})?:([^\s,;"')]+)/g, function (m, p, s, r, a, rest) {
      var b = rest.split(/([\/:])/); var tail = b.length >= 3 ? b[0] + b[1] + hashName(b.slice(2).join("")) : hashName(rest);
      return "arn:" + p + ":" + s + ":" + r + ":<acct>:" + tail;
    });
    t = t.replace(/\/subscriptions\/[^\/\s]+/gi, "/subscriptions/<sub>");
    t = t.replace(/\/resourceGroups\/[^\/\s]+/gi, function (m) { return "/resourceGroups/" + hashName(m.split("/").pop()); });
    t = t.replace(/(\/providers\/[A-Za-z0-9.]+)((?:\/[A-Za-z0-9]+\/[^\/\s"',;)?]+)+)/gi, function (m, prov, rest) {
      var segs = rest.replace(/^\/|\/$/g, "").split("/"), out = [], j;
      for (j = 0; j + 1 < segs.length; j += 2) out.push(segs[j], hashName(segs[j + 1]));
      return prov + "/" + out.join("/");
    });
    t = t.replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "<id>");
    t = t.replace(/\b(projects|folders|organizations)\/(?!<)([^\/\s"',;)]+)/gi, function (m, k) { return k + "/<" + (k === "projects" ? "project" : k.slice(0, -1)) + ">"; });
    t = t.replace(/\b(buckets|instances|topics|subscriptions|secrets|keyRings|cryptoKeys|clusters|services|functions|jobs|datasets|tables|databases|queues|serviceAccounts|networks|disks|repositories)\/(?!<)([A-Za-z0-9_.@:\-]+)/gi, function (m, k, n) { return k + "/" + hashName(n); });
    t = t.replace(/\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b/g, "<ip>");
    t = t.replace(/(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}(?![\w:])/gi, "<ip>");
    t = t.replace(/(?<![\w.\-])\d{12}(?![\w\-])/g, "<acct>");
    t = t.replace(/\b(?=[A-Za-z0-9_\-+\/=]*\d)(?=[A-Za-z0-9_\-+\/=]*[A-Za-z])[A-Za-z0-9_\-+\/=]{32,}\b/g, "<token>");
    t = t.replace(/\b[0-9a-fA-F]{24,}\b/g, "<id>");
    t = t.replace(/(?<![\w<])\/(?:home|Users|root|tmp|var|opt|app|data|usr|workspace)[^\s:"')]*|(?<![\w])[A-Za-z]:\\[^\s:"')]+/g, "<path>");
    var keep = { name: 1, id: 1, arn: 1, region: 1, type: 1, status: 1, key: 1, value: 1, tags: 1, none: 1, "null": 1, "true": 1, "false": 1, str: 1, int: 1, list: 1, dict: 1, bytes: 1, code: 1, message: 1, detail: 1 };
    t = t.replace(/(['"`])([^'"`\n]{1,120})\1/g, function (m, q, v) {
      return (v.charAt(0) === "<" || /<res:[0-9a-f]{8}>/.test(v) || keep[v.toLowerCase()]) ? m : q + hashName(v) + q;
    });
    return t.replace(/\s+/g, " ").trim().slice(0, limit || MAX_MSG);
  }
  function frame(f) { // "file:function" only
    var p = String(f).split(":"); var file = (p[0] || "?").split(/[\\\/]/).pop().replace(/[^A-Za-z0-9_.\-]/g, "") || "?";
    var fn = (p[1] || "?").replace(/[^A-Za-z0-9_<>.$\-]/g, "") || "?"; return file + ":" + fn;
  }
  function framesFromStack(stack) {
    var out = [], re = /at\s+(?:async\s+)?([^\s(]+)?\s*\(?(?:[a-z]+:\/\/)?[^\s)]*?([^\/\s:)]+?\.(?:js|mjs|html|py)):\d+/g, m;
    var py = /File "[^"]*?([^\/\\"]+\.py)", line \d+, in ([^\s]+)/g;
    while ((m = py.exec(String(stack || "")))) out.push(frame(m[1] + ":" + m[2]));       // Python (Pyodide) traceback
    while ((m = re.exec(String(stack || "")))) out.push(frame((m[2] || "?") + ":" + (m[1] || "?")));
    return out.slice(-5);
  }
  function shouldReport(ev) {
    if (!ev || ev.cancelled) return false;
    var code = String(ev.code || "");
    if (/^tier[_\-]|tier.?(locked|limit|required|denied)|upgrade.?required/i.test(code)) return false;
    if (/tier/i.test(String(ev.message || "").slice(0, 80)) && (ev.status === 402 || ev.status === 403)) return false;
    if (ev.kind === "js-error" || ev.kind === "exception") return true;
    if (ev.kind === "console-action") return !(ev.status >= 400 && ev.status < 500);
    return (ev.status || 0) >= 500;
  }

  function cloudOf() {
    var m = (root.location && root.location.pathname || "").match(/(aws|gcp|azure)/i);
    return m ? m[1].toLowerCase() : "unknown";
  }
  var seen = {};
  function endpoint() { return NANO ? "/api/issues/report" : "/api/issue-reporting/report"; }
  function settingsUrl() { return NANO ? "/api/issues/settings" : "/api/issue-reporting"; }
  function send(ev) { // ev: {kind, service, action, status, code, message, stack}
    try {
      if (!shouldReport(ev)) return Promise.resolve(false);
      var body = {
        kind: ev.kind || "js-error", cloud: ev.cloud || cloudOf(), service: ev.service || "console",
        action: scrub(ev.action || ev.kind || "console", 80), status: ev.status || null,
        code: String(ev.code || "").replace(/[^A-Za-z0-9_.\-:]/g, "").slice(0, 80),
        message: scrub(ev.message), frames: framesFromStack(ev.stack), surface: NANO ? "nano" : "offline"
      };
      var key = [body.cloud, body.service, body.action, body.status, body.code, body.message.replace(/<res:[0-9a-f]{8}>/g, "<res>").replace(/\d+/g, "<n>")].join("|");
      if (seen[key]) return Promise.resolve(false); seen[key] = 1; // one per fingerprint per page; the server adds the +1s
      return fetch(endpoint(), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(NANO ? { fingerprint: "", mode: null, report: body, client: true } : body) })
        .then(function () { return true; }, function () { return false; });
    } catch (e) { return Promise.resolve(false); }
  }

  var api = { scrub: scrub, shouldReport: shouldReport, send: send, framesFromStack: framesFromStack };
  root.VyomiIssueReporter = api;
  if (typeof document === "undefined") return; // service worker: scrub/send only

  // ── capture ─────────────────────────────────────────────────────────
  root.addEventListener("error", function (e) {
    if (e.target && e.target !== root) return; // resource load errors are not JS errors
    send({ kind: "js-error", action: "window.onerror", message: e.message, stack: e.error && e.error.stack });
  });
  root.addEventListener("unhandledrejection", function (e) {
    var r = e.reason || {};
    if (r && r.name === "AbortError") return; // cancelled
    send({ kind: "js-error", action: "unhandledrejection", message: r.message || String(r), stack: r.stack });
  });
  // Failed console actions: a mutating /api call that answers 5xx.
  var of = root.fetch && root.fetch.bind(root);
  if (of) root.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    return of(input, init).then(function (res) {
      if (res.status >= 500 && /\/api\//.test(url) && !/\/api\/(issues|issue-reporting)/.test(url)) {
        var svc = (url.match(/\/api\/(?:aws|gcp|azure)?\/?([a-z0-9\-]+)/i) || [])[1];
        res.clone().json().catch(function () { return {}; }).then(function (d) {
          send({ kind: "console-action", service: svc, action: method + " " + url.replace(/^https?:\/\/[^\/]+/, "").split("?")[0].split("/").slice(0, 4).join("/"),
                 status: res.status, code: d.code || d.error && d.error.code, message: d.detail || d.message });
        });
      }
      return res;
    });
  };

  // ── consent dialog + settings ───────────────────────────────────────
  function el(tag, attrs, kids) {
    var n = document.createElement(tag), k;
    for (k in attrs || {}) { if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); }
    (kids || []).forEach(function (c) { n.appendChild(c); });
    return n;
  }
  function putMode(mode) {
    return fetch(settingsUrl(), { method: "PUT", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ mode: mode }) })
      .then(function (r) { return r.ok ? r.json() : null; }, function () { return null; })
      .then(function (d) { // "Yes" -> authorise the Vyomi GitHub App (only when the portal has it configured)
        if (d && d.authorize_url) { try { root.open(d.authorize_url, "_blank", "noopener"); } catch (e) {} }
        return d;
      });
  }
  function overlay(id, panel) {
    var old = document.getElementById(id); if (old) old.remove();
    var o = el("div", { id: id, role: "dialog", "aria-modal": "true", style: "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2147483000;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif" }, [panel]);
    document.body.appendChild(o); return o;
  }
  var CARD = "background:#fff;color:#1f2933;max-width:520px;margin:16px;padding:24px 28px;border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.35);line-height:1.5;font-size:14px";
  var BTN = "font:inherit;font-weight:600;padding:9px 16px;border-radius:8px;cursor:pointer;border:1px solid #6b7280;background:#fff;color:#1f2933;margin-right:10px";
  function showConsent() {
    var done = function (mode) { putMode(mode).then(function () { var o = document.getElementById("vyomi-consent"); if (o) o.remove(); }); };
    var yes = el("button", { id: "vyomi-consent-yes", style: BTN + ";background:#2563eb;border-color:#2563eb;color:#fff", text: "Yes, file issues for me" });
    var no = el("button", { id: "vyomi-consent-no", style: BTN, text: "Not now" });
    yes.onclick = function () { done("named"); }; no.onclick = function () { done("anonymous"); };
    overlay("vyomi-consent", el("div", { style: CARD }, [
      el("h2", { style: "margin:0 0 10px;font-size:20px", text: "Help us make Vyomi better for you 🙌" }),
      el("p", { text: "When something breaks while you're building, Vyomi can file a GitHub issue for you automatically, under your GitHub account, so our team (and our fixing agents) see it right away and ship the fix in the next release. You'll get notified when it's fixed." }),
      el("p", { text: "We only send what's needed to reproduce the problem: the service, the action and the error. We never send your data, secrets, keys or resource names." }),
      el("div", { style: "margin:16px 0 12px" }, [yes, no]),
      el("p", { style: "margin:0;font-size:12.5px;color:#52606d;font-style:italic", text: "If you choose \"Not now\", we'll still send anonymous reports (no name, same scrubbing) so the bug gets fixed. You can change this anytime in Settings → Issue reporting." })
    ]));
  }
  function openSettings() {
    fetch(settingsUrl(), { credentials: "include" }).then(function (r) { return r.json(); }).then(function (s) {
      var named = el("input", { type: "radio", name: "vyomi-ir", value: "named", id: "vyomi-ir-named" });
      var anon = el("input", { type: "radio", name: "vyomi-ir", value: "anonymous", id: "vyomi-ir-anonymous" });
      (s.mode === "named" ? named : anon).checked = true;
      var close = el("button", { style: BTN, text: "Close" }); close.onclick = function () { document.getElementById("vyomi-ir-settings").remove(); };
      [named, anon].forEach(function (r) { r.onchange = function () { putMode(r.value); }; });
      overlay("vyomi-ir-settings", el("div", { style: CARD }, [
        el("h2", { style: "margin:0 0 10px;font-size:18px", text: "Issue reporting" }),
        el("p", { text: "When something breaks, Vyomi files a GitHub issue with only the service, action and error." + (s.enabled === false ? " (Disabled: VYOMI_NO_TELEMETRY is set.)" : "") }),
        el("label", { style: "display:block;margin:8px 0" }, [named, el("span", { text: " File issues under my GitHub account" })]),
        el("label", { style: "display:block;margin:8px 0" }, [anon, el("span", { text: " Anonymous reports only (no name)" })]),
        el("div", { style: "margin-top:14px" }, [close])
      ]));
    }).catch(function () {});
  }
  api.showConsent = showConsent; api.openSettings = openSettings;
  function maybeAsk() {
    fetch(settingsUrl(), { credentials: "include" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
      if (s && s.enabled !== false && s.signed_in !== false && !s.consent_asked) showConsent();
    }).catch(function () {});
  }
  function boot() {
    var link = el("a", { id: "vyomi-ir-link", href: "#issue-reporting", style: "position:fixed;right:10px;bottom:6px;z-index:2147482000;font:11px system-ui,sans-serif;color:#6b7280;opacity:.7;text-decoration:underline;cursor:pointer", text: "Issue reporting" });
    link.onclick = function (e) { e.preventDefault(); openSettings(); };
    document.body.appendChild(link);
    setTimeout(maybeAsk, 1500);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})(typeof self !== "undefined" ? self : this);
