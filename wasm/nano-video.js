// "How Nano <cloud> works": a slim banner on each console's Home; the 1-minute video opens in a
// pop-up over the page. The videos ship inside the Nano bundle (assets/videos/). Nothing autoplays;
// dismissing the banner is remembered per cloud and leaves a small link to bring it back.
(function () {
  var COPY = {
    aws:   { title: "How Nano AWS works",          sub: "The tech behind it, and the real AWS CLI talking to this console" },
    gcp:   { title: "How Nano Google Cloud works", sub: "The tech behind it, and the real gcloud CLI talking to this console" },
    azure: { title: "How Nano Azure works",        sub: "The tech behind it, and the real az CLI talking to this portal" }
  };
  var ICON = '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
  function dismissed(cloud) { try { return localStorage.getItem("vyomi.video.dismissed." + cloud) === "1"; } catch (_) { return false; } }
  function setDismissed(cloud, on) { try { on ? localStorage.setItem("vyomi.video.dismissed." + cloud, "1") : localStorage.removeItem("vyomi.video.dismissed." + cloud); } catch (_) {} }

  function play(cloud) {
    if (document.getElementById("vy-video-modal")) return;
    var m = document.createElement("div");
    m.id = "vy-video-modal";
    m.setAttribute("role", "dialog");
    m.setAttribute("aria-label", COPY[cloud].title);
    m.style.cssText = "position:fixed;inset:0;z-index:200000;background:rgba(10,14,28,.72);display:flex;align-items:center;justify-content:center;padding:32px";
    m.innerHTML = '<video controls autoplay playsinline style="display:block;width:min(1100px,92vw);max-height:84vh;aspect-ratio:16/9;border-radius:12px;background:#000;box-shadow:0 30px 80px rgba(0,0,0,.5)" src="assets/videos/' + cloud + '.mp4"></video>'
      + '<button type="button" aria-label="Close video" style="position:absolute;right:22px;top:18px;width:36px;height:36px;border:0;border-radius:50%;background:rgba(255,255,255,.14);color:#fff;font:18px system-ui;cursor:pointer">&#10005;</button>';
    function close() { var v = m.querySelector("video"); if (v) { v.pause(); v.removeAttribute("src"); v.load(); } m.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(e) { if (e.key === "Escape") close(); }
    m.addEventListener("click", function (e) { if (e.target === m || e.target.tagName === "BUTTON") close(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(m);
  }

  window.vyVideoBanner = function (cloud) {
    var c = COPY[cloud], w = document.createElement("div");
    w.className = "vy-video-banner";
    function paint() {
      w.innerHTML = "";
      if (dismissed(cloud)) {
        w.style.cssText = "margin:0 0 12px";
        var a = document.createElement("a");
        a.href = "#"; a.style.cssText = "display:inline-flex;align-items:center;gap:6px;font:600 13px system-ui;color:#0972d3;text-decoration:none";
        a.innerHTML = ICON + c.title + " &middot; 1 min";
        a.onclick = function (e) { e.preventDefault(); setDismissed(cloud, false); paint(); };
        w.appendChild(a);
        return;
      }
      w.style.cssText = "display:flex;align-items:center;gap:14px;margin:0 0 16px;padding:8px 12px 8px 8px;background:#fff;border:1px solid #e4e7ec;border-radius:10px;box-sizing:border-box;color:#16191f";
      w.innerHTML = '<button type="button" data-play aria-label="Play ' + c.title + '" style="position:relative;flex:none;width:96px;height:54px;padding:0;border:0;border-radius:6px;cursor:pointer;background:#000 url(assets/videos/' + cloud + '.jpg) center/cover"><span style="position:absolute;inset:0;display:grid;place-items:center;border-radius:6px;background:rgba(0,0,0,.28);color:#fff">' + ICON.replace(/12/g, "20") + '</span></button>'
        + '<div style="flex:1;min-width:0"><div style="font:600 15px system-ui">' + c.title + '</div><div style="margin-top:2px;font:13px system-ui;color:#5f6b7a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + c.sub + '</div></div>'
        + '<button type="button" data-play style="flex:none;display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border:1px solid #d0d5dd;border-radius:8px;background:#fff;color:#16191f;font:600 13px system-ui;cursor:pointer">' + ICON + 'Watch &middot; 1 min</button>'
        + '<button type="button" data-x aria-label="Dismiss" title="Dismiss" style="flex:none;width:26px;height:26px;border:0;background:none;color:#5f6b7a;font:15px system-ui;cursor:pointer">&#10005;</button>';
      w.querySelectorAll("[data-play]").forEach(function (b) { b.onclick = function () { play(cloud); }; });
      w.querySelector("[data-x]").onclick = function () { setDismissed(cloud, true); paint(); };
    }
    paint();
    return w;
  };
})();
