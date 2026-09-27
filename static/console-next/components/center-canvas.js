// Center canvas (§4): the active view. Given the selected service, it looks up the
// widget id + capability mode from the manifest and renders the matching widget.
//
// This is the anti-fork seam (§15.2): the canvas dispatches on widget id + mode
// (DATA), never on substrate/cloud. A "generic" mode renders the generic-control-
// plane fallback; "full" renders the rich widget.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { widgetMode } from '../api.js';

import '../widgets/object-browser.js';
import '../widgets/nosql-item-viewer.js';
import '../widgets/queue-topic-viewer.js';
import '../widgets/kv-secret-viewer.js';
import '../widgets/kms-crypto-view.js';
import '../widgets/generic-control-plane.js';

class CenterCanvas extends LitElement {
  static properties = {
    caps: { attribute: false },
    selected: { attribute: false },   // { serviceId }
    deepLink: { attribute: false },   // backend.ref from Inspector, or null
  };

  static styles = css`
    :host { display: block; height: 100%; }
    .empty { padding: var(--vy-s6); color: var(--vy-fg-muted); }
    .wrap { padding: var(--vy-s5); box-sizing: border-box; }
  `;

  _service() {
    const id = this.selected && this.selected.serviceId;
    return (this.caps.services || []).find((s) => s.id === id) || null;
  }

  render() {
    const svc = this._service();
    if (!svc) {
      return html`<div class="empty">Select a service from the rail to get connected.</div>`;
    }
    const mode = widgetMode(svc.widget) || 'generic';
    return html`<div class="wrap">${this._widget(svc, mode)}</div>`;
  }

  _widget(svc, mode) {
    // object-browser is the P0 rich widget. Everything else (or a non-"full" mode)
    // falls back to the generic control-plane view — conformance-gated (§14.5).
    if (svc.widget === 'object-browser' && mode === 'full') {
      return html`<vyomi-object-browser
        .caps=${this.caps}
        .service=${svc}
        .deepLink=${this.deepLink}
      ></vyomi-object-browser>`;
    }
    if (svc.widget === 'nosql-item-viewer' && mode === 'full') {
      return html`<vyomi-nosql-item-viewer
        .caps=${this.caps}
        .service=${svc}
        .deepLink=${this.deepLink}
      ></vyomi-nosql-item-viewer>`;
    }
    if (svc.widget === 'queue-topic-viewer' && mode === 'full') {
      return html`<vyomi-queue-topic-viewer
        .caps=${this.caps}
        .service=${svc}
        .deepLink=${this.deepLink}
      ></vyomi-queue-topic-viewer>`;
    }
    if (svc.widget === 'kv-secret-viewer' && mode === 'full') {
      return html`<vyomi-kv-secret-viewer
        .caps=${this.caps}
        .service=${svc}
        .deepLink=${this.deepLink}
      ></vyomi-kv-secret-viewer>`;
    }
    if (svc.widget === 'kms-crypto-view' && mode === 'full') {
      return html`<vyomi-kms-crypto-view
        .caps=${this.caps}
        .service=${svc}
        .deepLink=${this.deepLink}
      ></vyomi-kms-crypto-view>`;
    }
    return html`<vyomi-generic-control-plane
      .service=${svc}
      .mode=${mode}
    ></vyomi-generic-control-plane>`;
  }
}

customElements.define('vyomi-center-canvas', CenterCanvas);
