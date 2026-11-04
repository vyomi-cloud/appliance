/* Closable "Download Vyomi" card shown next to the bottom drawer (Nano consoles) and bottom-right in the
   enterprise admin shell. Black & white. Closing collapses it to a round download icon above the disclaimer icon; clicking the icon expands it again. */
(function () {
  if (window.__vyDlCard) return; window.__vyDlCard = 1;
  var KEY = 'vyomi.dlCardClosed';
  if (/\/downloads/.test(location.pathname) || /[?&]embed=1/.test(location.search)) return;
  function go() {
    var st = document.createElement('style');
    st.textContent =
      '#vy-dl{position:fixed;z-index:69;bottom:66px;right:18px;box-sizing:border-box;padding:10px 30px 10px 14px;background:#fff;color:#18181b;border:1px solid #d4d4d8;border-radius:8px;box-shadow:0 4px 18px rgba(0,0,0,.18);z-index:9997 !important;font:12px/1.35 Inter,system-ui,sans-serif;white-space:nowrap}' +
            '#vy-dl a.dl{display:block;color:#0a0a0a;font-weight:700;font-size:14px;text-decoration:none}#vy-dl a.dl:hover{text-decoration:underline}#vy-dl .rn{display:block;color:#52525b;font-size:12px;margin-top:2px;text-decoration:none}' +
      '#vy-dl button{position:absolute;top:6px;right:6px;width:20px;height:20px;border:0;border-radius:6px;background:none;color:#0a0a0a;cursor:pointer;font-size:18px;line-height:1;padding:0}' +
      '#vy-dl button:hover{background:#f4f4f5;color:#0a0a0a}' +
      '#vy-dl.min{display:none}' +
      '#vy-dl-ic.hdr{width:34px;height:34px;flex:none;border:1px solid #e4e4e7;border-radius:10px;background:#fff;color:#27272a;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;margin-right:10px}#vy-dl-ic.hdr svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}#vy-dl-ic.hdr:hover{background:#f4f4f5}' +
      '#vy-dl-ic.flt{position:fixed;right:12px;bottom:60px;z-index:9998;width:30px;height:30px;border:1px solid #d4d4d8;border-radius:50%;background:#fff;color:#52525b;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0}#vy-dl-ic.flt svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}' +
      /* ripple on the download icon: 3 pulses once per session (never a loop); calm while the card is open and for reduced-motion users */
      '#vy-dl-ic{position:relative}' +
      '#vy-dl-ic.rip::before,#vy-dl-ic.rip::after{content:"";position:absolute;inset:0;border-radius:inherit;border:1px solid currentColor;opacity:0;pointer-events:none;animation:vy-dl-rip 2s ease-out 3}' +
      '#vy-dl-ic.rip::after{animation-delay:1s}' +
      '#vy-dl-ic.open::before,#vy-dl-ic.open::after{animation:none}' +
      '@keyframes vy-dl-rip{0%{transform:scale(.95);opacity:.4}100%{transform:scale(1.25);opacity:0}}' +
      '@media(prefers-reduced-motion:reduce){#vy-dl-ic.rip::before,#vy-dl-ic.rip::after{animation:none}}' +
      '@media(max-width:700px){#vy-dl{display:none}}';
    document.head.appendChild(st);
    var d = document.createElement('div'); d.id = 'vy-dl'; d.setAttribute('role', 'complementary');
    d.innerHTML = '<a class="dl" href="/downloads" target="_blank" rel="noopener">Download Pro / Max</a>' +
      '<span class="rn">Offline Simulator</span>' +
      '<button type="button" aria-label="Close">&times;</button>';
    document.body.appendChild(d);
    function mode(min) { d.classList.toggle('min', min); var i = document.getElementById('vy-dl-ic'); if (i) i.classList.toggle('open', !min);  try { sessionStorage.setItem(KEY, min ? '1' : '0'); } catch (_) {} if (!min) place(); }
    d.querySelector('button').onclick = function (e) { e.stopPropagation(); mode(true); };
    function tog() { if (d.classList.contains('min')) { var nb = document.querySelector('.sim-bar'); if (nb) nb.remove(); mode(false); } else mode(true); }  // one expanded card at a time
    // Start collapsed if the user collapsed it this session, or while the first-visit notice is showing (don't stack).
    var was = false, seen = false; try { was = sessionStorage.getItem(KEY) === '1'; seen = sessionStorage.getItem('vyomi.simNoticeSeen') === '1'; } catch (_) {}
    if (was || navigator.webdriver || (!seen && !/\/admin/.test(location.pathname))) d.classList.add('min');   // collapsed under UI tests
    // The download icon lives in the bottom drawer (right end, after the info icon); admin pages have no drawer,
    // so it goes into the header's right cluster there, else floats.
    var ic = document.createElement('button'); ic.type = 'button'; ic.className = 'vy-exp vy-ic'; ic.id = 'vy-dl-ic'; ic.style.order = '3'; ic.title = 'Download Vyomi'; ic.setAttribute('aria-label', 'Download Vyomi');
    ic.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>';
    ic.onclick = tog;
    document.addEventListener('click', function (e) { if (e.target.closest && e.target.closest('.vy-ic:not(#vy-dl-ic)') && !d.classList.contains('min')) mode(true); }, true);
    document.addEventListener('click', function (e) { if (e.target.closest && e.target.closest('#disk-widget-slot .disk-chip') && !d.classList.contains('min')) mode(true); }, true);
    ic.classList.toggle('open', !d.classList.contains('min'));
    var played = false; try { played = sessionStorage.getItem('vyomi.dlRip') === '1'; } catch (_) {}
    // the flag is set when the pulses FINISH (Nano's service worker can reload the page right after first load)
    if (!played) { ic.classList.add('rip'); setTimeout(function () { ic.classList.remove('rip'); try { sessionStorage.setItem('vyomi.dlRip', '1'); } catch (_) {} }, 6500); }
    var tries = 0;
    (function mount() {
      var n = document.querySelector('#vy-appbar .vy-notch');
      if (n) { n.appendChild(ic); place(); return; }
      if (tries++ < 20) return setTimeout(mount, 250);
      var tb = document.querySelector('.topbar');
      if (tb) { ic.classList.add('hdr'); tb.insertBefore(ic, tb.lastElementChild); }
      else { ic.classList.add('flt'); document.body.appendChild(ic); }
    })();
    // Nano: sit right beside the drawer (to the right of its notch), on the drawer's baseline.
    function place() {
      var n = document.querySelector('#vy-appbar .vy-notch'); if (!n || d.classList.contains('min')) return;
      var r = n.getBoundingClientRect();
      d.style.left = 'auto'; d.style.right = Math.max(12, innerWidth - r.right) + 'px'; d.style.bottom = (innerHeight - r.top + 12) + 'px';
    }
    place(); addEventListener('resize', place); setTimeout(place, 800); setTimeout(place, 2500);
    var nn = document.querySelector('#vy-appbar .vy-notch'); if (nn && window.ResizeObserver) new ResizeObserver(place).observe(nn);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
})();
