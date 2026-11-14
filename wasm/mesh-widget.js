/* Vyomi Global Mesh widget for the AWS / GCP / Azure Nano consoles: an in-page card on the console HOME page (beside the "How Nano ... works" video banner).
 *   Pro / Max (or active trial) with mesh enabled -> Start / Leave the Mesh button
 *   Pro / Max entitled but switched off              -> "Turn on the Mesh"
 *   Free, trial never used                           -> "Start 30-day trial" (one per account; same trial as the appliance)
 *   Trial ended / not entitled                       -> "Upgrade to Pro / Max"
 * Uses window.VyomiMesh (mesh-link.js) and /api/account/mesh. Cloud = data-cloud on this script tag. */
(function () {
  "use strict";
  var me = document.currentScript, CLOUD = (me && me.getAttribute("data-cloud")) || "";
  var PRICING = "https://vyomi.cloud/pricing";
  var card, busy = false, msg = "", view = "main", collapsed = false;

  // ── one-command tunnel install (macOS) ─────────────────────────────────────────────────────────────────────────────────────────
  // POST /api/tunnel/pair/start returns a single-use command bound to THIS signed-in account:  curl -fsSL <portal>/i/<code> | sh
  // The script installs a private Node + the tunnel, connects the account (so a wrong-account key cannot happen) and starts the tunnel at
  // login. It reports each step; this card polls GET /api/tunnel/pair/status and shows them live. Other systems keep the brew/npm steps.
  var inst = { s: "idle", cmd: "", code: "", st: null, err: "", copied: false, t0: 0 }, instTimer = 0;
  var INST_STEPS = [["node", "Configuring Tunnel"], ["tunnel", "Installing the tunnel"], ["pair", "Connecting your account"], ["service", "Starting the tunnel"], ["running", "Tunnel running"]];
  function isMac() { return /Mac/i.test(navigator.platform || "") && !/iPhone|iPad|iPod/i.test(navigator.userAgent || ""); }
  function instFail(text) { inst = { s: "error", cmd: "", code: "", st: null, err: text, copied: false, t0: 0 }; repaint(); }
  function instGet() {
    clearTimeout(instTimer); inst = { s: "loading", cmd: "", code: "", st: null, err: "", copied: false, t0: 0 }; repaint();
    fetch("/api/tunnel/pair/start", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify({ platform: "mac" }) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); })
      .then(function (r) {
        if (!r.ok || !r.j.command) return instFail(r.status === 401 ? "Sign in again, then retry." : (r.j && (r.j.message || r.j.error)) || "Could not create the install command.");
        inst = { s: "ready", cmd: r.j.command, code: r.j.code, st: null, err: "", copied: false, t0: Date.now() }; repaint(); instPoll();
      }, function () { instFail("Could not reach Vyomi. Check your connection and retry."); });
  }
  function instPoll() {
    clearTimeout(instTimer);
    if (inst.s !== "ready") return;
    fetch("/api/tunnel/pair/status?code=" + encodeURIComponent(inst.code), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; }, function () { return null; })
      .then(function (j) {
        if (inst.s !== "ready") return;
        if (j) { inst.st = j; if (j.finished && B() && B().checkTunnel) B().checkTunnel().then(repaint); repaint(); }
        if (!(j && (j.finished || j.expired)) && Date.now() - inst.t0 < 31 * 60 * 1000) instTimer = setTimeout(instPoll, 2000);
      });
  }
  function instCopy() {
    var done = function () { inst.copied = true; repaint(); setTimeout(function () { inst.copied = false; repaint(); }, 2500); };
    try { navigator.clipboard.writeText(inst.cmd).then(done, function () { toast("Select the command and copy it."); }); } catch (_) { toast("Select the command and copy it."); }
  }
  // ── the Setup Tunnel dialog ──────────────────────────────────────────────────────────────────────────────────────────────────
  // The card only shows a "Setup Tunnel" button; the command, copy button, live steps and the package-manager fallback live in this
  // dialog. It can be closed at any time; closing mid-install keeps the install (and its progress polling) going, and reopening resumes it.
  var tm = { open: false, last: "" };
  function instDone() { var st = inst.st || {}, ts = tunnelState(); return !!(st.finished || ts === "up" || ts === "notab"); }
  function instTerminal() { var st = inst.st || {}; return !!(st.finished || st.failed || st.expired); }
  function repaint() { paint(); paintModal(); }
  function modalHtml() {
    var done = instDone(), body;
    if (!isMac()) {
      body = '<ol class="steps"><li>Install: <code>brew install vyomi-cloud/tap/vyomi-tunnel</code> (or <code>npm i -g vyomi-tunnel</code>)</li><li>Run <code>vyomi-tunnel</code></li><li>Click <b>Start tunnel</b> in the bar at the bottom of this page</li></ol>';
    } else body = installPanel();
    return '<div class="tm-ov" data-tm-ov><div class="tm" role="dialog" aria-modal="true" aria-labelledby="vy-tm-t" tabindex="-1">'
      + '<div class="tm-h"><h3 id="vy-tm-t">' + (done ? "Tunnel ready" : "Set up the Vyomi tunnel") + '</h3>'
      + '<button class="tm-x" data-vyb-keep data-tm-close aria-label="Close"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="M3.22 3.22a.75.75 0 0 1 1.06 0L8 6.94l3.72-3.72a.75.75 0 1 1 1.06 1.06L9.06 8l3.72 3.72a.75.75 0 1 1-1.06 1.06L8 9.06l-3.72 3.72a.75.75 0 0 1-1.06-1.06L6.94 8 3.22 4.28a.75.75 0 0 1 0-1.06z"/></svg></button></div>'
      + '<div class="tm-b">' + body + '</div>'
      + '<div class="tm-f"><button class="go' + (done ? "" : " sec") + '" data-vyb-keep data-tm-close>' + (done ? "Done" : "Close") + '</button></div></div></div>';
  }
  function paintModal() {
    var el = document.getElementById("vy-tm-root");
    if (!tm.open) { if (el) el.parentNode.removeChild(el); tm.last = ""; return; }
    var created = false;
    if (!el) {
      created = true; el = document.createElement("div"); el.id = "vy-tm-root"; el.setAttribute("data-vyb-keep", "1"); el.setAttribute("data-cloud", CLOUD); document.body.appendChild(el);
      el.addEventListener("click", function (e) {
        var t = e.target;
        if (t.closest && t.closest("[data-inst-get]")) { e.preventDefault(); instGet(); }
        else if (t.closest && t.closest("[data-inst-copy]")) { e.preventDefault(); instCopy(); }
        else if (t.closest && t.closest("[data-tm-close]")) { e.preventDefault(); instClose(); }
        else if (t.hasAttribute && t.hasAttribute("data-tm-ov")) instClose();                     // click outside the dialog
      });
    }
    var html = modalHtml();
    if (html !== tm.last) { el.innerHTML = html; tm.last = html; }
    if (created) { var d = el.querySelector(".tm"); if (d && d.focus) d.focus(); }
  }
  function instOpen() {
    var st = inst.st || {};
    tm.open = true; tm.last = "";
    if (isMac() && (inst.s === "idle" || inst.s === "error" || st.finished || st.expired || st.failed)) instGet(); else paintModal();
    paint();
  }
  function instClose() {
    tm.open = false; tm.last = "";
    if (instTerminal()) { clearTimeout(instTimer); inst = { s: "idle", cmd: "", code: "", st: null, err: "", copied: false, t0: 0 }; }   // a running install keeps polling in the background
    paintModal(); paint();
  }
  document.addEventListener("keydown", function (e) { if (tm.open && (e.key === "Escape" || e.key === "Esc")) instClose(); });
  function installPanel() {
    if (inst.s === "idle" || inst.s === "error") {
      return '<div class="inst"><p class="fine">Install the Vyomi tunnel on this Mac with one command. It connects to <b>your</b> account, so there is nothing to copy or configure.</p>'
        + (inst.err ? '<p class="fine" style="color:#b10e1c">' + esc(inst.err) + '</p>' : '')
        + '<button class="go" data-inst-get>Get install command</button>'
        + '<div class="sub">Prefer a package manager? <code>npm i -g vyomi-tunnel</code>, then run <code>vyomi-tunnel</code></div></div>';
    }
    if (inst.s === "loading") return '<div class="inst"><p class="fine">Creating your install command…</p></div>';
    var st = inst.st || {}, done = st.done || [];
    var items = INST_STEPS.map(function (s) { return '<li style="list-style:none;margin-left:-18px">' + (done.indexOf(s[0]) >= 0 ? "✓" : "○") + " " + esc(s[1]) + "</li>"; }).join("");
    var head = st.finished ? '<p class="fine"><b>Tunnel installed and running.</b> Click <b>Start tunnel</b> in the bar at the bottom of this page, then join the Mesh.</p>'
      : st.expired ? '<p class="fine">This command expired. <a href="#" data-inst-get>Get a new one</a></p>'
      : '<p class="fine">Open <b>Terminal</b>, paste this, and press Enter. This page follows the progress.</p>';
    var ICON_COPY = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="M0 6.75C0 5.78.78 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .14.11.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25z"/><path d="M5 1.75C5 .78 5.78 0 6.75 0h7.5C15.22 0 16 .78 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .14.11.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25z"/></svg>';
    var ICON_OK = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0z"/></svg>';
    return '<div class="inst">' + head + '<div class="cmd"><code>' + esc(inst.cmd) + '</code>'
      + '<button class="cp' + (inst.copied ? " ok" : "") + '" data-vyb-keep data-inst-copy aria-label="' + (inst.copied ? "Copied" : "Copy command") + '" title="' + (inst.copied ? "Copied" : "Copy") + '">' + (inst.copied ? ICON_OK : ICON_COPY) + '</button></div>'
      + '<ol class="steps">' + items + '</ol>'
      + (st.failed ? '<p class="fine" style="color:#b10e1c">The install stopped' + (st.detail ? ": " + esc(st.detail) : "") + '. Run the command again, or <a href="#" data-inst-get>get a new one</a>.</p>' : "") + '</div>';
  }

  function B() { return window.VyomiMesh; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  // Errors are shown as a 5-second toast (shared implementation in mesh-link.js), never inside the Mesh card.
  function toast(text) { var b = B(); if (b && b.toast) b.toast(text); }
  function css() {
    var st = document.createElement("style");
    st.textContent = "#vy-bw{position:relative;z-index:2;box-sizing:border-box;margin:14px 0 18px;padding:14px 18px;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#fff;color:#16191f;border:1px solid #d5dbdb;border-radius:8px;font-size:14px;line-height:1.45;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px 20px}"
      + ".vy-nano-video{display:flex;flex-wrap:wrap;gap:16px;align-items:stretch}.vy-nano-video>.vy-video-banner{order:1;flex:1 1 340px;min-width:0;margin:0 0 16px!important}.vy-nano-video>#vy-bw{order:2;flex:1 1 340px;min-width:0;margin:0 0 16px}"
      + "#vy-bw .main{min-width:0}"
      + "#vy-tm-root .tm-ov{position:fixed;inset:0;z-index:2147483000;background:rgba(15,20,25,.55);display:flex;align-items:center;justify-content:center;padding:16px;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif}"
      + "#vy-tm-root .tm{box-sizing:border-box;background:#fff;color:#1b2430;width:min(780px,100%);max-height:calc(100vh - 32px);overflow:auto;border-radius:12px;box-shadow:0 24px 70px rgba(0,0,0,.4);outline:0}"
      + "#vy-tm-root .tm-h{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #e3e6e8}#vy-tm-root .tm-h h3{margin:0;font-size:17px;font-weight:650}"
      + "#vy-tm-root .tm-x{border:0;background:none;font-size:24px;line-height:1;cursor:pointer;color:#59636e;padding:0 4px}"
      + "#vy-tm-root .tm-b{padding:16px 20px}#vy-tm-root .tm-f{padding:0 20px 18px;text-align:right;min-height:28px}"
      + "#vy-tm-root .fine{font-size:12px;color:#6b7280}#vy-tm-root a{color:#1a56c4}#vy-tm-root p{margin:0 0 10px;line-height:1.5;font-size:14px}#vy-tm-root p.fine{font-size:13px}"
      + "#vy-tm-root .go{display:inline-block;box-sizing:border-box;text-align:center;text-decoration:none;padding:9px 18px;border-radius:8px;border:0;background:#2f6fdc;color:#fff!important;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}"
      + "#vy-tm-root .sub{font-size:12px;color:#6b7280;margin-top:8px}#vy-tm-root .steps{margin:8px 0 0;padding-left:20px;color:#414d5c;font-size:14px}#vy-tm-root .steps li{padding:3px 0}"
      + "#vy-tm-root code{background:#f2f3f3;border:1px solid #e3e6e8;border-radius:4px;padding:1px 6px;font-size:12px}"
      + "#vy-tm-root[data-cloud=aws] .tm-ov{background:rgba(15,20,26,.7);font-family:'Amazon Ember','Open Sans','Helvetica Neue',Roboto,Arial,sans-serif}"
      + "#vy-tm-root[data-cloud=aws] .tm{border-radius:8px;color:#0f141a;box-shadow:0 4px 20px 1px rgba(0,28,36,.5);font-family:'Amazon Ember','Open Sans','Helvetica Neue',Roboto,Arial,sans-serif}"
      + "#vy-tm-root[data-cloud=aws] .tm-h{padding:20px 20px 16px;border-bottom:1px solid #e9ebed}.tm-h h3{font-size:20px;font-weight:700;line-height:24px;letter-spacing:.005em}"
      + "#vy-tm-root[data-cloud=aws] .tm-x{color:#5f6b7a;border-radius:4px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;padding:0}.tm-x:hover{color:#0f141a;background:#f2f3f3}"
      + "#vy-tm-root[data-cloud=aws] .tm-b{padding:20px}.tm-b p,.tm-b .steps{color:#414d5c}.fine{color:#5f6b7a}"
      + "#vy-tm-root[data-cloud=aws] .tm-f{padding:16px 20px;border-top:1px solid #e9ebed}"
      + "#vy-tm-root[data-cloud=aws] .go{border-radius:20px;background:#ff9900;color:#0f141a!important;font-weight:700;padding:6px 20px;border:2px solid #ff9900}.go:hover{background:#ec7211;border-color:#ec7211}"
      + "#vy-tm-root[data-cloud=aws] .go.sec{background:#fff;color:#0972d3!important;border:2px solid #0972d3}.go.sec:hover{background:#f2f8fd}"
      + "#vy-tm-root[data-cloud=aws] a{color:#0972d3}code{font-family:Monaco,Menlo,Consolas,'Courier New',monospace}.cmd code{background:#f9fafa;border:1px solid #e9ebed;border-radius:8px}"
      + "#vy-tm-root[data-cloud=aws] .cp{border:2px solid #0972d3;border-radius:50%;color:#0972d3;background:#fff;top:7px;right:7px}.cp:hover{background:#f2f8fd}.cp.ok{color:#037f0c;border-color:#037f0c}"
      + "#vy-tm-root[data-cloud=aws] button:focus-visible{outline:2px solid #0972d3;outline-offset:2px}"
      + "#vy-tm-root[data-cloud=gcp] .tm-ov{background:rgba(0,0,0,.32);font-family:'Google Sans',Roboto,Arial,sans-serif}"
      + "#vy-tm-root[data-cloud=gcp] .tm{border-radius:28px;color:#202124;box-shadow:0 8px 12px 6px rgba(0,0,0,.15),0 4px 4px rgba(0,0,0,.3);font-family:'Google Sans',Roboto,Arial,sans-serif}"
      + "#vy-tm-root[data-cloud=gcp] .tm-h{padding:24px 24px 8px}.tm-h h3{font-size:24px;font-weight:400;line-height:32px}"
      + "#vy-tm-root[data-cloud=gcp] .tm-x{color:#5f6368;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;padding:0}.tm-x:hover{background:rgba(60,64,67,.08)}"
      + "#vy-tm-root[data-cloud=gcp] .tm-b{padding:8px 24px}.tm-b p,.tm-b .steps{color:#5f6368}.fine{color:#5f6368}"
      + "#vy-tm-root[data-cloud=gcp] .tm-f{padding:16px 24px 24px}"
      + "#vy-tm-root[data-cloud=gcp] .go{border-radius:20px;background:#0b57d0;font-weight:500;padding:9px 24px;border:0;letter-spacing:.01em}.go:hover{background:#0842a0;box-shadow:0 1px 2px rgba(60,64,67,.3),0 1px 3px 1px rgba(60,64,67,.15)}"
      + "#vy-tm-root[data-cloud=gcp] .go.sec{background:transparent;color:#0b57d0!important;padding:9px 12px;box-shadow:none}.go.sec:hover{background:rgba(11,87,208,.08)}"
      + "#vy-tm-root[data-cloud=gcp] a{color:#0b57d0}code{font-family:'Roboto Mono',Menlo,Consolas,monospace}.cmd code{background:#f1f3f4;border:0;border-radius:12px}"
      + "#vy-tm-root[data-cloud=gcp] .cp{border:0;background:transparent;border-radius:50%;width:36px;height:36px;color:#5f6368;top:4px;right:4px}.cp:hover{background:rgba(60,64,67,.08)}.cp.ok{color:#188038}"
      + "#vy-tm-root[data-cloud=gcp] button:focus-visible{outline:2px solid #0b57d0;outline-offset:2px}"
      + "#vy-tm-root[data-cloud=azure] .tm-ov{background:rgba(0,0,0,.4);font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,sans-serif}"
      + "#vy-tm-root[data-cloud=azure] .tm{border-radius:8px;color:#242424;box-shadow:0 0 8px rgba(0,0,0,.12),0 32px 64px rgba(0,0,0,.14);font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,sans-serif}"
      + "#vy-tm-root[data-cloud=azure] .tm-h{padding:24px 24px 0;border:0}.tm-h h3{font-size:20px;font-weight:600;line-height:28px}"
      + "#vy-tm-root[data-cloud=azure] .tm-x{color:#424242;border-radius:4px;width:32px;height:32px;display:flex;align-items:center;justify-content:center;padding:0}.tm-x:hover{background:#f5f5f5}"
      + "#vy-tm-root[data-cloud=azure] .tm-b{padding:12px 24px}.tm-b p,.tm-b .steps{color:#616161}.fine{color:#616161}"
      + "#vy-tm-root[data-cloud=azure] .tm-f{padding:12px 24px 24px}"
      + "#vy-tm-root[data-cloud=azure] .go{border-radius:4px;background:#0f6cbd;font-weight:600;padding:5px 16px;border:1px solid #0f6cbd;line-height:22px}.go:hover{background:#115ea3;border-color:#115ea3}"
      + "#vy-tm-root[data-cloud=azure] .go.sec{background:#fff;color:#242424!important;border:1px solid #d1d1d1}.go.sec:hover{background:#f5f5f5;border-color:#c7c7c7}"
      + "#vy-tm-root[data-cloud=azure] a{color:#0f6cbd}code{font-family:Consolas,'Courier New',monospace}.cmd code{background:#f5f5f5;border:1px solid #e0e0e0;border-radius:4px}"
      + "#vy-tm-root[data-cloud=azure] .cp{border:0;background:transparent;border-radius:4px;width:28px;height:28px;color:#424242;top:7px;right:7px}.cp:hover{background:#e0e0e0}.cp.ok{color:#107c10}"
      + "#vy-tm-root[data-cloud=azure] button:focus-visible{outline:2px solid #242424;outline-offset:1px}"
      + "#vy-tm-root .cmd{position:relative;margin:10px 0}#vy-tm-root .cmd code{display:block;word-break:break-all;padding:12px 48px 12px 14px;font-size:13px;line-height:1.45;user-select:all}"
      + "#vy-tm-root .cp{position:absolute;top:6px;right:6px;width:30px;height:30px;display:flex;align-items:center;justify-content:center;border:1px solid #d0d7de;border-radius:6px;background:#fff;color:#57606a;cursor:pointer;padding:0}#vy-tm-root .cp:hover{background:#f3f4f6}#vy-tm-root .cp.ok{color:#1a7f37;border-color:#1a7f37}"
      + "#vy-bw .cmd{margin:8px 0}#vy-bw .cmd code{display:block;word-break:break-all;background:#f2f3f3;border:1px solid #e3e6e8;border-radius:4px;padding:8px 10px;font-size:12px;user-select:all}#vy-bw .inst .go{margin:2px 0 6px}"
      + "@media(max-width:560px){#vy-bw{grid-template-columns:minmax(0,1fr)}#vy-bw .act{min-width:0}}"
      + "#vy-bw .foot:empty{display:none}#vy-bw .foot{grid-column:1/-1;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 20px;padding-top:8px;border-top:1px solid rgba(128,128,128,.22)}"
      + "#vy-bw .foot p,#vy-bw .foot .sub{margin:0;text-align:left}#vy-bw .foot .sub a{white-space:nowrap}"
      + "#vy-bw h4{margin:0;font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px;white-space:nowrap}"
      + "#vy-bw .tag{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:999px;background:#e8f0fe;color:#1a56c4}"
      + "#vy-bw .tag.free{background:#eceff3;color:#4b5563}"
      + "#vy-bw p{margin:0 0 6px;color:#4b5563}#vy-bw p:last-child{margin:0}"
      + "#vy-bw .fine{font-size:12px;color:#6b7280}#vy-bw a{color:#1a56c4}"
      + "#vy-bw .act{display:flex;flex-direction:column;align-items:stretch;gap:4px;min-width:170px}#vy-bw .act .go{white-space:nowrap}"
      + "#vy-bw .go{display:block;box-sizing:border-box;text-align:center;text-decoration:none;padding:9px 16px;border-radius:8px;border:0;background:#2f6fdc;color:#fff!important;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}"
      + "#vy-bw .go.stop{background:#b42318}#vy-bw .go[disabled]{opacity:.6;cursor:default}"
      + "#vy-bw .sub{font-size:12px;color:#6b7280;text-align:center}"
      + "#vy-bw .cd{margin-top:6px;text-align:center;font:600 22px/1.1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.04em;font-variant-numeric:tabular-nums}#vy-bw .cdl{text-align:center;font-size:11px;color:#6b7280;margin-top:-2px}"
      + "#vy-bw .err{color:#b42318;font-size:13px;margin-top:4px}"
      + "#vy-bw .ka{margin-left:auto;display:inline-flex;align-items:center;gap:8px;font-size:12px;color:#6b7280;cursor:pointer;user-select:none}#vy-bw .ka .sw{position:relative;width:32px;height:18px;border-radius:999px;border:0;padding:0;background:#c3c9d1;cursor:pointer;transition:background .15s}#vy-bw .ka .sw::after{content:'';position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:transform .15s}#vy-bw .ka .sw[aria-checked=true]{background:#2f6fdc}#vy-bw .ka .sw[aria-checked=true]::after{transform:translateX(14px)}#vy-bw .ka .sw[disabled]{opacity:.6;cursor:default}"
      + "#vy-bw .go[disabled]{background:#e9ebed!important;color:#8a94a3!important;border-color:#e9ebed!important;cursor:not-allowed!important;opacity:1!important}"
      + "#vy-bw .foot:has(.pgw){flex-direction:column;align-items:stretch}#vy-bw .foot .stg{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:2px 18px;margin:6px 0 2px}#vy-bw .pgw{width:100%}#vy-bw .pgb{height:8px;border-radius:999px;background:#e9ebed;overflow:hidden}#vy-bw .pgb i{display:block;height:100%;border-radius:999px;background:#2f6fdc;transition:width .6s ease}#vy-bw .pgb.bad i{background:#b42318}#vy-bw .ex{border:1px solid #d5dbdb;background:#fff;color:#4b5563;border-radius:6px;width:26px;height:22px;line-height:1;cursor:pointer;font-size:12px;padding:0}#vy-bw .ex:hover{background:#f2f3f3}#vy-bw .pgl{font-size:12px;color:#6b7280;margin-top:4px}#vy-bw .stg .badx{color:#b42318;font-weight:600}"
      + "#vy-bw .steps{margin:2px 0 0;padding-left:20px;color:#414d5c}#vy-bw .steps li{padding:2px 0}#vy-bw .steps code{background:#f2f3f3;border:1px solid #e3e6e8;border-radius:4px;padding:1px 6px;font-size:12px;user-select:all}"
      + "#vy-bw .warn{color:#b54708;font-size:13px}#vy-bw .stg{list-style:none;margin:6px 0 0;padding:0;font-size:13px;color:#4b5563}#vy-bw .stg li{display:flex;gap:8px;align-items:baseline;padding:1px 0}"
      + "#vy-bw .stg .m{width:14px;text-align:center;flex:0 0 14px}#vy-bw .stg .done{color:#067647}#vy-bw .stg .now{color:#16191f;font-weight:600}#vy-bw .stg .todo{color:#9ca3af}"
      // ── native look per cloud ──
      // AWS · Cloudscape: Open Sans / Amazon Ember, 1px #c6c6cd-ish container, orange primary pill (as "Add widgets"), outlined blue pill for normal actions
      + "#vy-bw[data-cloud=aws]{font-family:'Amazon Ember','Open Sans','Helvetica Neue',Roboto,Arial,sans-serif;border:1px solid #e9ebed;border-radius:8px;box-shadow:none;color:#0f141a;font-size:14px}"
      + "#vy-bw[data-cloud=aws] h4{font-size:16px;font-weight:700;letter-spacing:.005em}#vy-bw[data-cloud=aws] p{color:#414d5c}"
      + "#vy-bw[data-cloud=aws] .tag{border-radius:4px;background:#0972d3;color:#fff;letter-spacing:.02em}#vy-bw[data-cloud=aws] .tag.free{background:#5f6b7a;color:#fff}"
      + "#vy-bw[data-cloud=aws] .go{border-radius:20px;background:#ff9900;color:#0f141a!important;font-weight:700;padding:6px 20px;border:2px solid #ff9900}"
      + "#vy-bw[data-cloud=aws] .go.stop{background:#fff;color:#d91515!important;border:2px solid #d91515}"
      + "#vy-bw[data-cloud=aws] a{color:#0972d3}"
      // GCP · Material 3: Google Sans / Roboto, 12px radius #dadce0 outline, filled blue pill
      + "#vy-bw[data-cloud=gcp]{font-family:'Google Sans',Roboto,Arial,sans-serif;border:1px solid #dadce0;border-radius:12px;color:#202124;font-size:14px}"
      + "#vy-bw[data-cloud=gcp] h4{font-size:16px;font-weight:500}#vy-bw[data-cloud=gcp] p{color:#5f6368}"
      + "#vy-bw[data-cloud=gcp] .tag{border-radius:8px;background:#e8f0fe;color:#1967d2;letter-spacing:.03em}#vy-bw[data-cloud=gcp] .tag.free{background:#f1f3f4;color:#5f6368}"
      + "#vy-bw[data-cloud=gcp] .go{border-radius:20px;background:#0b57d0;font-weight:500;padding:9px 24px;letter-spacing:.01em}"
      + "#vy-bw[data-cloud=gcp] .go.stop{background:#fff;color:#b3261e!important;border:1px solid #dadce0}"
      + "#vy-bw[data-cloud=gcp] a{color:#0b57d0}"
      // Azure · Fluent 2: Segoe UI, 4px radius, #e0e0e0 stroke, brand #0f6cbd, subtle buttons
      + "#vy-bw[data-cloud=azure]{font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,sans-serif;border:1px solid #e0e0e0;border-radius:4px;box-shadow:none;color:#242424;font-size:14px}"
      + "#vy-bw[data-cloud=azure] h4{font-size:16px;font-weight:600}#vy-bw[data-cloud=azure] p{color:#616161}"
      + "#vy-bw[data-cloud=azure] .tag{border-radius:2px;background:#ebf3fc;color:#0f6cbd;font-weight:600}#vy-bw[data-cloud=azure] .tag.free{background:#f0f0f0;color:#424242}"
      + "#vy-bw[data-cloud=azure] .go{border-radius:4px;background:#0f6cbd;font-weight:600;padding:7px 14px}"
      + "#vy-bw[data-cloud=azure] .go.stop{background:#fff;color:#b10e1c!important;border:1px solid #d1d1d1}"
      + "#vy-bw[data-cloud=azure] a{color:#0f6cbd}";
    document.head.appendChild(st);
  }
  function api(path, body) {
    return fetch("/api/account/mesh" + path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function refresh() { var b = B(); return b ? Promise.all([b.loadAccount(), b.loadSession()]).then(paint, paint) : Promise.resolve(); }
  function run(fn) { if (busy) return; busy = true; msg = ""; paint(); Promise.resolve().then(fn).catch(function () { toast("Something went wrong. Try again."); }).then(function () { busy = false; return refresh(); }); }

  // Agreement is stored per GitHub account and per terms version (bump TERMS_V when the wording changes: everyone sees it again).
  var TERMS_V = "v2";
  function termsKey() { var x = B() && B().session && B().session(); return "vy_mesh_terms_" + TERMS_V + ":" + ((x && x.github && x.github.login) || ""); }
  function agreed() { try { return localStorage.getItem(termsKey()) === "1"; } catch (_) { return false; } }
  function show(v) { view = v; collapsed = false; try { localStorage.setItem("vy_bw_collapsed", "0"); } catch (_) {} paint(); }
  function doStart() {
    var b = B();
    run(function () {
      return b.sessionStart(CLOUD).then(function (r) {
        if (!r || r.cancelled) return;
        var er = !r.ok && r.j; if (!er) return;
        if (er.action === "reconnect") view = "connect"; else toast(er.message || er.error || "Could not start the mesh.");
      });
    });
  }
  function startStop() {
    var b = B(), x = b.session();
    if (!x || !x.github || !x.github.connected) { show("connect"); return; }
    if (x.active) { run(function () { return b.sessionStop(); }); return; }
    b.confirmTerms().then(function (ok) { if (ok) { b.termsAccept(); doStart(); } });     // terms: modal dialog
  }
  function enable(trial) {
    run(function () {
      return api(trial ? "/enable?trial=1" : "/enable").then(function (r) {
        if (!r.ok) { toast(r.j.message || "Could not turn on the mesh."); return; }
        // Pro = ONE cloud: a fresh trial pins the cloud of the console it was started from
        if (trial && r.j.clouds === "one" && !r.j.primary_cloud && CLOUD) return api("/primary-cloud", { cloud: CLOUD });
      });
    });
  }

  // Staged progress while the Mesh comes up. The portal reports only pending/starting/running + started_at, so the stages are paced by elapsed
  // time; the last stage stays active until the appliance reports ready. First starts commonly take 4 to 8 minutes.
  function mmss(sec) { sec = Math.max(0, sec | 0); return Math.floor(sec / 60) + "m " + String(sec % 60).padStart(2, "0") + "s"; }
  // Progress bar + current step; the full done/awaiting list is in the diagnostic dialog (Details). Steps come from mesh-link (progress()).
  function progressHtml() {
    var p = B().progress && B().progress(); if (!p) return "";
    var cur = p.now >= 0 ? p.steps[p.now] : null;
    return '<div class="pgw"><div class="pgb' + (p.bad ? " bad" : "") + '" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + p.pct + '"><i style="width:' + p.pct + '%"></i></div>'
      + '<div class="pgl">Step ' + (p.now >= 0 ? p.now + 1 : p.n) + ' of ' + p.n + (cur ? " · " + esc(cur.label) : "") + ' · ' + mmss(p.el) + ' · <a href="#" data-vc>Details</a></div></div>';
  }
  function tunnelState() { var b = B(); return b && b.tunnel ? b.tunnel().state : "unknown"; }

  function paint() {
    if (!card) return;
    var b = B(), a = b && b.account && b.account(), x = b && b.session && b.session(), main, act = "", ka = "";
    card.className = "";
    if (!a) {                                                       // not signed in / account unavailable
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag free">Free</span></h4><p>Your Free plan runs everything in the browser. Pro and Max add the Vyomi Global Mesh: real compute and AI on your own free GitHub quota.</p>';
      act = '<a class="go" href="' + PRICING + '" target="_blank" rel="noopener">See plans</a>';
    } else if (view === "connect") {                                // inline GitHub connect
      main = '<h4>\u26A1 Connect your GitHub account</h4><p>The Mesh runs on the free quota of <b>your own GitHub account</b>. Your Vyomi sign-in (Google, LinkedIn or any other) stays the same; we just link GitHub to it.</p><p class="fine">No GitHub account? <a href="https://github.com/signup" target="_blank" rel="noopener">Create a free one</a> (about 2 minutes), then come back and click Connect GitHub.</p>';
      act = '<button class="go" data-gh>Connect GitHub</button><div class="sub"><a href="#" data-back>Cancel</a></div>';
    } else if (a.effective) {                                       // Pro / Max / active trial, switched on
      var ss = x && x.session, stt = ss && ss.state, conn = !!(x && x.github && x.github.connected);
      var starting = stt === "pending" || stt === "starting", running = stt === "running", stopping = stt === "stopping";
      var tierName = (a.tier || "pro").charAt(0).toUpperCase() + (a.tier || "pro").slice(1);
      var cloudName = a.clouds === "one" && a.primary_cloud ? ({ aws: "AWS", gcp: "GCP", azure: "Azure" }[a.primary_cloud] || a.primary_cloud) : "";
      var sub = a.source === "trial" && a.days_left != null ? tierName + " trial: " + a.days_left + " day" + (a.days_left === 1 ? "" : "s") + " left" + (cloudName ? " \u00b7 " + cloudName + " only" : "") : (cloudName ? tierName + " \u00b7 " + cloudName + " only" : "");
      var CLOUD_NAMES = { aws: "AWS", gcp: "GCP", azure: "Azure" };
      var offCloud = !!(a.clouds === "one" && a.primary_cloud && CLOUD && String(a.primary_cloud).toLowerCase() !== CLOUD);   // Pro = one cloud; this console is another
      var hrs = x && x.hours_remaining != null ? x.hours_remaining + " h left this cycle" : "";
      var line, btn, warn = false, tunLink = "";
      var stg = "";
      if (starting) { var el0 = ss && ss.started_at ? Math.max(0, (Date.now() - Date.parse(ss.started_at)) / 1000) : 0; line = "Your Mesh is coming up on a GitHub Codespace."; stg = progressHtml(); btn = '<button class="go" disabled>Starting\u2026 ' + esc(mmss(el0)) + '</button>'; }
      else if (stopping) { line = "Stopping\u2026"; btn = '<button class="go" disabled>Stopping\u2026</button>'; }
      else if (running && !(B().joined && B().joined()) && ss.joined && ss.keep_alive !== false) {   // keep-alive reattach: no dialog, just reconnect through the tunnel
        var sec0 = Math.max(0, ss.countdown_seconds | 0), q2 = function (n) { return String(n).padStart(2, "0"); }, tup = tunnelState() === "up";
        line = tup ? "Reconnecting to your Mesh\u2026" : "Your Mesh is still running. Start your local tunnel (vyomi-tunnel), then click Start tunnel in the bar at the bottom, and this tab reconnects by itself.";
        warn = !tup;
        btn = '<button class="go" disabled>Reconnecting\u2026</button><div class="cd" title="Time left in this session">' + q2(Math.floor(sec0 / 3600)) + ':' + q2(Math.floor(sec0 % 3600 / 60)) + ':' + q2(sec0 % 60) + '</div><div class="cdl">session time left</div>';
        tunLink = '<div class="sub"><a href="#" data-leave>Leave the Mesh</a></div>';
      }
      else if (running && !(B().joined && B().joined())) {           // up, but not yet verified + joined: the health-check modal gates Join
        var k = B().checks ? B().checks() : { state: "idle" };
        line = k.state === "passed" ? "Your Mesh is healthy. Joining\u2026" : k.state === "failed" ? "A health check failed. Stopping the Codespace\u2026" : "Your Mesh is up. Running health checks\u2026";
        warn = k.state === "failed"; stg = progressHtml();
        btn = k.state === "passed" ? '<button class="go" data-jn>Join the Mesh</button>' : '<button class="go" disabled>' + (k.state === "failed" ? "Join the Mesh" : "Checking\u2026") + '</button>';
        tunLink = k.state === "failed" ? "" : '<div class="sub"><a href="#" data-leave>Cancel and leave</a></div>';
      }
      else if (running) {
        var sec = Math.max(0, ss.countdown_seconds | 0), p2 = function (n) { return String(n).padStart(2, "0"); };
        line = "Running on your own GitHub Codespace.";
        tunLink = '<div class="sub"><a href="#" data-vc>Details</a></div>';
        if (tunnelState() !== "up") { line = "The tunnel is disconnected. EC2, VMs and AI will not work until it is back. Click Start tunnel in the bar at the bottom."; warn = true; }
        btn = '<button class="go stop" data-ss ' + (busy ? "disabled" : "") + '>Leave the Mesh</button>'
          + '<div class="cd" aria-live="off" title="Time left in this session">' + p2(Math.floor(sec / 3600)) + ':' + p2(Math.floor(sec % 3600 / 60)) + ':' + p2(sec % 60) + '</div><div class="cdl">session time left</div>';
      }
      else {
        line = (x && x.ended_note) || (conn ? "Runs inside your GitHub account, at no cost to you." : "Connect your GitHub account to start.");
        btn = '<button class="go" data-ss ' + (busy ? "disabled" : "") + '>' + (conn ? "Join the Mesh" : "Connect GitHub & join") + '</button>';
        var tst = tunnelState();
        if (conn && tst === "connecting") {                             // just reloaded: the strip is resuming the tunnel by itself
          line = "Connecting to your tunnel\u2026"; btn = '<button class="go" disabled>Join the Mesh</button>';
        } else if (conn && tst !== "up" && tst !== "unknown") {                // Mesh data + control plane run over the local tunnel: no tunnel, no Join
          line = "Join needs your local Vyomi tunnel, because EC2, VMs and AI all travel through it.";
          stg = tst === "notab" ? '<ol class="steps"><li>The tunnel is running. Click <b>Start tunnel</b> in the bar at the bottom of this page.</li></ol>'
            : "";
          btn = tst === "notab" ? '<button class="go" disabled title="Start the tunnel first">Join the Mesh</button>' : '<button class="go" data-inst-open>Setup Tunnel</button>';
          tunLink = '<div class="sub"><a href="#" data-tun>Check again</a></div>';
        }
        var lf = B().lastFailure && B().lastFailure();
        if (conn && lf && (tst === "up" || tst === "unknown")) { tunLink = '<div class="sub"><a href="#" data-vc>Last attempt failed. See details</a></div>'; }
        if (offCloud) {                                             // not this cloud's plan: no Join here, say why and where to go
          line = "Your " + (a.source === "trial" ? "trial" : tierName + " plan") + " covers " + cloudName + " only. The Mesh on " + (CLOUD_NAMES[CLOUD] || CLOUD) + " is part of Max.";
          btn = '<a class="go" href="' + PRICING + '" target="_blank" rel="noopener">See plans</a>';
        }
      }
      if (running && ss) {          // footer, right-aligned: survive a closed / inactive tab for the whole 8 h window
        var kon = ss.keep_alive !== false;
        ka = '<label class="ka" title="' + (kon ? "Your Mesh stays up for the whole 8 hours even if this tab is closed or inactive. Open any Vyomi console to reattach (your local tunnel must be running). If the tunnel is lost, the Mesh still ends at the 8-hour limit." : "Off: the Mesh stops after 30 minutes with no Vyomi tab open.") + '">Keep running when this tab is closed <button type="button" class="sw" role="switch" data-ka aria-checked="' + kon + '" aria-label="Keep the Mesh running when this tab is closed"' + (busy ? " disabled" : "") + '></button></label>';
      }
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag">' + esc(a.source === "trial" ? tierName + " trial" : tierName) + '</span></h4><p' + (warn ? ' class="warn"' : '') + '>' + esc(line) + '</p>' + stg;
      act = btn + tunLink + '<div class="sub">' + esc([sub, hrs].filter(Boolean).join(" \u00b7 ")) + '</div>';
    } else if (a.status === "active" || a.status === "trial") {      // entitled but switched off
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag">' + esc(a.tier || "pro") + '</span></h4><p>Your plan includes the Mesh. It is switched off.</p>';
      act = '<button class="go" data-en ' + (busy ? "disabled" : "") + '>' + (busy ? "Turning on\u2026" : "Turn on the Mesh") + '</button>';
    } else if (!a.trial_used) {                                     // Free, the account's one 30-day trial not started yet
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag free">Free</span></h4><p>Try the Mesh with a free 30-day Pro trial (one cloud): real compute and AI on your own free GitHub quota. One trial per account.</p>';
      act = '<button class="go" data-tr ' + (busy ? "disabled" : "") + '>' + (busy ? "Starting trial\u2026" : "Start 30-day Pro trial") + '</button><div class="sub">or <a href="' + PRICING + '" target="_blank" rel="noopener">compare plans</a></div>';
    } else {                                                        // trial used / expired
      main = '<h4>\u26A1 Vyomi Global Mesh <span class="tag free">Free</span></h4><p>The Mesh is included with Pro and Max. Upgrade to use it.</p>';
      act = '<a class="go" href="' + PRICING + '" target="_blank" rel="noopener">Upgrade to Pro / Max</a>';
    }
    // Fixed layout for every state: row 1 = title (left, no wrap) + buttons (right); row 2 spans both columns with the note lines.
    var tm = /^(<h4>[\s\S]*?<\/h4>)([\s\S]*)$/.exec(main), title = tm ? tm[1] : main, notes = tm ? tm[2] : "", subs = "";
    act = act.replace(/<div class="sub">[\s\S]*?<\/div>/g, function (s) { if (s.replace(/<[^>]*>/g, "").trim()) subs += s; return ""; });
    card.innerHTML = '<div class="main">' + title + '</div><div class="act">' + act + '</div>'
      + '<div class="foot">' + notes + subs + ka + (msg ? '<div class="err">' + esc(msg) + '</div>' : "") + '</div>';
  }

  // Mount as an in-page card on the console HOME page: directly beside the "How Nano ... works" video banner; if that banner was dismissed,
  // before the Home heading. Not on other pages (the mesh status chip covers those).
  var HEADINGS = { aws: "Console Home", azure: "Azure services", gcp: "Welcome" };
  function findHeading() {
    var want = HEADINGS[CLOUD], els = document.querySelectorAll("h1,h2,h3"), i;
    for (i = 0; i < els.length; i++) if (els[i].textContent.trim() === want) return els[i];
    return null;
  }
  function place() {
    var vid = document.querySelector(".vy-nano-video"), h = vid ? null : findHeading();
    if (!vid && !h) { if (card.isConnected) card.remove(); return; }
    // The banner wrapper is a React-owned empty div whose children are script-injected: the card joins it, side by side with the video banner.
    if (vid) { if (card.parentElement !== vid) vid.appendChild(card); }
    if (vid && CLOUD === "aws") {          // AWS: the "Welcome to the Vyomi AWS console" alert goes first, above the video + Mesh row
      var row = vid.closest('[class*="awsui_child"]'), kids = row && row.parentElement ? row.parentElement.children : [], i;
      for (i = 0; i < kids.length; i++) if (kids[i] !== row && /^\s*Welcome to the/.test(kids[i].textContent) && kids[i].style.order !== "-1") kids[i].style.order = "-1";
    }
    else if (h) { var tgt = h.closest('[class*="awsui_child"]') || h.parentElement; if (card.nextElementSibling !== tgt || !card.isConnected) tgt.parentElement.insertBefore(card, tgt); }
  }

  function boot() {
    if (document.getElementById("vy-bw")) return;
    css(); card = document.createElement("div"); card.id = "vy-bw"; card.setAttribute("data-cloud", CLOUD); card.setAttribute("data-vyb-keep", "1");
    card.addEventListener("click", function (e) {
      var t = e.target;
      if (t.closest("[data-ss]")) startStop();
      else if (t.closest("[data-gh]")) { location.href = "/api/mesh/github/connect"; }
      else if (t.closest("[data-inst-open]")) { e.preventDefault(); instOpen(); }
      else if (t.closest("[data-tun]")) { e.preventDefault(); if (B() && B().checkTunnel) B().checkTunnel().then(paint); }
      else if (t.closest("[data-rr]")) { e.preventDefault(); if (B() && B().rerunChecks) B().rerunChecks(); }
      else if (t.closest("[data-vc]")) { e.preventDefault(); if (B() && B().openDetails) B().openDetails(); }
      else if (t.closest("[data-jn]")) { if (B() && B().joinMesh()) paint(); }
      else if (t.closest("[data-leave]")) { e.preventDefault(); run(function () { return B().sessionStop(); }); }
      else if (t.closest("[data-ka]")) { e.preventDefault(); var cur = B().session && B().session(), on = !(cur && cur.session && cur.session.keep_alive !== false); run(function () { return B().setKeepAlive(on); }); }
      else if (t.closest("[data-back]")) { e.preventDefault(); view = "main"; paint(); }
      else if (t.closest("[data-en]")) enable(false);
      else if (t.closest("[data-tr]")) enable(true);
    });
    var pending = false;
    new MutationObserver(function () { if (pending) return; pending = true; requestAnimationFrame(function () { pending = false; place(); }); })
      .observe(document.body, { childList: true, subtree: true });
    place(); paint();
    window.addEventListener("vyomi-mesh-session", paint); window.addEventListener("vyomi-mesh-account", paint); window.addEventListener("vyomi-tunnel", function () { paint(); paintModal(); }); window.addEventListener("vyomi-mesh-checks", paint);
    window.VyomiMeshWidget = { agreed: agreed, accept: function () { try { localStorage.setItem(termsKey(), "1"); } catch (_) {} }, show: function (v) { view = v; paint(); place(); if (card.scrollIntoView) card.scrollIntoView({ block: "center", behavior: "smooth" }); } };
    setInterval(function () { var x = B() && B().session && B().session(); if (x && x.session && (x.session.state === "running" || x.session.state === "starting" || x.session.state === "pending") && view === "main") paint(); }, 1000);
    var tries = 0; (function wait() { if (B() && B().loadAccount) { refresh(); setInterval(refresh, 60000); } else if (tries++ < 40) setTimeout(wait, 250); })();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
