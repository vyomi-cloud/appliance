// Glass-box Inspector drawer (§12) — the flagship. Right-hand persistent drawer
// with four tabs; P0 ships the LIVE Calls tab (SSE stream of the §12.2 events).
// State / Snapshots / Conformance are present as placeholders (P1/P2).
//
// The event shape is identical across substrates (§15.1 #5), so this UI is the
// same whether the FastAPI middleware or the Nano SW/router produced the events.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiUrl } from '../api.js';

const METHOD_VAR = {
  GET: '--vy-m-get', POST: '--vy-m-post', PUT: '--vy-m-put',
  DELETE: '--vy-m-delete', HEAD: '--vy-m-head',
};

class InspectorDrawer extends LitElement {
  static properties = {
    open: { attribute: false },
    caps: { attribute: false },
    _tab: { state: true },
    _calls: { state: true },
    _filter: { state: true },
    _paused: { state: true },
    _selected: { state: true },
    _connected: { state: true },
  };

  static styles = css`
    :host { display: block; }
    .drawer {
      width: var(--vy-inspector-w); height: 100%; box-sizing: border-box;
      background: var(--vy-panel); border-left: 1px solid var(--vy-border);
      display: flex; flex-direction: column;
    }
    .drawer.closed { width: 0; overflow: hidden; border-left: 0; }
    .tabs { display: flex; border-bottom: 1px solid var(--vy-border); background: var(--vy-bg-elev); }
    .tabs button {
      flex: 1; background: transparent; color: var(--vy-fg-dim);
      border: 0; border-bottom: 2px solid transparent; padding: var(--vy-s2);
      cursor: pointer; font-size: var(--vy-fs-sm);
    }
    .tabs button.on { color: var(--vy-fg); border-bottom-color: var(--vy-accent); }
    .toolbar { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3);
      border-bottom: 1px solid var(--vy-border-soft); }
    .toolbar input {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    .toolbar button {
      background: transparent; color: var(--vy-fg-dim);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: pointer;
    }
    .live { display: inline-flex; align-items: center; gap: 4px; font-size: var(--vy-fs-xs); }
    .live .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--vy-ok); }
    .live.off .dot { background: var(--vy-fg-dim); }
    ul { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; }
    li.call { padding: var(--vy-s2) var(--vy-s3); border-bottom: 1px solid var(--vy-border-soft);
      cursor: pointer; font-size: var(--vy-fs-sm); }
    li.call:hover { background: var(--vy-bg-elev); }
    li.call.sel { background: var(--vy-bg-elev-2); }
    .cl { display: flex; align-items: center; gap: var(--vy-s2); }
    .method { font-family: var(--vy-mono); font-weight: 600; font-size: var(--vy-fs-xs); min-width: 44px; }
    .status { font-family: var(--vy-mono); font-size: var(--vy-fs-xs); }
    .s-ok { color: var(--vy-ok); } .s-warn { color: var(--vy-warn); } .s-err { color: var(--vy-err); }
    .svc { color: var(--vy-fg); }
    .action { color: var(--vy-fg-muted); }
    .ms { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .path { color: var(--vy-fg-dim); font-family: var(--vy-mono); font-size: var(--vy-fs-xs);
      margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .detail { padding: var(--vy-s3); border-top: 1px solid var(--vy-border);
      background: var(--vy-bg); max-height: 45%; overflow: auto; }
    .detail h4 { margin: var(--vy-s2) 0 var(--vy-s1); color: var(--vy-fg-dim);
      font-size: var(--vy-fs-xs); text-transform: uppercase; letter-spacing: .06em; }
    pre { font-family: var(--vy-mono); font-size: var(--vy-fs-xs); color: var(--vy-fg);
      background: var(--vy-bg-elev); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s2); white-space: pre-wrap;
      word-break: break-all; max-height: 140px; overflow: auto; }
    .explain { border-radius: var(--vy-radius); padding: var(--vy-s2); font-size: var(--vy-fs-sm); }
    .explain.error { background: rgba(248,81,73,.08); border: 1px solid var(--vy-err); color: var(--vy-err); }
    .explain.warn { background: rgba(210,153,34,.08); border: 1px solid var(--vy-warn); color: var(--vy-warn); }
    .hint { color: var(--vy-fg-muted); margin-top: 2px; }
    .backend { color: var(--vy-info); font-family: var(--vy-mono); font-size: var(--vy-fs-xs); }
    .actions { display: flex; gap: var(--vy-s2); margin-top: var(--vy-s2); flex-wrap: wrap; }
    .actions button { background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: pointer; }
    .actions button.primary { color: var(--vy-accent); border-color: var(--vy-accent); }
    .stub { padding: var(--vy-s5); color: var(--vy-fg-dim); font-size: var(--vy-fs-sm); }
    .empty { padding: var(--vy-s5); color: var(--vy-fg-dim); text-align: center; font-size: var(--vy-fs-sm); }
  `;

  constructor() {
    super();
    this._tab = 'calls';
    this._calls = [];
    this._filter = '';
    this._paused = false;
    this._selected = null;
    this._connected = false;
    this._es = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._connect();
  }

  disconnectedCallback() {
    this._disconnect();
    super.disconnectedCallback();
  }

