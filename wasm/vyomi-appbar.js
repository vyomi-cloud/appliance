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
    '#vy-acct-btn{flex:none;width:30px;height:30px;overflow:hidden;margin-left:8px;padding:0;border:0;border-radius:50%;background:#4d8cf3;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 0 0 2px rgba(255,255,255,.25)}' +
    '#vy-acct-btn:hover,#vy-acct-btn[aria-expanded=true]{background:#2f6fdc}' +
    '#vy-acct-btn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}' +
    '#vy-acct-menu{position:fixed;z-index:250;min-width:250px;display:none;padding:6px;background:#fff;color:#101828;border:1px solid #e4e7ec;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.28);font-family:Inter,system-ui,sans-serif}' +
    '#vy-acct-menu.open{display:block}' +
    '#vy-acct-menu .vy-who{display:flex;align-items:center;gap:10px;padding:8px 12px 10px;font-size:12px;color:#667085;word-break:break-all}' +
    '#vy-acct-menu .vy-av{width:40px;height:40px;flex:none;border-radius:50%;overflow:hidden;background:#4d8cf3;color:#fff;display:inline-flex;align-items:center;justify-content:center;font:700 16px Inter,system-ui,sans-serif}' +
    '#vy-acct-menu .vy-av img,#vy-acct-btn img{width:100%;height:100%;object-fit:cover;border-radius:50%;display:block}' +
    '#vy-acct-menu .vy-av svg{width:22px;height:22px;fill:none;stroke:#fff;stroke-width:2}' +
    '#vy-acct-menu .vy-wt{display:flex;flex-direction:column;min-width:0}#vy-acct-menu .vy-wt b{font-size:14px;color:#101828}' +
    '#vy-acct-menu .vy-wt small{font-size:12px;color:#667085}#vy-acct-menu .vy-wt .vy-via{color:#475467;font-weight:600}' +
    '#vy-acct-btn .vy-ini{font:700 13px Inter,system-ui,sans-serif}' +
    '#vy-acct-menu .vy-hr{height:1px;background:#e4e7ec;margin:4px 0}' +
    '#vy-acct-menu a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;font-size:13.5px;color:#101828;text-decoration:none;cursor:pointer}' +
    '#vy-acct-menu a:hover{background:#f2f4f7}' +
    '#vy-acct-menu a svg{width:17px;height:17px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;color:#475467}' +
    '#vy-acct-menu a .vy-n{margin-left:auto;font-weight:600;font-size:12px;color:#475467}' +
    '#vy-acct-menu a[data-act=signout]{color:#b42318}#vy-acct-menu a[data-act=signout] svg{color:#b42318}' +
    /* ---- per-cloud look of the account menu + sign-out confirmation (follows each console's own account UX) ---- */
    '#vy-so{position:fixed;inset:0;z-index:400;background:rgba(15,20,30,.55);display:none;align-items:center;justify-content:center}#vy-so.open{display:flex}' +
    '#vy-so .dlg{width:min(440px,92vw);background:#fff;color:#16191f;box-shadow:0 12px 40px rgba(0,0,0,.35)}' +
    '#vy-so h4{margin:0;font-size:18px;font-weight:700}#vy-so p{margin:10px 0 0;font-size:14px;line-height:1.5;color:#414d5c}' +
    '#vy-so .row{display:flex;justify-content:flex-end;gap:10px;margin-top:22px}#vy-so button{cursor:pointer;font:inherit;font-size:14px;font-weight:700}' +
    /* AWS: Cloudscape — navy chrome, 2px radii, orange primary */
    '#vy-acct-btn.vy-aws{background:#545b64;box-shadow:none;border-radius:50%}#vy-acct-btn.vy-aws:hover{background:#687078}' +
    '#vy-acct-menu.vy-aws{min-width:300px;padding:0;border:1px solid #d5dbdb;border-radius:2px;box-shadow:0 1px 1px 0 rgba(0,28,36,.3),1px 1px 1px 0 rgba(0,28,36,.15),-1px 1px 1px 0 rgba(0,28,36,.15);font-family:"Amazon Ember","Helvetica Neue",Arial,sans-serif;color:#16191f}' +
    '#vy-acct-menu.vy-aws .vy-who{padding:16px 20px;border-bottom:1px solid #eaeded;background:#fafafa}#vy-acct-menu.vy-aws .vy-av{width:44px;height:44px;background:#545b64}' +
    '#vy-acct-menu.vy-aws a{padding:10px 20px;border-radius:0;font-size:14px}#vy-acct-menu.vy-aws a:hover{background:#f2f3f3}' +
    '#vy-acct-menu.vy-aws .vy-hr{margin:0;background:#eaeded}#vy-acct-menu.vy-aws a[data-act=signout]{margin:12px 20px;padding:6px 20px;justify-content:center;background:#ec7211;color:#fff;border-radius:2px;font-weight:700}' +
    '#vy-acct-menu.vy-aws a[data-act=signout]:hover{background:#eb5f07}#vy-acct-menu.vy-aws a[data-act=signout] svg{color:#fff}' +
    '#vy-so.vy-aws .dlg{border-radius:2px;padding:20px 24px;font-family:"Amazon Ember","Helvetica Neue",Arial,sans-serif}#vy-so.vy-aws .go{background:#ec7211;color:#fff;border:2px solid #ec7211;border-radius:2px;padding:4px 20px}#vy-so.vy-aws .no{background:#fff;color:#545b64;border:2px solid #545b64;border-radius:2px;padding:4px 20px}' +
    /* Google Cloud: Material 3 account card (Google account chooser) */
    '#vy-acct-btn.vy-gcp{background:#1a73e8;box-shadow:none}' +
    '#vy-acct-menu.vy-gcp{width:340px;min-width:0;padding:12px;background:#e9eef6;border:0;border-radius:28px;box-shadow:0 4px 8px 3px rgba(60,64,67,.15),0 1px 3px rgba(60,64,67,.3);font-family:"Google Sans",Roboto,Arial,sans-serif}' +
    '#vy-acct-menu.vy-gcp .vy-who{flex-direction:column;text-align:center;padding:14px 8px 12px;gap:8px;align-items:center}#vy-acct-menu.vy-gcp .vy-av{width:72px;height:72px;font-size:28px;background:#1a73e8}#vy-acct-menu.vy-gcp .vy-av svg{width:38px;height:38px}' +
    '#vy-acct-menu.vy-gcp .vy-wt{align-items:center}#vy-acct-menu.vy-gcp .vy-wt b{font-size:16px;font-weight:500;color:#1f1f1f}#vy-acct-menu.vy-gcp .vy-wt small{color:#444746}' +
    '#vy-acct-menu.vy-gcp a{background:#fff;padding:12px 16px;border-radius:4px;margin-bottom:2px;font-size:14px;color:#1f1f1f}#vy-acct-menu.vy-gcp a:hover{background:#f6f8fc}' +
    '#vy-acct-menu.vy-gcp a[data-act=activate],#vy-acct-menu.vy-gcp a[data-act=upgrade]{border-radius:16px 16px 4px 4px}#vy-acct-menu.vy-gcp a[href*=github]{border-radius:4px 4px 16px 16px}' +
    '#vy-acct-menu.vy-gcp .vy-hr{display:none}#vy-acct-menu.vy-gcp a[data-act=signout]{margin:8px 0 2px;justify-content:center;border-radius:100px;border:1px solid #747775;background:transparent;color:#1f1f1f;font-weight:500}#vy-acct-menu.vy-gcp a[data-act=signout]:hover{background:#fff}#vy-acct-menu.vy-gcp a[data-act=signout] svg{color:#444746}' +
    '#vy-so.vy-gcp .dlg{border-radius:28px;padding:24px;font-family:"Google Sans",Roboto,Arial,sans-serif;color:#1f1f1f}#vy-so.vy-gcp h4{font-weight:400;font-size:24px}#vy-so.vy-gcp p{color:#444746}#vy-so.vy-gcp button{background:none;border:0;color:#0b57d0;padding:10px 16px;border-radius:100px;font-weight:500}#vy-so.vy-gcp button:hover{background:#e9eef6}#vy-so.vy-gcp .go{background:#0b57d0;color:#fff}#vy-so.vy-gcp .go:hover{background:#0a4cb8}' +
    /* Azure: Fluent flyout — avatar left, "Sign out" link top-right */
    '#vy-acct-btn.vy-azure{background:#0078d4;box-shadow:none;border-radius:50%}#vy-acct-btn.vy-azure:hover{background:#106ebe}' +
    '#vy-acct-menu.vy-azure{width:340px;min-width:0;padding:0;border:1px solid #edebe9;border-radius:2px;box-shadow:0 6.4px 14.4px rgba(0,0,0,.132),0 1.2px 3.6px rgba(0,0,0,.108);font-family:"Segoe UI",system-ui,sans-serif;color:#323130}' +
    '#vy-acct-menu.vy-azure .vy-who{padding:20px 20px 16px;gap:14px;align-items:center;border-bottom:1px solid #edebe9}#vy-acct-menu.vy-azure .vy-av{width:56px;height:56px;background:#0078d4;font-size:22px}#vy-acct-menu.vy-azure .vy-wt{padding-right:70px}' +
    '#vy-acct-menu.vy-azure .vy-wt b{font-size:16px;font-weight:600}#vy-acct-menu.vy-azure a{padding:10px 20px;border-radius:0;font-size:14px;color:#323130}#vy-acct-menu.vy-azure a:hover{background:#f3f2f1}' +
    '#vy-acct-menu.vy-azure .vy-hr{display:none}#vy-acct-menu.vy-azure a[data-act=signout]{position:absolute;top:14px;right:14px;padding:4px 8px;color:#0078d4;font-size:13px}#vy-acct-menu.vy-azure a[data-act=signout]:hover{background:transparent;text-decoration:underline}#vy-acct-menu.vy-azure a[data-act=signout] svg{display:none}' +
    '#vy-so.vy-azure .dlg{border-radius:2px;padding:24px;font-family:"Segoe UI",system-ui,sans-serif;color:#323130}#vy-so.vy-azure h4{font-weight:600}#vy-so.vy-azure button{border-radius:2px;padding:6px 20px;font-weight:600}#vy-so.vy-azure .go{background:#0078d4;color:#fff;border:1px solid #0078d4}#vy-so.vy-azure .no{background:#fff;color:#323130;border:1px solid #8a8886}' +
    '@media(max-width:900px){#vy-appbar .vy-notch a span{display:none}#vy-appbar .vy-cloud{display:none}}';
  function build() {
    if (document.getElementById('vy-appbar')) return;
    // The drawer is fixed over the bottom 44px: reserve that strip so nothing is hidden or unclickable under it
    // (a 1280x720 window put e.g. the APIM "Metrics" sub-tab right under the drawer).
    var RES = { aws: '.page{min-height:calc(100vh - 40px - 36px - 44px) !important}',
                gcp: '.body{min-height:calc(100vh - 56px - 44px) !important}',
                azure: '.body{height:calc(100vh - 48px - 44px) !important}#blade{bottom:44px !important;height:auto !important}' };
    var st = document.createElement('style'); st.textContent = css + (RES[cloud] || ''); document.head.appendChild(st);
    if (cloud !== 'azure' && !document.getElementById('vy-spacer')) { var spc = document.createElement('div'); spc.id = 'vy-spacer'; spc.style.cssText = 'height:44px;flex:none'; document.body.appendChild(spc); }
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
    // ---- account menu: a button in the console's main header (top-right) -> Activate appliance · GitHub ★ · Sign out
    var nav = bar.querySelector('.vy-notch'), NANO = CL !== '/clouds', st = { tier: 'free', trial: null }, authed = false, who = '', prof = { email: '', name: '', avatar: '', via: '' };
    function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    var PERSON = '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/></svg>';
    var hdr = document.querySelector('header'), host = document.querySelector('header .right') || (function () { var h = document.querySelectorAll('header .hicons'); return h.length ? h[h.length - 1] : hdr; })();
    var ab = document.getElementById('avatarBtn'); if (ab && ab.classList.contains('avatar')) ab.style.display = 'none';   // GCP's inert "U" avatar: ours replaces it
    var btn = document.createElement('button'); btn.type = 'button'; btn.id = 'vy-acct-btn'; btn.className = 'vy-' + cloud; btn.title = 'Vyomi account'; btn.setAttribute('aria-haspopup', 'true'); btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = PERSON;
    if (host) host.appendChild(btn);
    var menu = document.createElement('div'); menu.id = 'vy-acct-menu'; menu.className = 'vy-' + cloud; menu.setAttribute('role', 'menu');
    var who$ = document.createElement('div'); who$.className = 'vy-who';
    var act = document.createElement('a'); act.href = '#'; act.setAttribute('data-act', 'activate'); act.setAttribute('role', 'menuitem');
    var gh = document.createElement('a'); gh.href = 'https://github.com/vyomi-cloud/appliance'; gh.target = '_blank'; gh.rel = 'noopener noreferrer'; gh.setAttribute('role', 'menuitem');
    gh.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span>Star on GitHub</span><b class="vy-n"></b>';
    var so = document.createElement('a'); so.href = '#'; so.setAttribute('data-act', 'signout'); so.setAttribute('role', 'menuitem'); so.style.display = 'none';
    so.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg><span>Sign out</span>';
    var hr = document.createElement('div'); hr.className = 'vy-hr';
    [who$, act, gh, hr, so].forEach(function (n) { menu.appendChild(n); }); document.body.appendChild(menu);
    function closeMenu() { menu.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (menu.classList.contains('open')) { closeMenu(); return; }
      var r = btn.getBoundingClientRect(); menu.style.top = (r.bottom + 8) + 'px'; menu.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
      menu.classList.add('open'); btn.setAttribute('aria-expanded', 'true');
    });
    document.addEventListener('click', function (e) { if (!menu.contains(e.target)) closeMenu(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });
    function paintAcct() {
      var t = st.trial, ic = '<svg viewBox="0 0 24 24"><path d="M9 12l2 2 4-4M12 2l2.4 1.8 3-.2.9 2.9 2.5 1.7-.9 2.9.9 2.9-2.5 1.7-.9 2.9-3-.2L12 22l-2.4-1.8-3 .2-.9-2.9-2.5-1.7.9-2.9-.9-2.9 2.5-1.7.9-2.9 3 .2z"/></svg>';
      if (t && t.active) { act.title = 'Free trial running — upgrade'; act.setAttribute('data-act', 'upgrade'); act.innerHTML = ic + '<span>' + String(st.tier || 'pro').toUpperCase() + ' trial · Upgrade</span>'; }
      else if (t && t.ended) { act.title = 'Your free trial has ended — upgrade'; act.setAttribute('data-act', 'upgrade'); act.innerHTML = ic + '<span>Trial ended · Upgrade</span>'; }
      else if (st.tier && st.tier !== 'free') { act.title = 'Appliance activated — re-bind to a different account'; act.setAttribute('data-act', 'activate'); act.innerHTML = ic + '<span>Activated · ' + String(st.tier).toUpperCase() + '</span>'; }
      else { act.title = 'Sign in to activate — starts your free 14-day Pro trial'; act.setAttribute('data-act', 'activate'); act.innerHTML = ic + '<span>Activate appliance</span>'; }
      var em = prof.email || who, nm = prof.name || (em ? em.split('@')[0] : ''), signed = authed || (!NANO && st.tier && st.tier !== 'free');
      var av = prof.avatar ? '<img src="' + esc(prof.avatar) + '" alt="" referrerpolicy="no-referrer">' : (em ? '<span class="vy-ini">' + esc(em.charAt(0).toUpperCase()) + '</span>' : PERSON);
      btn.innerHTML = av; btn.title = signed && em ? 'Vyomi account \u2014 ' + em : 'Vyomi account';
      who$.innerHTML = signed ? '<span class="vy-av">' + av + '</span><span class="vy-wt"><b>' + esc(nm || 'Signed in') + '</b>' + (em && em !== nm ? '<small>' + esc(em) + '</small>' : '') + (prof.via ? '<small class="vy-via">Signed in with ' + esc(prof.via) + '</small>' : '') + '</span>' : '<span class="vy-wt"><small>Not signed in</small></span>';
      so.style.display = (authed || (!NANO && st.tier && st.tier !== 'free') || (!NANO && t && t.activated)) ? '' : 'none';
    }
    function refreshAcct() {
      fetch('/api/license/status', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        st = { tier: d && d.active_tier, trial: d && d.trial }; who = (d && (d.issued_to || (d.license && (d.license.email || d.license.issued_to)))) || who; paintAcct();
      }).catch(function () { paintAcct(); });
      if (NANO) { try { var x = new XMLHttpRequest(); x.open('GET', '/api/auth/me', true); x.withCredentials = true;
        x.onload = function () { try { var j = JSON.parse(x.responseText); authed = !!j.authenticated; if (j.email) { who = j.email; prof.email = j.email; } prof.avatar = j.avatar_url || ''; prof.name = j.name || j.github_login || ''; prof.via = j.provider || ((j.github_login || /githubusercontent|github\.com/.test(j.avatar_url || '')) ? 'GitHub' : ''); } catch (e) {} paintAcct(); }; x.send(); } catch (e) {} }
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
    var so$ = document.createElement('div'); so$.id = 'vy-so'; so$.className = 'vy-' + cloud;
    so$.innerHTML = '<div class="dlg" role="alertdialog" aria-modal="true" aria-labelledby="vy-so-t"><h4 id="vy-so-t">Sign out of Vyomi?</h4><p></p><div class="row"><button type="button" class="no">Cancel</button><button type="button" class="go">Sign out</button></div></div>';
    document.body.appendChild(so$);
    function closeSo() { so$.classList.remove('open'); }
    so$.addEventListener('click', function (e) { if (e.target === so$) closeSo(); });
    so$.querySelector('.no').addEventListener('click', closeSo);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeSo(); });
    function signOut() {
      so$.querySelector('p').textContent = NANO ? 'You will be signed out of your Vyomi account on this device.' : 'Your tier reverts to Free until you re-activate this appliance.';
      so$.classList.add('open'); so$.querySelector('.go').focus();
    }
    so$.querySelector('.go').addEventListener('click', function () {
      closeSo();
      var done = function () { if (NANO) location.href = '/dashboard'; else location.reload(); };
      try { var l = new XMLHttpRequest(); l.open('POST', '/api/auth/logout', true); l.withCredentials = true; l.onloadend = done; l.send(); } catch (e) { done(); }
    });
    window.addEventListener('message', function (e) { if (e.data && e.data.vy === 'close-modal') { close(); refreshAcct(); } });
    function onItem(e) {
      var l = e.target.closest('a'); if (!l) return; if (menu.contains(l)) closeMenu();
      var ac = l.getAttribute('data-act');
      if (ac === 'activate') { e.preventDefault(); openView('acct', 'Activate this appliance', true); return; }
      if (ac === 'upgrade') { e.preventDefault(); window.open((st.trial && st.trial.upgrade_url) || 'https://vyomi.cloud/pricing', '_blank', 'noopener'); return; }
      if (ac === 'signout') { e.preventDefault(); signOut(); return; }
      if (!l.getAttribute('data-v')) return;
      e.preventDefault();
      openView(l.getAttribute('data-v'), l.title, false);
    }
    nav.addEventListener('click', onItem); menu.addEventListener('click', onItem);
    // The vyomi logo in a console header opens the same Spaces dialog (never the old full-page UI).
    document.addEventListener('click', function (e) {
      var lg = e.target.closest && e.target.closest('a.vy-co'); if (!lg) return;
      e.preventDefault(); e.stopPropagation(); openView('spaces', 'Spaces', false);
    }, true);
  }
  if (document.body) build(); else document.addEventListener('DOMContentLoaded', build);
})();
