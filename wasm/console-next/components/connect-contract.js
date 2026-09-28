// The common Connect contract (§13.1) — ONE component, three invariant blocks:
//   Connect  (native access + client snippet + CLI-reveal)
//   Live     (the real backend, in-line) + mandatory `⛃ backed by <X>` badge
//   Actions  (lifecycle + snapshot/fork)
//
// Parameterized by resource via attributes + named slots. It is the SAME component
// for every service/cloud/substrate; the `connect.mode` variant (ssh/endpoint/relay)
// only changes the Connect block's copy — never forks into three components (§15.2).

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import './reveal-cli.js';

class ConnectContract extends LitElement {
  static properties = {
    resourceId: { type: String },
    resourceKind: { type: String },
    backedBy: { type: String },
    connectMode: { type: String },  // endpoint | ssh | relay (from caps.connect.mode)
    endpoint: { type: String },
    snippet: { type: String },      // SDK snippet text
    cliReveal: { type: String },    // exact provider CLI command
    // Optional per-action reveal-CLI lines (§12.8): [{label, command}]. When a widget
    // passes its primary actions here, each gets a uniform "↳ reveal CLI" affordance
    // in the Actions block. When omitted, the Actions block still reveals the
    // resource-level command (cliReveal) so the affordance is present everywhere.
    revealActions: { attribute: false },
    _copied: { state: true },
    _tab: { state: true },          // sdk | cli | tf
  };

  static styles = css`
    :host { display: block; }
    .card {
      background: var(--vy-panel); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius-lg); overflow: hidden;
    }
    .hd {
      display: flex; align-items: center; gap: var(--vy-s2);
      padding: var(--vy-s3) var(--vy-s4);
      background: var(--vy-bg-elev); border-bottom: 1px solid var(--vy-border);
    }
    .hd .id { font-weight: 600; }
    .hd .kind { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .hd .sp { flex: 1; }
    .familiar {
      background: var(--vy-bg-elev-2); color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: not-allowed;
    }
    .block { padding: var(--vy-s3) var(--vy-s4); border-bottom: 1px solid var(--vy-border-soft); }
    .block:last-child { border-bottom: 0; }
    .label {
      color: var(--vy-fg-dim); font-size: var(--vy-fs-xs);
      text-transform: uppercase; letter-spacing: .06em; margin-bottom: var(--vy-s2);
    }
    .row { display: flex; align-items: center; gap: var(--vy-s2); margin: var(--vy-s1) 0; }
    code {
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm);
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s2);
      color: var(--vy-fg); white-space: pre-wrap; word-break: break-all;
    }
    /* SDK/CLI snippet as a real code block: preserve newlines AND indentation
       (white-space: pre), scroll long lines horizontally, NO word-break (it
       mangles code mid-token). */
    .snippet-wrap { position: relative; }
    pre.snippet {
      margin: 0; display: block;
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); line-height: 1.5;
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s2) var(--vy-s3);
      padding-right: calc(var(--vy-s3) + 28px);
      color: var(--vy-fg); white-space: pre; overflow-x: auto;
    }
    .snippet-copy {
      position: absolute; top: var(--vy-s1); right: var(--vy-s1);
      cursor: pointer; color: var(--vy-fg-dim); background: var(--vy-bg-elev);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs);
    }
    .snippet-copy:hover { color: var(--vy-fg); border-color: var(--vy-accent); }
    .copy {
      cursor: pointer; color: var(--vy-fg-dim); background: transparent;
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs);
    }
    .copy:hover { color: var(--vy-fg); border-color: var(--vy-accent); }
    .tabs { display: flex; gap: var(--vy-s1); margin-bottom: var(--vy-s2); }
    .tabs button {
      background: transparent; color: var(--vy-fg-dim);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: pointer;
    }
    .tabs button.on { color: var(--vy-accent); border-color: var(--vy-accent); }
    .reveal {
      margin-top: var(--vy-s2); color: var(--vy-info); font-family: var(--vy-mono);
      font-size: var(--vy-fs-sm);
    }
    .badge {
      display: inline-flex; align-items: center; gap: var(--vy-s1);
      color: var(--vy-badge-fg); background: var(--vy-badge-bg);
      border: 1px solid var(--vy-ok); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2);
    }
    .mode-note { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s1); }
    .reveal-actions { display: flex; flex-wrap: wrap; gap: var(--vy-s2); margin-top: var(--vy-s2); }
  `;

