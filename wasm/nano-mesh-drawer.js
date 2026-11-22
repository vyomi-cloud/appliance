/* "Vyomi Mesh" drawer for the Nano consoles (AWS / GCP / Azure): one expandable, collapsible drawer that hangs from the console header.
 * It holds what used to sit on the Home page: the "Welcome to the ..." banner, the "How Vyomi <cloud> works" video banner and the
 * Vyomi Global Mesh card. The video banner comes from nano-video.js; the Mesh card (mesh-widget.js) joins the `.vy-nano-video` row on its own.
 * Open/closed is remembered per cloud (default: open). The drawer sits IN the page flow right under the console header, so it pushes the console
 * down instead of covering it (--mesh-drawer-h carries its height for anyone who needs it). No shadow, only a 1px border. Cloud = data-cloud on this script tag. */
(function () {
  "use strict";
  var me = document.currentScript, CLOUD = (me && me.getAttribute("data-cloud")) || "";
  var KEY = "vyomi.meshDrawer2." + CLOUD;
  var HEADER = { aws: "#vyomi-top", gcp: "header", azure: "header.vy-top" };
  var WELCOME = {
    aws:   ["Welcome to the Vyomi AWS console", "Everything here runs against your local Vyomi simulator, using the same native APIs your SDKs and CLI call. Features Vyomi doesn’t simulate are marked."],
    gcp:   ["Welcome to Vyomi Google Cloud", "Everything in this console runs against your local Vyomi simulator — the same native APIs gcloud, gsutil and the client libraries call. Products without a v4 page open in the classic Vyomi console."],
    azure: ["Welcome to Vyomi Azure", "Everything in this portal runs against your local Vyomi simulator — the same native APIs az, the SDKs and ARM templates call. Features Vyomi doesn’t simulate are marked."]
  };
  var LS = function (m, v) { try { return m === "g" ? localStorage.getItem(KEY) : localStorage.setItem(KEY, v); } catch (_) { return null; } };

  var CSS =
    "#vy-md{position:relative;flex:none;box-sizing:border-box;width:100%;z-index:1;background:var(--md-bg);border-bottom:0;box-shadow:none;filter:none;font:14px/1.45 var(--md-font);color:var(--md-fg);--md-font:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;--md-fg:#16191f;--md-line:#d5dbdb;--md-bg:#fff;--md-accent:#0972d3;--md-al-bg:#f1faff;--md-al-bd:#0972d3;--md-al-fg:#414d5c;--md-al-r:10px;--md-al-bw:1px;--md-shadow:none}" +
    "#vy-md .md-panel{display:grid;grid-template-rows:0fr;background:var(--md-bg);transition:grid-template-rows .25s ease}" +
    "#vy-md.open .md-panel{grid-template-rows:1fr}" +
    /* expanded: a 1px bottom border closes the section so the console below it never looks like it has a margin; collapsed stays borderless */
    "#vy-md.open{border-bottom:1px solid var(--md-line)}" +
    /* expanded: the tab sits ON that bottom border, same flat-edge style as the collapsed tab (flat bottom, rounded top; collapsed = flat top, rounded bottom) */
    "#vy-md.open .md-tabrow{align-items:flex-end}" +
    "#vy-md.open .md-tab{margin-bottom:-1px;z-index:2}" +
    "#vy-md .md-clip{overflow:hidden;min-height:0}" +
    "#vy-md .md-body{box-sizing:border-box;max-width:calc(var(--md-cw,1272px) + 2 * var(--md-px,24px));margin:0 auto;padding:16px var(--md-px,24px) 18px;max-height:min(56vh,calc(100vh - 220px));overflow:auto}" +
    "#vy-md:not(.open) .md-body{visibility:hidden}" +
    "#vy-md .md-welcome{display:flex;gap:12px;align-items:flex-start;margin:0 0 14px;padding:12px 16px;background:var(--md-al-bg);border:var(--md-al-bw) solid var(--md-al-bd);border-radius:var(--md-al-r)}" +
    "#vy-md .md-welcome svg{flex:none;margin-top:2px;color:var(--md-accent)}" +
    "#vy-md .md-welcome b{display:block;font-size:15px;line-height:1.3;margin-bottom:2px}" +
    "#vy-md .md-welcome span{color:var(--md-al-fg);font-size:13.5px}" +
    "#vy-md .md-tabrow{position:relative;display:flex;justify-content:center;align-items:center;height:calc(var(--md-bh,32px) + 8px)}" +
    "#vy-md .md-tab{position:relative;display:inline-flex;align-items:center;justify-content:center;gap:8px;white-space:nowrap;height:var(--md-bh);padding:0 var(--md-bp);border:1px solid var(--md-bbd);border-radius:var(--md-br);background:var(--md-bbg);color:var(--md-bfg);cursor:pointer;font:var(--md-bfw) 14px/1 var(--md-font);letter-spacing:var(--md-bls);box-shadow:none;transition:background .15s}" +
    "#vy-md .md-tab svg{flex:none;width:16px;height:16px}" +
    "#vy-md .md-tab span{display:inline-flex;align-items:center;gap:8px}" +
    "#vy-md .md-tab i{display:inline-block;width:7px;height:7px;border-right:1.8px solid currentColor;border-bottom:1.8px solid currentColor;transform:translateY(-2px) rotate(45deg);transition:transform .2s}" +
    "#vy-md.open .md-tab i{transform:translateY(1px) rotate(225deg)}" +
    "#vy-md.wait .md-tab{cursor:progress;opacity:.6}#vy-md.wait .md-tab i{width:9px;height:9px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;transform:none;animation:vymdspin .8s linear infinite}@keyframes vymdspin{to{transform:rotate(360deg)}}#vy-md.wait .md-panel{display:none}" +
    "#vy-md .md-tab:hover{background:var(--md-bhv)}#vy-md .md-tab:focus-visible{outline:2px solid var(--md-bbg);outline-offset:3px}" +
    "#vy-md .md-line{pointer-events:none;position:absolute;left:0;right:0;top:0;border-top:1px solid var(--md-line)}" +
    "#vy-md .vy-nano-video{display:flex;flex-wrap:wrap;gap:16px;align-items:stretch}" +
    /* native look per cloud: AWS Cloudscape, Google Material, Azure Fluent */
    "#vy-md.c-aws{--md-font:'Open Sans','Helvetica Neue',Roboto,Arial,sans-serif;--md-fg:#0f141a;--md-line:#c6c6cd;--md-accent:#0972d3;--md-al-bg:#f2f8fd;--md-al-bd:#0972d3;--md-al-fg:#0f141a;--md-al-r:12px;--md-al-bw:2px}" +
    "#vy-md.c-aws{--md-bh:32px;--md-bp:20px;--md-br:20px;--md-bbg:#0972d3;--md-bhv:#033160;--md-bbd:#0972d3;--md-bfg:#fff;--md-bfw:700;--md-bls:0;--md-bsh:none}" +
    "#vy-md.c-gcp{--md-bh:36px;--md-bp:20px;--md-br:18px;--md-bbg:#0b57d0;--md-bhv:#0a4cb8;--md-bbd:#0b57d0;--md-bfg:#fff;--md-bfw:500;--md-bls:.01em;--md-bsh:none}" +
    "#vy-md.c-azure{--md-bh:32px;--md-bp:16px;--md-br:4px;--md-bbg:#0f6cbd;--md-bhv:#115ea3;--md-bbd:#0f6cbd;--md-bfg:#fff;--md-bfw:600;--md-bls:0;--md-bsh:none}" +
    "#vy-md.c-gcp{--md-font:'Google Sans Text','Google Sans',Roboto,'Segoe UI','Helvetica Neue',Arial,sans-serif;--md-fg:#1f1f1f;--md-line:#c4c7c5;--md-bg:#fff;--md-accent:#0b57d0;--md-al-bg:#e5f6fd;--md-al-bd:transparent;--md-al-fg:#014361;--md-al-r:8px;--md-al-bw:0px;--md-shadow:none}" +
    "#vy-md.c-gcp .md-welcome svg{color:#0288d1}#vy-md.c-gcp .md-welcome b{font-weight:500;color:#014361}" +
    "#vy-md.c-azure{--md-font:'Segoe UI','Segoe UI Web (West European)',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',sans-serif;--md-fg:#242424;--md-line:#e0e0e0;--md-accent:#0f6cbd;--md-al-bg:#f5f5f5;--md-al-bd:#e0e0e0;--md-al-fg:#424242;--md-al-r:4px;--md-al-bw:1px;--md-shadow:none}" +
    "#vy-md.c-azure .md-welcome svg{color:#0f6cbd}#vy-md.c-azure .md-welcome b{font-weight:600}" +
    "#vy-md,#vy-md *{box-shadow:none!important;text-shadow:none!important}#vy-md{filter:none!important}" +
    /* content column of each console, so the drawer lines up with the page below it: --md-cw = widest content, --md-px = side inset */
    "#vy-md.c-aws{--md-cw:1280px;--md-px:24px}" +
    "#vy-md.c-azure{--md-cw:1052px;--md-px:24px}" +
    "#vy-md.c-gcp{--md-cw:996px;--md-px:72px}" +
    /* AWS service pages (S3, DynamoDB, ...) put a side navigation beside the content: the section is the nav + content frame, edge to
       edge with the console's 24px gutters, not the 1280px centred column of Home. The class is toggled by place(). */
    "#vy-md.c-aws.nav .md-body{max-width:none;padding-left:var(--md-pl,24px);padding-right:var(--md-pr,24px)}" +
    /* AWS service page with the side navigation open and the drawer collapsed: the tab row must not take height, or the nav's vertical
       divider starts 40px below the header. The tab hangs from the top edge of the page instead (the row is 0px tall). */
    "#vy-md.c-aws.nav:not(.open) .md-tabrow{height:0}" +
    "#vy-md.c-aws.nav:not(.open) .md-tab{position:absolute;top:0;left:50%;transform:translateX(-50%);height:var(--md-bh);z-index:5}" +
    /* GCP service page (left nav present): the drawer spans nav + content like the section below it (16px gutters), and a collapsed drawer
       hangs from the header instead of reserving a 44px row above the nav (which cut the nav's top). */
    "#vy-md.c-gcp.nav .md-body{max-width:none;padding-left:16px;padding-right:16px}" +
    /* Azure: every page except the home dashboard is a service page: the drawer runs edge to edge with the page's own 20px gutters */
    "#vy-md.c-azure.nav .md-body{max-width:none;padding-left:20px;padding-right:20px}" +
    "#vy-md.c-gcp.nav:not(.open) .md-tabrow{height:0}" +
    "#vy-md.c-gcp.nav:not(.open) .md-tab{position:absolute;top:0;left:50%;transform:translateX(-50%);height:var(--md-bh);z-index:5}" +
    "@media(max-width:687px){#vy-md.c-aws{--md-px:20px}}" +
    "@media(min-width:600px) and (max-width:899px){#vy-md.c-gcp{--md-px:40px}}" +
    "@media(max-width:599px){#vy-md.c-gcp{--md-px:24px}}" +
    "@media(max-width:700px){#vy-md .md-tab{padding:0 12px}}";

  function header() { return document.querySelector(HEADER[CLOUD] || "header"); }
  var box, open = LS("g") !== "0";   // default EXPANDED; only a user's explicit collapse ("0") is remembered
  // The Nano backend (Pyodide) boots on the page's main thread for several seconds after load, during which no click is handled anywhere.
  // Until it finishes ("vyomi-nano-ready") the tab shows a spinner and ignores clicks, instead of looking clickable but dead.
  var ready = !!window.__vyNanoReady;
  addEventListener("vyomi-nano-ready", function () { ready = true; if (box) box.classList.remove("wait"); });
  setTimeout(function () { ready = true; if (box) box.classList.remove("wait"); }, 45000);

  function build() {
    var st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
    var w = WELCOME[CLOUD] || WELCOME.aws;
    box = document.createElement("div"); box.id = "vy-md"; box.className = "c-" + CLOUD + (open ? " open" : "") + (ready ? "" : " wait");
    box.innerHTML =
      '<div class="md-panel" role="region" aria-label="Vyomi Mesh"><div class="md-clip"><div class="md-body">' +
        '<div class="md-welcome"><svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 7.2v4M8 4.7v.3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>' +
          '<div><b>' + w[0] + '</b><span>' + w[1] + '</span></div></div>' +
        '<div class="vy-nano-video"></div>' +
      '</div></div></div>' +
      '<div class="md-tabrow">' +
        '<button type="button" class="md-tab" aria-expanded="' + open + '" title="Vyomi Mesh: welcome, how it works, Global Mesh">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2L4 14h7l-1 8 9-12h-7z" fill="currentColor"/></svg>' +
          '<span>Vyomi Mesh<i></i></span></button></div>';
    place();
    var row = box.querySelector(".vy-nano-video");
    if (typeof window.vyVideoBanner === "function") row.appendChild(window.vyVideoBanner(CLOUD));
    box.querySelector(".md-tab").onclick = function () {
      if (!ready) return;
      open = !open; box.classList.toggle("open", open); this.setAttribute("aria-expanded", open); LS("s", open ? "1" : "0");
    };
    addEventListener("resize", place);
    addEventListener("hashchange", function () { setTimeout(place, 150); setTimeout(place, 900); });
    if (window.ResizeObserver) { var ro = new ResizeObserver(publish); ro.observe(box); }
    publish();
    setInterval(place, 1500);   // React can re-create the header after us: keep the drawer right behind it
  }
  // The drawer lives in the page flow: first element after the console header (or first in <body> when there is no header). It
  // takes real height, so the console below is pushed down (AWS: the page grows; GCP / Azure: the flex-1 content area shrinks).
  function place() {
    if (!box) return;
    var h = header();
    if (h && h.parentNode) { if (h.nextElementSibling !== box) h.parentNode.insertBefore(box, h.nextSibling); }
    else if (box.parentNode !== document.body) document.body.insertBefore(box, document.body.firstChild);
    if (CLOUD === "aws") {   // side navigation open -> the drawer spans the whole section (nav + content), like the page below it
      var nv = document.querySelector('[class*="awsui_navigation-container"]');
      var on = !!(nv && nv.getBoundingClientRect().width > 40);
      if (box.classList.contains("nav") !== on) box.classList.toggle("nav", on);
      // the page content column is centred and capped (1280px) on wide windows: end the drawer at the column's right edge (the breadcrumb
      // row spans it), not at the window edge, so the drawer lines up with the cards below it. Falls back to the 24px gutter.
      // When the column is capped (wide window: it floats clear of the nav) the drawer takes the column's left edge too, so it is exactly as
      // wide as the section below it; on narrower windows the column runs from the nav to the edge and the drawer keeps the nav's gutter.
      var bc = on && document.querySelector('main [class*="awsui_breadcrumbs_"]'), pr = 24, pl = 24;
      if (bc) {
        var bb = bc.getBoundingClientRect(); if (bb.right > 300) pr = Math.max(24, Math.round(document.documentElement.clientWidth - bb.right));
        if (bb.width >= 1270 && bb.left > 330) pl = Math.round(bb.left);
      }
      if (box.style.getPropertyValue("--md-pr") !== pr + "px") box.style.setProperty("--md-pr", pr + "px");
      if (box.style.getPropertyValue("--md-pl") !== pl + "px") box.style.setProperty("--md-pl", pl + "px");
      // Console Home (no side nav): the content column is capped at 1280px up to ~2000px and 1620px beyond it, so take the real width of
      // the page's content wrapper instead of the fixed 1280px.
      var cw = 1280;
      if (!on) document.querySelectorAll("main > div").forEach(function (d) {
        var hw = Math.round(d.getBoundingClientRect().width); if (cw === 1280 && hw >= 600 && hw <= 2400) cw = hw;
      });
      if (box.style.getPropertyValue("--md-cw") !== cw + "px") box.style.setProperty("--md-cw", cw + "px");
    }
    if (CLOUD === "azure") {   // service page = any route but the home dashboard
      var az = location.hash.replace(/^#\/?/, "").replace(/^home$/, "") !== "";
      if (box.classList.contains("nav") !== az) box.classList.toggle("nav", az);
    }
    if (CLOUD === "aws") {   // Console Home (no side nav): the content column is 1280px up to ~2000px wide and 1620px beyond; follow it
      var cw = 1280;
      if (!box.classList.contains("nav")) document.querySelectorAll("main > div").forEach(function (d) {
        var hw = Math.round(d.getBoundingClientRect().width); if (cw === 1280 && hw >= 600 && hw <= 2400) cw = hw;
      });
      if (box.style.getPropertyValue("--md-cw") !== cw + "px") box.style.setProperty("--md-cw", cw + "px");
    }
    if (CLOUD === "gcp") {   // GCP service pages have a left nav (expanded 256px or collapsed 64px rail): same nav mode as AWS
      var gn = document.querySelector("nav.MuiBox-root");
      var gon = !!(gn && gn.getBoundingClientRect().width > 40);
      if (box.classList.contains("nav") !== gon) box.classList.toggle("nav", gon);
    }
    publish();
  }
  function publish() { if (box) document.documentElement.style.setProperty("--mesh-drawer-h", box.offsetHeight + "px"); }
  function init() {
    if (document.getElementById("vy-md")) return;
    var tries = 0;
    (function wait() { if (header() || tries++ > 60) build(); else setTimeout(wait, 250); })();
  }
  if (document.body) init(); else addEventListener("DOMContentLoaded", init);
})();
