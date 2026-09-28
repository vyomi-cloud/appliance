// nosql-item-viewer widget (§13 / §14.3) — NoSQL item viewer.
//
// Lists NoSQL tables/collections, browses items in a selected one, and supports
// get/put a single item + a simple key query. It is CLOUD-AGNOSTIC: it reads its
// endpoint paths from the selected service descriptor's `api` block (§15.2) — so the
// SAME widget serves AWS DynamoDB (/api/dynamodb/*, backed by DynamoDB-Local) and GCP
// Firestore (/api/console/firestore/*) with ZERO branching. When no `api` block is
// present it falls back to the DynamoDB defaults, so the AWS lens keeps working
// unchanged.
//
// Rendered inside the common Connect contract with the mandatory `⛃ backed by
// <engine>` badge (§13.1) and a boto3 / CLI snippet (also descriptor-driven via the
// service's `connect` block, DynamoDB defaults preserved).
//
// It talks ONLY to /api/* (§15.1 #2) — no substrate knowledge. It also honors a
// deepLink (backend.ref {ddb.item, table, key}) pushed from the glass-box Inspector:
// selecting a PutItem/GetItem call jumps here and selects that table (+ item).
//
// Item JSON here is the NATIVE (plain-JSON) form — the REST API takes `item`/`key`
// as native maps and does the attribute-typing itself, so the console never
// hand-writes {"S": ...} wrappers.
//
// API contract (service.api): { listTables, createTable, getTable, listItems,
// putItem, deleteItem, queryItems } — path templates with a {table} placeholder this
// widget substitutes + URL-encodes.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend } from '../api.js';
import '../components/connect-contract.js';

