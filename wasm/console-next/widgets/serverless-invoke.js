// serverless-invoke widget (§13) — cloud-agnostic serverless function invoke surface.
//
// Lists functions (name, runtime, handler, state) and, for a selected function,
// shows its configuration + an INVOKE panel: a JSON event-payload editor and an
// Invoke button that POSTs to the runtime. It is CLOUD-AGNOSTIC (§15.2): it reads
// its endpoint paths (list, get config, invoke, create) AND its connect snippet/CLI
// from the SELECTED service descriptor's `api` / `connect` blocks — so the SAME
// widget serves AWS Lambda and GCP Cloud Functions with ZERO branching. When no
// descriptor block is present it falls back to the AWS Lambda defaults, so the AWS
// lens keeps working unchanged:
//   GET  /api/lambda/functions                       (list)
//   GET  /api/lambda/functions/{name}                (config + invocations)
//   POST /api/lambda/functions                       (create — optional)
//   POST /api/lambda/functions/{name}/invoke         (invoke → response payload)
// so nothing here reinvents the runtime; the real sandboxed handler runs. Rendered
// inside the common Connect contract with the mandatory `⛃ backed by <engine>` badge
// (§13.1) + a native SDK / CLI snippet.
//
// It talks ONLY to /api/* (§15.1 #2) — no substrate/backend knowledge; the runtime
// backing is surfaced purely as the `backed_by` DATA from the manifest.
//
// API contract (service.api): { listFunctions, getFunction, invoke, createFunction }
// — path templates with a {name} placeholder this widget substitutes + URL-encodes.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend } from '../api.js';
import '../components/connect-contract.js';