  constructor() {
    super();
    this._tab = 'sdk';
    this.connectMode = 'endpoint';
  }

  _copy(text) {
    navigator.clipboard?.writeText(text).catch(() => {});
    this._copied = true;
    setTimeout(() => (this._copied = false), 1000);
  }

  _connectRow() {
    const mode = this.connectMode || 'endpoint';
    if (mode === 'ssh') {
      return html`<div class="row"><span>SSH</span>
        <code>ssh -i vyomi.pem -p &lt;port&gt; ubuntu@&lt;host&gt;</code></div>`;
    }
    if (mode === 'relay') {
      return html`<div class="row"><span>Relay endpoint</span>
        <code>${this.endpoint || '(relay URL)'}</code>
        <button class="copy" @click=${() => this._copy(this.endpoint || '')}>⧉</button></div>
        <div class="mode-note">Nano substrate — external SDK/CLI reach this via the relay.</div>`;
    }
    return html`<div class="row"><span>Endpoint</span>
      <code>${this.endpoint || '(endpoint)'}</code>
      <button class="copy" @click=${() => this._copy(this.endpoint || '')}>${this._copied ? '✓' : '⧉'}</button>
    </div>`;
  }

  // reveal-CLI affordances for this resource's primary actions (§12.8). Uniform via
  // the shared <vyomi-reveal-cli> so every widget gets the same control. If a widget
  // supplied `revealActions`, render one per action; otherwise fall back to the
  // resource-level command (cliReveal) so the affordance exists everywhere.
  _revealActions() {
    const list = (this.revealActions && this.revealActions.length)
      ? this.revealActions
      : (this.cliReveal ? [{ label: '', command: this.cliReveal }] : []);
    if (!list.length) return '';
    return html`<div class="reveal-actions">
      ${list.map((a) => html`<vyomi-reveal-cli
        .label=${a.label || ''} .command=${a.command || ''}></vyomi-reveal-cli>`)}
    </div>`;
  }

  render() {
    return html`
      <div class="card">
        <div class="hd">
          <span class="id">${this.resourceId || ''}</span>
          <span class="kind">· ${this.resourceKind || ''}</span>
          <span class="sp"></span>
          <span class="familiar" title="native lens — theming only, deferred (§7)">Familiar ▾</span>
        </div>

        <div class="block">
          <div class="label">Connect</div>
          ${this._connectRow()}
          <div class="tabs">
            <button class=${this._tab === 'sdk' ? 'on' : ''} @click=${() => (this._tab = 'sdk')}>boto3</button>
            <button class=${this._tab === 'cli' ? 'on' : ''} @click=${() => (this._tab = 'cli')}>cli</button>
            <button class=${this._tab === 'tf' ? 'on' : ''} @click=${() => (this._tab = 'tf')}>tf</button>
          </div>
          ${(() => {
            const text = this._tab === 'cli'
              ? (this.cliReveal || '(cli snippet)')
              : (this.snippet || '(sdk snippet)');
            return html`<div class="snippet-wrap">
              <pre class="snippet">${text}</pre>
              <button class="snippet-copy" title="copy"
                @click=${() => this._copy(text)}>${this._copied ? '✓' : '⧉'}</button>
            </div>`;
          })()}
          ${this.cliReveal
            ? html`<div class="reveal">↳ reveal CLI: ${this.cliReveal}</div>`
            : ''}
        </div>

        <div class="block">
          <div class="label">Live (real · ${this.backedBy || 'backend'})</div>
          <slot name="live"></slot>
          <div class="badge">⛃ backed by ${this.backedBy || 'backend'}</div>
        </div>

        <div class="block">
          <div class="label">Actions</div>
          <slot name="actions"></slot>
          ${this._revealActions()}
        </div>
      </div>
    `;
  }
}

customElements.define('vyomi-connect-contract', ConnectContract);
