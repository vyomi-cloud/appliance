// reveal-cli (§12.8 / §13.1 — "reveal CLI") — ONE shared affordance so any primary
// action can surface its equivalent CLI / SDK line, consistently across every widget.
//
// It is intentionally tiny and cloud/substrate-agnostic (§15.2): it renders a single
// "↳ reveal CLI" toggle that, when opened, shows one command line and a copy button.
// Widgets don't hand-roll this — they render <vyomi-reveal-cli .command=…> (or let
// the shared Connect contract render it from the service descriptor's connect.cli),
// so the affordance is uniform everywhere. It holds NO cloud logic; the command text
// comes from the caller (the manifest's `service.connect.cli` / the widget's action
// context via the cliForAction() helper in api.js).

import { LitElement, html, css } from '../vendor/lit-core.min.js';

class RevealCli extends LitElement {
  static properties = {
    command: { type: String },   // the exact CLI/SDK line to reveal
    label: { type: String },     // optional action label (e.g. "create bucket")
    _open: { state: true },
    _copied: { state: true },
  };

  static styles = css`
    :host { display: inline-block; }
    .toggle {
      background: transparent; color: var(--vy-info);
      border: 1px dashed var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: pointer;
      font-family: var(--vy-mono);
    }
    .toggle:hover { border-color: var(--vy-accent); color: var(--vy-accent); }
    .panel {
      margin-top: var(--vy-s1); display: flex; align-items: flex-start; gap: var(--vy-s2);
    }
    /* Reveal-CLI output as a real code block: preserve newlines AND indentation
       (white-space: pre), scroll long lines horizontally, NO word-break. */
    pre.cmd {
      margin: 0; flex: 1; min-width: 0;
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); line-height: 1.5;
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s2);
      color: var(--vy-fg); white-space: pre; overflow-x: auto;
    }
    .copy {
      cursor: pointer; color: var(--vy-fg-dim); background: transparent;
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs);
    }
    .copy:hover { color: var(--vy-fg); border-color: var(--vy-accent); }
  `;

  constructor() {
    super();
    this._open = false;
  }

  _copy() {
    navigator.clipboard?.writeText(this.command || '').catch(() => {});
    this._copied = true;
    setTimeout(() => (this._copied = false), 1000);
  }

  render() {
    if (!this.command) return html``;
    const tag = this.label ? `reveal CLI: ${this.label}` : 'reveal CLI';
    return html`
      <button class="toggle" title="show the equivalent CLI/SDK command"
        @click=${() => (this._open = !this._open)}>↳ ${tag}</button>
      ${this._open
        ? html`<div class="panel">
            <pre class="cmd">${this.command}</pre>
            <button class="copy" @click=${this._copy}>${this._copied ? '✓' : '⧉'}</button>
          </div>`
        : ''}
    `;
  }
}

customElements.define('vyomi-reveal-cli', RevealCli);
