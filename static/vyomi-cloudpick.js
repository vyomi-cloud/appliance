/* vyomi-cloudpick.js — first-visit "default space" dialog + entry redirect (offline + Nano).
 *  - First visit (no default space saved, or the saved one is gone / not in the plan): the SAME Spaces dialog the drawer
 *    opens, but FORCED — no ✕/Esc, opaque backdrop, nothing of the page behind it — until a space is opened or starred
 *    (or created); that space becomes the default. Later visits open straight into the default space's console.
 *  - Switching spaces and changing the default both happen in Spaces (drawer → Spaces): each card has a star.
 * The default is per browser (localStorage 'vyomi.defaultSpace' = space_id). Include with:
 *   <script src="/assets/vyomi-cloudpick.js" defer></script>            (offline)
 *   <script src="./vyomi-cloudpick.js" data-nano defer></script>        (Nano)
 */
(function () {
  var s = document.currentScript;
  var NANO = !!(s && s.hasAttribute('data-nano'));
  var KEY = 'vyomi.defaultSpace';
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
    '#vy-pick .box{width:min(1100px,94vw);height:min(760px,90vh);background:#fff;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.45);display:flex;flex-direction:column;overflow:hidden}' +
    '#vy-pick .hd{display:flex;align-items:center;height:46px;padding:0 18px;border-bottom:1px solid #e4e7ec;font:600 15px Inter,system-ui,sans-serif;color:#101828}' +
    '#vy-pick iframe{flex:1;border:0;width:100%}';

  // First visit / stale default: the SAME Spaces dialog the drawer opens, but forced (no ✕, no Esc, opaque backdrop)
  // until a space is opened or starred - that space becomes the default. Nothing of the page shows behind it.
  function open() {
    if (document.getElementById('vy-pick')) return;
    if (!document.getElementById('vy-pick-css')) { var st = document.createElement('style'); st.id = 'vy-pick-css'; st.textContent = CSS; document.head.appendChild(st); }
    document.documentElement.classList.remove('vy-entering'); document.documentElement.classList.add('vy-pickopen');
    var ov = document.createElement('div'); ov.id = 'vy-pick';
    ov.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="vy-pick-t"><div class="hd"><span id="vy-pick-t">Spaces</span></div><iframe title="Spaces"></iframe></div>';
    ov.querySelector('iframe').src = (NANO ? 'clouds.html' : '/clouds') + '?embed=1&pick=1#spaces';
    document.body.appendChild(ov);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && document.getElementById('vy-pick')) { e.preventDefault(); e.stopPropagation(); } }, true);
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
