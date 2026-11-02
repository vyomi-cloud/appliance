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
  var CL = (s && s.getAttribute('data-clouds')) || '/clouds';   // appliance page: '/clouds' offline, 'clouds.html' on Nano
  var NAMES = { aws: 'AWS', gcp: 'Google Cloud', azure: 'Azure' };
  var ITEMS = [
    ['spaces', 'Spaces', 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5'],
    ['workspace', 'Health', 'M3 3v18h18M7 12h3v6H7zM12 8h3v10h-3zM17 4h3v14h-3z'],
    ['kc', 'Knowledge Center', 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'],
    ['usage', 'SDK & CLI usage', 'M4 17l6-6-6-6M12 19h8'],
    ['api', 'API reference', 'M16 18l6-6-6-6M8 6l-6 6 6 6']
  ];
  var css = '' +
    '#vy-appbar{position:fixed;left:0;right:0;bottom:0;height:0;z-index:70;display:flex;justify-content:center;pointer-events:none;font-family:Inter,system-ui,sans-serif}' +
    'body:has(#nano-foot) #vy-appbar{bottom:34px}' +   /* Nano: sit above its relay-tunnel footer bar */
    '#vy-appbar::before{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:#0f121c}' +   /* the line along the bottom edge */
    '#vy-appbar .vy-notch{width:auto !important;max-width:none !important;overflow:visible !important;pointer-events:auto;position:absolute;bottom:0;height:44px;padding:0 44px;display:flex;align-items:center;gap:2px;isolation:isolate}' +
    '#vy-appbar .vy-notch::before{content:"";position:absolute;inset:0;z-index:-1;background:#0f121c;clip-path:polygon(30px 0,calc(100% - 30px) 0,100% 100%,0 100%)}' +
    '#vy-appbar .vy-notch .vy-sep{width:1px;height:20px;background:rgba(255,255,255,.18);margin:0 6px}' +
    '#vy-appbar #disk-widget-slot{position:relative !important;top:auto !important;right:auto !important;left:auto !important;z-index:5 !important;display:inline-block}' +
    '#vy-appbar #disk-widget-slot .disk-chip{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 10px;font:400 12px Inter,system-ui,sans-serif;border:0 !important;border-radius:8px;background:transparent !important;color:#b4b8cc !important;box-shadow:none !important}' +
    '#vy-appbar #disk-widget-slot .disk-chip:hover,#vy-appbar #disk-widget-slot.open .disk-chip{background:rgba(255,255,255,.08) !important;color:#fff !important}' +
    '#vy-appbar #disk-widget-slot .disk-chip *{color:inherit !important;font:inherit !important}' +
    '#vy-appbar #disk-widget-slot .disk-chip .disk-chip-caret{display:none}' +
    '#vy-appbar #disk-widget-slot .disk-popover{top:auto !important;bottom:calc(100% + 14px) !important;right:auto !important;left:50% !important;transform:translateX(-50%)}' +
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
    '#vy-modal.sm .box{width:min(560px,94vw);height:min(660px,92vh);background:transparent;box-shadow:none}#vy-modal.sm .hd{display:none}' +
    '#vy-modal iframe{flex:1;border:0;width:100%}' +
    '#vy-appbar .vy-notch a.vy-acct-act{color:#fff}' +
    '#vy-appbar .vy-notch a .vy-n{opacity:.75;font-size:11px}' +
    '@media(max-width:900px){#vy-appbar .vy-notch a span{display:none}#vy-appbar .vy-cloud{display:none}}';
  function build() {
    if (document.getElementById('vy-appbar')) return;
    var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    var bar = document.createElement('div'); bar.id = 'vy-appbar';
    var links = ITEMS.map(function (i) {
      return '<a href="' + CL + '#' + i[0] + '" data-v="' + i[0] + '" title="' + i[1] + '"><svg viewBox="0 0 24 24"><path d="' + i[2] + '"/></svg><span>' + i[1] + '</span></a>';
    }).join('');
    bar.innerHTML = '<div class="vy-notch" role="navigation" aria-label="Appliance">' + links + '</div>';
    document.body.appendChild(bar);
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
    function openView(view, title, small) {
      m.querySelector('#vy-modal-t').textContent = title;
      m.classList.toggle('sm', !!small);
      fr.src = CL + '?embed=1' + (view === 'acct' ? '&acct=1' : '') + '#' + (view === 'acct' ? 'spaces' : view);
      m.classList.add('open');
    }
    // ---- account group (right of the disk chip): Activate appliance · GitHub ★ · Sign out
    var nav = bar.querySelector('.vy-notch'), NANO = CL !== '/clouds', st = { tier: 'free', trial: null }, authed = false;
    var sep2 = document.createElement('span'); sep2.className = 'vy-sep'; nav.appendChild(sep2);
    var act = document.createElement('a'); act.href = '#'; act.setAttribute('data-act', 'activate'); act.className = 'vy-acct-act';
    var gh = document.createElement('a'); gh.href = 'https://github.com/vyomi-cloud/appliance'; gh.target = '_blank'; gh.rel = 'noopener noreferrer'; gh.title = 'Star Vyomi on GitHub';
    gh.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span>GitHub <b class="vy-n"></b></span>';
    var so = document.createElement('a'); so.href = '#'; so.setAttribute('data-act', 'signout'); so.title = 'Sign out'; so.style.display = 'none';
    so.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg><span>Sign out</span>';
    nav.appendChild(act); nav.appendChild(gh); nav.appendChild(so);
    function paintAcct() {
      var t = st.trial, ic = '<svg viewBox="0 0 24 24"><path d="M9 12l2 2 4-4M12 2l2.4 1.8 3-.2.9 2.9 2.5 1.7-.9 2.9.9 2.9-2.5 1.7-.9 2.9-3-.2L12 22l-2.4-1.8-3 .2-.9-2.9-2.5-1.7.9-2.9-.9-2.9 2.5-1.7.9-2.9 3 .2z"/></svg>';
      if (t && t.active) { act.title = 'Free trial running — upgrade'; act.setAttribute('data-act', 'upgrade'); act.innerHTML = ic + '<span>' + String(st.tier || 'pro').toUpperCase() + ' trial · Upgrade</span>'; }
      else if (t && t.ended) { act.title = 'Your free trial has ended — upgrade'; act.setAttribute('data-act', 'upgrade'); act.innerHTML = ic + '<span>Trial ended · Upgrade</span>'; }
      else if (st.tier && st.tier !== 'free') { act.title = 'Appliance activated — re-bind to a different account'; act.setAttribute('data-act', 'activate'); act.innerHTML = ic + '<span>Activated · ' + String(st.tier).toUpperCase() + '</span>'; }
      else { act.title = 'Sign in to activate — starts your free 14-day Pro trial'; act.setAttribute('data-act', 'activate'); act.innerHTML = ic + '<span>Activate appliance</span>'; }
      so.style.display = (authed || (!NANO && st.tier && st.tier !== 'free') || (!NANO && t && t.activated)) ? '' : 'none';
    }
    function refreshAcct() {
      fetch('/api/license/status', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        st = { tier: d && d.active_tier, trial: d && d.trial, upgrade: d && d.trial && d.trial.upgrade_url }; paintAcct();
      }).catch(function () { paintAcct(); });
      if (NANO) { try { var x = new XMLHttpRequest(); x.open('GET', '/api/auth/me', true); x.withCredentials = true;
        x.onload = function () { try { authed = !!JSON.parse(x.responseText).authenticated; } catch (e) {} paintAcct(); }; x.send(); } catch (e) {} }
    }
    paintAcct(); refreshAcct();
    try {                                                    // live GitHub star count (cached for the tab session, same key as the Spaces page)
      var c = JSON.parse(sessionStorage.getItem('vyomi.community.stars') || 'null'), nEl = gh.querySelector('.vy-n');
      var show = function (n) { nEl.textContent = '★ ' + (n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : n); };
      if (c && c.count != null && Date.now() - c.at < 3600e3) show(c.count);
      else fetch('https://api.github.com/repos/vyomi-cloud/appliance').then(function (r) { return r.json(); }).then(function (j) {
        if (j && typeof j.stargazers_count === 'number') { show(j.stargazers_count); try { sessionStorage.setItem('vyomi.community.stars', JSON.stringify({ count: j.stargazers_count, at: Date.now() })); } catch (e) {} }
      }).catch(function () {});
    } catch (e) {}
    function signOut() {
      if (!confirm('Sign out? ' + (NANO ? '' : 'Your tier reverts to Free until you re-activate.'))) return;
      var done = function () { if (NANO) location.href = '/dashboard'; else location.reload(); };
      try { var l = new XMLHttpRequest(); l.open('POST', '/api/auth/logout', true); l.withCredentials = true; l.onloadend = done; l.send(); } catch (e) { done(); }
    }
    window.addEventListener('message', function (e) { if (e.data && e.data.vy === 'close-modal') { close(); refreshAcct(); } });
    nav.addEventListener('click', function (e) {
      var l = e.target.closest('a'); if (!l) return;
      var ac = l.getAttribute('data-act');
      if (ac === 'activate') { e.preventDefault(); openView('acct', 'Activate this appliance', true); return; }
      if (ac === 'upgrade') { e.preventDefault(); window.open((st.trial && st.trial.upgrade_url) || 'https://vyomi.cloud/pricing', '_blank', 'noopener'); return; }
      if (ac === 'signout') { e.preventDefault(); signOut(); return; }
      if (!l.getAttribute('data-v')) return;
      e.preventDefault();
      openView(l.getAttribute('data-v'), l.title, false);
    });
    // The vyomi logo in a console header opens the same Spaces dialog (never the old full-page UI).
    document.addEventListener('click', function (e) {
      var lg = e.target.closest && e.target.closest('a.vy-co'); if (!lg) return;
      e.preventDefault(); e.stopPropagation(); openView('spaces', 'Spaces', false);
    }, true);
  }
  if (document.body) build(); else document.addEventListener('DOMContentLoaded', build);
})();
