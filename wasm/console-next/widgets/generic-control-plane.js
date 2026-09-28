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
    // Substrate-driven degrade CTA (§14.9). Non-empty only when the manifest marked
    // this widget "degraded"/"partial" on the current substrate (e.g. Nano compute).
    // Rendered as data — this component never checks the substrate name (§15.2).
    degradeNote: { attribute: false },
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
    /* substrate degrade banner (§14.9) — the "open a Codespace" CTA state. */
    .degrade {
      color: var(--vy-fg); background: var(--vy-badge-bg);
      border: 1px solid var(--vy-warn); border-radius: var(--vy-radius);
      padding: var(--vy-s2); margin-bottom: var(--vy-s2);
      font-size: var(--vy-fs-sm); line-height: 1.5;
    }
  `;

  render() {
    const s = this.service || {};
    const mode = (this.mode || 'generic').toLowerCase();
    const note = this.degradeNote || '';
    // A degraded/partial widget on this substrate renders its capability-driven CTA
    // in place of the "coming in P1" copy. Same component, note-driven (§15.2).
    const liveBody = note
      ? html`<div class="degrade">
               <span class="tag">${mode.toUpperCase()}</span>
               ${note}
             </div>`
      : html`<div class="note">
               <span class="tag">${mode.toUpperCase()}</span>
               The rich <b>${s.widget}</b> data-plane view is conformance-gated (§14.5)
               and lands in P1. Until then this service uses the generic control-plane
               view — the SDK/CLI already work against the endpoint above.
             </div>`;
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
          ${liveBody}
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
