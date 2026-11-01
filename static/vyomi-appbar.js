/* vyomi-appbar.js — shared "notch" bar for the cloud consoles (MOCK).
 *   ───────────╲  ⌂ Spaces · Health · Knowledge · SDK&CLI · API  ╱───────────
 * A thin strip above each console's own header; the centre drops into a notch that
 * holds the appliance icons. The cloud is chosen by which space you open, so there are
 * no cloud icons here — only a read-only "Cloud: X" label. Include with:
 *   <script src="/vyomi-appbar.js" data-cloud="gcp" defer></script>
 */
(function () {
  var s = document.currentScript;
  var cloud = (s && s.getAttribute('data-cloud')) || 'aws';
  var NAMES = { aws: 'AWS', gcp: 'Google Cloud', azure: 'Azure' };
  var ITEMS = [
    ['spaces', 'Spaces', 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5'],
    ['workspace', 'Health', 'M3 3v18h18M7 12h3v6H7zM12 8h3v10h-3zM17 4h3v14h-3z'],
    ['kc', 'Knowledge Center', 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'],
    ['usage', 'SDK & CLI usage', 'M4 17l6-6-6-6M12 19h8'],
    ['api', 'API reference', 'M16 18l6-6-6-6M8 6l-6 6 6 6']
  ];
  var css = '' +
    '#vy-appbar{position:relative;z-index:70;height:30px;background:#0f121c;border-bottom:1px solid rgba(255,255,255,.10);display:flex;justify-content:center;font-family:Inter,system-ui,sans-serif}' +
    '#vy-appbar .vy-cloud{position:absolute;left:14px;top:0;height:30px;display:flex;align-items:center;gap:6px;font-size:12px;color:#9aa0b4}' +
    '#vy-appbar .vy-cloud b{color:#e4e4e7;font-weight:600}' +
    '#vy-appbar .vy-notch{height:44px;margin-top:0;padding:0 34px 0 34px;display:flex;align-items:center;gap:2px;background:#0f121c;' +
      'clip-path:polygon(0 0,100% 0,calc(100% - 22px) 100%,22px 100%);border-bottom:2px solid #4d8cf3;position:relative;top:0}' +
    '#vy-appbar .vy-notch a{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 10px;border-radius:8px;color:#b4b8cc;font-size:12px;text-decoration:none;white-space:nowrap}' +
    '#vy-appbar .vy-notch a:hover{background:rgba(255,255,255,.08);color:#fff}' +
    '#vy-appbar .vy-notch a svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}' +
    '#vy-appbar .vy-notch a.on{background:rgba(77,140,243,.18);color:#fff}' +
    '@media(max-width:900px){#vy-appbar .vy-notch a span{display:none}#vy-appbar .vy-cloud{display:none}}';
  function build() {
    if (document.getElementById('vy-appbar')) return;
    var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    var bar = document.createElement('div'); bar.id = 'vy-appbar';
    var links = ITEMS.map(function (i) {
      return '<a href="/ui#' + i[0] + '" data-v="' + i[0] + '" title="' + i[1] + '"><svg viewBox="0 0 24 24"><path d="' + i[2] + '"/></svg><span>' + i[1] + '</span></a>';
    }).join('');
    bar.innerHTML = '<div class="vy-cloud">Cloud: <b>' + (NAMES[cloud] || cloud) + '</b></div><nav class="vy-notch" aria-label="Appliance">' + links + '</nav>';
    document.body.insertBefore(bar, document.body.firstChild);
  }
  if (document.body) build(); else document.addEventListener('DOMContentLoaded', build);
})();