class NosqlItemViewer extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _tables: { state: true },      // [{ table_name, partition_key_name, sort_key_name, item_count, ... }]
    _table: { state: true },       // selected table view (with keys/metadata)
    _rows: { state: true },        // [{ key, item, item_json, size_human, ... }]
    _viewing: { state: true },     // selected row's native item
    _draft: { state: true },       // put-item JSON draft text
    _qval: { state: true },        // query partition-key value
    _qsort: { state: true },       // query sort-key begins_with
    _busy: { state: true },
    _msg: { state: true },
    _newTable: { state: true },    // { name, pk, sk }
  };

  static styles = css`
    :host { display: block; }
    .cols { display: grid; grid-template-columns: 240px 1fr; gap: var(--vy-s4); }
    .panel { background: var(--vy-panel); border: 1px solid var(--vy-border); border-radius: var(--vy-radius); }
    .panel .ph {
      padding: var(--vy-s2) var(--vy-s3); border-bottom: 1px solid var(--vy-border-soft);
      color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase; letter-spacing: .06em;
      display: flex; align-items: center; gap: var(--vy-s2);
    }
    ul { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 300px; overflow: auto; }
    li { padding: var(--vy-s1) var(--vy-s2); border-radius: var(--vy-radius); cursor: pointer;
      display: flex; align-items: center; gap: var(--vy-s2); color: var(--vy-fg-muted); font-size: var(--vy-fs-sm); }
    li:hover { background: var(--vy-bg-elev); color: var(--vy-fg); }
    li.sel { background: var(--vy-bg-elev-2); color: var(--vy-fg); }
    .sz { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .keys { color: var(--vy-fg-dim); font-family: var(--vy-mono); font-size: var(--vy-fs-xs); padding: var(--vy-s1) var(--vy-s3); }
    .keys .pk { color: var(--vy-accent); }
    .row { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3); }
    input[type=text] {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    input[type=text]:focus { border-color: var(--vy-accent); }
    textarea {
      width: 100%; box-sizing: border-box; min-height: 120px; resize: vertical;
      background: var(--vy-bg); color: var(--vy-fg); font-family: var(--vy-mono);
      font-size: var(--vy-fs-sm); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: var(--vy-s2); outline: none;
    }
    textarea:focus { border-color: var(--vy-accent); }
    .barr { display: flex; align-items: center; gap: var(--vy-s2); margin-top: var(--vy-s2); flex-wrap: wrap; }
    button.act { background: var(--vy-accent); color: var(--vy-accent-fg); border: 0;
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s3); cursor: pointer; font-size: var(--vy-fs-sm); }
    button.act:disabled { opacity: .5; cursor: default; }
    button.ghost {
      background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); cursor: pointer; font-size: var(--vy-fs-xs);
    }
    pre {
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); color: var(--vy-fg);
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s3); max-height: 240px; overflow: auto;
      white-space: pre-wrap; word-break: break-all;
    }
    .meta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin: var(--vy-s2) 0; }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
    .editor { padding: var(--vy-s3); }
    .sub { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin: var(--vy-s3) 0 var(--vy-s1); }
  `;

  // ── Endpoint resolution (§15.2): read paths from the service descriptor's `api`
  //    block, falling back to the DynamoDB REST defaults so the AWS lens works
  //    unchanged. The widget is thereby cloud-agnostic — the GCP lens supplies
  //    Firestore paths of the same shape and NOTHING below changes. ──
  static _DDB_DEFAULTS = {
    listTables: '/api/dynamodb/tables',
    createTable: '/api/dynamodb/tables',
    getTable: '/api/dynamodb/tables/{table}',
    listItems: '/api/dynamodb/tables/{table}/items',
    putItem: '/api/dynamodb/tables/{table}/items',
    deleteItem: '/api/dynamodb/tables/{table}/items',
    queryItems: '/api/dynamodb/tables/{table}/query',
  };

  _tpl(name) {
    const api = (this.service && this.service.api) || {};
    return api[name] || NosqlItemViewer._DDB_DEFAULTS[name];
  }

  // Substitute + URL-encode the {table} placeholder in a path template.
  _path(name, { table } = {}) {
    let p = this._tpl(name);
    if (table != null) p = p.replace('{table}', encodeURIComponent(table));
    return p;
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadTables();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced table (+ item).
    if (changed.has('deepLink') && this.deepLink && this.deepLink.table) {
      const t = this.deepLink.table;
      if (t !== this._tableName()) {
        this._selectTable(t).then(() => {
          if (this.deepLink && this.deepLink.key) this._getByKey(this.deepLink.key);
        });
      } else if (this.deepLink.key) {
        this._getByKey(this.deepLink.key);
      }
    }
  }

  _tableName() { return this._table && this._table.table_name; }

  async _loadTables() {
    try {
      const r = await apiGet(this._path('listTables'));
      this._tables = r.tables || [];
      if (!this._table && this._tables.length) {
        this._selectTable(this._tables[0].table_name);
      }
    } catch (e) {
      this._msg = 'Could not list tables: ' + e.message;
    }
  }

  async _selectTable(name) {
    this._viewing = null;
    this._msg = '';
    try {
      const r = await apiGet(this._path('getTable', { table: name }));
      this._table = r.table || null;
      this._draft = this._sampleItem(this._table);
      await this._listItems(name);
    } catch (e) {
      this._table = null; this._rows = [];
      this._msg = 'Could not load table: ' + e.message;
    }
  }

  async _listItems(name) {
    try {
      const r = await apiGet(this._path('listItems', { table: name }));
      this._rows = r.items || [];
    } catch (e) {
      this._rows = [];
      this._msg = 'Could not list items: ' + e.message;
    }
  }

  _sampleItem(t) {
    if (!t) return '{\n  "id": "item-1"\n}';
    const obj = {};
    obj[t.partition_key_name || 'id'] = 'item-1';
    if (t.sort_key_name) obj[t.sort_key_name] = 'sort-1';
    obj.note = 'edit me';
    return JSON.stringify(obj, null, 2);
  }

  async _createTable() {
    const nt = this._newTable || {};
    const name = (nt.name || '').trim();
    if (!name) return;
    this._busy = true;
    try {
      await apiSend('POST', this._path('createTable'), {
        table_name: name,
        partition_key_name: (nt.pk || 'id').trim() || 'id',
        sort_key_name: (nt.sk || '').trim(),
      });
      this._newTable = {};
      await this._loadTables();
      await this._selectTable(name);
    } catch (e) {
      this._msg = 'Create table failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _view(row) {
    this._viewing = row;
    this._msg = '';
  }

  async _putItem() {
    const name = this._tableName();
    if (!name) return;
    let item;
    try {
      item = JSON.parse(this._draft || '{}');
    } catch (e) {
      this._msg = 'Invalid JSON: ' + e.message;
      return;
    }
    this._busy = true;
    this._msg = '';
    try {
      await apiSend('POST', this._path('putItem', { table: name }), { item });
      this._msg = `Put item → ${(this.service && this.service.backed_by) || 'DynamoDB-Local'}`;
      await this._listItems(name);
    } catch (e) {
      this._msg = 'Put failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _deleteItem(row) {
    const name = this._tableName();
    if (!name || !row) return;
    this._busy = true;
    try {
      await apiSend('DELETE', this._path('deleteItem', { table: name }), { key: row.key });
      if (this._viewing && this._viewing === row) this._viewing = null;
      await this._listItems(name);
    } catch (e) {
      this._msg = 'Delete failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  // GetItem by native key map — used by deep-links (match against the loaded rows).
  async _getByKey(key) {
    const row = (this._rows || []).find((r) => JSON.stringify(r.key) === JSON.stringify(key));
    if (row) this._view(row);
  }

  async _query() {
    const name = this._tableName();
    if (!name) return;
    const pk = (this._qval || '').trim();
    if (!pk) { this._msg = 'Enter a partition-key value to query'; return; }
    this._busy = true;
    this._msg = '';
    try {
      const body = { partition_key_value: pk };
      const sk = (this._qsort || '').trim();
      if (sk) body.sort_key_begins_with = sk;
      const r = await apiSend('POST', this._path('queryItems', { table: name }), body);
      this._rows = r.items || [];
      this._msg = `Query → ${r.count} item(s) (scanned ${r.scanned_count})`;
    } catch (e) {
      this._msg = 'Query failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _clearQuery() {
    this._qval = ''; this._qsort = ''; this._msg = '';
    if (this._tableName()) this._listItems(this._tableName());
  }

  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  // The connect snippet/CLI/hint are descriptor-driven too (§15.2): a service may
  // carry a `connect` block { snippet, cli } — templates with {ep} and {table}
  // placeholders. Absent → the AWS DynamoDB (boto3) defaults, so the AWS lens is
  // unchanged; the GCP lens supplies a Firestore variant with NO widget branching.
  static _DDB_CONNECT = {
    snippet:
      'import boto3\nddb = boto3.resource("dynamodb", endpoint_url="{ep}",\n' +
      '    aws_access_key_id="test", aws_secret_access_key="test")\n' +
      'table = ddb.Table("{table}")\n' +
      'table.put_item(Item={"id": "item-1", "note": "hello"})\n' +
      'table.get_item(Key={"id": "item-1"})',
    cli: 'aws --endpoint-url {ep} dynamodb scan --table-name {table}',
  };

  _connect(name) {
    const c = (this.service && this.service.connect) || {};
    return c[name] || NosqlItemViewer._DDB_CONNECT[name];
  }

  _fill(tpl) {
    return String(tpl).split('{ep}').join(this._endpoint())
      .split('{table}').join(this._tableName() || 'my-table');
  }

  _snippet() { return this._fill(this._connect('snippet')); }
  _cli() { return this._fill(this._connect('cli')); }

  render() {
    const svc = this.service || {};
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const t = this._table;
    const pkName = (t && t.partition_key_name) || 'id';
    const skName = t && t.sort_key_name;
    const v = this._viewing;
    return html`
      <vyomi-connect-contract
        .resourceId=${this._tableName() || svc.label || 'DynamoDB'}
        .resourceKind=${svc.terminology || 'table'}
        .backedBy=${svc.backed_by || 'DynamoDB-Local'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Tables</div>
              <ul>
                ${(this._tables || []).map((tb) => html`<li
                  class=${tb.table_name === this._tableName() ? 'sel' : ''}
                  @click=${() => this._selectTable(tb.table_name)}>
                  ⊞ ${tb.table_name}<span class="sz">${tb.item_count ?? ''}</span>
                </li>`)}
                ${(this._tables && this._tables.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no tables —</li>` : ''}
              </ul>
              <div class="row">
                <input type="text" placeholder="new-table" .value=${(this._newTable && this._newTable.name) || ''}
                  @input=${(e) => (this._newTable = { ...(this._newTable || {}), name: e.target.value })}
                  @keydown=${(e) => e.key === 'Enter' && this._createTable()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createTable}>+ create</button>
              </div>
              <div class="row" style="padding-top:0">
                <input type="text" placeholder="pk (default id)" .value=${(this._newTable && this._newTable.pk) || ''}
                  @input=${(e) => (this._newTable = { ...(this._newTable || {}), pk: e.target.value })} />
                <input type="text" placeholder="sort key (opt)" .value=${(this._newTable && this._newTable.sk) || ''}
                  @input=${(e) => (this._newTable = { ...(this._newTable || {}), sk: e.target.value })} />
              </div>
            </div>

            <div class="panel">
              <div class="ph">
                Items — ${this._tableName() || '(no table)'}
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${!this._tableName() || this._busy}
                  @click=${() => this._listItems(this._tableName())}>↻ refresh</button>
              </div>
              ${t ? html`<div class="keys">key: <span class="pk">${pkName}</span> (${t.partition_key_type || 'S'})${
                skName ? html` · sort <span class="pk">${skName}</span> (${t.sort_key_type || 'S'})` : ''}</div>` : ''}
              <ul>
                ${(this._rows || []).map((r) => html`<li class=${v === r ? 'sel' : ''} @click=${() => this._view(r)}>
                  ▢ ${this._keyLabel(r, pkName, skName)}
                  <span class="sz">${r.size_human || ''}</span>
                  <button class="ghost" @click=${(e) => { e.stopPropagation(); this._deleteItem(r); }}
                    title="delete item">✕</button>
                </li>`)}
                ${(this._rows && this._rows.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no items —</li>` : ''}
              </ul>
            </div>
          </div>

          ${t ? html`
            <div class="panel editor" style="margin-top:var(--vy-s4)">
              <div class="sub" style="margin-top:0">Query — by partition key</div>
              <div class="barr">
                <input type="text" placeholder=${`${pkName} value`} .value=${this._qval || ''}
                  @input=${(e) => (this._qval = e.target.value)}
                  @keydown=${(e) => e.key === 'Enter' && this._query()} style="max-width:220px" />
                ${skName ? html`<input type="text" placeholder=${`${skName} begins_with`} .value=${this._qsort || ''}
                  @input=${(e) => (this._qsort = e.target.value)}
                  @keydown=${(e) => e.key === 'Enter' && this._query()} style="max-width:220px" />` : ''}
                <button class="act" ?disabled=${this._busy} @click=${this._query}>▸ query</button>
                <button class="ghost" @click=${this._clearQuery}>clear</button>
              </div>

              <div class="sub">Put item — native JSON</div>
              <textarea .value=${this._draft || ''} @input=${(e) => (this._draft = e.target.value)}
                @keydown=${(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this._putItem(); }}></textarea>
              <div class="barr">
                <button class="act" ?disabled=${this._busy} @click=${this._putItem}>▸ put item</button>
                <span class="hint">⌘/Ctrl+Enter · must include the partition key (${pkName})${
                  skName ? ` + sort key (${skName})` : ''}</span>
              </div>

              ${v ? html`
                <div class="sub">Get item — ${this._keyLabel(v, pkName, skName)}</div>
                <div class="meta">${v.size_human || ''} · created ${v.created || '—'} · real record from DynamoDB-Local</div>
                <pre>${JSON.stringify(v.item != null ? v.item : v, null, 2)}</pre>
                <div class="barr">
                  <button class="ghost" @click=${() => { this._draft = JSON.stringify(v.item || {}, null, 2); }}>↥ load into editor</button>
                  <button class="ghost" @click=${() => this._deleteItem(v)}>✕ delete</button>
                </div>
              ` : ''}

              ${this._msg ? html`<div class="${/(failed|Invalid|Could not|Enter)/.test(this._msg) ? 'err' : 'ok'}">${this._msg}</div>` : ''}
            </div>
          ` : (this._msg ? html`<div class="err" style="padding:var(--vy-s3)">${this._msg}</div>` : '')}
        </div>

        <div slot="actions">
          <button class="ghost" title="scan (refresh)" @click=${() => this._tableName() && this._listItems(this._tableName())}>scan</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }

  _keyLabel(r, pkName, skName) {
    const k = (r && r.key) || {};
    const pk = k[pkName];
    const sk = skName ? k[skName] : undefined;
    const s = pk !== undefined ? String(pk) : '(item)';
    return sk !== undefined && sk !== '' ? `${s} / ${sk}` : s;
  }
}

customElements.define('vyomi-nosql-item-viewer', NosqlItemViewer);
