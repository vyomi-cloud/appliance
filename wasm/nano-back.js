/* "← Dashboard" back button for enterprise users who entered the cloud console from the enterprise dashboard
   (admin side menu → Cloud links here with ?from=dashboard). The flag is kept for the browser session so it stays
   across clouds.html → console navigation. In a console it sits at the left end of the bottom drawer; on the
   Spaces page (no drawer) it is a small pill at the top-left. Skipped inside embedded views. */
(function () {
  if (/[?&]embed=1/.test(location.search) || window.__vyBack) return; window.__vyBack = 1;
  var K = 'vyomi.fromDash', on = false;
  try {
    if (/[?&]from=dashboard\b/.test(location.search)) sessionStorage.setItem(K, '1');
    on = sessionStorage.getItem(K) === '1';
  } catch (_) {}
  if (!on) return;
  var st = document.createElement('style');
  st.textContent =
    '#vy-appbar .vy-notch a.vy-back{order:-1;font-weight:600;color:#fff;margin-right:4px}' +
    'a.vy-back.flt{position:fixed;top:12px;left:12px;z-index:9999;display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 14px;background:#fff;color:#0a0a0a;border:1px solid #d4d4d8;border-radius:8px;font:600 13px Inter,system-ui,sans-serif;text-decoration:none;box-shadow:0 4px 18px rgba(0,0,0,.18)}' +
    'a.vy-back.flt:hover{background:#f4f4f5}' +
    'html.vy-pickopen body>a#vy-back.flt{visibility:visible !important}';   /* the Spaces picker hides every other body child */
  document.head.appendChild(st);
  var a = document.createElement('a'); a.className = 'vy-back'; a.id = 'vy-back'; a.href = '/admin/cloud'; a.title = 'Back to the Cloud page in the dashboard';
  a.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><path d="M19 12H5M12 19l-7-7 7-7"/></svg><span>Dashboard</span>';
  var tries = 0;
  (function mount() {
    var spaces = /clouds\.html/.test(location.pathname), n = spaces ? null : document.querySelector('#vy-appbar .vy-notch');   // Spaces page: its drawer is hidden
    if (n) { n.insertBefore(a, n.firstChild); return; }
    if (!spaces && tries++ < 16) return setTimeout(mount, 250);
    a.classList.add('flt'); document.body.appendChild(a);
  })();
})();
