/* "Vyomi Mesh" drawer for the Nano consoles (AWS / GCP / Azure): one expandable, collapsible drawer that hangs from the console header.
 * It holds what used to sit on the Home page: the "Welcome to the ..." banner, the "How Vyomi <cloud> works" video banner and the
 * Vyomi Global Mesh card. The video banner comes from nano-video.js; the Mesh card (mesh-widget.js) joins the `.vy-nano-video` row on its own.
 * Open/closed is remembered per cloud. Cloud = data-cloud on this script tag. */
(function () {
  "use strict";
  var me = document.currentScript, CLOUD = (me && me.getAttribute("data-cloud")) || "";
  var KEY = "vyomi.meshDrawer." + CLOUD;
  var HEADER = { aws: "#vyomi-top", gcp: "header", azure: "header.vy-top" };
  var WELCOME = {
    aws:   ["Welcome to the Vyomi AWS console", "Everything here runs against your local Vyomi simulator, using the same native APIs your SDKs and CLI call. Features Vyomi doesn’t simulate are marked."],
    gcp:   ["Welcome to Vyomi Google Cloud", "Everything in this console runs against your local Vyomi simulator — the same native APIs gcloud, gsutil and the client libraries call. Products without a v4 page open in the classic Vyomi console."],
    azure: ["Welcome to Vyomi Azure", "Everything in this portal runs against your local Vyomi simulator — the same native APIs az, the SDKs and ARM templates call. Features Vyomi doesn’t simulate are marked."]
  };
  var LS = function (m, v) { try { return m === "g" ? localStorage.getItem(KEY) : localStorage.setItem(KEY, v); } catch (_) { return null; } };

  var CSS =
    "#vy-md{position:fixed;left:0;right:0;z-index:1400;pointer-events:none;font:14px/1.45 var(--md-font);color:var(--md-fg);--md-font:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;--md-fg:#16191f;--md-line:#d5dbdb;--md-bg:#fff;--md-accent:#0972d3;--md-al-bg:#f1faff;--md-al-bd:#0972d3;--md-al-fg:#414d5c;--md-al-r:10px;--md-al-bw:1px;--md-shadow:0 14px 28px -14px rgba(0,0,0,.35)}" +
    "#vy-md .md-panel{pointer-events:auto;display:grid;grid-template-rows:0fr;background:var(--md-bg);border-bottom:1px solid var(--md-line);transition:grid-template-rows .25s ease,box-shadow .25s ease}" +
    "#vy-md.open .md-panel{grid-template-rows:1fr;box-shadow:var(--md-shadow)}" +
    "#vy-md .md-clip{overflow:hidden;min-height:0}" +
    "#vy-md .md-body{box-sizing:border-box;max-width:1320px;margin:0 auto;padding:16px 24px 18px;max-height:calc(100vh - 150px);overflow:auto}" +
    "#vy-md:not(.open) .md-body{visibility:hidden}" +
    "#vy-md .md-welcome{display:flex;gap:12px;align-items:flex-start;margin:0 0 14px;padding:12px 16px;background:var(--md-al-bg);border:var(--md-al-bw) solid var(--md-al-bd);border-radius:var(--md-al-r)}" +
    "#vy-md .md-welcome svg{flex:none;margin-top:2px;color:var(--md-accent)}" +
    "#vy-md .md-welcome b{display:block;font-size:15px;line-height:1.3;margin-bottom:2px}" +
    "#vy-md .md-welcome span{color:var(--md-al-fg);font-size:13.5px}" +
    "#vy-md .md-tabrow{position:relative;height:0}" +
    "#vy-md .md-tab{pointer-events:auto;position:absolute;left:50%;top:8px;transform:translateX(-50%);display:inline-flex;align-items:center;justify-content:center;gap:8px;white-space:nowrap;height:var(--md-bh);padding:0 var(--md-bp);border:1px solid var(--md-bbd);border-radius:var(--md-br);background:var(--md-bbg);color:var(--md-bfg);cursor:pointer;font:var(--md-bfw) 14px/1 var(--md-font);letter-spacing:var(--md-bls);box-shadow:var(--md-bsh);transition:background .15s,box-shadow .15s}" +
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
    "#vy-md.c-gcp{--md-bh:36px;--md-bp:20px;--md-br:18px;--md-bbg:#0b57d0;--md-bhv:#0a4cb8;--md-bbd:#0b57d0;--md-bfg:#fff;--md-bfw:500;--md-bls:.01em;--md-bsh:0 1px 2px rgba(60,64,67,.3),0 1px 3px 1px rgba(60,64,67,.15)}" +
    "#vy-md.c-azure{--md-bh:32px;--md-bp:16px;--md-br:4px;--md-bbg:#0f6cbd;--md-bhv:#115ea3;--md-bbd:#0f6cbd;--md-bfg:#fff;--md-bfw:600;--md-bls:0;--md-bsh:none}" +
    "#vy-md.c-gcp{--md-font:'Google Sans Text','Google Sans',Roboto,'Segoe UI','Helvetica Neue',Arial,sans-serif;--md-fg:#1f1f1f;--md-line:#c4c7c5;--md-bg:#fff;--md-accent:#0b57d0;--md-al-bg:#e5f6fd;--md-al-bd:transparent;--md-al-fg:#014361;--md-al-r:8px;--md-al-bw:0px;--md-shadow:0 6px 10px 4px rgba(60,64,67,.15),0 2px 3px rgba(60,64,67,.3)}" +
    "#vy-md.c-gcp .md-welcome svg{color:#0288d1}#vy-md.c-gcp .md-welcome b{font-weight:500;color:#014361}" +
    "#vy-md.c-azure{--md-font:'Segoe UI','Segoe UI Web (West European)',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',sans-serif;--md-fg:#242424;--md-line:#e0e0e0;--md-accent:#0f6cbd;--md-al-bg:#f5f5f5;--md-al-bd:#e0e0e0;--md-al-fg:#424242;--md-al-r:4px;--md-al-bw:1px;--md-shadow:0 8px 16px rgba(0,0,0,.14),0 0 2px rgba(0,0,0,.12)}" +
    "#vy-md.c-azure .md-welcome svg{color:#0f6cbd}#vy-md.c-azure .md-welcome b{font-weight:600}" +
    "@media(max-width:700px){#vy-md .md-tab{padding:0 12px}}";

  function header() { return document.querySelector(HEADER[CLOUD] || "header"); }
  var box, open = LS("g") === "1";
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
    document.body.appendChild(box);
    var row = box.querySelector(".vy-nano-video");
    if (typeof window.vyVideoBanner === "function") row.appendChild(window.vyVideoBanner(CLOUD));
    box.querySelector(".md-tab").onclick = function () {
      if (!ready) return;
      open = !open; box.classList.toggle("open", open); this.setAttribute("aria-expanded", open); LS("s", open ? "1" : "0");
    };
    place();
    addEventListener("resize", place);
    if (window.ResizeObserver && header()) new ResizeObserver(place).observe(header());
    setInterval(place, 1500);   // the header can mount after us (React) or change height with the viewport
  }
  function place() {
    var h = header(); if (!h || !box) return;
    var b = Math.round(h.getBoundingClientRect().bottom);
    if (box.style.top !== b + "px") box.style.top = b + "px";
  }
  function init() {
    if (document.getElementById("vy-md")) return;
    var tries = 0;
    (function wait() { if (header() || tries++ > 60) build(); else setTimeout(wait, 250); })();
  }
  if (document.body) init(); else addEventListener("DOMContentLoaded", init);
})();