class ServerlessInvoke extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _functions: { state: true },   // [{ function_name, runtime, handler, state, ... }]
    _sel: { state: true },         // selected function_name
    _fn: { state: true },          // selected function's full view (config + invocations)
    _payload: { state: true },     // invoke event-payload JSON draft text
    _result: { state: true },      // last invoke result { status, payload, stdout, stderr, error, at }
    _busy: { state: true },
    _msg: { state: true },
    _newFn: { state: true },       // { name, code }
  };

  static styles = css`
    :host { display: block; }
    .cols { display: grid; grid-template-columns: 260px 1fr; gap: var(--vy-s4); }
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
    li .fn { font-family: var(--vy-mono); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--vy-fg-dim); flex: none; }
    .dot.active { background: var(--vy-ok); }
    .dot.pending, .dot.creating { background: var(--vy-info); }
    .dot.failed, .dot.inactive { background: var(--vy-err); }
    .rt { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .editor { padding: var(--vy-s3); }
    .kv { display: grid; grid-template-columns: 120px 1fr; gap: var(--vy-s1) var(--vy-s2);
      font-size: var(--vy-fs-sm); margin: var(--vy-s1) 0; }
    .kv .k { color: var(--vy-fg-dim); }
    .kv .v { color: var(--vy-fg); font-family: var(--vy-mono); word-break: break-all; }
    .sub { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin: var(--vy-s3) 0 var(--vy-s1); }
    input[type=text] {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    input[type=text]:focus { border-color: var(--vy-accent); }
    textarea {
      width: 100%; box-sizing: border-box; min-height: 110px; resize: vertical;
      background: var(--vy-bg); color: var(--vy-fg); font-family: var(--vy-mono);
      font-size: var(--vy-fs-sm); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: var(--vy-s2); outline: none;
    }
    textarea:focus { border-color: var(--vy-accent); }
    .row { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3); }
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
      border-radius: var(--vy-radius); padding: var(--vy-s3); max-height: 220px; overflow: auto;
      white-space: pre-wrap; word-break: break-all;
    }
    pre.logs { color: var(--vy-fg-muted); }
    .status { display: inline-flex; align-items: center; gap: var(--vy-s1); font-size: var(--vy-fs-sm);
      font-family: var(--vy-mono); }
    .status.success { color: var(--vy-ok); }
    .status.error { color: var(--vy-err); }
    .status.accepted { color: var(--vy-info); }
    .meta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin: var(--vy-s1) 0; }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
  `;

  // ── Endpoint resolution (§15.2): read paths from the service descriptor's `api`
  //    block, falling back to the AWS Lambda defaults so the AWS lens works
  //    unchanged. The widget is thereby cloud-agnostic — the GCP lens supplies Cloud
  //    Functions paths of the same shape and NOTHING below changes. The only
  //    placeholder is {name} (getFunction / invoke), which the widget URL-encodes. ──
  static _LAMBDA_DEFAULTS = {
    listFunctions: '/api/lambda/functions',
    getFunction: '/api/lambda/functions/{name}',
    invoke: '/api/lambda/functions/{name}/invoke',
    createFunction: '/api/lambda/functions',
  };

  _tpl(name) {
    const api = (this.service && this.service.api) || {};
    return api[name] || ServerlessInvoke._LAMBDA_DEFAULTS[name];
  }

  // Substitute + URL-encode the {name} placeholder in a template.
  _apiPath(name, { fnName } = {}) {
    let p = this._tpl(name);
    if (fnName != null) p = p.replace('{name}', encodeURIComponent(fnName));
    return p;
  }

  connectedCallback() {
    super.connectedCallback();
    this._payload = '{}';
    this._loadFunctions();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced function.
    if (changed.has('deepLink') && this.deepLink && this.deepLink.function &&
        this.deepLink.function !== this._sel) {
      this._select(this.deepLink.function);
    }
  }

  _fname(f) { return f && (f.function_name || f.functionName || f.name); }
  _state(f) { return String((f && f.state) || '').toLowerCase(); }

  async _loadFunctions() {
    try {
      const r = await apiGet(this._apiPath('listFunctions'));
      this._functions = r.functions || [];
      if (!this._sel && this._functions.length) this._select(this._fname(this._functions[0]));
    } catch (e) {
      this._msg = 'Could not list functions: ' + e.message;
    }
  }

  async _select(name) {
    this._sel = name;
    this._fn = null;
    this._result = null;
    this._msg = '';
    if (!name) return;
    this._busy = true;
    try {
      this._fn = await apiGet(this._apiPath('getFunction', { fnName: name }));
    } catch (e) {
      this._fn = null;
      this._msg = 'Could not load function: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _createFunction() {
    const nf = this._newFn || {};
    const name = (nf.name || '').trim();
    if (!name) return;
    this._busy = true;
    this._msg = '';
    try {
      // Optional convenience: create a simple function. If code is left blank the
      // API supplies a default echo handler — either way the real runtime backs it.
      const body = { function_name: name };
      if ((nf.code || '').trim()) body.code = nf.code;
      await apiSend('POST', this._apiPath('createFunction'), body);
      this._newFn = {};
      await this._loadFunctions();
      await this._select(name);
    } catch (e) {
      this._msg = 'Create failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _invoke() {
    const name = this._sel;
    if (!name || this._busy) return;
    let payload;
    try {
      payload = JSON.parse((this._payload || '{}').trim() || '{}');
    } catch (e) {
      this._msg = 'Invalid JSON payload: ' + e.message;
      return;
    }
    this._busy = true;
    this._msg = '';
    this._result = null;
    try {
      const r = await apiSend('POST', this._apiPath('invoke', { fnName: name }),
        { payload, invocation_type: 'RequestResponse' });
      this._result = r || {};
      // Refresh config so the invocation history / counts update.
      this._select(name);
    } catch (e) {
      this._msg = 'Invoke failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  // The connect snippet/CLI are descriptor-driven too (§15.2): a service may carry a
  // `connect` block { snippet, cli } — templates with {ep} and {name} placeholders.
  // Absent → the AWS Lambda (boto3) defaults, so the AWS lens is unchanged; the GCP
  // lens supplies a Cloud Functions variant with NO widget branching.
  static _LAMBDA_CONNECT = {
    snippet:
      'import boto3, json\nlam = boto3.client("lambda", endpoint_url="{ep}",\n' +
      '    aws_access_key_id="test", aws_secret_access_key="test")\n' +
      'resp = lam.invoke(FunctionName="{name}",\n' +
      '    Payload=json.dumps({"hello": "world"}))\n' +
      'print(resp["Payload"].read().decode())',
    cli:
      'aws --endpoint-url {ep} lambda invoke --function-name {name} \\\n' +
      '    --payload \'{"hello":"world"}\' /dev/stdout',
  };

  _connectTpl(name) {
    const c = (this.service && this.service.connect) || {};
    return c[name] || ServerlessInvoke._LAMBDA_CONNECT[name];
  }

  _fill(tpl) {
    return String(tpl).split('{ep}').join(this._endpoint())
      .split('{name}').join(this._sel || 'my-function');
  }

  _snippet() { return this._fill(this._connectTpl('snippet')); }
  _cli() { return this._fill(this._connectTpl('cli')); }

  _configBlock(f) {
    if (this._busy && !f) return html`<div class="meta">Loading function…</div>`;
    if (!f) return html`<div class="meta" style="padding:var(--vy-s3)">Select a function to invoke.</div>`;
    return html`
      <div class="editor">
        <div class="kv">
          <span class="k">runtime</span><span class="v">${f.runtime || '—'}</span>
          <span class="k">handler</span><span class="v">${f.handler || '—'}</span>
          <span class="k">state</span><span class="v">${f.state || 'Active'}</span>
          <span class="k">memory</span><span class="v">${f.memory_size != null ? f.memory_size + ' MB' : '—'}</span>
          <span class="k">timeout</span><span class="v">${f.timeout != null ? f.timeout + ' s' : '—'}</span>
          <span class="k">arn</span><span class="v">${f.function_arn || '—'}</span>
        </div>

        <div class="sub">Invoke — event payload (JSON)</div>
        <textarea .value=${this._payload || '{}'} @input=${(e) => (this._payload = e.target.value)}
          @keydown=${(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this._invoke(); }}></textarea>
        <div class="barr">
          <button class="act" ?disabled=${this._busy} @click=${this._invoke}>▸ invoke</button>
          <span class="hint">⌘/Ctrl+Enter · RequestResponse · runs the real sandboxed handler</span>
        </div>

        ${this._resultBlock()}
        ${this._msg ? html`<div class="${/(failed|Invalid|Could not)/.test(this._msg) ? 'err' : 'ok'}">${this._msg}</div>` : ''}
      </div>
    `;
  }

  _resultBlock() {
    const r = this._result;
    if (!r) return '';
    const st = String(r.status || '').toLowerCase();
    const glyph = st === 'success' ? '✓' : st === 'error' ? '✕' : '⋯';
    return html`
      <div class="sub">Response</div>
      <div class="meta">
        <span class="status ${st}">${glyph} ${r.status || 'unknown'}</span>
        ${r.at ? html` · ${r.at}` : ''}
      </div>
      <pre>${this._fmt(r.payload)}</pre>
      ${r.error ? html`<div class="err">${r.error}${r.traceback ? '\n' + r.traceback : ''}</div>` : ''}
      ${(r.stdout || r.stderr) ? html`
        <div class="sub">Logs</div>
        <pre class="logs">${(r.stdout || '') + (r.stderr ? (r.stdout ? '\n' : '') + r.stderr : '') || '(no output)'}</pre>
      ` : ''}
    `;
  }

  _fmt(v) {
    if (v == null) return '(no payload)';
    if (typeof v === 'string') return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  render() {
    const svc = this.service || {};
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const f = this._fn;
    return html`
      <vyomi-connect-contract
        .resourceId=${this._sel || 'Lambda'}
        .resourceKind=${'function'}
        .backedBy=${svc.backed_by || 'in-proc runtime'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Functions</div>
              <ul>
                ${(this._functions || []).map((fn) => {
                  const n = this._fname(fn);
                  const st = this._state(fn) || 'active';
                  return html`<li class=${n === this._sel ? 'sel' : ''} @click=${() => this._select(n)}>
                    <span class="dot ${st}"></span>
                    <span class="fn">${n}</span>
                    <span class="rt">${fn.runtime || ''}</span>
                  </li>`;
                })}
                ${(this._functions && this._functions.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no functions —</li>` : ''}
              </ul>
              <div class="row">
                <input type="text" placeholder="new-function" .value=${(this._newFn && this._newFn.name) || ''}
                  @input=${(e) => (this._newFn = { ...(this._newFn || {}), name: e.target.value })}
                  @keydown=${(e) => e.key === 'Enter' && this._createFunction()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createFunction}>+ create</button>
              </div>
              <div class="hint" style="padding:0 var(--vy-s3) var(--vy-s3)">Creates a default Python echo handler you can invoke immediately.</div>
            </div>

            <div class="panel">
              <div class="ph">
                Function — ${this._sel || '(none selected)'}
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${!this._sel || this._busy}
                  @click=${() => this._select(this._sel)}>↻ refresh</button>
              </div>
              ${this._configBlock(f)}
            </div>
          </div>
        </div>

        <div slot="actions">
          <button class="ghost" title="refresh" @click=${() => this._loadFunctions()}>refresh</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-serverless-invoke', ServerlessInvoke);
