// Vyomi console-next — the persistent shell (§4).
//
// ONE component tree (§15.1 #4): status bar · service rail · center canvas ·
// Inspector drawer · ⌘K palette. Substrate/cloud variation is absorbed by the
// capability manifest, never by a forked component.

import { LitElement, html, css } from './vendor/lit-core.min.js';
import { loadCapabilities, capabilities } from './api.js';

// Register the shell's children.
import './components/status-bar.js';
import './components/service-rail.js';
import './components/center-canvas.js';
import './components/inspector-drawer.js';
import './components/command-palette.js';

class VyomiConsole extends LitElement {
  static properties = {
    _caps: { state: true },
    _lens: { state: true },           // current cloud lens (aws|gcp|…)
    _selected: { state: true },       // { serviceId } | null
    _inspectorOpen: { state: true },
    _paletteOpen: { state: true },
    _deepLink: { state: true },        // backend.ref pushed from the Inspector
    _error: { state: true },
    _sandboxDismissed: { state: true },  // one-time SSH setup banner dismissed?
  };

  static styles = css`
    :host {
      display: block;
      height: 100vh;
      background: var(--vy-bg);
      color: var(--vy-fg);
      font-family: var(--vy-font);
      font-size: var(--vy-fs-md);
      overflow: hidden;
    }
    .shell {
      display: grid;
      grid-template-rows: var(--vy-statusbar-h) 1fr;
      height: 100%;
    }
    .body {
      display: grid;
      grid-template-columns: var(--vy-rail-w) 1fr auto;
      min-height: 0;
    }
    .center { min-width: 0; overflow: auto; }
    /* One-time SSH bastion setup (Codespaces sandbox). Global + dismissible. */
    .setup-banner {
      margin: var(--vy-s3) var(--vy-s4) 0;
      padding: var(--vy-s3) var(--vy-s4);
      border: 1px solid var(--vy-accent, #3b82f6);
      border-radius: var(--vy-radius);
      background: rgba(59,130,246,.08);
      display: flex; flex-direction: column; gap: 6px;
    }
    .setup-banner .row { display: flex; align-items: center; gap: 10px; }
    .setup-banner .title { font-weight: 600; flex: 1; }
    .setup-banner .cmd {
      display: flex; align-items: center; gap: 8px;
      background: var(--vy-bg-elev, rgba(0,0,0,.25));
      border: 1px solid var(--vy-border, rgba(255,255,255,.1));
      border-radius: 6px; padding: 6px 10px;
      font-family: var(--vy-font-mono, ui-monospace, monospace); font-size: var(--vy-fs-sm, 12.5px);
    }
    .setup-banner .cmd code { flex: 1; overflow-x: auto; white-space: nowrap; }
    .setup-banner .note { color: var(--vy-fg-muted); font-size: var(--vy-fs-sm, 12.5px); line-height: 1.5; }
    .setup-banner button {
      background: transparent; color: var(--vy-fg); border: 1px solid var(--vy-border, rgba(255,255,255,.15));
      border-radius: 6px; padding: 3px 8px; cursor: pointer; font: inherit; font-size: 12px;
    }
    .setup-banner button:hover { border-color: var(--vy-accent, #3b82f6); }
    .setup-banner .x { border: 0; font-size: 16px; line-height: 1; color: var(--vy-fg-muted); }
    .err {
      margin: var(--vy-s5); padding: var(--vy-s4);
      border: 1px solid var(--vy-err); border-radius: var(--vy-radius);
      color: var(--vy-err); background: rgba(248,81,73,.08);
    }
  `;

  constructor() {
    super();
    this._caps = null;
    this._lens = 'aws';
    this._selected = null;
    this._inspectorOpen = true;
    this._paletteOpen = false;
    this._deepLink = null;
    this._error = null;
    this._sandboxDismissed = false;
    this._onKey = this._onKey.bind(this);
  }

  async connectedCallback() {
    super.connectedCallback();
    window.addEventListener('keydown', this._onKey);
    try {
      this._caps = await loadCapabilities(this._lens);
      // Default selection: first service in the catalog.
      const svcs = this._caps.services || [];
      if (svcs.length) this._selected = { serviceId: svcs[0].id };
      // Restore the "SSH setup banner dismissed" choice for THIS codespace.
      const sb = this._caps.sandbox;
      if (sb && sb.codespace_name) {
        try {
          this._sandboxDismissed =
            localStorage.getItem('vy-ssh-setup-dismissed:' + sb.codespace_name) === '1';
        } catch (_) { /* localStorage may be unavailable */ }
      }
    } catch (e) {
      this._error = 'Could not load capabilities: ' + e.message;
    }
  }

