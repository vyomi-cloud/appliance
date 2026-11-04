/* Simulated-console disclaimer. Two parts:
 *  1. A small chip that is ALWAYS visible ("Simulated console") and re-opens the full notice on click.
 *  2. The full notice, shown at the start of every browser session (sessionStorage), and whenever the chip is clicked.
 * Nothing is sent anywhere. */
(function () {
  var SS = function (m, k, v) { try { return m === "g" ? sessionStorage.getItem(k) : sessionStorage.setItem(k, v); } catch (_) { return null; } };
  var KEY = "vyomi.simNoticeSeen";
  var css = ".sim-bar{position:fixed;left:50%;bottom:72px;transform:translateX(-50%);z-index:9999;display:flex;align-items:center;gap:16px;max-width:680px;width:calc(100% - 32px);padding:12px 16px;background:#fff;color:#18181b;border:1px solid #d4d4d8;border-radius:8px;font:13px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.18)}" +
    ".sim-bar a{color:#18181b;text-decoration:underline}.sim-bar button{flex:none;padding:7px 18px;background:#000;color:#fff;border:1px solid #000;border-radius:6px;font:600 13px inherit;cursor:pointer}.sim-bar button:hover{background:#27272a}" +
    ".sim-chip{position:fixed;right:12px;bottom:52px;z-index:9998;display:flex;align-items:center;justify-content:center;width:30px;height:30px;padding:0;background:#fff;color:#52525b;border:1px solid #d4d4d8;border-radius:50%;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.15)}.sim-chip:hover,.sim-chip:focus{color:#000;border-color:#000;outline:none}.sim-chip svg{width:17px;height:17px}.sim-chip i{position:absolute;top:-1px;right:-1px;width:8px;height:8px;border-radius:50%;background:#f59e0b;border:1.5px solid #fff}" +
    "@media(max-width:560px){.sim-bar{flex-direction:column;align-items:stretch;gap:10px}}";
  function notice() {
    if (document.querySelector(".sim-bar")) return;
    var d = document.createElement("div"); d.className = "sim-bar"; d.setAttribute("role", "region"); d.setAttribute("aria-label", "Simulator notice");
    d.innerHTML = '<span><strong>Simulated console.</strong> This is an independent re-creation built for a near-real experience, not the provider\'s console. Some screens, fields or features may be missing or behave differently. Use it at your own discretion and verify anything critical on the real cloud. <a href="/terms#simulated-consoles" target="_blank" rel="noopener">Terms</a></span><button type="button">OK</button>';
    d.querySelector("button").onclick = function () { SS("s", KEY, "1"); d.remove(); };
    document.body.appendChild(d);
    // Centered (css: left 50% + translateX), 12px above the drawer — same gap as the download card.
    var n = document.querySelector("#vy-appbar .vy-notch");
    if (n) { var r = n.getBoundingClientRect(); d.style.bottom = (innerHeight - r.top + 12) + "px"; }
  }
  function toggle() { var b = document.querySelector(".sim-bar"); if (b) b.remove(); else notice(); }   // info icon: click shows, click again hides
  document.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("#disk-widget-slot .disk-chip")) { var b = document.querySelector(".sim-bar"); if (b) b.remove(); } }, true);
  function init() {
    if (document.querySelector(".sim-chip")) return;
    var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    var c = document.createElement("div"); c.className = "sim-chip"; c.setAttribute("role", "button"); c.tabIndex = 0;
    c.title = "Simulated console. Behaviour may differ from the real cloud. Click for details."; c.setAttribute("aria-label", "Simulated console: behaviour may differ from the real cloud");
    c.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.8" r=".6" fill="currentColor"/></svg><i></i>';
    c.onclick = toggle; c.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") toggle(); };
    // The info icon lives in the bottom drawer (right end, after the expand arrow); floats only where there is no drawer.
    var ib = document.createElement("button"); ib.type = "button"; ib.className = "vy-exp vy-ic"; ib.style.order = "2"; ib.title = "Simulated console: behaviour may differ from the real cloud";
    ib.setAttribute("aria-label", ib.title); ib.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.8" r=".6" fill="currentColor"/></svg>'; ib.onclick = toggle;
    var tries = 0;
    (function mount() {
      var n = document.querySelector("#vy-appbar .vy-notch");
      if (n) n.appendChild(ib); else if (tries++ < 40) setTimeout(mount, 250); else document.body.appendChild(c);
    })();
    if (!SS("g", KEY) && !navigator.webdriver) setTimeout(notice, 1500);   // never in the way of UI tests
  }
  if (document.body) init(); else addEventListener("DOMContentLoaded", init);
})();
