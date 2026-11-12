/* Nano disk chip (v2.0.4 legacy-console widget, shared by the v4 consoles). Creates #disk-widget-slot
   synchronously (vyomi-appbar.js, loaded defer, then moves it into the drawer), injects the chip/popover CSS and
   renders GET /api/runtime/disk-health (answered by the Nano service worker), refreshing every 30s.
   Ported verbatim from wasm/aws-console.html; one file for all clouds. */
(function () {
  if (window.__vyDiskChip) return; window.__vyDiskChip = 1;
  var st = document.createElement('style');
  st.id = 'vy-disk-chip-css';
  st.textContent = `/* ── Disk chip (v2.0.4) — small top-right pill; click to maximize ── */
#disk-widget-slot {
  position: fixed !important;
  top: 56px !important;
  right: 16px !important;
  padding: 0 !important;
  margin: 0 !important;
  max-width: none !important;
  z-index: 80 !important;
  width: auto !important;
}
#disk-widget-slot .disk-chip {
  display: inline-flex; align-items: center; gap: 8px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 999px;
  padding: 6px 12px 6px 8px;
  font-size: 12px; font-weight: 600; color: #1a2330;
  cursor: pointer; font-family: inherit;
  box-shadow: 0 2px 8px rgba(15,27,45,0.10);
  transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}
#disk-widget-slot .disk-chip:hover {
  border-color: #94a3b8;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(15,27,45,0.16);
}
#disk-widget-slot .disk-chip .disk-chip-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16,185,129,0.18);
}
#disk-widget-slot .disk-chip.warn   .disk-chip-dot { background: #f59e0b; box-shadow: 0 0 0 3px rgba(245,158,11,0.20); }
#disk-widget-slot .disk-chip.danger .disk-chip-dot { background: #ef4444; box-shadow: 0 0 0 3px rgba(239,68,68,0.20); animation: chipPulse 1400ms ease-in-out infinite; }
@keyframes chipPulse {
  0%,100% { box-shadow: 0 0 0 3px rgba(239,68,68,0.20); }
  50%     { box-shadow: 0 0 0 6px rgba(239,68,68,0.10); }
}
#disk-widget-slot .disk-chip .disk-chip-pct { font-variant-numeric: tabular-nums; }
#disk-widget-slot .disk-chip .disk-chip-caret { font-size: 10px; color: #5f6b7a; }
#disk-widget-slot .disk-popover {
  display: none;
  position: absolute; top: calc(100% + 6px); right: 0;
  width: 320px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 12px 30px rgba(15,27,45,0.18);
  border: 1px solid #e7e7e9;
  overflow: hidden;
}
#disk-widget-slot.open .disk-popover { display: block; }
#disk-widget-slot .disk-popover .dp-close {
  position: absolute; top: 8px; right: 10px;
  background: none; border: 0; font-size: 22px; color: #5f6b7a;
  cursor: pointer; line-height: 1; padding: 2px 6px;
  z-index: 1;
}
#disk-widget-slot .disk-popover .dp-close:hover { color: #0f1b2d; }`;
  document.head.appendChild(st);
  if (!document.getElementById('disk-widget-slot')) {
    var s = document.createElement('div'); s.id = 'disk-widget-slot';
    (document.body || document.documentElement).appendChild(s);
  }
let _diskWidgetState = null;

function _diskStatusToClass(s) {
  if (s === "warn") return "warn";
  if (s === "freeze" || s === "danger") return "danger";
  return "";
}
function _toggleDiskPopover() {
  const el = document.getElementById("disk-widget-slot");
  if (!el) return;
  el.classList.toggle("open");
}
function _closeDiskPopover(ev) {
  if (ev) { ev.stopPropagation(); }
  const el = document.getElementById("disk-widget-slot");
  if (el) el.classList.remove("open");
}
function _wrapWithChip(cardHtml, d) {
  const disk = d.disk || {};
  const pct = Math.round(disk.pct_used || 0);
  const klass = _diskStatusToClass(d.status);
  return (
    '<button class="disk-chip ' + klass + '" type="button" onclick="_toggleDiskPopover()" title="Click to expand disk health">'+
      '<span class="disk-chip-dot"></span>'+
      '<span>Disk</span>'+
      '<span class="disk-chip-pct">' + pct + '%</span>'+
      '<span class="disk-chip-caret">▾</span>'+
    '</button>'+
    '<div class="disk-popover" onclick="event.stopPropagation()">'+
      '<button class="dp-close" type="button" onclick="_closeDiskPopover(event)" title="Minimize">×</button>'+
      cardHtml +
    '</div>'
  );
}
// Close popover when clicking outside the chip
document.addEventListener("click", function(ev) {
  const el = document.getElementById("disk-widget-slot");
  if (!el || !el.classList.contains("open")) return;
  if (!el.contains(ev.target)) el.classList.remove("open");
});

function renderDiskWidget(d) {
  const slot = document.getElementById("disk-widget-slot");
  if (!slot) return;
  if (!d || !d.available) {
    slot.innerHTML = "";
    return;
  }
  _diskWidgetState = d;
  const disk = d.disk || {};
  const pct = Math.round(disk.pct_used || 0);
  const tier = String(d.tier || "free").toUpperCase();
  const status = d.status;  // green | warn | freeze
  const accent = status === "green" ? "#10b981"
               : status === "warn"  ? "#f59e0b"
               :                      "#ef4444";
  const bg = status === "green" ? "#fff"
           : status === "warn"  ? "#fffbeb"
           :                      "#fef2f2";
  const statusLabel = status === "green" ? "Healthy"
                    : status === "warn"  ? "Warning · " + pct + "% used"
                    :                      "Critical · " + pct + "% used — new launches will be refused";
  // Accept both new (pro/max) and legacy (student/developer) tier names.
  const canGrow = ["pro", "max", "enterprise", "student", "developer"].includes(String(d.tier || "").toLowerCase());
  slot.innerHTML = _wrapWithChip('<div style="background:' + bg + ';border:1.5px solid ' + accent + ';border-radius:10px;padding:12px 16px;margin-bottom:12px">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">' +
        '<div style="font-size:13.5px;font-weight:600;color:#1f2937">' +
          'Appliance disk' +
          '<span style="display:inline-block;margin-left:8px;padding:2px 8px;background:#ede9fe;color:#6d28d9;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:0.05em">' + tier + '</span>' +
        '</div>' +
        '<div style="font-size:12px;font-weight:600;color:' + accent + '">' + statusLabel + '</div>' +
      '</div>' +
      '<div style="margin-bottom:10px">' +
        '<div style="height:8px;background:#f3f4f6;border-radius:999px;overflow:hidden">' +
          '<div style="height:100%;width:' + pct + '%;background:' + accent + ';transition:width 0.3s"></div>' +
        '</div>' +
        '<div style="font-size:11px;color:#6b7280;margin-top:6px">' +
          (+disk.used_gb).toFixed(2) + " / " + (+disk.total_gb).toFixed(2) + " GB · " + (+disk.avail_gb).toFixed(2) + " GB free" +
        '</div>' +
      '</div>' +
      '<div style="display:flex;gap:8px">' +
        '<button class="btn" onclick="openDiskCleanup()" style="font-size:12px;padding:6px 12px">Free up space →</button>' +
        (canGrow
          ? '<button class="btn" onclick="openDiskGrow()" style="font-size:12px;padding:6px 12px;background:#fff;color:#1a2330;border:1px solid #d8e0ea">Grow disk</button>'
          : '') +
      '</div>' +
    '</div>', d);
}
// Nano is served under /nano/ on the portal: root-relative /api/* must be sent to the in-page service worker (scope /nano/), as the
// legacy consoles' fetch shim does. Offline/dev (served from /) keeps the plain path.
function _api(u) { var m = location.pathname.match(/^(.*\/nano)\//); return m && u.charAt(0) === "/" && u.indexOf(m[1] + "/") !== 0 ? m[1] + u : u; }
async function fetchDiskHealth() {
  try {
    const r = await fetch(_api("/api/runtime/disk-health"));
    const d = await r.json();
    renderDiskWidget(d);
  } catch (e) { /* keep last render */ }
}
async function openDiskCleanup() {
  let html = '<div class="empty">Scanning disk…</div>';
  const modal = document.createElement("div");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.5);display:flex;align-items:center;justify-content:center;z-index:9999";
  modal.innerHTML = '<div style="background:#fff;border-radius:10px;max-width:640px;width:90%;max-height:80vh;display:flex;flex-direction:column;overflow:hidden">' +
    '<div style="padding:16px 20px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center">' +
      '<h3 style="margin:0;font-size:16px">Free up appliance disk</h3>' +
      '<button onclick="this.closest(\'.modal-disk\').remove()" style="background:none;border:0;font-size:24px;cursor:pointer">×</button>' +
    '</div>' +
    '<div id="cleanup-body" style="padding:20px;overflow-y:auto;flex:1">' + html + '</div>' +
    '<div id="cleanup-foot" style="padding:12px 20px;border-top:1px solid #e5e7eb;display:flex;gap:8px;justify-content:flex-end"></div>' +
    '</div>';
  modal.className = "modal-disk";
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  document.body.appendChild(modal);
  try {
    const r = await fetch(_api("/api/runtime/disk-cleanup/suggestions"));
    const d = await r.json();
    const body = modal.querySelector("#cleanup-body");
    const foot = modal.querySelector("#cleanup-foot");
    body.innerHTML = '<div style="margin-bottom:12px;font-size:13px;color:#475569">Select what to clean. All options below are safe — they never affect running workloads.</div>' +
      (d.suggestions || []).map((s, i) =>
        '<label style="display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #f1f5f9;cursor:pointer">' +
          '<input type="checkbox" data-key="' + s.key + '"' + (s.safe ? ' checked' : '') + ' style="margin-top:3px">' +
          '<div style="flex:1">' +
            '<div style="font-size:13.5px;font-weight:500">' + s.label +
              (s.est_reclaim_gb ? ' <span style="color:#059669;font-weight:600;margin-left:6px">≈ ' + s.est_reclaim_gb + ' GB</span>' : '') +
            '</div>' +
            '<div style="font-size:12px;color:#6b7280;margin-top:2px">' + s.detail + '</div>' +
          '</div>' +
        '</label>'
      ).join("");
    foot.innerHTML =
      '<button class="btn" onclick="this.closest(\'.modal-disk\').remove()" style="padding:8px 14px;background:#fff;border:1px solid #d8e0ea;color:#1a2330">Cancel</button>' +
      '<button class="btn" id="cleanup-run" style="padding:8px 14px;background:#0f1b2d;color:#fff">Run cleanup</button>';
    foot.querySelector("#cleanup-run").onclick = async () => {
      const cats = [...body.querySelectorAll("input[type=checkbox]:checked")].map(i => i.dataset.key);
      foot.querySelector("#cleanup-run").textContent = "Running…";
      foot.querySelector("#cleanup-run").disabled = true;
      try {
        const r = await fetch(_api("/api/runtime/disk-cleanup/run"), {
          method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({categories: cats}),
        });
        const out = await r.json();
        body.innerHTML = '<div style="background:#ecfdf5;color:#047857;padding:10px 14px;border-radius:6px;margin-bottom:12px">✓ Cleanup complete.</div>' +
          '<pre style="background:#0f172a;color:#e2e8f0;padding:10px;border-radius:6px;font-size:11px;overflow:auto;max-height:300px">' +
            JSON.stringify(out, null, 2) + '</pre>';
        foot.innerHTML = '<button class="btn" onclick="this.closest(\'.modal-disk\').remove(); fetchDiskHealth()" style="padding:8px 14px;background:#0f1b2d;color:#fff">Done</button>';
      } catch (e) {
        body.innerHTML += '<div style="color:#b91c1c">Error: ' + e.message + '</div>';
      }
    };
  } catch (e) {
    modal.querySelector("#cleanup-body").innerHTML = '<div style="color:#b91c1c">Failed to load suggestions: ' + e.message + '</div>';
  }
}
function openDiskGrow() {
  const current = (_diskWidgetState && _diskWidgetState.disk && _diskWidgetState.disk.total_gb) || 30;
  const modal = document.createElement("div");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.5);display:flex;align-items:center;justify-content:center;z-index:9999";
  modal.className = "modal-disk";
  modal.innerHTML = '<div style="background:#fff;border-radius:10px;max-width:480px;width:90%">' +
    '<div style="padding:16px 20px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center">' +
      '<h3 style="margin:0;font-size:16px">Grow appliance disk</h3>' +
      '<button onclick="this.closest(\'.modal-disk\').remove()" style="background:none;border:0;font-size:24px;cursor:pointer">×</button>' +
    '</div>' +
    '<div id="grow-body" style="padding:20px">' +
      '<div style="margin-bottom:14px;font-size:13px;color:#475569">Current size: ' + current + ' GB. Pick a new size:</div>' +
      '<div style="display:flex;gap:8px;margin-bottom:14px">' +
        [60, 120, 240].map(g =>
          '<button class="grow-btn btn" data-gb="' + g + '" style="padding:6px 14px;background:#fff;color:#1a2330;border:1px solid #d8e0ea">' + g + ' GB</button>'
        ).join("") +
      '</div>' +
      '<div style="font-size:12px;color:#6b7280;line-height:1.5">Resize requires a brief restart of the appliance VM (≈30 s + 2 min boot). Running workloads will pause then resume.</div>' +
    '</div>' +
    '<div style="padding:12px 20px;border-top:1px solid #e5e7eb;display:flex;justify-content:flex-end">' +
      '<button class="btn" onclick="this.closest(\'.modal-disk\').remove()" style="padding:8px 14px;background:#fff;border:1px solid #d8e0ea;color:#1a2330">Close</button>' +
    '</div>' +
    '</div>';
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  document.body.appendChild(modal);
  modal.querySelectorAll(".grow-btn").forEach(b => {
    b.onclick = async () => {
      const target = parseInt(b.dataset.gb, 10);
      try {
        const r = await fetch(_api("/api/runtime/disk-grow"), {
          method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({target_gb: target}),
        });
        const d = await r.json();
        const body = modal.querySelector("#grow-body");
        if (r.ok && d.deferred) {
          body.innerHTML = '<div style="background:#e0f2fe;color:#075985;padding:10px;border-radius:6px;margin-bottom:10px">Run this command on the machine running your multipass:</div>' +
            '<pre style="background:#0f172a;color:#e2e8f0;padding:10px;border-radius:6px;font-size:12px">' + d.command + '</pre>' +
            '<div style="font-size:12px;color:#6b7280;margin-top:8px">' + d.instructions + '</div>';
        } else {
          body.innerHTML = '<div style="background:#fee2e2;color:#b91c1c;padding:10px;border-radius:6px">Failed: ' + ((d.detail && d.detail.reason) || d.reason || "unknown") + '</div>';
        }
      } catch (e) {
        modal.querySelector("#grow-body").innerHTML = '<div style="color:#b91c1c">Error: ' + e.message + '</div>';
      }
    };
  });
}
// Initial fetch + 30s auto-refresh
fetchDiskHealth();
setInterval(fetchDiskHealth, 30000);
  // The legacy markup uses inline onclick handlers -> expose them
  window._toggleDiskPopover = _toggleDiskPopover; window._closeDiskPopover = _closeDiskPopover;
  window.openDiskCleanup = openDiskCleanup; window.openDiskGrow = openDiskGrow; window.fetchDiskHealth = fetchDiskHealth;
})();
