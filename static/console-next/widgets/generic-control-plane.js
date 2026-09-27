// generic-control-plane widget (§14.5 fallback) — the honest gate. A service that
// isn't yet conformance-gated to a rich data-plane widget falls back to THIS view
// rather than shipping a shallow-parity screen. In P0, all non-S3 services land here.
//
// It still renders inside the Connect contract so the shape is consistent, and it
// states plainly what's available and what's coming.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import '../components/connect-contract.js';

class GenericControlPlane extends LitElement {
  static properties = {
    service: { attribute: false },
    mode: { attribute: false },
  };

  static styles = css`
    :host { display: block; }
    .note {
      color: var(--vy-fg-muted); font-size: var(--vy-fs-sm);
      line-height: 1.5; padding: var(--vy-s2) 0;
    }
    .tag {
      display: inline-block; color: var(--vy-warn);
      border: 1px solid var(--vy-warn); border-radius: var(--vy-radius);
      padding: 0 var(--vy-s2); font-size: var(--vy-fs-xs); margin-right: var(--vy-s2);
    }
  `;

  render() {
    const s = this.service || {};
    return html`
      <vyomi-connect-contract
        .resourceId=${s.label || s.id}
        .resourceKind=${s.terminology || 'resource'}
        .backedBy=${s.backed_by || 'backend'}
        .connectMode=${'endpoint'}
        .endpoint=${location.origin}
        .snippet=${`# ${s.label} control-plane\n# point your SDK at the endpoint; the rich\n# ${s.widget} widget lands in P1 (conformance-gated).`}
      >
        <div slot="live">
          <div class="note">
            <span class="tag">${(this.mode || 'generic').toUpperCase()}</span>
            The rich <b>${s.widget}</b> data-plane view is conformance-gated (§14.5)
            and lands in P1. Until then this service uses the generic control-plane
            view — the SDK/CLI already work against the endpoint above.
          </div>
        </div>
        <div slot="actions">
          <button style="opacity:.5" disabled>snapshot</button>
          <button style="opacity:.5" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-generic-control-plane', GenericControlPlane);