  _connect() {
    if (this._es) return;
    try {
      const es = new EventSource(apiUrl('/api/console/calls/stream?replay=50'));
      es.addEventListener('call', (ev) => {
        if (this._paused) return;
        try {
          const call = JSON.parse(ev.data);
          this._calls = [call, ...this._calls].slice(0, 500);
        } catch (_) { /* ignore malformed */ }
      });
      es.addEventListener('ready', () => (this._connected = true));
      es.onopen = () => (this._connected = true);
      es.onerror = () => (this._connected = false);
      this._es = es;
    } catch (e) {
      this._connected = false;
    }
  }

  _disconnect() {
    if (this._es) { this._es.close(); this._es = null; }
    this._connected = false;
  }

  _statusClass(status) {
    if (status >= 500 || status === 0) return 's-err';
    if (status >= 400) return 's-warn';
    return 's-ok';
  }

  _filtered() {
    const q = (this._filter || '').toLowerCase();
    if (!q) return this._calls;
    return this._calls.filter((c) =>
      (c.service + ' ' + c.action + ' ' + c.http.method + ' ' + c.http.status + ' ' +
        c.http.path + ' ' + c.principal).toLowerCase().includes(q)
    );
  }

  _deepLink(call) {
    const ref = call.backend && call.backend.ref;
    if (!ref) return;
    this.dispatchEvent(new CustomEvent('deep-link', { detail: { ref }, bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="drawer ${this.open ? '' : 'closed'}">
        <div class="tabs">
          ${['calls', 'state', 'snapshots', 'conformance'].map(
            (t) => html`<button class=${this._tab === t ? 'on' : ''} @click=${() => (this._tab = t)}>${t}</button>`
          )}
        </div>
        ${this._tab === 'calls' ? this._renderCalls() : this._renderStub()}
      </div>
    `;
  }

  _renderStub() {
    const labels = {
      state: 'State — browse the real backend state (objects, rows, containers). Deep-linked from a call in P1.',
      snapshots: 'Snapshots — snapshot / fork / rollback tree over real state. Lands in P2.',
      conformance: 'Conformance — per-service checks vs the real SDK. Live panel lands with F5/P1.',
    };
    return html`<div class="stub">${labels[this._tab]}</div>`;
  }

  _renderCalls() {
    const calls = this._filtered();
    return html`
      <div class="toolbar">
        <span class="live ${this._connected ? '' : 'off'}"><span class="dot"></span>${this._connected ? 'live' : 'off'}</span>
        <input placeholder="filter service/status/principal…" .value=${this._filter}
          @input=${(e) => (this._filter = e.target.value)} />
        <button @click=${() => (this._paused = !this._paused)}>${this._paused ? '▶' : '⏸'}</button>
        <button @click=${() => { this._calls = []; this._selected = null; }}>clear</button>
      </div>
      <ul>
        ${calls.length === 0
          ? html`<li class="empty" style="cursor:default">
              No calls captured yet. Point boto3 / aws-cli / the object-browser at the
              endpoint and calls stream here live.</li>`
          : calls.map((c) => this._renderCall(c))}
      </ul>
      ${this._selected ? this._renderDetail(this._selected) : ''}
    `;
  }

  _renderCall(c) {
    const mv = METHOD_VAR[c.http.method] || '--vy-fg-muted';
    const sel = this._selected && this._selected.id === c.id;
    return html`
      <li class="call ${sel ? 'sel' : ''}" @click=${() => (this._selected = sel ? null : c)}>
        <div class="cl">
          <span class="method" style="color:var(${mv})">${c.http.method}</span>
          <span class="status ${this._statusClass(c.http.status)}">${c.http.status}</span>
          <span class="svc">${c.service}</span>
          <span class="action">${c.action}</span>
          <span class="ms">${c.http.ms}ms</span>
        </div>
        <div class="path">${c.http.path}</div>
      </li>
    `;
  }

  _renderDetail(c) {
    const ex = c.explain || {};
    const ref = c.backend && c.backend.ref;
    const linkable = ref && ref.type && ref.type.startsWith('s3') && ref.bucket;
    return html`
      <div class="detail">
        ${ex.level === 'error' || ex.level === 'warn'
          ? html`<div class="explain ${ex.level}">
              <b>why:</b> ${ex.why}
              ${ex.hint ? html`<div class="hint">↳ ${ex.hint}</div>` : ''}
            </div>` : ''}

        <h4>backend</h4>
        <div class="backend">served_by=${c.backend?.served_by} · kind=${c.backend?.kind}
          · ref=${JSON.stringify(ref || {})}</div>

        <h4>request</h4>
        <pre>${c.request?.body_summary || '(no body)'}</pre>
        <h4>response ${c.response?.code ? `· ${c.response.code}` : ''}</h4>
        <pre>${c.response?.body_summary || '(no body)'}</pre>

        <div class="actions">
          <button class=${linkable ? 'primary' : ''} ?disabled=${!linkable}
            @click=${() => this._deepLink(c)}>view in backend ▸</button>
          <button title="reveal CLI (stub)">reveal CLI</button>
          <button disabled title="snapshot — P2">snapshot</button>
          <button disabled title="replay — P2">replay</button>
        </div>
      </div>
    `;
  }
}

customElements.define('vyomi-inspector-drawer', InspectorDrawer);
