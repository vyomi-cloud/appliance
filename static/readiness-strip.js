/* Vyomi appliance readiness strip — persistent backend-status / diagnostics bar.
 *
 * Shown on BOTH the launch page (/) and the workspaces page (/clouds). While the
 * backend containers are still cold-starting it shows weighted pull progress
 * ("Appliance is getting ready — X/Y backends ready", blue, animated). Once every
 * backend is up it STAYS visible as a green "Appliance is Ready" status bar, so
 * the user always has an at-a-glance view of the behind-the-scenes tech stack and
 * can pop the Details panel to see every service + its live status (green = up)
 * for diagnostics.
 *
 * Self-mounting: include with <script src="/assets/readiness-strip.js" defer>.
 * It renders into #vyomi-readiness-mount if that element exists, else prepends a
 * strip to <body>. Polls /api/runtime/readiness — fast while loading, slow once
 * ready (it keeps polling so the live status stays accurate).
 */
(function () {
  'use strict';

  var POLL_LOADING_MS = 3000;   // tight cadence while backends are still booting
  var POLL_READY_MS = 20000;    // slow keep-alive once ready — diagnostics, low cost
  var _timer = null;

  var GRAD_LOADING = 'linear-gradient(90deg,#0ea5e9 0%,#0284c7 100%)';
  var GRAD_READY = 'linear-gradient(90deg,#10b981 0%,#059669 100%)';

  function injectStyles() {
    if (document.getElementById('vyomi-readiness-style')) return;
    var st = document.createElement('style');
    st.id = 'vyomi-readiness-style';
    st.textContent = '@keyframes vyrspin{to{transform:rotate(360deg)}}';
    document.head.appendChild(st);
  }

  function buildStrip() {
    var wrap = document.createElement('div');
    wrap.id = 'vyomi-readiness-strip';
    wrap.style.cssText =
      'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;' +
      'color:#fff; background:' + GRAD_LOADING + '; box-shadow:inset 0 -1px 0 rgba(0,0,0,.12);';
    wrap.innerHTML = [
      '<div style="max-width:1180px; margin:0 auto; padding:10px 18px; display:flex; align-items:center; gap:14px; font-size:13.5px;">',
      '  <span id="vyr-icon" style="display:inline-flex; flex:none;"></span>',
      '  <span id="vyr-title" style="font-weight:600">Appliance is getting ready</span>',
      '  <span id="vyr-summary" style="opacity:.85;">— starting backends…</span>',
      '  <div id="vyr-barwrap" style="flex:1; height:6px; background:rgba(255,255,255,.18); border-radius:3px; overflow:hidden; min-width:140px;">',
      '    <div id="vyr-bar" style="height:100%; width:0%; background:#fff; transition:width .3s ease-out;"></div>',
      '  </div>',
      '  <span id="vyr-spacer" style="flex:1; display:none;"></span>',
      '  <span id="vyr-pct" style="font-variant-numeric:tabular-nums; font-weight:600; min-width:40px; text-align:right;">0%</span>',
      '  <button id="vyr-details-btn" type="button" aria-expanded="false" style="background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.3); color:#fff; padding:3px 10px; border-radius:4px; cursor:pointer; font-size:12px;">Details &#9662;</button>',
      '</div>',
      '<div id="vyr-detail" style="display:none; background:rgba(0,0,0,.18); padding:12px 18px;">',
      '  <div id="vyr-list" style="max-width:1180px; margin:0 auto; display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:8px 16px; font-size:12.5px;"></div>',
      '</div>'
    ].join('');
    var btn = wrap.querySelector('#vyr-details-btn');
    btn.addEventListener('click', function () {
      var p = wrap.querySelector('#vyr-detail');
      var open = p.style.display === 'block';
      p.style.display = open ? 'none' : 'block';
      btn.setAttribute('aria-expanded', String(!open));
      btn.innerHTML = open ? 'Details &#9662;' : 'Details &#9652;';
    });
    return wrap;
  }

  function mount() {
    var existing = document.getElementById('vyomi-readiness-strip');
    if (existing) return existing;
    injectStyles();
    var strip = buildStrip();
    var host = document.getElementById('vyomi-readiness-mount');
    if (host) host.appendChild(strip);
    else document.body.insertBefore(strip, document.body.firstChild);
    return strip;
  }

  function spinnerHTML() {
    return '<span style="display:inline-flex; width:16px; height:16px; border:2px solid rgba(255,255,255,.45);' +
      ' border-top-color:#fff; border-radius:50%; animation:vyrspin .8s linear infinite;"></span>';
  }
  function checkHTML() {
    return '<span style="display:inline-flex; align-items:center; justify-content:center; width:16px; height:16px;' +
      ' border-radius:50%; background:rgba(255,255,255,.28); font-size:11px; font-weight:700; line-height:1;">&#10003;</span>';
  }

  function render(j) {
    var strip = mount();
    var ready = !!j.ready;
    var rc = (j.ready_count != null) ? j.ready_count : 0;
    var tc = (j.total_count != null) ? j.total_count : 0;

    strip.style.background = ready ? GRAD_READY : GRAD_LOADING;
    strip.querySelector('#vyr-icon').innerHTML = ready ? checkHTML() : spinnerHTML();
    strip.querySelector('#vyr-title').textContent = ready ? 'Appliance is Ready' : 'Appliance is getting ready';
    strip.querySelector('#vyr-summary').textContent = ready
      ? '— all ' + tc + ' services running'
      : '— ' + rc + '/' + tc + ' backends ready';

    // Progress bar + pct are only meaningful while loading. When ready, swap the
    // bar for a flexible spacer so the Details button stays right-aligned.
    strip.querySelector('#vyr-barwrap').style.display = ready ? 'none' : 'block';
    strip.querySelector('#vyr-spacer').style.display = ready ? 'block' : 'none';
    strip.querySelector('#vyr-pct').style.display = ready ? 'none' : 'inline';
    if (!ready) {
      strip.querySelector('#vyr-bar').style.width = (j.overall_pct || 0) + '%';
      strip.querySelector('#vyr-pct').textContent = (j.overall_pct || 0) + '%';
    }

    // Detail rows — populated in both states so the panel is always useful.
    var list = strip.querySelector('#vyr-list');
    list.innerHTML = '';
    (j.services || []).forEach(function (s) {
      var up = s.status === 'ready';
      var row = document.createElement('div');
      row.style.cssText = 'display:flex; align-items:center; gap:8px;';
      var dot = document.createElement('span');
      dot.style.cssText = 'width:8px; height:8px; border-radius:50%; flex:none; background:' +
        (up ? '#34d399' : 'rgba(255,255,255,.35)') + ';';
      row.appendChild(dot);
      var name = document.createElement('span');
      name.style.cssText = 'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;';
      name.textContent = s.label || s.name || '';
      row.appendChild(name);
      var tag = document.createElement('span');
      tag.style.cssText = 'margin-left:auto; opacity:.65; font-size:11px; text-transform:uppercase; letter-spacing:.4px;';
      tag.textContent = up ? 'ready' : 'loading…';
      row.appendChild(tag);
      list.appendChild(row);
    });
    return ready;
  }

  function schedule(ms) {
    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(poll, ms);
  }

  function poll() {
    fetch('/api/runtime/readiness', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) { schedule(POLL_LOADING_MS); return; }
        var ready = render(j);
        schedule(ready ? POLL_READY_MS : POLL_LOADING_MS);
      })
      .catch(function () { schedule(POLL_LOADING_MS); });
  }

  function start() { mount(); poll(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
