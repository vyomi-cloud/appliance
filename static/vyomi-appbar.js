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
    '#vy-appbar{position:relative;z-index:70;height:44px;background:#fff;display:flex;justify-content:center;font-family:Inter,system-ui,sans-serif}' +
    '#vy-appbar::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:#0f121c}' +   /* the line:  ------ */
    '#vy-appbar + header{border-top:1px solid #dadce0}' +
    '#vy-appbar .vy-cloud{position:absolute;left:14px;top:10px;display:flex;align-items:center;gap:6px;font-size:12px;color:#667085}' +
    '#vy-appbar .vy-cloud b{color:#101828;font-weight:600}' +
    '#vy-appbar .vy-notch{height:44px;padding:0 44px;display:flex;align-items:center;gap:2px;position:relative;isolation:isolate}' +   /* the dip:  \\____/ */
    '#vy-appbar .vy-notch::before{content:"";position:absolute;inset:0;z-index:-1;background:#0f121c;clip-path:polygon(0 0,100% 0,calc(100% - 30px) 100%,30px 100%)}' +
    '#vy-appbar .vy-notch .vy-sep{width:1px;height:20px;background:rgba(255,255,255,.18);margin:0 6px}' +
    '#vy-appbar #disk-widget-slot{position:relative !important;top:auto !important;right:auto !important;left:auto !important;z-index:5 !important;display:inline-block}' +
    '#vy-appbar #disk-widget-slot .disk-chip{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 10px;font:400 12px Inter,system-ui,sans-serif;border:0 !important;border-radius:8px;background:transparent !important;color:#b4b8cc !important;box-shadow:none !important}' +
    '#vy-appbar #disk-widget-slot .disk-chip:hover,#vy-appbar #disk-widget-slot.open .disk-chip{background:rgba(255,255,255,.08) !important;color:#fff !important}' +
    '#vy-appbar #disk-widget-slot .disk-chip *{color:inherit !important;font:inherit !important}' +
    '#vy-appbar #disk-widget-slot .disk-chip .disk-chip-caret{display:none}' +
    '#vy-appbar #disk-widget-slot .disk-popover{top:calc(100% + 14px) !important;right:auto !important;left:50% !important;transform:translateX(-50%)}' +
    '#vy-appbar .vy-notch a{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 10px;border-radius:8px;color:#b4b8cc;font-size:12px;text-decoration:none;white-space:nowrap}' +
    '#vy-appbar .vy-notch a:hover{background:rgba(255,255,255,.08);color:#fff}' +
    '#vy-appbar .vy-notch a svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}' +
    '#vy-appbar .vy-notch a.on{background:rgba(77,140,243,.18);color:#fff}' +
    '#vy-modal{position:fixed;inset:0;z-index:200;background:rgba(10,12,24,.62);display:none;align-items:center;justify-content:center}' +
    '#vy-modal.open{display:flex}' +
    '#vy-modal .box{width:min(1100px,94vw);height:min(760px,90vh);background:#fff;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.45);display:flex;flex-direction:column;overflow:hidden}' +
    '#vy-modal .hd{display:flex;align-items:center;gap:8px;height:46px;padding:0 10px 0 18px;border-bottom:1px solid #e4e7ec;font:600 15px Inter,system-ui,sans-serif;color:#101828}' +
    '#vy-modal .hd button{margin-left:auto;width:32px;height:32px;border:0;border-radius:50%;background:none;cursor:pointer;font-size:20px;color:#475467}' +
    '#vy-modal .hd button:hover{background:#f2f4f7}' +
    '#vy-modal iframe{flex:1;border:0;width:100%}' +
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
    var disk = document.getElementById('disk-widget-slot');          // the disk-usage chip lives in the drawer too
    if (disk) { var nav = bar.querySelector('.vy-notch'); var sp = document.createElement('span'); sp.className = 'vy-sep'; nav.appendChild(sp); nav.appendChild(disk); }
    var m = document.createElement('div'); m.id = 'vy-modal';
    m.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="vy-modal-t"><div class="hd"><span id="vy-modal-t"></span><button type="button" aria-label="Close">\u2715</button></div><iframe title="Appliance"></iframe></div>';
    document.body.appendChild(m);
    var fr = m.querySelector('iframe');
    function close() { m.classList.remove('open'); fr.removeAttribute('src'); }
    m.addEventListener('click', function (e) { if (e.target === m) close(); });
    m.querySelector('.hd button').addEventListener('click', close);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    bar.querySelector('.vy-notch').addEventListener('click', function (e) {
      var a = e.target.closest('a[data-v]'); if (!a) return;
      e.preventDefault();
      m.querySelector('#vy-modal-t').textContent = a.title;
      fr.src = '/clouds?embed=1#' + a.getAttribute('data-v');
      m.classList.add('open');
    });
  }
  if (document.body) build(); else document.addEventListener('DOMContentLoaded', build);
})();
