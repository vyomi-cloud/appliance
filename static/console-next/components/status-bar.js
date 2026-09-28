// Status bar (§4): workspace · cloud-lens switcher (stub) · endpoint (click-copy) ·
// conformance pill (placeholder) · TTL/reset (stubs) · Inspector toggle · ⌘K.

import { LitElement, html, css } from '../vendor/lit-core.min.js';

class StatusBar extends LitElement {
  static properties = {
    caps: { attribute: false },
    lens: { attribute: false },
    inspectorOpen: { attribute: false },
    _copied: { state: true },
  };

  static styles = css`
    :host { display: block; }
    .bar {
      height: var(--vy-statusbar-h);
      display: flex; align-items: center; gap: var(--vy-s3);
      padding: 0 var(--vy-s4);
      background: var(--vy-bg-elev);
      border-bottom: 1px solid var(--vy-border);
      font-size: var(--vy-fs-sm);
      white-space: nowrap;
    }
    .ws { display: flex; align-items: center; gap: var(--vy-s2); font-weight: 600; }
    .dot { color: var(--vy-ok); }
    .lens {
      background: var(--vy-bg-elev-2); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 2px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: pointer;
    }
    .endpoint {
      display: inline-flex; align-items: center; gap: var(--vy-s1);
      color: var(--vy-fg-muted); cursor: pointer; font-family: var(--vy-mono);
      max-width: 320px; overflow: hidden; text-overflow: ellipsis;
      border: 1px dashed var(--vy-border); border-radius: var(--vy-radius);
      padding: 2px var(--vy-s2);
    }
    .endpoint:hover { color: var(--vy-fg); border-color: var(--vy-accent); }
    .pill {
      display: inline-flex; align-items: center; gap: var(--vy-s1);
      color: var(--vy-badge-fg); background: var(--vy-badge-bg);
      border: 1px solid var(--vy-ok); border-radius: 20px;
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs);
    }
    /* pill colour tracks the worst status: green=all conformant, amber=partial. */
    .pill .dot { color: var(--vy-ok); }
    .pill.partial { border-color: var(--vy-warn); }
    .pill.partial .dot { color: var(--vy-warn); }
    .pill.unknown { border-color: var(--vy-border); }
    .pill.unknown .dot { color: var(--vy-fg-dim); }
    .chip {
      color: var(--vy-fg-dim); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs);
    }
    .spacer { flex: 1; }
    .btn {
      background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 2px var(--vy-s2); cursor: pointer; font-size: var(--vy-fs-xs);
    }
    .btn:hover { color: var(--vy-fg); border-color: var(--vy-accent); }
    .btn.on { color: var(--vy-accent); border-color: var(--vy-accent); }
    .copied { color: var(--vy-ok); }
  `;

  _copyEndpoint() {
    const ep = this._endpoint();
    if (!ep) return;
    navigator.clipboard?.writeText(ep).catch(() => {});
    this._copied = true;
    setTimeout(() => (this._copied = false), 1200);
  }

  _endpoint() {
    const ws = (this.caps && this.caps.workspace) || {};
    // Fall back to the current origin (the appliance serves S3 here in most setups).
    return ws.endpoint || location.origin;
  }

  // Live conformance pill from the manifest summary
  // ({services_total, services_full, checks_passed, checks_total, status}).
  // Colour tracks the worst status; label shows the summed check counts.
  _pill(conf) {
    if (!conf) return html`<span class="pill unknown" title="conformance (loading)"><span class="dot">●</span> …</span>`;
    const status = conf.status || 'unknown';
    const passed = conf.checks_passed ?? 0;
    const total = conf.checks_total ?? 0;
    const full = conf.services_full ?? 0;
    const svcs = conf.services_total ?? 0;
    const cls = status === 'conformant' ? '' : (status === 'partial' ? 'partial' : 'unknown');
    const label = total ? `${passed}/${total} conformant` : status;
    const title = `conformance: ${status} — ${full}/${svcs} services full, ${passed}/${total} checks`;
    return html`<span class="pill ${cls}" title=${title}><span class="dot">●</span> ${label}</span>`;
  }

  // Live cloud-lens switch: emit `switch-lens` so the shell re-fetches the manifest
  // for that lens and re-renders the rail + widgets. Capability-driven — the switcher
  // only knows the lens NAMES from the manifest; it holds no cloud logic (§15.2).
  _onLensChange(e) {
    const lens = (e.target.value || 'aws').toLowerCase();
    this.dispatchEvent(new CustomEvent('switch-lens', { detail: { lens } }));
  }

  render() {
    const caps = this.caps || {};
    const ws = caps.workspace || {};
    const lenses = caps.cloud_lenses || ['aws'];
    const current = (this.lens || caps.lens || lenses[0] || 'aws').toLowerCase();
    const ep = this._endpoint();
    return html`
      <div class="bar">
        <span class="ws"><span class="dot">◐</span> ${ws.name || 'workspace'}</span>

        <!-- cloud-lens switcher — live; re-fetches the manifest for the chosen lens -->
        <select class="lens" title="Cloud lens" @change=${this._onLensChange}>
          ${lenses.map((l) => html`<option value=${l} ?selected=${l === current}>${l.toUpperCase()}</option>`)}
        </select>

        <!-- endpoint, click to copy -->
        <span class="endpoint" title="click to copy endpoint" @click=${this._copyEndpoint}>
          ⧉ ${this._copied ? html`<span class="copied">copied ✓</span>` : ep}
        </span>

        <!-- conformance pill — live from the capability manifest's summary (§4) -->
        ${this._pill(caps.conformance)}

        <!-- TTL + reset (stubs) -->
        <span class="chip" title="time-to-live (stub)">⏱ 2h</span>
        <button class="btn" title="reset workspace (stub)">⟲ reset</button>

        <span class="spacer"></span>

        <button class="btn" title="command palette (⌘K)" @click=${() => this.dispatchEvent(new CustomEvent('open-palette'))}>⌘K</button>
        <button class="btn ${this.inspectorOpen ? 'on' : ''}" title="Inspector (⌘I)"
          @click=${() => this.dispatchEvent(new CustomEvent('toggle-inspector'))}>⌘I Inspector</button>
      </div>
    `;
  }
}

customElements.define('vyomi-status-bar', StatusBar);