  // Cloud-lens switch (§15.2): re-fetch the manifest for the chosen lens and
  // re-render the whole shell from it. NO cloud branching — the new manifest's
  // `services` + per-service `api` blocks drive the rail + widgets.
  async _switchLens(e) {
    const lens = (e.detail && e.detail.lens) || 'aws';
    if (lens === this._lens) return;
    try {
      const caps = await loadCapabilities(lens);
      this._lens = lens;
      this._caps = caps;
      this._deepLink = null;
      const svcs = caps.services || [];
      this._selected = svcs.length ? { serviceId: svcs[0].id } : null;
    } catch (err) {
      this._error = 'Could not load capabilities for lens ' + lens + ': ' + err.message;
    }
  }

  disconnectedCallback() {
    window.removeEventListener('keydown', this._onKey);
    super.disconnectedCallback();
  }

  _onKey(e) {
    const meta = e.metaKey || e.ctrlKey;
    if (meta && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      this._paletteOpen = !this._paletteOpen;
    } else if (meta && (e.key === 'i' || e.key === 'I')) {
      e.preventDefault();
      this._inspectorOpen = !this._inspectorOpen;
    } else if (e.key === 'Escape') {
      this._paletteOpen = false;
    }
  }

  _selectService(e) {
    this._selected = { serviceId: e.detail.serviceId };
    this._deepLink = null;
  }

  _onDeepLink(e) {
    // A call row in the Inspector was clicked — deep-link to its backend.ref.
    const ref = e.detail.ref;
    if (ref && ref.type && ref.type.startsWith('s3')) {
      this._selected = { serviceId: 's3' };
      this._deepLink = ref;
    }
  }

  _paletteAction(e) {
    const a = e.detail.action;
    this._paletteOpen = false;
    if (a === 'toggle-inspector') this._inspectorOpen = !this._inspectorOpen;
    else if (a && a.startsWith('service:')) {
      this._selected = { serviceId: a.slice('service:'.length) };
      this._deepLink = null;
    }
  }

  // One-time SSH bastion setup banner — shown once per Codespace, laptop-wide
  // (covers every instance and cloud). Absent off-Codespace (manifest.sandbox={}).
  _renderSandboxBanner(caps) {
    const sb = caps && caps.sandbox;
    if (!sb || !sb.ssh_setup_command || this._sandboxDismissed) return '';
    return html`
      <div class="setup-banner">
        <div class="row">
          <span class="title">One-time SSH setup — run once on your laptop to reach every instance</span>
          <button class="x" title="dismiss" @click=${() => this._dismissSandbox(sb)}>×</button>
        </div>
        <div class="cmd">
          <code>${sb.ssh_setup_command}</code>
          <button @click=${() => this._copy(sb.ssh_setup_command)}>Copy</button>
        </div>
        <div class="note">${sb.note}</div>
      </div>
    `;
  }

  _dismissSandbox(sb) {
    this._sandboxDismissed = true;
    try {
      if (sb && sb.codespace_name)
        localStorage.setItem('vy-ssh-setup-dismissed:' + sb.codespace_name, '1');
    } catch (_) { /* ignore */ }
  }

  _copy(text) { navigator.clipboard?.writeText(text || '').catch(() => {}); }

  render() {
    if (this._error) {
      return html`<div class="err">${this._error}</div>`;
    }
    if (!this._caps) {
      return html`<div style="padding:var(--vy-s5);color:var(--vy-fg-muted)">Loading…</div>`;
    }
    const caps = this._caps;
    return html`
      <div class="shell">
        <vyomi-status-bar
          .caps=${caps}
          .lens=${this._lens}
          .inspectorOpen=${this._inspectorOpen}
          @switch-lens=${this._switchLens}
          @toggle-inspector=${() => (this._inspectorOpen = !this._inspectorOpen)}
          @open-palette=${() => (this._paletteOpen = true)}
        ></vyomi-status-bar>

        <div class="body">
          <vyomi-service-rail
            .services=${caps.services || []}
            .selected=${this._selected && this._selected.serviceId}
            @select-service=${this._selectService}
          ></vyomi-service-rail>

          <div class="center">
            ${this._renderSandboxBanner(caps)}
            <vyomi-center-canvas
              .caps=${caps}
              .selected=${this._selected}
              .deepLink=${this._deepLink}
            ></vyomi-center-canvas>
          </div>

          <vyomi-inspector-drawer
            .open=${this._inspectorOpen}
            .caps=${caps}
            @deep-link=${this._onDeepLink}
            @close=${() => (this._inspectorOpen = false)}
          ></vyomi-inspector-drawer>
        </div>
      </div>

      ${this._paletteOpen
        ? html`<vyomi-command-palette
            .caps=${caps}
            @palette-action=${this._paletteAction}
            @close=${() => (this._paletteOpen = false)}
          ></vyomi-command-palette>`
        : ''}
    `;
  }
}

customElements.define('vyomi-console', VyomiConsole);
