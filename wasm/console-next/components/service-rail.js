// Left service rail (§4): the resource explorer. Renders ONLY the services in the
// capability manifest's catalog (§8 — the console is a view over the catalog).
// Searchable. No per-service bespoke code — it's data-driven.

import { LitElement, html, css } from '../vendor/lit-core.min.js';

class ServiceRail extends LitElement {
  static properties = {
    services: { attribute: false },
    selected: { attribute: false },
    _q: { state: true },
  };

  static styles = css`
    :host { display: block; }
    .rail {
      height: 100%; box-sizing: border-box;
      background: var(--vy-panel);
      border-right: 1px solid var(--vy-border);
      display: flex; flex-direction: column;
    }
    .hd { padding: var(--vy-s3) var(--vy-s3) var(--vy-s2);
      color: var(--vy-fg-dim); font-size: var(--vy-fs-xs);
      text-transform: uppercase; letter-spacing: .06em; }
    .search {
      margin: 0 var(--vy-s3) var(--vy-s2);
      background: var(--vy-bg-elev); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    .search:focus { border-color: var(--vy-accent); }
    ul { list-style: none; margin: 0; padding: 0 var(--vy-s2); overflow: auto; }
    li {
      display: flex; align-items: center; gap: var(--vy-s2);
      padding: var(--vy-s2) var(--vy-s2); border-radius: var(--vy-radius);
      cursor: pointer; color: var(--vy-fg-muted);
    }
    li:hover { background: var(--vy-bg-elev); color: var(--vy-fg); }
    li.sel { background: var(--vy-bg-elev-2); color: var(--vy-fg);
      box-shadow: inset 2px 0 0 var(--vy-accent); }
    .icon { width: 18px; text-align: center; opacity: .9; }
    .backed { margin-left: auto; font-size: 10px; color: var(--vy-fg-dim); }
  `;

  _filtered() {
    const q = (this._q || '').toLowerCase();
    return (this.services || []).filter(
      (s) => !q || s.label.toLowerCase().includes(q) || s.id.includes(q)
    );
  }

  _pick(id) {
    this.dispatchEvent(new CustomEvent('select-service', { detail: { serviceId: id } }));
  }

  render() {
    return html`
      <div class="rail">
        <div class="hd">Services</div>
        <input class="search" placeholder="filter…" .value=${this._q || ''}
          @input=${(e) => (this._q = e.target.value)} />
        <ul>
          ${this._filtered().map(
            (s) => html`
              <li class=${s.id === this.selected ? 'sel' : ''} @click=${() => this._pick(s.id)}>
                <span class="icon">${s.icon || '▸'}</span>
                <span>${s.label}</span>
                <span class="backed">${s.backed_by || ''}</span>
              </li>
            `
          )}
        </ul>
      </div>
    `;
  }
}

customElements.define('vyomi-service-rail', ServiceRail);
