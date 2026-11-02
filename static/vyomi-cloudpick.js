/* vyomi-cloudpick.js — "default cloud" dialog (shared by the appliance page and the drawer; offline + Nano).
 *  - First visit (no default saved): a forced dialog on the entry page — no ✕/Esc/backdrop close — until a
 *    cloud is chosen. Later visits open straight into the default cloud's console.
 *  - From a console, the drawer's "Default cloud" item reopens it (dismissible) to change the default.
 * The default is per browser (localStorage 'vyomi.defaultCloud'). Include with:
 *   <script src="/assets/vyomi-cloudpick.js" defer></script>            (offline)
 *   <script src="./vyomi-cloudpick.js" data-nano defer></script>        (Nano)
 */
(function () {
  var s = document.currentScript;
  var NANO = !!(s && s.hasAttribute('data-nano'));
  var KEY = 'vyomi.defaultCloud';
  var CLOUDS = [
    { id: 'aws', name: 'AWS', sub: 'Amazon Web Services' },
    { id: 'gcp', name: 'Google Cloud', sub: 'GCP' },
    { id: 'azure', name: 'Microsoft Azure', sub: 'Azure' }
  ];
  var MARK = {
    aws: '<span style="font:800 26px/1 Inter,system-ui,sans-serif;color:#ff9900;letter-spacing:-1px">aws</span>',
    gcp: '<svg viewBox="0 0 32 28" width="38" height="34"><path fill="#ea4335" d="M21.85,7.41l1,0,2.85-2.85.14-1.21A12.81,12.81,0,0,0,5,9.6a1.55,1.55,0,0,1,1-.06l5.7-.94s.29-.48.44-.45a7.11,7.11,0,0,1,9.73-.74Z"/><path fill="#4285f4" d="M29.76,9.6a12.84,12.84,0,0,0-3.87-6.24l-4,4A7.11,7.11,0,0,1,24.5,13v.71a3.56,3.56,0,1,1,0,7.12H17.38l-.71.72v4.27l.71.71H24.5A9.26,9.26,0,0,0,29.76,9.6Z"/><path fill="#34a853" d="M10.25,26.49h7.12v-5.7H10.25a3.54,3.54,0,0,1-1.47-.32l-1,.31L4.91,23.63l-.25,1A9.21,9.21,0,0,0,10.25,26.49Z"/><path fill="#fbbc05" d="M10.25,8A9.26,9.26,0,0,0,4.66,24.6l4.13-4.13a3.56,3.56,0,1,1,4.71-4.71l4.13-4.13A9.25,9.25,0,0,0,10.25,8Z"/></svg>',
    azure: '<svg viewBox="0 0 96 96" width="34" height="34"><path fill="#0078d4" d="M33.338 6.544h26.038l-27.03 80.087a4.152 4.152 0 0 1-3.933 2.824H8.149a4.145 4.145 0 0 1-3.928-5.47L29.404 9.368a4.152 4.152 0 0 1 3.934-2.825z"/><path fill="#0078d4" d="M71.175 60.261h-41.29a1.911 1.911 0 0 0-1.305 3.309l26.532 24.764a4.171 4.171 0 0 0 2.846 1.121h23.38z"/><path fill="#3ccbf4" d="M66.595 9.364a4.145 4.145 0 0 0-3.928-2.82H33.648a4.146 4.146 0 0 1 3.928 2.82l25.184 74.62a4.146 4.146 0 0 1-3.928 5.472h29.02a4.146 4.146 0 0 0 3.927-5.472z"/></svg>'
  };
  function consolePath(c) { return NANO ? c + '-console.html' : '/console/' + c; }
  function getDefault() { try { var v = localStorage.getItem(KEY); return CLOUDS.some(function (c) { return c.id === v; }) ? v : null; } catch (e) { return null; } }
  function setDefault(c) { try { localStorage.setItem(KEY, c); } catch (e) {} }
  function jget(u) { return fetch(u).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function canUse(c, pol) {          // same rule as clouds.html _canAccessProvider; unknown policy fails open
    if (!pol) return true;
    var ap = pol.active_policy || pol.policy || pol, provs = ap.providers;
    if (provs === 'primary_cloud_only') { var pc = String(pol.primary_cloud || ap.primary_cloud || '').toLowerCase(); return !!pc && c === pc; }
    return Array.isArray(provs) ? provs.indexOf(c) >= 0 : true;
  }
  function provOf(sp) { return String(sp.provider || sp.provider_id || '').toLowerCase(); }

  // Switch to a space on cloud c (the active one if it matches, else the newest; create one if none), then open its console.
  function enter(c) {
    return jget('/api/spaces').then(function (d) {
      var list = ((d && d.spaces) || []).filter(function (x) { return provOf(x) === c; });
      var act = list.filter(function (x) { return x.space_id === (d && d.active_space_id); })[0];
      var pick = act || list[list.length - 1];
      if (pick) return pick.space_id;
      var nm = CLOUDS.filter(function (x) { return x.id === c; })[0].name + ' space';
      return fetch('/api/spaces', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: c, name: nm }) })
        .then(function (r) { if (!r.ok) throw new Error('Could not create a ' + nm + ' (HTTP ' + r.status + ')'); return r.json(); })
        .then(function (j) { return j && j.space && j.space.space_id; });
    }).then(function (id) {
      return (id ? fetch('/api/spaces/' + id + '/switch', { method: 'POST' }).catch(function () {}) : null);
    }).then(function () { (window.top || window).location.href = consolePath(c); });
  }

  var CSS = '#vy-pick{position:fixed;inset:0;z-index:300;display:flex;align-items:center;justify-content:center;background:rgba(5,7,26,.82);font-family:Inter,system-ui,sans-serif}' +
    '#vy-pick .box{width:min(640px,94vw);background:#fff;border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.5);padding:26px 26px 20px;color:#101828}' +
    '#vy-pick h2{margin:0 0 6px;font-size:20px;font-weight:700}' +
    '#vy-pick p.sub{margin:0 0 18px;font-size:13.5px;color:#475467;line-height:1.5}' +
    '#vy-pick .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}' +
    '#vy-pick .tile{position:relative;display:flex;flex-direction:column;align-items:center;gap:8px;padding:20px 10px 16px;border:2px solid #e4e7ec;border-radius:12px;background:#fff;cursor:pointer;font:inherit;color:inherit}' +
    '#vy-pick .tile:hover:not([disabled]){border-color:#98a2b3}' +
    '#vy-pick .tile.sel{border-color:#2563eb;background:#eff6ff}' +
    '#vy-pick .tile[disabled]{opacity:.45;cursor:not-allowed}' +
    '#vy-pick .tile .mk{height:38px;display:flex;align-items:center}' +
    '#vy-pick .tile b{font-size:14px}' +
    '#vy-pick .tile small{font-size:12px;color:#667085}' +
    '#vy-pick .badge{position:absolute;top:8px;right:8px;font-size:10.5px;font-weight:700;color:#1d4ed8;background:#dbeafe;border-radius:999px;padding:2px 8px}' +
    '#vy-pick .err{margin-top:12px;font-size:13px;color:#b42318;min-height:0}' +
    '#vy-pick .ft{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:20px}' +
    '#vy-pick .ft button{height:38px;padding:0 18px;border-radius:9px;font:600 14px Inter,system-ui,sans-serif;cursor:pointer;border:1px solid #d0d5dd;background:#fff;color:#344054}' +
    '#vy-pick .ft button.go{background:#2563eb;border-color:#2563eb;color:#fff}' +
    '#vy-pick .ft button.go[disabled]{background:#93b4f5;border-color:#93b4f5;cursor:not-allowed}' +
    '@media(max-width:560px){#vy-pick .tiles{grid-template-columns:1fr}}';

  function open(opts) {
    opts = opts || {};
    var forced = !!opts.forced, cur = getDefault(), sel = opts.forced ? null : cur;
    if (document.getElementById('vy-pick')) return;
    if (!document.getElementById('vy-pick-css')) { var st = document.createElement('style'); st.id = 'vy-pick-css'; st.textContent = CSS; document.head.appendChild(st); }
    var ov = document.createElement('div'); ov.id = 'vy-pick';
    ov.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="vy-pick-t"><h2 id="vy-pick-t">' + (forced ? 'Choose your default cloud' : 'Default cloud') + '</h2>' +
      '<p class="sub">' + (forced ? 'Pick the cloud you work in most. ' : '') + 'Vyomi opens straight into your default cloud’s console each time. You can change it any time from the drawer.</p>' +
      '<div class="tiles"></div><div class="err"></div><div class="ft">' + (forced ? '' : '<button type="button" class="cancel">Cancel</button>') + '<button type="button" class="go" disabled>' + (forced ? 'Continue' : 'Set as default') + '</button></div></div>';
    document.body.appendChild(ov);
    var tiles = ov.querySelector('.tiles'), go = ov.querySelector('.go'), err = ov.querySelector('.err');
    function close() { ov.remove(); document.removeEventListener('keydown', onKey, true); }
    function onKey(e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (!forced) close(); } }
    document.addEventListener('keydown', onKey, true);
    if (!forced) { ov.querySelector('.cancel').onclick = close; ov.addEventListener('click', function (e) { if (e.target === ov) close(); }); }
    function paint() {
      [].forEach.call(tiles.children, function (t) { t.classList.toggle('sel', t.getAttribute('data-c') === sel); });
      go.disabled = !sel;
    }
    Promise.all([jget('/api/runtime/tier'), jget('/api/spaces')]).then(function (r) {
      var pol = r[0], sp = (r[1] && r[1].spaces) || [];
      tiles.innerHTML = CLOUDS.map(function (c) {
        var n = sp.filter(function (x) { return provOf(x) === c.id; }).length, ok = canUse(c.id, pol);
        return '<button type="button" class="tile" data-c="' + c.id + '"' + (ok ? '' : ' disabled') + '>' + (c.id === cur ? '<span class="badge">Default</span>' : '') +
          '<span class="mk">' + MARK[c.id] + '</span><b>' + c.name + '</b><small>' + (ok ? (n + (n === 1 ? ' space' : ' spaces')) : 'Not in your plan') + '</small></button>';
      }).join('');
      paint();
    });
    tiles.addEventListener('click', function (e) { var t = e.target.closest('.tile'); if (!t || t.disabled) return; sel = t.getAttribute('data-c'); paint(); });
    go.onclick = function () {
      if (!sel) return;
      go.disabled = true; go.textContent = 'Opening…'; err.textContent = '';
      setDefault(sel);
      var here = (location.pathname.match(/(?:\/console\/|\/)(aws|gcp|azure)(?:-console\.html)?\/?$/) || [])[1];
      if (!forced && here === sel) { close(); return; }                   // already in that cloud
      enter(sel).catch(function (e) { err.textContent = String(e.message || e); go.disabled = false; go.textContent = forced ? 'Continue' : 'Set as default'; });
    };
  }

  // Entry page (clouds.html, no #view, not embedded): first visit → forced dialog; later → straight into the default.
  function entry() {
    var de = document.documentElement;
    if (/[?&]embed=1/.test(location.search) || (window.__vyHash !== undefined ? window.__vyHash : location.hash)) { de.classList.remove('vy-entering'); return; }
    var d = getDefault();
    if (!d) { de.classList.remove('vy-entering'); open({ forced: true }); return; }
    jget('/api/runtime/tier').then(function (pol) {
      if (!canUse(d, pol)) { de.classList.remove('vy-entering'); open({ forced: true }); return; }
      enter(d).catch(function () { de.classList.remove('vy-entering'); open({ forced: true }); });
    });
  }
  window.VyomiCloudPick = { open: open, getDefault: getDefault, enter: enter };
  if (s && s.hasAttribute('data-entry')) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', entry); else entry(); }
})();
