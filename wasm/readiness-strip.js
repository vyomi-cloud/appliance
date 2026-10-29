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

  // Live per-service CPU/Mem (Service-status body card only): poll() fetches
  // /api/runtime/service-metrics alongside readiness; the tiles render a
  // colour-graded bar for the selected metric with a CPU/Mem toggle.
  var _metric = 'cpu';          // 'cpu' | 'mem'
  var _metrics = {};            // name -> {cpu_pct, mem_pct}
  var _lastJ = null;            // last readiness payload (re-render on toggle)

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

    // Detail rows — the per-service status list. If the page provides a body
    // mount (#vyomi-services-mount), render the list THERE (in the page body,
    // e.g. below the Host-utilization card) and hide the strip's Details toggle
    // so the top bar stays a clean banner. Otherwise keep the strip's built-in
    // collapsible panel (launch page / anywhere without a body mount).
    var bodyMount = document.getElementById('vyomi-services-mount');
    var onDark = !bodyMount;                          // strip = dark bg; body card = light

    // Live CPU%/Mem% bar for a service (green <50, amber 50-80, red >=80; grey
    // when no sample). Body card only.
    function metricCell(s) {
      var m = _metrics[s.name];
      var v = m ? (_metric === 'mem' ? m.mem_pct : m.cpu_pct) : null;
      var has = (typeof v === 'number');
      var col = !has ? '#d4d4d8' : (v >= 80 ? '#ef4444' : v >= 50 ? '#f59e0b' : '#10b981');
      var w = has ? Math.min(100, v) : 0;
      var txt = has ? v.toFixed(1) + '%' : '—';
      var cell = document.createElement('span');
      cell.style.cssText = 'margin-left:auto; display:inline-flex; align-items:center; gap:6px; flex:none;';
      cell.title = 'live ' + (_metric === 'mem' ? 'memory' : 'CPU');
      cell.innerHTML =
        '<span style="width:44px;height:5px;border-radius:3px;background:rgba(255,255,255,0.10);overflow:hidden;display:inline-block;">' +
        '<span style="display:block;height:100%;width:' + w + '%;background:' + col + ';"></span></span>' +
        '<span style="font-variant-numeric:tabular-nums;color:#a1a1aa;min-width:40px;text-align:right;font-size:11px;">' + txt + '</span>';
      return cell;
    }

    function buildRow(s) {
      var up = s.status === 'ready';
      var row = document.createElement('div');
      row.style.cssText = 'display:flex; align-items:center; gap:8px;';
      var dot = document.createElement('span');
      dot.style.cssText = 'width:8px; height:8px; border-radius:50%; flex:none; background:' +
        (up ? '#34d399' : (onDark ? 'rgba(255,255,255,.35)' : '#d4d4d8')) + ';';
      row.appendChild(dot);
      var name = document.createElement('span');
      name.style.cssText = 'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;' +
        (onDark ? '' : ' color:#c7cbe0;');
      name.textContent = s.label || s.name || '';
      row.appendChild(name);
      if (!onDark) row.appendChild(metricCell(s));    // live CPU/Mem bar (body card)
      var tag = document.createElement('span');
      tag.style.cssText = 'font-size:11px; text-transform:uppercase; letter-spacing:.4px;' +
        (onDark ? ' margin-left:auto; opacity:.65;' : ' color:' + (up ? '#16a34a' : '#a1a1aa') + ';');
      tag.textContent = up ? 'ready' : 'loading…';
      row.appendChild(tag);
      return row;
    }

    // CPU / Mem segmented toggle (body card, top-right, above the tiles).
    function buildMetricToggle() {
      var rowEl = document.createElement('div');
      rowEl.style.cssText = 'display:flex; justify-content:flex-end; margin-bottom:14px;';
      var wrap = document.createElement('div');
      wrap.style.cssText = 'display:inline-flex; border:1px solid rgba(255,255,255,0.14); border-radius:999px; overflow:hidden;';
      ['cpu', 'mem'].forEach(function (mk) {
        var on = (_metric === mk);
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.style.cssText = 'border:0; padding:4px 14px; font:inherit; font-size:11px; font-weight:600; cursor:pointer; background:' +
          (on ? 'rgba(255,255,255,0.14)' : 'transparent') + '; color:' + (on ? '#fff' : '#a1a1aa') + ';';
        btn.textContent = (mk === 'cpu') ? 'CPU' : 'Mem';
        btn.addEventListener('click', function () {
          if (_metric !== mk) { _metric = mk; if (_lastJ) render(_lastJ); }
        });
        wrap.appendChild(btn);
      });
      rowEl.appendChild(wrap);
      return rowEl;
    }

    if (bodyMount) {
      // Body card: one TILE per service category (Core / AWS / GCP / Azure),
      // each row carrying a live CPU/Mem bar (metric picked by the toggle).
      _lastJ = j;
      strip.querySelector('#vyr-details-btn').style.display = 'none';
      strip.querySelector('#vyr-detail').style.display = 'none';
      var CAT_LABELS = { core: 'Core', aws: 'AWS', gcp: 'GCP', azure: 'Azure' };
      var CAT_ICONS = { core: 'dns', aws: 'cloud', gcp: 'cloud_queue', azure: 'cloud_circle' };
      var CAT_ORDER = ['core', 'aws', 'gcp', 'azure'];
      var groups = {};
      (j.services || []).forEach(function (s) {
        var c = s.category || 'core';
        (groups[c] = groups[c] || []).push(s);
      });
      var cats = CAT_ORDER.filter(function (c) { return groups[c]; })
        .concat(Object.keys(groups).filter(function (c) { return CAT_ORDER.indexOf(c) < 0; }));
      bodyMount.style.cssText = '';
      bodyMount.innerHTML = '';
      bodyMount.appendChild(buildMetricToggle());
      var grid = document.createElement('div');
      grid.style.cssText = 'display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:16px;';
      cats.forEach(function (cat) {
        var svcs = groups[cat];
        var byc = (j.by_category || {})[cat] || {};
        var rc = (byc.ready != null) ? byc.ready : svcs.filter(function (x) { return x.status === 'ready'; }).length;
        var tc = (byc.total != null) ? byc.total : svcs.length;
        var tile = document.createElement('div');    // each tile IS the card now
        tile.style.cssText = 'background:linear-gradient(180deg,#14172e 0%,#0d1228 100%); border:1px solid rgba(255,255,255,0.10); ' +
          'border-radius:14px; padding:16px 18px;';
        var head = document.createElement('div');
        head.style.cssText = 'display:flex; align-items:center; justify-content:space-between; ' +
          'padding-bottom:9px; margin-bottom:12px; border-bottom:1px solid rgba(255,255,255,0.12);';  // tab-style title + rule
        var htitle = document.createElement('span');
        htitle.style.cssText = 'font-weight:600; color:#e4e4e7; font-size:13.5px; display:inline-flex; align-items:center; gap:6px;';
        var tico = document.createElement('span');
        tico.className = 'material-icons';
        tico.style.cssText = 'font-size:16px; color:#2563eb;';
        tico.textContent = CAT_ICONS[cat] || 'dns';
        htitle.appendChild(tico);
        htitle.appendChild(document.createTextNode(CAT_LABELS[cat] || cat));
        var hcount = document.createElement('span');
        var allUp = rc === tc;
        hcount.style.cssText = 'font-size:12px; font-weight:600; color:' + (allUp ? '#16a34a' : '#a1a1aa') + ';';
        hcount.textContent = rc + '/' + tc + ' ready';
        head.appendChild(htitle); head.appendChild(hcount);
        tile.appendChild(head);
        var rows = document.createElement('div');
        rows.style.cssText = 'display:flex; flex-direction:column; gap:9px; font-size:13px;';
        svcs.forEach(function (s) { rows.appendChild(buildRow(s)); });
        tile.appendChild(rows);
        grid.appendChild(tile);
      });
      bodyMount.appendChild(grid);
      return ready;
    }

    // Strip's built-in collapsible panel (flat grid).
    var list = strip.querySelector('#vyr-list');
    list.innerHTML = '';
    (j.services || []).forEach(function (s) { list.appendChild(buildRow(s)); });
    return ready;
  }

  function schedule(ms) {
    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(poll, ms);
  }

  function poll() {
    var getJSON = function (url) {
      return fetch(url, { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    };
    // Fetch live CPU/Mem only where the body card is mounted (appliance /clouds).
    var wantMetrics = !!document.getElementById('vyomi-services-mount');
    var reqs = [getJSON('/api/runtime/readiness')];
    if (wantMetrics) reqs.push(getJSON('/api/runtime/service-metrics'));
    Promise.all(reqs).then(function (res) {
      var j = res[0];
      if (wantMetrics) _metrics = (res[1] && res[1].services) || {};
      if (!j) { schedule(POLL_LOADING_MS); return; }
      var ready = render(j);
      schedule(ready ? POLL_READY_MS : POLL_LOADING_MS);
    });
  }

  function start() { mount(); poll(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
