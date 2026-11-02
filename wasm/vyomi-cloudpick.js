/* vyomi-cloudpick.js — "default space" chooser + entry redirect (shared by the appliance page; offline + Nano).
 *  - First visit (no default space saved, or the saved one is gone / not in the plan): a FORCED, opaque dialog on the
 *    entry page — no ✕/Esc/backdrop close, nothing of the page visible behind it — until a space is chosen (or a new
 *    one created). Later visits open straight into the default space's console.
 *  - Switching spaces and changing the default both happen in Spaces (drawer → Spaces): each card has a star.
 * The default is per browser (localStorage 'vyomi.defaultSpace' = space_id). Include with:
 *   <script src="/assets/vyomi-cloudpick.js" defer></script>            (offline)
 *   <script src="./vyomi-cloudpick.js" data-nano defer></script>        (Nano)
 */
(function () {
  var s = document.currentScript;
  var NANO = !!(s && s.hasAttribute('data-nano'));
  var KEY = 'vyomi.defaultSpace';
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
  function getDefault() { try { return localStorage.getItem(KEY) || null; } catch (e) { return null; } }
  function setDefault(id) { try { localStorage.setItem(KEY, id); } catch (e) {} }
  function jget(u) { return fetch(u).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function canUse(c, pol) {          // same rule as clouds.html _canAccessProvider; unknown policy fails open
    if (!pol) return true;
    var ap = pol.active_policy || pol.policy || pol, provs = ap.providers;
    if (provs === 'primary_cloud_only') { var pc = String(pol.primary_cloud || ap.primary_cloud || '').toLowerCase(); return !!pc && c === pc; }
    return Array.isArray(provs) ? provs.indexOf(c) >= 0 : true;
  }
  function provOf(sp) { return String(sp.provider || sp.provider_id || '').toLowerCase(); }

  function nameOf(c) { return CLOUDS.filter(function (x) { return x.id === c; })[0].name; }
  function createSpace(c) {
    return fetch('/api/spaces', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: c, name: nameOf(c) + ' space' }) })
      .then(function (r) { if (!r.ok) throw new Error('Could not create a ' + nameOf(c) + ' space (HTTP ' + r.status + ')'); return r.json(); })
      .then(function (j) { var id = j && j.space && j.space.space_id; if (!id) throw new Error('Could not create a space'); return { id: id, provider: c }; });
  }
  // Switch to a space, then open its cloud's console.
  function go(id, c) {
    return fetch('/api/spaces/' + id + '/switch', { method: 'POST' }).catch(function () {}).then(function () { (window.top || window).location.href = consolePath(c); });
  }
  // Open the saved default space (rejects if it is gone or its cloud is not in the plan).
  function enter() {
    var id = getDefault();
    return Promise.all([jget('/api/spaces'), jget('/api/runtime/tier')]).then(function (r) {
      var sp = ((r[0] && r[0].spaces) || []).filter(function (x) { return x.space_id === id; })[0];
      if (!id || !sp) throw new Error('no default space');
      var c = provOf(sp);
      if (!canUse(c, r[1])) throw new Error('not in plan');
      return go(id, c);
    });
  }

  var CSS = '#vy-pick{position:fixed;inset:0;z-index:300;display:flex;align-items:center;justify-content:center;background:#0b1020;font-family:Inter,system-ui,sans-serif}' +
    'html.vy-pickopen body>*:not(#vy-pick){visibility:hidden !important}' +
    '#vy-pick .box{width:min(620px,94vw);max-height:92vh;overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.5);padding:26px 26px 20px;color:#101828}' +
    '#vy-pick h2{margin:0 0 6px;font-size:20px;font-weight:700}' +
    '#vy-pick p.sub{margin:0 0 16px;font-size:13.5px;color:#475467;line-height:1.5}' +
    '#vy-pick h3{margin:16px 0 8px;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#667085}' +
    '#vy-pick .opt{display:flex;align-items:center;gap:12px;width:100%;padding:10px 12px;margin-bottom:8px;border:2px solid #e4e7ec;border-radius:12px;background:#fff;cursor:pointer;font:inherit;color:inherit;text-align:left}' +
    '#vy-pick .opt:hover:not([disabled]){border-color:#98a2b3}' +
    '#vy-pick .opt.sel{border-color:#2563eb;background:#eff6ff}' +
    '#vy-pick .opt[disabled]{opacity:.45;cursor:not-allowed}' +
    '#vy-pick .opt .mk{width:44px;height:34px;display:flex;align-items:center;justify-content:center;flex:none}' +
    '#vy-pick .opt .tx{display:flex;flex-direction:column;min-width:0}' +
    '#vy-pick .opt b{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '#vy-pick .opt small{font-size:12px;color:#667085}' +
    '#vy-pick .news{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}' +
    '#vy-pick .news .opt{margin:0;flex-direction:column;gap:4px;text-align:center;padding:12px 8px}' +
    '#vy-pick .err{margin-top:12px;font-size:13px;color:#b42318}' +
    '#vy-pick .ft{display:flex;justify-content:flex-end;margin-top:18px}' +
    '#vy-pick .ft button{height:38px;padding:0 18px;border-radius:9px;font:600 14px Inter,system-ui,sans-serif;cursor:pointer;border:1px solid #2563eb;background:#2563eb;color:#fff}' +
    '#vy-pick .ft button[disabled]{background:#93b4f5;border-color:#93b4f5;cursor:not-allowed}' +
    '@media(max-width:560px){#vy-pick .news{grid-template-columns:1fr}}';

  // The forced chooser: pick an existing space, or create one on a cloud. Nothing of the page shows behind it.
  function open() {
    if (document.getElementById('vy-pick')) return;
    var sel = null;                                   // {id} existing space  |  {create: 'aws'|'gcp'|'azure'}
    if (!document.getElementById('vy-pick-css')) { var st = document.createElement('style'); st.id = 'vy-pick-css'; st.textContent = CSS; document.head.appendChild(st); }
    document.documentElement.classList.remove('vy-entering'); document.documentElement.classList.add('vy-pickopen');
    var ov = document.createElement('div'); ov.id = 'vy-pick';
    ov.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="vy-pick-t"><h2 id="vy-pick-t">Choose your default space</h2>' +
      '<p class="sub">Vyomi opens straight into your default space each time. Switch spaces — or pick another default — any time from <b>Spaces</b> in the drawer.</p>' +
      '<div class="list"></div><div class="err"></div><div class="ft"><button type="button" class="go" disabled>Continue</button></div></div>';
    document.body.appendChild(ov);
    var list = ov.querySelector('.list'), btn = ov.querySelector('.go'), err = ov.querySelector('.err');
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && document.getElementById('vy-pick')) { e.preventDefault(); e.stopPropagation(); } }, true);
    function paint() {
      [].forEach.call(list.querySelectorAll('.opt'), function (o) {
        var on = sel && ((sel.id && o.getAttribute('data-s') === sel.id) || (sel.create && o.getAttribute('data-n') === sel.create));
        o.classList.toggle('sel', !!on);
      });
      btn.disabled = !sel;
    }
    Promise.all([jget('/api/runtime/tier'), jget('/api/spaces')]).then(function (r) {
      var pol = r[0], sp = (r[1] && r[1].spaces) || [];
      var h = '';
      if (sp.length) {
        h += '<h3>Your spaces</h3>' + sp.map(function (x) {
          var c = provOf(x), ok = canUse(c, pol), cn = CLOUDS.filter(function (k) { return k.id === c; })[0];
          return '<button type="button" class="opt" data-s="' + x.space_id + '" data-c="' + c + '"' + (ok ? '' : ' disabled') + '><span class="mk">' + (MARK[c] || '') + '</span>' +
            '<span class="tx"><b>' + (x.name || x.space_id).replace(/</g, '&lt;') + '</b><small>' + (ok ? (cn ? cn.name : c) + (x.region ? ' · ' + x.region : '') : 'Not in your plan') + '</small></span></button>';
        }).join('');
      }
      h += '<h3>' + (sp.length ? 'Or create a new space' : 'Create your first space') + '</h3><div class="news">' + CLOUDS.map(function (c) {
        var ok = canUse(c.id, pol);
        return '<button type="button" class="opt" data-n="' + c.id + '"' + (ok ? '' : ' disabled') + '><span class="mk">' + MARK[c.id] + '</span><b>' + c.name + '</b><small>' + (ok ? 'New space' : 'Not in your plan') + '</small></button>';
      }).join('') + '</div>';
      list.innerHTML = h; paint();
    });
    list.addEventListener('click', function (e) {
      var o = e.target.closest('.opt'); if (!o || o.disabled) return;
      sel = o.getAttribute('data-s') ? { id: o.getAttribute('data-s'), c: o.getAttribute('data-c') } : { create: o.getAttribute('data-n') };
      paint();
    });
    btn.onclick = function () {
      if (!sel) return;
      btn.disabled = true; btn.textContent = 'Opening…'; err.textContent = '';
      (sel.create ? createSpace(sel.create) : Promise.resolve({ id: sel.id, provider: sel.c })).then(function (s) {
        setDefault(s.id); return go(s.id, s.provider);
      }).catch(function (e) { err.textContent = String(e.message || e); btn.disabled = false; btn.textContent = 'Continue'; });
    };
  }

  // Entry page (clouds.html, no #view, not embedded): no valid default → forced chooser; otherwise straight into it.
  function entry() {
    var de = document.documentElement;
    if (/[?&]embed=1/.test(location.search) || (window.__vyHash !== undefined ? window.__vyHash : location.hash)) { de.classList.remove('vy-entering'); return; }
    if (!getDefault()) { open(); return; }
    enter().catch(function () { open(); });
  }
  window.VyomiCloudPick = { open: open, getDefault: getDefault, setDefault: setDefault, enter: enter };
  if (s && s.hasAttribute('data-entry')) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', entry); else entry(); }
})();
