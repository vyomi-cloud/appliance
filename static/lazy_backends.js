/* CloudLearn — lazy backend UI helper.
 *
 * Talks to /api/runtime/backends/{name}/{provision|status|stop} and shows a
 * floating progress banner while a backend is being pulled + started.
 *
 * Drop-in: include via <script src="/assets/lazy_backends.js"></script>.
 *
 * Public API on window:
 *   cloudlearnEnsureBackend(name)   → Promise<{ ready, error }>
 *                                     Kicks off provision (if needed),
 *                                     shows the banner, resolves when ready
 *                                     OR rejects on failure.
 *   cloudlearnBackendStatus(name)   → Promise<state object>  (cheap probe)
 *   cloudlearnStopBackend(name)     → Promise<void>          (admin/devs)
 */
(function () {
  if (window.cloudlearnEnsureBackend) return;   // double-include guard

  /* ── Banner UI — injected once on first call ─────────────────────────── */

  let banner = null;
  let pollTimer = null;

  function ensureBanner() {
    if (banner) return banner;
    const style = document.createElement("style");
    style.textContent = `
      .cl-lazy-banner {
        position: fixed; top: 16px; right: 16px; z-index: 99999;
        font-family: -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
        font-size: 13px; color: #e8eef6;
        background: rgba(15, 27, 45, 0.96);
        border: 1px solid rgba(168, 85, 247, 0.45);
        border-radius: 12px;
        padding: 14px 18px;
        min-width: 280px; max-width: 360px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.45), 0 0 16px rgba(168,85,247,0.18);
        backdrop-filter: blur(8px);
        opacity: 0; transform: translateY(-6px);
        transition: opacity .2s, transform .2s;
        pointer-events: auto;
      }
      .cl-lazy-banner.show { opacity: 1; transform: translateY(0); }
      .cl-lazy-banner .cl-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
      .cl-lazy-banner .cl-name { font-weight: 600; }
      .cl-lazy-banner .cl-state { color: #a78bfa; font-size: 11.5px;
        text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
      .cl-lazy-banner .cl-bar {
        height: 6px; background: rgba(255,255,255,0.10);
        border-radius: 3px; overflow: hidden;
      }
      .cl-lazy-banner .cl-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, #f0abfc 0%, #c084fc 60%, #a855f7 100%);
        transition: width .25s;
      }
      .cl-lazy-banner .cl-desc { font-size: 11.5px; color: #b3becf; margin-top: 6px; }
      .cl-lazy-banner .cl-err { color: #fca5a5; font-size: 12px; margin-top: 6px; }
      .cl-lazy-banner .cl-close {
        position: absolute; top: 8px; right: 10px;
        background: transparent; border: 0; color: #94a3b8;
        cursor: pointer; font-size: 16px; line-height: 1;
      }
      .cl-lazy-banner .cl-close:hover { color: #fff; }
      .cl-lazy-banner .cl-spin {
        width: 14px; height: 14px; border-radius: 50%;
        border: 2px solid rgba(168,85,247,0.30);
        border-top-color: #c084fc; animation: cl-spin 0.9s linear infinite;
      }
      @keyframes cl-spin { to { transform: rotate(360deg); } }
    `;
    document.head.appendChild(style);

    banner = document.createElement("div");
    banner.className = "cl-lazy-banner";
    banner.innerHTML = `
      <button class="cl-close" title="Hide">×</button>
      <div class="cl-row">
        <div class="cl-spin"></div>
        <span class="cl-name"></span>
        <span class="cl-state"></span>
      </div>
      <div class="cl-bar"><div class="cl-bar-fill" style="width:0%"></div></div>
      <div class="cl-desc"></div>
      <div class="cl-err"></div>
    `;
    document.body.appendChild(banner);
    banner.querySelector(".cl-close").addEventListener("click", hideBanner);
    return banner;
  }

  function showBanner(meta, st) {
    const b = ensureBanner();
    b.querySelector(".cl-name").textContent = meta.name || st.name;
    b.querySelector(".cl-desc").textContent = meta.description || "";
    updateBanner(st);
    b.classList.add("show");
  }

  function updateBanner(st) {
    if (!banner) return;
    const stateLabel =
      st.state === "pulling"  ? `pulling… ${st.pull_progress_pct ?? 0}%` :
      st.state === "starting" ? "starting…" :
      st.state === "ready"    ? "ready ✓" :
      st.state === "failed"   ? "failed" :
      st.state;
    banner.querySelector(".cl-state").textContent = stateLabel;
    const pct =
      st.state === "ready"    ? 100 :
      st.state === "starting" ? 95 :
      st.state === "pulling"  ? Math.max(2, st.pull_progress_pct ?? 0) :
      0;
    banner.querySelector(".cl-bar-fill").style.width = `${pct}%`;
    const errEl = banner.querySelector(".cl-err");
    errEl.textContent = st.error || "";
    if (st.state === "ready") {
      setTimeout(hideBanner, 1800);
    }
  }

  function hideBanner() {
    if (!banner) return;
    banner.classList.remove("show");
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  /* ── Public API ───────────────────────────────────────────────────────── */

  async function api(url, opts = {}) {
    const r = await fetch(url, { credentials: "same-origin", ...opts });
    const body = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, body };
  }

  window.cloudlearnBackendStatus = async function (name) {
    const r = await api(`/api/runtime/backends/${encodeURIComponent(name)}/status`);
    if (!r.ok) throw new Error(r.body.detail || `HTTP ${r.status}`);
    return r.body;
  };

  window.cloudlearnStopBackend = async function (name) {
    const r = await api(
      `/api/runtime/backends/${encodeURIComponent(name)}/stop`,
      { method: "POST" }
    );
    if (!r.ok) throw new Error(r.body.detail || `HTTP ${r.status}`);
    return r.body;
  };

  window.cloudlearnEnsureBackend = function (name) {
    return new Promise(async (resolve, reject) => {
      try {
        const initial = await window.cloudlearnBackendStatus(name);
        if (initial.provisioning?.state === "ready") {
          // Already running — no banner, no wait.
          resolve({ ready: true });
          return;
        }
        // Kick off (idempotent — won't double-pull)
        const r = await api(
          `/api/runtime/backends/${encodeURIComponent(name)}/provision`,
          { method: "POST" }
        );
        if (!r.ok && r.status !== 202) {
          reject(new Error(r.body.detail || `HTTP ${r.status}`));
          return;
        }
        showBanner(r.body, r.body.provisioning);

        // Poll every 1 s — resolves on ready, rejects on failed
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(async () => {
          try {
            const cur = await window.cloudlearnBackendStatus(name);
            updateBanner(cur.provisioning);
            if (cur.provisioning?.state === "ready") {
              clearInterval(pollTimer); pollTimer = null;
              resolve({ ready: true });
            } else if (cur.provisioning?.state === "failed") {
              clearInterval(pollTimer); pollTimer = null;
              reject(new Error(cur.provisioning.error || "provisioning failed"));
            }
          } catch (e) {
            // Transient network blip during poll — keep trying
          }
        }, 1000);
      } catch (e) {
        reject(e);
      }
    });
  };
})();
