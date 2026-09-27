// ⌘K command palette (§4) — P0 stub. Fuzzy-jump to a service, toggle the Inspector,
// and a "reveal CLI" placeholder. Real "do anything / reveal CLI for any action"
// depth lands with the CLI-reveal framework (F8).

import { LitElement, html, css } from '../vendor/lit-core.min.js';

class CommandPalette extends LitElement {
  static properties = {
    caps: { attribute: false },
    _q: { state: true },
    _idx: { state: true },
  };

  static styles = css`
    :host { position: fixed; inset: 0; z-index: 1000; }
    .backdrop { position: absolute; inset: 0; background: rgba(0,0,0,.5); }
    .panel {
      position: absolute; top: 14%; left: 50%; transform: translateX(-50%);
      width: 520px; max-width: 90vw;
      background: var(--vy-bg-elev); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius-lg); box-shadow: var(--vy-shadow); overflow: hidden;
    }
    input {
      width: 100%; box-sizing: border-box; background: transparent; color: var(--vy-fg);
      border: 0; border-bottom: 1px solid var(--vy-border); outline: none;
      padding: var(--vy-s4); font-size: var(--vy-fs-lg); font-family: var(--vy-font);
    }
    ul { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 320px; overflow: auto; }
    li { display: flex; align-items: center; gap: var(--vy-s2);
      padding: var(--vy-s2) var(--vy-s3); border-radius: var(--vy-radius);
      cursor: pointer; color: var(--vy-fg-muted); font-size: var(--vy-fs-md); }
    li.on, li:hover { background: var(--vy-bg-elev-2); color: var(--vy-fg); }
    .kind { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
  `;

  constructor() { super(); this._q = ''; this._idx = 0; }

  firstUpdated() {
    const el = this.renderRoot.querySelector('input');
    if (el) el.focus();
  }

  _commands() {
    const svcs = (this.caps && this.caps.services) || [];
    const cmds = svcs.map((s) => ({
      label: `Go to ${s.label}`, kind: 'service', action: 'service:' + s.id,
    }));
    cmds.push({ label: 'Toggle Inspector', kind: 'view', action: 'toggle-inspector' });
    cmds.push({ label: 'Reveal CLI (coming in F8)', kind: 'stub', action: 'noop' });
    return cmds;
  }

  _filtered() {
    const q = (this._q || '').toLowerCase();
    return this._commands().filter((c) => !q || c.label.toLowerCase().includes(q));
  }

  _onKey(e) {
    const items = this._filtered();
    if (e.key === 'ArrowDown') { e.preventDefault(); this._idx = Math.min(this._idx + 1, items.length - 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this._idx = Math.max(this._idx - 1, 0); }
    else if (e.key === 'Enter') { e.preventDefault(); this._run(items[this._idx]); }
    else if (e.key === 'Escape') { this.dispatchEvent(new CustomEvent('close')); }
  }

  _run(cmd) {
    if (!cmd || cmd.action === 'noop') { this.dispatchEvent(new CustomEvent('close')); return; }
    this.dispatchEvent(new CustomEvent('palette-action', { detail: { action: cmd.action } }));
  }

  render() {
    const items = this._filtered();
    return html`
      <div class="backdrop" @click=${() => this.dispatchEvent(new CustomEvent('close'))}></div>
      <div class="panel">
        <input placeholder="Type a command or jump to a service…"
          .value=${this._q}
          @input=${(e) => { this._q = e.target.value; this._idx = 0; }}
          @keydown=${this._onKey} />
        <ul>
          ${items.map((c, i) => html`
            <li class=${i === this._idx ? 'on' : ''} @click=${() => this._run(c)}>
              <span>${c.label}</span><span class="kind">${c.kind}</span>
            </li>`)}
        </ul>
      </div>
    `;
  }
}

customElements.define('vyomi-command-palette', CommandPalette);
