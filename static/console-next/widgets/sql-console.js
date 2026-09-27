// sql-console widget (§13.4 / §14.3) — RDS real SQL console.
//
// A SQL editor + run button + result grid + schema (tables/columns) browser, all
// against the console-next RDS Data API path (/api/console/rds/execute), which drives
// the same rds_data_core (ExecuteStatement) the Nano relay uses — the relay-safe SQL
// surface. Rendered inside the common Connect contract with the mandatory
// `⛃ backed by <engine>` badge and a psycopg2 / rds-data / CLI snippet.
//
// It talks ONLY to /api/* (§15.1 #2) — no substrate knowledge. Honors a deepLink
// (backend.ref {rds.rows, db, sql}) from the glass-box Inspector: pre-fills the db +
// SQL and runs it, so `view in backend ▸` on an ExecuteStatement lands on the rows.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend } from '../api.js';
import '../components/connect-contract.js';

class SqlConsole extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _dbs: { state: true },
    _db: { state: true },
    _sql: { state: true },
    _result: { state: true },   // { ok, columns, rows, rowcount, is_select, error }
    _schema: { state: true },   // { tables: [{name, columns}] }
    _busy: { state: true },
    _msg: { state: true },
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
    ul.tables { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 300px; overflow: auto; }
    ul.tables li { padding: var(--vy-s1) var(--vy-s2); border-radius: var(--vy-radius);
      color: var(--vy-fg-muted); font-size: var(--vy-fs-sm); cursor: pointer; }
    ul.tables li:hover { background: var(--vy-bg-elev); color: var(--vy-fg); }
    .colname { color: var(--vy-fg-dim); font-family: var(--vy-mono); font-size: var(--vy-fs-xs);
      padding: 1px 0 1px var(--vy-s4); }
    .colname .pk { color: var(--vy-accent); }
    textarea {
      width: 100%; box-sizing: border-box; min-height: 96px; resize: vertical;
      background: var(--vy-bg); color: var(--vy-fg); font-family: var(--vy-mono);
      font-size: var(--vy-fs-sm); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: var(--vy-s2); outline: none;
    }
    textarea:focus { border-color: var(--vy-accent); }
    .barr { display: flex; align-items: center; gap: var(--vy-s2); margin-top: var(--vy-s2); }
    button.act { background: var(--vy-accent); color: var(--vy-accent-fg); border: 0;
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s3); cursor: pointer; font-size: var(--vy-fs-sm); }
    button.act:disabled { opacity: .5; cursor: default; }
    select.db { background: var(--vy-bg-elev-2); color: var(--vy-fg); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: 2px var(--vy-s2); font-size: var(--vy-fs-sm); }
    .grid { margin-top: var(--vy-s3); overflow: auto; max-height: 300px; border: 1px solid var(--vy-border-soft); border-radius: var(--vy-radius); }
    table { border-collapse: collapse; width: 100%; font-size: var(--vy-fs-sm); }
    th, td { text-align: left; padding: var(--vy-s1) var(--vy-s2); border-bottom: 1px solid var(--vy-border-soft);
      font-family: var(--vy-mono); white-space: nowrap; }
    th { color: var(--vy-fg-dim); background: var(--vy-bg-elev); position: sticky; top: 0; }
    td { color: var(--vy-fg); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
  `;

  constructor() {
    super();
    this._sql = 'SELECT 1 AS hello;';
    this._dbs = [];
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadDbs();
  }

  updated(changed) {
    if (changed.has('deepLink') && this.deepLink && this.deepLink.type === 'rds.rows') {
      if (this.deepLink.db) this._db = this.deepLink.db;
      if (this.deepLink.sql) { this._sql = this.deepLink.sql; this._run(); }
    }
  }

  async _loadDbs() {
    try {
      const r = await apiGet('/api/console/rds/databases');
      this._dbs = r.databases || [];
      if (!this._db) this._db = r.default || (this._dbs[0] && this._dbs[0].db_instance_identifier);
      this._loadSchema();
    } catch (e) {
      this._msg = 'Could not list databases: ' + e.message;
    }
  }

  async _loadSchema() {
    if (!this._db) return;
    try {
      this._schema = await apiGet(`/api/console/rds/databases/${encodeURIComponent(this._db)}/schema`);
    } catch (_) { this._schema = { tables: [] }; }
  }

  async _run() {
    const sql = (this._sql || '').trim();
    if (!sql) return;
    this._busy = true;
    this._msg = '';
    try {
      const r = await apiSend('POST', '/api/console/rds/execute', { db: this._db, sql });
      this._result = r;
      if (r.ok) this._loadSchema();   // DDL may have changed the schema
    } catch (e) {
      this._result = { ok: false, error: e.message, columns: [], rows: [] };
    } finally {
      this._busy = false;
    }
  }

  _pickTable(t) {
    this._sql = `SELECT * FROM ${t} LIMIT 50;`;
    this._run();
  }

  _snippet() {
    const ep = this._endpoint();
    return `import boto3\nrds = boto3.client("rds-data", endpoint_url="${ep}",\n    aws_access_key_id="test", aws_secret_access_key="test")\nrds.execute_statement(\n    resourceArn="arn:aws:rds:us-east-1:123456789012:db:${this._db || 'acme'}",\n    database="${this._db || 'acme'}",\n    sql="SELECT * FROM orders WHERE qty > 10")`;
  }
  _cli() {
    const ep = this._endpoint();
    return `aws --endpoint-url ${ep} rds-data execute-statement \\\n  --resource-arn arn:aws:rds:...:db:${this._db || 'acme'} --database ${this._db || 'acme'} \\\n  --sql "SELECT * FROM orders"`;
  }
  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  render() {
    const svc = this.service || {};
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const r = this._result;
    return html`
      <vyomi-connect-contract
        .resourceId=${this._db || 'RDS'}
        .resourceKind=${'db instance'}
        .backedBy=${svc.backed_by || 'PostgreSQL/sqlite'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Schema
                <span style="flex:1"></span>
                <select class="db" .value=${this._db || ''}
                  @change=${(e) => { this._db = e.target.value; this._loadSchema(); }}>
                  ${(this._dbs || []).map((d) => html`<option .value=${d.db_instance_identifier}
                    ?selected=${d.db_instance_identifier === this._db}>${d.db_instance_identifier}</option>`)}
                </select>
              </div>
              <ul class="tables">
                ${((this._schema && this._schema.tables) || []).map((t) => html`
                  <li @click=${() => this._pickTable(t.name)}>◫ ${t.name}</li>
                  ${(t.columns || []).map((c) => html`<div class="colname">${c.name}
                    <span style="color:var(--vy-fg-dim)">${c.type || ''}</span>
                    ${c.pk ? html`<span class="pk">PK</span>` : ''}</div>`)}
                `)}
                ${(this._schema && this._schema.tables && this._schema.tables.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no tables — run a CREATE TABLE —</li>` : ''}
              </ul>
            </div>

            <div class="panel" style="padding:var(--vy-s3)">
              <div class="ph" style="border:0;padding:0 0 var(--vy-s2)">SQL</div>
              <textarea .value=${this._sql || ''} @input=${(e) => (this._sql = e.target.value)}
                @keydown=${(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this._run(); }}></textarea>
              <div class="barr">
                <button class="act" ?disabled=${this._busy} @click=${this._run}>▸ run</button>
                <span class="hint">⌘/Ctrl+Enter · runs via RDS Data API (ExecuteStatement) — relay-safe</span>
              </div>

              ${r && !r.ok ? html`<div class="err">✗ ${r.error}</div>` : ''}
              ${r && r.ok && !r.is_select
                ? html`<div class="ok">✓ ${r.rowcount} row(s) affected</div>` : ''}
              ${r && r.ok && r.is_select ? html`
                <div class="grid">
                  <table>
                    <thead><tr>${(r.columns || []).map((c) => html`<th>${c}</th>`)}</tr></thead>
                    <tbody>
                      ${(r.rows || []).map((row) => html`<tr>${row.map((v) =>
                        html`<td>${v === null ? html`<span style="color:var(--vy-fg-dim)">NULL</span>` : String(v)}</td>`)}</tr>`)}
                      ${(r.rows && r.rows.length === 0)
                        ? html`<tr><td style="color:var(--vy-fg-dim)" colspan=${(r.columns || []).length || 1}>— 0 rows —</td></tr>` : ''}
                    </tbody>
                  </table>
                </div>
                <div class="hint">${(r.rows || []).length} real row(s) — persist across the session</div>
              ` : ''}
              ${this._msg ? html`<div class="err">${this._msg}</div>` : ''}
            </div>
          </div>
        </div>

        <div slot="actions">
          <button style="opacity:.5" disabled title="reboot (stub)">reboot</button>
          <button style="opacity:.5" disabled title="snapshot — P2">snapshot</button>
          <button style="opacity:.5" disabled title="fork — P2">fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-sql-console', SqlConsole);
