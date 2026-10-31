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
    strip.querySelector('#vyr-icon').innerHTML = ready ? checkHTML() : (j.status === 'idle' ? '' : spinnerHTML());
    strip.querySelector('#vyr-title').textContent = ready ? 'Appliance is Ready'
      : j.status === 'idle' ? 'Engines not running' : 'Appliance is getting ready';
    // Nano: no runtime is running its engines (no console or relay open) — say so,
    // rather than spinning as if something were starting.
    var idle = j.status === 'idle';
    strip.querySelector('#vyr-summary').textContent = ready
      ? '— all ' + tc + ' services running'
      : idle ? '— they start when you open a console (0/' + tc + ' running)'
      : '— ' + rc + '/' + tc + ' backends ready';

    // Progress bar + pct are only meaningful while loading. When ready, swap the
    // bar for a flexible spacer so the Details button stays right-aligned.
    var noBar = ready || j.status === 'idle';
    strip.querySelector('#vyr-barwrap').style.display = noBar ? 'none' : 'block';
    strip.querySelector('#vyr-spacer').style.display = noBar ? 'block' : 'none';
    strip.querySelector('#vyr-pct').style.display = noBar ? 'none' : 'inline';
    if (!noBar) {
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
        '<span style="width:44px;height:5px;border-radius:3px;background:#e4e7ec;overflow:hidden;display:inline-block;">' +
        '<span style="display:block;height:100%;width:' + w + '%;background:' + col + ';"></span></span>' +
        '<span style="font-variant-numeric:tabular-nums;color:#667085;min-width:40px;text-align:right;font-size:11px;">' + txt + '</span>';
      return cell;
    }

    // Each backend's native service icon — what it serves, in that cloud's console style:
    // AWS / Azure tiles from service-icons.js (the v4 consoles' set), GCP as Material glyphs in
    // Google blue (as the GCP console does). Keys cover the offline containers and the Nano engines.
    var SVC_ICON = {
      // offline appliance containers
      mysql: ['aws', 'rds', 'Amazon RDS'], vault: ['aws', 'secretsmanager', 'Secrets Manager'],
      minio: ['aws', 's3', 'Amazon S3'], dynamodb: ['aws', 'dynamodb', 'DynamoDB'],
      nats: ['aws', 'eventbridge', 'EventBridge'], elasticmq: ['aws', 'sqs', 'Amazon SQS'],
      victoriametrics: ['aws', 'cloudwatch', 'CloudWatch'], gateway: ['aws', 'apigateway', 'API Gateway'],
      'fake-gcs': ['gcp', 'inventory_2', 'Cloud Storage'], pubsub: ['gcp', 'message', 'Pub/Sub'],
      firestore: ['gcp', 'description', 'Firestore'], valkey: ['gcp', 'speed', 'Memorystore'],
      registry: ['gcp', 'view_in_ar', 'Artifact Registry'], azurite: ['azure', 'storage', 'Storage accounts'],
      // Nano in-browser engines
      s3: ['aws', 's3', 'Amazon S3'], ddb: ['aws', 'dynamodb', 'DynamoDB'], kms: ['aws', 'kms', 'AWS KMS'],
      sec: ['aws', 'secretsmanager', 'Secrets Manager'], rds: ['aws', 'rds', 'Amazon RDS'], iam: ['aws', 'iam', 'IAM'],
      msg: ['aws', 'sqs', 'Amazon SQS + SNS'], kinesis: ['aws', 'kinesis', 'Kinesis', 'Analytics'],
      apigwv2: ['aws', 'apigateway', 'API Gateway'], logs: ['aws', 'cloudwatch', 'CloudWatch Logs'],
      cw: ['aws', 'cloudwatch', 'CloudWatch'], elbv2: ['aws', 'elbv2', 'Elastic Load Balancing', 'Networking'],
      ssm: ['aws', 'ssm', 'Systems Manager', 'Management'], sfn: ['aws', 'sfn', 'Step Functions', 'Application Integration'],
      gcs: ['gcp', 'inventory_2', 'Cloud Storage'], gcp_fs: ['gcp', 'description', 'Firestore'],
      gcp_kms: ['gcp', 'vpn_key', 'Cloud KMS'], gcp_sec: ['gcp', 'password', 'Secret Manager'],
      gcp_gke: ['gcp', 'hub', 'Kubernetes Engine'], gcp_mon: ['gcp', 'bar_chart', 'Cloud Monitoring'],
      gcp_redis: ['gcp', 'speed', 'Memorystore'], gcp_iamc: ['gcp', 'admin_panel_settings', 'IAM Credentials'],
      gcp_sched: ['gcp', 'schedule', 'Cloud Scheduler'], gcp_msg: ['gcp', 'message', 'Pub/Sub'],
      gcp_iam: ['gcp', 'admin_panel_settings', 'IAM'], gcp_sql: ['gcp', 'storage', 'Cloud SQL'],
      gcp_ar: ['gcp', 'view_in_ar', 'Artifact Registry'],
      az_blob: ['azure', 'storage', 'Blob storage'], az_cosmos: ['azure', 'cosmos', 'Azure Cosmos DB'],
      az_kvsec: ['azure', 'keyvaults', 'Key Vault secrets'], az_kvkeys: ['azure', 'keyvaults', 'Key Vault keys'],
      az_queue: ['azure', 'storage', 'Queue storage'], az_sb: ['azure', 'servicebus', 'Service Bus'],
      az_arm: ['azure', 'resourcegroups', 'Resource Manager'],
      // shared core (serves every cloud)
      simulator: ['core', 'dns', 'Vyomi engine'], postgres: ['core', 'storage', 'Shared PostgreSQL'],
      cloudsim: ['core', 'hub', 'Cloud simulator'], runtime: ['core', 'memory', 'Pyodide runtime'],
      events: ['core', 'bolt', 'Event store']
    };
    function svcIcon(s) {
      var m = SVC_ICON[s.name] || [s.category === 'core' ? 'core' : (s.category || 'core'), null, ''];
      var box = document.createElement('span');
      box.style.cssText = 'flex:none; width:18px; height:18px; display:inline-flex; align-items:center; justify-content:center;';
      if (m[2]) box.title = m[2];
      var lib = window.VyomiServiceIcons;
      if ((m[0] === 'aws' || m[0] === 'azure') && lib) {
        box.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" style="display:block">' +
          (m[0] === 'aws' ? lib.aws(m[1] || '', m[3]) : lib.azure(m[1] || '')) + '</svg>';
      } else {
        var g = document.createElement('span');
        g.className = 'material-icons'; g.setAttribute('aria-hidden', 'true');
        g.style.cssText = 'font-size:17px; color:' + (m[0] === 'gcp' ? '#4285f4' : '#667085') + ';';
        g.textContent = m[1] || (m[0] === 'core' ? 'dns' : 'cloud');
        box.appendChild(g);
      }
      return box;
    }

    // Tile header: the cloud's logo (the same inline SVGs the space cards use, when the page
    // has them); core gets a server glyph. Gradient ids are unique per copy so a logo never
    // points at a definition inside a hidden view.
    var _markSeq = 0;
    function cloudMark(cat) {
      var box = document.createElement('span');
      box.style.cssText = 'flex:none; width:22px; height:16px; display:inline-flex; align-items:center; justify-content:center;';
      var logos = (typeof SPACE_LOGOS !== 'undefined') ? SPACE_LOGOS : null;
      if (logos && logos[cat]) {
        box.innerHTML = logos[cat].replace(/sp-az-g/g, 'vyr' + (++_markSeq) + '-az-g');
        var svg = box.firstChild;
        svg.setAttribute('aria-hidden', 'true'); svg.removeAttribute('role');
        svg.style.cssText = 'height:' + (cat === 'aws' ? 13 : 15) + 'px; width:' + (cat === 'aws' ? 22 : 15) + 'px; display:block;';
      } else {
        var g = document.createElement('span');
        g.className = 'material-icons'; g.style.cssText = 'font-size:16px; color:#667085;';
        g.textContent = cat === 'core' ? 'dns' : 'cloud';
        box.appendChild(g);
      }
      return box;
    }

    function buildRow(s) {
      var up = s.status === 'ready';
      var row = document.createElement('div');
      row.style.cssText = 'display:flex; align-items:center; gap:8px;';
      if (onDark) {
        var dot = document.createElement('span');
        dot.style.cssText = 'width:8px; height:8px; border-radius:50%; flex:none; background:' +
          (up ? '#34d399' : s.status === 'error' ? '#ef4444' : 'rgba(255,255,255,.35)') + ';';
        row.appendChild(dot);
      } else {
        row.appendChild(svcIcon(s));                 // status card: the native service icon
      }
      var name = document.createElement('span');
      name.style.cssText = 'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;' +
        (onDark ? '' : ' color:#344054;');
      name.textContent = s.label || s.name || '';
      row.appendChild(name);
      if (!onDark) row.appendChild(metricCell(s));    // live CPU/Mem bar (body card)
      var failed = s.status === 'error';
      var said = up ? 'Running' : failed ? 'Error' : s.status === 'idle' ? 'Not running' : 'Starting…';
      if (failed && s.error) row.title = s.error;
      if (!onDark) {
        // Status card: a bordered tick (running) or cross (not running / error); the word is the
        // tooltip + accessible name, so the state never rests on colour alone.
        var col = up ? '#22c55e' : (failed || s.status === 'idle') ? '#ef4444' : '#a1a1aa';
        var ic = document.createElement('span');
        ic.setAttribute('role', 'img'); ic.setAttribute('aria-label', said); ic.title = failed && s.error ? said + ': ' + s.error : said;
        ic.style.cssText = 'flex:none; width:18px; height:18px; box-sizing:border-box; border-radius:50%; border:1.5px solid ' + col +
          '; color:' + col + '; display:inline-flex; align-items:center; justify-content:center;';
        if (up || failed || s.status === 'idle') {
          var g = document.createElement('span');
          g.className = 'material-icons'; g.style.cssText = 'font-size:12px; font-weight:700; line-height:1;';
          g.textContent = up ? 'check' : 'close';
          ic.appendChild(g);
        }
        row.appendChild(ic);
        return row;
      }
      var tag = document.createElement('span');
      tag.style.cssText = 'font-size:11px; text-transform:uppercase; letter-spacing:.4px; margin-left:auto; opacity:.65;';
      tag.textContent = said;
      row.appendChild(tag);
      return row;
    }

    // CPU / Mem segmented toggle (body card, top-right, above the tiles).
    function buildMetricToggle() {
      var rowEl = document.createElement('div');
      rowEl.style.cssText = 'display:flex; justify-content:flex-end; margin-bottom:14px;';
      var wrap = document.createElement('div');
      wrap.style.cssText = 'display:inline-flex; border:1px solid #d0d5dd; border-radius:999px; overflow:hidden;';
      ['cpu', 'mem'].forEach(function (mk) {
        var on = (_metric === mk);
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.style.cssText = 'border:0; padding:4px 14px; font:inherit; font-size:11px; font-weight:600; cursor:pointer; background:' +
          (on ? '#eef4ff' : 'transparent') + '; color:' + (on ? '#1d4ed8' : '#667085') + ';';
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
      // The CPU / Mem toggle goes in the section header when the page provides a slot
      // (#vyomi-services-toggle), else above the tiles as before.
      var toggleSlot = document.getElementById('vyomi-services-toggle');
      if (toggleSlot) {
        var tg = buildMetricToggle(); tg.style.marginBottom = '0';
        toggleSlot.innerHTML = ''; toggleSlot.appendChild(tg);
      } else {
        bodyMount.appendChild(buildMetricToggle());
      }
      var grid = document.createElement('div');
      // Two tiles per row (one on narrow screens, where half the width is under 240px).
      grid.style.cssText = 'display:grid; grid-template-columns:repeat(auto-fit, minmax(max(240px, calc(50% - 8px)), 1fr)); gap:16px;';
      cats.forEach(function (cat) {
        var svcs = groups[cat];
        var byc = (j.by_category || {})[cat] || {};
        var rc = (byc.ready != null) ? byc.ready : svcs.filter(function (x) { return x.status === 'ready'; }).length;
        var tc = (byc.total != null) ? byc.total : svcs.length;
        var tile = document.createElement('div');    // each tile IS the card now
        tile.style.cssText = 'background:#f8fafc; border:1px solid #eef0f3; ' +
          'border-radius:14px; padding:16px 18px;';
        var head = document.createElement('div');
        head.style.cssText = 'display:flex; align-items:center; justify-content:space-between; ' +
          'padding-bottom:9px; margin-bottom:12px; border-bottom:1px solid #e4e7ec;';  // tab-style title + rule
        var htitle = document.createElement('span');
        htitle.style.cssText = 'font-weight:600; color:#101828; font-size:13.5px; display:inline-flex; align-items:center; gap:6px;';
        htitle.appendChild(cloudMark(cat));
        htitle.appendChild(document.createTextNode(CAT_LABELS[cat] || cat));
        var hcount = document.createElement('span');
        var allUp = rc === tc;
        hcount.style.cssText = 'font-size:12px; font-weight:600; color:' + (allUp ? '#16a34a' : '#667085') + ';';
        hcount.textContent = rc + '/' + tc + ' running';
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
