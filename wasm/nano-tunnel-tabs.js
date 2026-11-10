/* nano-tunnel-tabs.js — the footer's Logs pane gets two tabs, Local tunnel and Cloudflare, each with its own
 * live status; the relay's real log shows on whichever tab is carrying the connection. */
(function () {
  var foot = document.getElementById('nano-foot'), pane = document.getElementById('nano-logs'), pre = document.getElementById('nano-foot-log');
  if (!foot || !pane || !pre || document.getElementById('nano-tt')) return;
  var st = document.createElement('style');
  st.textContent = '#nano-tt{display:flex;gap:6px;padding:8px 10px 0;background:#0a0c24;border-bottom:1px solid #2a2f55}' +
    '#nano-tt button{display:inline-flex;align-items:center;gap:7px;background:#0f1233;border:1px solid #2a2f55;border-bottom:0;border-radius:8px 8px 0 0;color:#8b8ba7;padding:7px 14px;cursor:pointer;font:12.5px system-ui,-apple-system,sans-serif;margin-bottom:-1px}' +
    '#nano-tt button:hover{color:#e4e4e7;background:#14184a}#nano-tt button.on{color:#fff;background:#05071a;border-color:#4d8cf3}' +
    '#nano-tt i{width:8px;height:8px;border-radius:50%;background:#71717a;flex:none}' +
    '#nano-tt button.up i{background:#34d399;box-shadow:0 0 6px #34d39988}' +
    '#nano-tt small{color:#71717a;font-size:11.5px}#nano-tt button.up small{color:#6ee7b7}' +
    '#nano-td{padding:8px 14px;font:12px system-ui,-apple-system,sans-serif;color:#a1a1aa;border-bottom:1px solid #1a1f44;display:flex;flex-wrap:wrap;gap:4px 22px}' +
    '#nano-td b{color:#e4e4e7;font-weight:600}#nano-td .bad{color:#f87171}#nano-td .good{color:#34d399}' +
    '#nano-idle{flex:1;padding:14px;font:12.5px system-ui,-apple-system,sans-serif;color:#71717a;line-height:1.6}#nano-idle code{color:#cdd8e6;background:#12163a;padding:1px 5px;border-radius:4px}';
  document.head.appendChild(st);
  var tabs = document.createElement('div'); tabs.id = 'nano-tt';
  tabs.innerHTML = '<button data-k="local" class="on"><i></i>Local tunnel <small>checking…</small></button><button data-k="cloud"><i></i>Cloudflare <small>checking…</small></button>';
  var det = document.createElement('div'); det.id = 'nano-td';
  var idle = document.createElement('div'); idle.id = 'nano-idle'; idle.style.display = 'none';
  var h = pane.querySelector('.h'); pane.insertBefore(tabs, pre); pane.insertBefore(det, pre); pane.insertBefore(idle, pre);
  if (h) h.textContent = 'Relay endpoint — runs in a shared worker, stays connected across views.';
  var cur = 'local', info = { local: null, cloud: null }, health = null;
  function active() {   // which tunnel is carrying the relay right now
    var l = (foot.querySelector('.lbl') || {}).textContent || '';
    if (!/connect/.test(l)) return null;
    return /local/.test(l) ? 'local' : /cloud|Cloudflare/.test(l) ? 'cloud' : null;
  }
  function paint() {
    var act = active();
    ['local', 'cloud'].forEach(function (k) {
      var b = tabs.querySelector('[data-k=' + k + ']'), r = info[k];
      b.classList.toggle('up', !!r); b.classList.toggle('on', k === cur);
      b.querySelector('small').textContent = r === null ? 'checking…' : act === k ? 'running · in use' : r ? 'running' : (k === 'local' ? 'not running' : 'unreachable');
    });
    var rows = [], r = info[cur], yes = '<span class="good">yes</span>', no = '<span class="bad">no</span>';
    if (cur === 'local') {
      rows.push('Reachable: <b>' + (r === null ? '…' : r ? yes : no) + '</b>', 'Endpoint: <b>127.0.0.1:8090</b>');
      if (health) rows.push('Version: <b>' + (health.version || '?') + '</b>', 'Browser tabs: <b>' + (health.tabs != null ? health.tabs : '?') + '</b>',
        'Features: <b>' + ((health.features || []).join(', ') || '—') + '</b>', 'VM ports forwarded: <b>' + ((health.vms || []).length) + '</b>');
      if (r === false) rows.push('Install: <b>npm i -g vyomi-tunnel</b> or <b>brew install vyomi-cloud/tap/vyomi-tunnel</b>, then run <b>vyomi-tunnel</b>');
    } else {
      rows.push('Reachable: <b>' + (r === null ? '…' : r ? yes : no) + '</b>', 'Endpoint: <b>relay.vyomi.cloud</b>', 'VM / SSH bridge: <b>not available</b>');
    }
    det.innerHTML = rows.map(function (x) { return '<span>' + x + '</span>'; }).join('');
    var show = act === cur;   // the worker log belongs to the connected tunnel only
    pre.style.display = show ? '' : 'none'; idle.style.display = show ? 'none' : 'block';
    idle.innerHTML = act ? 'The relay is connected through the <b>' + (act === 'local' ? 'Local tunnel' : 'Cloudflare') + '</b> tab — its log is shown there. This tunnel is not carrying traffic.'
      : 'Not connected. Click <code>Start tunnel</code> — the relay prefers the local tunnel when it is running, and falls back to Cloudflare.';
  }
  function probe(k, url) {
    var ac = new AbortController(), t = setTimeout(function () { ac.abort(); }, 4000);
    fetch(url, { mode: 'no-cors', cache: 'no-store', signal: ac.signal }).then(function () { clearTimeout(t); info[k] = true; paint(); },
                                                                              function () { clearTimeout(t); info[k] = false; paint(); });
  }
  function tick() {
    probe('local', 'http://127.0.0.1:8090/health'); probe('cloud', 'https://relay.vyomi.cloud/health');
    fetch('http://127.0.0.1:8090/health', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (j) { health = j; paint(); }, function () { health = null; });
  }
  tabs.addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { cur = b.dataset.k; paint(); } });
  tick(); setInterval(tick, 8000); paint();
  var mo = new MutationObserver(paint); mo.observe(foot, { attributes: true, attributeFilter: ['class'] });
  var lb = foot.querySelector('.lbl'); if (lb) mo.observe(lb, { childList: true, characterData: true, subtree: true });
})();
