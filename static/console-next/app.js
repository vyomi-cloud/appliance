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
    _selected: { state: true },       // { serviceId } | null
    _inspectorOpen: { state: true },
    _paletteOpen: { state: true },
    _deepLink: { state: true },        // backend.ref pushed from the Inspector
    _error: { state: true },
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
    .err {
      margin: var(--vy-s5); padding: var(--vy-s4);
      border: 1px solid var(--vy-err); border-radius: var(--vy-radius);
      color: var(--vy-err); background: rgba(248,81,73,.08);
    }
  `;

  constructor() {
    super();
    this._caps = null;
    this._selected = null;
    this._inspectorOpen = true;
    this._paletteOpen = false;
    this._deepLink = null;
    this._error = null;
    this._onKey = this._onKey.bind(this);
  }

  async connectedCallback() {
    super.connectedCallback();
    window.addEventListener('keydown', this._onKey);
    try {
      this._caps = await loadCapabilities();
      // Default selection: first service in the catalog.
      const svcs = this._caps.services || [];
      if (svcs.length) this._selected = { serviceId: svcs[0].id };
    } catch (e) {
      this._error = 'Could not load capabilities: ' + e.message;
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
          .inspectorOpen=${this._inspectorOpen}
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
