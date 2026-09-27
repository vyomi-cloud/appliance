// kv-secret-viewer widget (§13 / §14.3) — AWS Secrets Manager secret viewer.
//
// Lists secrets, views a secret's metadata + versions with the value MASKED by
// default (reveal on click), and supports create / put-value — all against the
// appliance's Secrets Manager console REST API under /api/console/secrets/*
// (backed by the substrate-agnostic secrets_core over a shared KvStore, exactly
// what the Nano relay drives). Rendered inside the common Connect contract with the
// mandatory `⛃ backed by <engine>` badge (§13.1) and a boto3 / CLI snippet.
//
// It talks ONLY to /api/* (§15.1 #2) — no substrate knowledge. Secret VALUES are
// never shown until a deliberate reveal: the widget fetches the value lazily and
// masks it (••••) by default, so a casual glance never leaks a credential.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend } from '../api.js';
import '../components/connect-contract.js';

class KvSecretViewer extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _secrets: { state: true },     // [{ name, arn, description, created, last_changed, ... }]
    _sel: { state: true },         // selected secret name
    _detail: { state: true },      // describe result { name, arn, versions: [{version_id, stages}], ... }
    _value: { state: true },       // { version_id, secret_string, stages, ... } (fetched on reveal)
    _revealed: { state: true },    // bool — is the value currently un-masked?
    _draft: { state: true },       // put-value text
    _newSecret: { state: true },   // { name, value, description }
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
    ul { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 300px; overflow: auto; }
    li { padding: var(--vy-s1) var(--vy-s2); border-radius: var(--vy-radius); cursor: pointer;
      display: flex; align-items: center; gap: var(--vy-s2); color: var(--vy-fg-muted); font-size: var(--vy-fs-sm); }
    li:hover { background: var(--vy-bg-elev); color: var(--vy-fg); }
    li.sel { background: var(--vy-bg-elev-2); color: var(--vy-fg); }
    .sz { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .row { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3); }
    input[type=text] {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    input[type=text]:focus { border-color: var(--vy-accent); }
    textarea {
      width: 100%; box-sizing: border-box; min-height: 80px; resize: vertical;
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
    .val {
      display: flex; align-items: center; gap: var(--vy-s2); margin: var(--vy-s2) 0;
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); color: var(--vy-fg);
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s2) var(--vy-s3);
    }
    .val .masked { color: var(--vy-fg-dim); letter-spacing: .12em; }
    .val .shown { word-break: break-all; }
    .stages { display: inline-flex; gap: var(--vy-s1); }
    .tag { font-size: var(--vy-fs-xs); color: var(--vy-accent); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: 0 var(--vy-s1); }
    .vers { list-style: none; margin: var(--vy-s1) 0 0; padding: 0; }
    .vers li { font-family: var(--vy-mono); font-size: var(--vy-fs-xs); color: var(--vy-fg-muted);
      padding: 1px var(--vy-s2); cursor: pointer; }
    .vers li.sel { color: var(--vy-fg); }
    .meta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin: var(--vy-s2) 0; }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
    .editor { padding: var(--vy-s3); }
    .sub { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin: var(--vy-s3) 0 var(--vy-s1); }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._loadSecrets();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced secret.
    if (changed.has('deepLink') && this.deepLink && this.deepLink.secret &&
        this.deepLink.secret !== this._sel) {
      this._select(this.deepLink.secret);
    }
  }

  async _loadSecrets() {
    try {
      const r = await apiGet('/api/console/secrets');
      this._secrets = r.secrets || [];
      if (!this._sel && this._secrets.length) this._select(this._secrets[0].name);
    } catch (e) {
      this._msg = 'Could not list secrets: ' + e.message;
    }
  }

  async _select(name) {
    this._sel = name;
    this._value = null;
    this._revealed = false;
    this._msg = '';
    try {
      this._detail = await apiGet(`/api/console/secrets/${encodeURIComponent(name)}`);
    } catch (e) {
      this._detail = null;
      this._msg = 'Could not describe secret: ' + e.message;
    }
  }

  // Fetch the value ONLY on a deliberate reveal; then flip the mask.
  async _reveal(versionId) {
    if (!this._sel) return;
    this._busy = true;
    this._msg = '';
    try {
      let path = `/api/console/secrets/${encodeURIComponent(this._sel)}/value`;
      if (versionId) path += `?version_id=${encodeURIComponent(versionId)}`;
      this._value = await apiGet(path);
      this._revealed = true;
    } catch (e) {
      this._msg = 'Could not read value: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _mask() { this._revealed = false; }

  async _createSecret() {
    const ns = this._newSecret || {};
    const name = (ns.name || '').trim();
    if (!name) return;
    this._busy = true;
    this._msg = '';
    try {
      await apiSend('POST', '/api/console/secrets', {
        name,
        secret_string: ns.value || '',
        description: (ns.description || '').trim(),
      });
      this._newSecret = {};
      await this._loadSecrets();
      await this._select(name);
    } catch (e) {
      this._msg = 'Create failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _putValue() {
    if (!this._sel) return;
    this._busy = true;
    this._msg = '';
    try {
      const r = await apiSend('POST', `/api/console/secrets/${encodeURIComponent(this._sel)}/value`,
        { secret_string: this._draft || '' });
      this._msg = `Stored new version ${(r.version_id || '').slice(0, 8)}… → AWSCURRENT`;
      this._draft = '';
      await this._select(this._sel);
    } catch (e) {
      this._msg = 'Put value failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _deleteSecret() {
    if (!this._sel) return;
    this._busy = true;
    try {
      await apiSend('DELETE', `/api/console/secrets/${encodeURIComponent(this._sel)}`);
      this._sel = null; this._detail = null; this._value = null;
      await this._loadSecrets();
    } catch (e) {
      this._msg = 'Delete failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  _snippet() {
    const ep = this._endpoint();
    const n = this._sel || 'my-secret';
    return `import boto3\nsm = boto3.client("secretsmanager", endpoint_url="${ep}",\n    aws_access_key_id="test", aws_secret_access_key="test")\nsm.create_secret(Name="${n}", SecretString="s3cr3t")\nsm.get_secret_value(SecretId="${n}")["SecretString"]`;
  }

  _cli() {
    const ep = this._endpoint();
    const n = this._sel || 'my-secret';
    return `aws --endpoint-url ${ep} secretsmanager get-secret-value --secret-id ${n}`;
  }

  render() {
    const svc = this.service || {};
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const d = this._detail;
    return html`
      <vyomi-connect-contract
        .resourceId=${this._sel || 'Secrets Manager'}
        .resourceKind=${'secret'}
        .backedBy=${svc.backed_by || 'in-proc KvStore'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Secrets</div>
              <ul>
                ${(this._secrets || []).map((s) => html`<li
                  class=${s.name === this._sel ? 'sel' : ''}
                  @click=${() => this._select(s.name)}>
                  ⚿ ${s.name}
                </li>`)}
                ${(this._secrets && this._secrets.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no secrets —</li>` : ''}
              </ul>
              <div class="row">
                <input type="text" placeholder="new-secret" .value=${(this._newSecret && this._newSecret.name) || ''}
                  @input=${(e) => (this._newSecret = { ...(this._newSecret || {}), name: e.target.value })} />
              </div>
              <div class="row" style="padding-top:0">
                <input type="text" placeholder="value" .value=${(this._newSecret && this._newSecret.value) || ''}
                  @input=${(e) => (this._newSecret = { ...(this._newSecret || {}), value: e.target.value })}
                  @keydown=${(e) => e.key === 'Enter' && this._createSecret()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createSecret}>+ create</button>
              </div>
            </div>

            <div class="panel">
              <div class="ph">
                Secret — ${this._sel || '(none selected)'}
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${!this._sel || this._busy}
                  @click=${() => this._select(this._sel)}>↻ refresh</button>
              </div>
              ${d ? html`
                <div class="editor" style="padding-bottom:0">
                  <div class="meta">${d.arn || ''}</div>
                  ${d.description ? html`<div class="meta">${d.description}</div>` : ''}

                  <div class="sub" style="margin-top:0">Value — masked by default</div>
                  <div class="val">
                    ${this._revealed && this._value
                      ? html`<span class="shown">${this._value.secret_string != null
                          ? this._value.secret_string
                          : (this._value.secret_binary != null ? '(binary)' : '(no value)')}</span>`
                      : html`<span class="masked">••••••••••••</span>`}
                    <span style="flex:1"></span>
                    ${this._revealed
                      ? html`<button class="ghost" @click=${this._mask}>◎ hide</button>`
                      : html`<button class="ghost" ?disabled=${this._busy} @click=${() => this._reveal()}>👁 reveal</button>`}
                  </div>
                  ${this._revealed && this._value
                    ? html`<div class="meta">version <code>${(this._value.version_id || '').slice(0, 12)}…</code>
                        <span class="stages">${(this._value.stages || []).map((s) => html`<span class="tag">${s}</span>`)}</span></div>`
                    : ''}

                  <div class="sub">Versions</div>
                  <ul class="vers">
                    ${(d.versions || []).map((v) => html`<li
                      class=${this._value && this._value.version_id === v.version_id ? 'sel' : ''}
                      @click=${() => this._reveal(v.version_id)} title="reveal this version">
                      ${v.version_id.slice(0, 12)}…
                      <span class="stages">${(v.stages || []).map((s) => html`<span class="tag">${s}</span>`)}</span>
                    </li>`)}
                    ${(d.versions && d.versions.length === 0)
                      ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no versions —</li>` : ''}
                  </ul>
                </div>
              ` : html`<div class="meta" style="padding:var(--vy-s3)">Select a secret to view its metadata and versions.</div>`}
            </div>
          </div>

          ${d ? html`
            <div class="panel editor" style="margin-top:var(--vy-s4)">
              <div class="sub" style="margin-top:0">Put value — new AWSCURRENT version</div>
              <textarea placeholder="new secret value" .value=${this._draft || ''}
                @input=${(e) => (this._draft = e.target.value)}
                @keydown=${(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this._putValue(); }}></textarea>
              <div class="barr">
                <button class="act" ?disabled=${this._busy} @click=${this._putValue}>▸ put value</button>
                <button class="ghost" ?disabled=${this._busy} @click=${this._deleteSecret}>✕ delete secret</button>
                <span class="hint">⌘/Ctrl+Enter · the prior AWSCURRENT is demoted to AWSPREVIOUS</span>
              </div>
              ${this._msg ? html`<div class="${/(failed|Could not|Invalid)/.test(this._msg) ? 'err' : 'ok'}">${this._msg}</div>` : ''}
            </div>
          ` : (this._msg ? html`<div class="err" style="padding:var(--vy-s3)">${this._msg}</div>` : '')}
        </div>

        <div slot="actions">
          <button class="ghost" title="refresh" @click=${() => this._loadSecrets()}>refresh</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-kv-secret-viewer', KvSecretViewer);
