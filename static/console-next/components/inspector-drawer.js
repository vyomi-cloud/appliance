// Glass-box Inspector drawer (§12) — the flagship. Right-hand persistent drawer
// with four tabs; P0 ships the LIVE Calls tab (SSE stream of the §12.2 events).
// Snapshots is live (P2: capture/list/restore/FORK of in-process store state);
// Calls now offers REPLAY (re-issue a captured call against current state).
// State / Conformance remain placeholders (P1).
//
// The event shape is identical across substrates (§15.1 #5), so this UI is the
// same whether the FastAPI middleware or the Nano SW/router produced the events.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiUrl, apiGet, apiSend } from '../api.js';

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
    _snaps: { state: true },
    _snapBusy: { state: true },
    _snapErr: { state: true },
    _replay: { state: true },
    _replayBusy: { state: true },
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
    .actions button[disabled] { opacity: .5; cursor: default; }
    .replay { margin-top: var(--vy-s2); font-family: var(--vy-mono); font-size: var(--vy-fs-xs);
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s2); }
    .replay.changed { background: rgba(210,153,34,.08); border: 1px solid var(--vy-warn); color: var(--vy-fg); }
    .replay.same { background: var(--vy-bg-elev); border: 1px solid var(--vy-border-soft); color: var(--vy-fg-muted); }
    .replay.err { background: rgba(248,81,73,.08); border: 1px solid var(--vy-err); color: var(--vy-err); }
    .stub { padding: var(--vy-s5); color: var(--vy-fg-dim); font-size: var(--vy-fs-sm); }
    .empty { padding: var(--vy-s5); color: var(--vy-fg-dim); text-align: center; font-size: var(--vy-fs-sm); }
    .snaphead { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3);
      border-bottom: 1px solid var(--vy-border-soft); }
    .snaphead button { background: transparent; color: var(--vy-accent); border: 1px solid var(--vy-accent);
      border-radius: var(--vy-radius); padding: 1px var(--vy-s2); font-size: var(--vy-fs-xs); cursor: pointer; }
    .snaphead button[disabled] { opacity: .5; cursor: default; }
    .snaperr { color: var(--vy-err); font-size: var(--vy-fs-xs); margin-left: auto; }
    li.snap { padding: var(--vy-s2) var(--vy-s3); border-bottom: 1px solid var(--vy-border-soft);
      font-size: var(--vy-fs-sm); }
    .snaprow { display: flex; align-items: center; gap: var(--vy-s2); }
    .snapname { color: var(--vy-fg); font-family: var(--vy-mono); overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; }
    .snapmeta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: 2px; }
    .snaprestore { background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius); padding: 1px var(--vy-s2);
      font-size: var(--vy-fs-xs); cursor: pointer; }
    .snapfork { margin-left: auto; background: transparent; color: var(--vy-accent);
      border: 1px solid var(--vy-accent); border-radius: var(--vy-radius); padding: 1px var(--vy-s2);
      font-size: var(--vy-fs-xs); cursor: pointer; }
    .snapfork[disabled], .snaprestore[disabled] { opacity: .5; cursor: default; }
    .lineage { color: var(--vy-info); }
    .snapnote { padding: var(--vy-s3); color: var(--vy-fg-dim); font-size: var(--vy-fs-xs);
      border-top: 1px solid var(--vy-border-soft); line-height: 1.5; }
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
    this._snaps = [];
    this._snapBusy = false;
    this._snapErr = '';
    this._snapsLoaded = false;
    this._replay = null;      // { id, old_status, new_status, changed, error }
    this._replayBusy = false;
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

  // ── Replay (§12) — re-issue a captured call against CURRENT state and show a
  //    before/after (old status → new status) diff. Only /api/console/* facade
  //    calls are replayable server-side (native signed-wire calls can't be
  //    re-signed from a redacted capture). ──
  _replayable(call) {
    return !!(call && call.http && (call.http.path || '').startsWith('/api/console/'));
  }

  async _replayCall(call) {
    if (this._replayBusy || !this._replayable(call)) return;
    this._replayBusy = true;
    this._replay = null;
    try {
      const r = await apiSend('POST', `/api/console/calls/${encodeURIComponent(call.id)}/replay`, {});
      this._replay = { id: call.id, ...r };
      // a replay re-issues the call → state may have changed; let widgets refresh
      this.dispatchEvent(new CustomEvent('state-restored', { detail: { replay: call.id }, bubbles: true, composed: true }));
    } catch (e) {
      this._replay = { id: call.id, error: (e && e.message) || 'replay failed' };
    } finally {
      this._replayBusy = false;
    }
  }

  // ── Snapshots tab (§12.6) — capture / list / restore / FORK of the console's
  //    in-process backend store state. ──
  _selectTab(t) {
    this._tab = t;
    if (t === 'snapshots' && !this._snapsLoaded) this._loadSnapshots();
  }

  async _loadSnapshots() {
    this._snapErr = '';
    try {
      const r = await apiGet('/api/console/snapshots');
      this._snaps = r.snapshots || [];
      this._snapsLoaded = true;
    } catch (e) {
      this._snapErr = (e && e.message) || 'failed to load snapshots';
    }
  }

  async _snapshotNow() {
    if (this._snapBusy) return;
    this._snapBusy = true;
    this._snapErr = '';
    try {
      await apiSend('POST', '/api/console/snapshots', {});
      await this._loadSnapshots();
    } catch (e) {
      this._snapErr = (e && e.message) || 'snapshot failed';
    } finally {
      this._snapBusy = false;
    }
  }

  async _restoreSnapshot(id) {
    if (this._snapBusy) return;
    this._snapBusy = true;
    this._snapErr = '';
    try {
      await apiSend('POST', `/api/console/snapshots/${encodeURIComponent(id)}/restore`);
      // let widgets know state changed under them so they can refresh
      this.dispatchEvent(new CustomEvent('state-restored', { detail: { id }, bubbles: true, composed: true }));
    } catch (e) {
      this._snapErr = (e && e.message) || 'restore failed';
    } finally {
      this._snapBusy = false;
    }
  }

  async _forkSnapshot(id) {
    if (this._snapBusy) return;
    this._snapBusy = true;
    this._snapErr = '';
    try {
      await apiSend('POST', `/api/console/snapshots/${encodeURIComponent(id)}/fork`, {});
      await this._loadSnapshots();
    } catch (e) {
      this._snapErr = (e && e.message) || 'fork failed';
    } finally {
      this._snapBusy = false;
    }
  }

  _fmtSize(n) {
    if (n == null) return '—';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  _fmtWhen(ts) {
    if (!ts) return '';
    try { return new Date(ts * 1000).toLocaleString(); } catch (_) { return ''; }
  }

  _renderSnapshots() {
    return html`
      <div class="snaphead">
        <button ?disabled=${this._snapBusy} @click=${() => this._snapshotNow()}>
          ${this._snapBusy ? '…' : 'Snapshot now'}</button>
        <button @click=${() => this._loadSnapshots()} title="refresh">↻</button>
        ${this._snapErr ? html`<span class="snaperr">${this._snapErr}</span>` : ''}
      </div>
      <ul>
        ${this._snaps.length === 0
          ? html`<li class="empty" style="cursor:default">
              No snapshots yet. "Snapshot now" captures the current console state
              (secrets, KMS keys, queues/topics, RDS metadata).</li>`
          : this._snaps.map((s) => this._renderSnapRow(s))}
      </ul>
      <div class="snapnote">
        Captures the console's in-process backend state (control-plane first).
        <b>Fork</b> branches a new named line of state off any snapshot. Real MinIO
        objects, live SQL rows and Docker/LXD volumes are a later fidelity slice.
      </div>
    `;
  }

  _parentName(id) {
    const p = (this._snaps || []).find((x) => x.id === id);
    return p ? p.name : id;
  }

  _renderSnapRow(s) {
    const stores = (s.stores || []).join(', ');
    const isFork = s.kind === 'fork';
    return html`
      <li class="snap">
        <div class="snaprow">
          <span class="snapname">${isFork ? '⑂ ' : ''}${s.name}</span>
          <button class="snapfork" ?disabled=${this._snapBusy} title="branch a new line of state"
            @click=${() => this._forkSnapshot(s.id)}>fork</button>
          <button class="snaprestore" ?disabled=${this._snapBusy}
            @click=${() => this._restoreSnapshot(s.id)}>restore</button>
        </div>
        <div class="snapmeta">${this._fmtWhen(s.created)} · ${this._fmtSize(s.size)}${stores ? ` · ${stores}` : ''}</div>
        ${isFork && s.parent
          ? html`<div class="snapmeta lineage">⑂ forked from <b>${this._parentName(s.parent)}</b></div>`
          : ''}
        ${s.note && !isFork ? html`<div class="snapmeta">↳ ${s.note}</div>` : ''}
      </li>
    `;
  }

  render() {
    return html`
      <div class="drawer ${this.open ? '' : 'closed'}">
        <div class="tabs">
          ${['calls', 'state', 'snapshots', 'conformance'].map(
            (t) => html`<button class=${this._tab === t ? 'on' : ''} @click=${() => this._selectTab(t)}>${t}</button>`
          )}
        </div>
        ${this._tab === 'calls'
          ? this._renderCalls()
          : this._tab === 'snapshots'
            ? this._renderSnapshots()
            : this._renderStub()}
      </div>
    `;
  }

  _renderStub() {
    const labels = {
      state: 'State — browse the real backend state (objects, rows, containers). Deep-linked from a call in P1.',
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
      <li class="call ${sel ? 'sel' : ''}" @click=${() => { this._selected = sel ? null : c; this._replay = null; }}>
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
          <button ?disabled=${this._replayBusy || !this._replayable(c)}
            title=${this._replayable(c)
              ? 're-issue this call against current state'
              : 'only /api/console/* facade calls are replayable'}
            @click=${() => this._replayCall(c)}>${this._replayBusy ? 'replaying…' : 'replay'}</button>
        </div>
        ${this._replay && this._replay.id === c.id ? this._renderReplay(this._replay, c) : ''}
      </div>
    `;
  }

  _renderReplay(r, c) {
    if (r.error) {
      return html`<div class="replay err">replay failed: ${r.error}</div>`;
    }
    const oldS = r.old_status;
    const newS = r.new_status;
    const cls = r.changed ? 'changed' : 'same';
    return html`
      <div class="replay ${cls}">
        replayed · <span class="${this._statusClass(oldS)}">${oldS}</span>
        → <span class="${this._statusClass(newS)}">${newS}</span>
        ${r.changed ? html`<b> (changed)</b>` : ' (same)'}
      </div>
    `;
  }
}

customElements.define('vyomi-inspector-drawer', InspectorDrawer);
