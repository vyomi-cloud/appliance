// kms-crypto-view widget (§13 / §14.3) — AWS KMS crypto playground.
//
// Lists KMS keys, creates a key, and runs a live encrypt→ciphertext / decrypt→
// plaintext round-trip (plus generate-data-key for envelope encryption) — all
// against the appliance's KMS console REST API under /api/console/kms/* (backed by
// the substrate-agnostic kms_core over a shared KeyStore, exactly what the Nano
// relay drives). Rendered inside the common Connect contract with the mandatory
// `⛃ backed by <engine>` badge (§13.1) and a boto3 / CLI snippet.
//
// It talks ONLY to /api/* (§15.1 #2) — no substrate knowledge. Crypto is REAL:
// the widget passes base64 blobs (the native KMS wire) to the core and never does
// its own crypto — encrypt returns an honest CiphertextBlob, decrypt round-trips it.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend } from '../api.js';
import '../components/connect-contract.js';

// base64 <-> utf8 helpers (KMS wire carries base64 Plaintext/CiphertextBlob).
function b64FromText(s) {
  return btoa(unescape(encodeURIComponent(s || '')));
}
function textFromB64(b) {
  try { return decodeURIComponent(escape(atob(b || ''))); }
  catch (e) { return '(binary — ' + (b || '').length + ' b64 chars)'; }
}

class KmsCryptoView extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _keys: { state: true },        // [{ key_id, arn, description, state, enabled, usage, spec }]
    _sel: { state: true },         // selected key_id
    _detail: { state: true },      // describe result for the selected key
    _newDesc: { state: true },     // create-key description
    _plaintext: { state: true },   // encrypt input (utf8)
    _cipher: { state: true },      // ciphertext blob (base64) — encrypt output / decrypt input
    _decrypted: { state: true },   // decrypt output (utf8)
    _dataKey: { state: true },     // { plaintext, ciphertext_blob } from generate-data-key
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
    li .kid { font-family: var(--vy-mono); }
    .st { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .row { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3); }
    input[type=text] {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    input[type=text]:focus { border-color: var(--vy-accent); }
    textarea {
      width: 100%; box-sizing: border-box; min-height: 60px; resize: vertical;
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
    .blob {
      font-family: var(--vy-mono); font-size: var(--vy-fs-xs); color: var(--vy-fg);
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s2) var(--vy-s3);
      word-break: break-all; margin: var(--vy-s1) 0;
    }
    .meta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin: var(--vy-s2) 0; }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
    .editor { padding: var(--vy-s3); }
    .sub { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin: var(--vy-s3) 0 var(--vy-s1); }
    .tag { font-size: var(--vy-fs-xs); color: var(--vy-accent); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: 0 var(--vy-s1); }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._loadKeys();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced key.
    if (changed.has('deepLink') && this.deepLink && this.deepLink.key_id &&
        this.deepLink.key_id !== this._sel) {
      this._select(this.deepLink.key_id);
    }
  }

  async _loadKeys() {
    try {
      const r = await apiGet('/api/console/kms/keys');
      this._keys = r.keys || [];
      if (!this._sel && this._keys.length) this._select(this._keys[0].key_id);
    } catch (e) {
      this._msg = 'Could not list keys: ' + e.message;
    }
  }

  async _select(keyId) {
    this._sel = keyId;
    this._msg = '';
    try {
      this._detail = await apiGet(`/api/console/kms/keys/${encodeURIComponent(keyId)}`);
    } catch (e) {
      this._detail = null;
      this._msg = 'Could not describe key: ' + e.message;
    }
  }

  async _createKey() {
    this._busy = true;
    this._msg = '';
    try {
      const r = await apiSend('POST', '/api/console/kms/keys',
        { description: (this._newDesc || '').trim() });
      this._newDesc = '';
      await this._loadKeys();
      if (r && r.key_id) await this._select(r.key_id);
    } catch (e) {
      this._msg = 'Create failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _encrypt() {
    if (!this._sel) return;
    this._busy = true;
    this._msg = '';
    try {
      const r = await apiSend('POST', '/api/console/kms/encrypt',
        { key_id: this._sel, plaintext: b64FromText(this._plaintext || '') });
      this._cipher = r.ciphertext_blob || '';
      this._decrypted = null;
      this._msg = `Encrypted → ${(r.ciphertext_blob || '').length} b64 chars (${r.algorithm || ''})`;
    } catch (e) {
      this._msg = 'Encrypt failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _decrypt() {
    if (!this._cipher) return;
    this._busy = true;
    this._msg = '';
    try {
      // KeyId is intentionally NOT sent — the blob self-identifies its key (real
      // symmetric-KMS semantics). This proves the round-trip end to end.
      const r = await apiSend('POST', '/api/console/kms/decrypt',
        { ciphertext_blob: this._cipher });
      this._decrypted = textFromB64(r.plaintext || '');
      this._msg = `Decrypted with key ${(r.key_id || '').split('/').pop()}`;
    } catch (e) {
      this._msg = 'Decrypt failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _genDataKey() {
    if (!this._sel) return;
    this._busy = true;
    this._msg = '';
    try {
      this._dataKey = await apiSend('POST', '/api/console/kms/data-key',
        { key_id: this._sel, key_spec: 'AES_256' });
      this._msg = 'Generated a 256-bit data key (plaintext + wrapped ciphertext)';
    } catch (e) {
      this._msg = 'GenerateDataKey failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  _snippet() {
    const ep = this._endpoint();
    const k = this._sel || 'my-key-id';
    return `import boto3\nkms = boto3.client("kms", endpoint_url="${ep}",\n    aws_access_key_id="test", aws_secret_access_key="test")\nk = kms.create_key()["KeyMetadata"]["KeyId"]\nct = kms.encrypt(KeyId=k, Plaintext=b"hello")["CiphertextBlob"]\nkms.decrypt(CiphertextBlob=ct)["Plaintext"]`;
  }

  _cli() {
    const ep = this._endpoint();
    const k = this._sel || 'my-key-id';
    return `aws --endpoint-url ${ep} kms encrypt --key-id ${k} --plaintext "$(echo -n hello | base64)"`;
  }

  render() {
    const svc = this.service || {};
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const d = this._detail;
    return html`
      <vyomi-connect-contract
        .resourceId=${this._sel || 'KMS'}
        .resourceKind=${'key'}
        .backedBy=${svc.backed_by || 'in-proc KmsEngine'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Keys</div>
              <ul>
                ${(this._keys || []).map((k) => html`<li
                  class=${k.key_id === this._sel ? 'sel' : ''}
                  @click=${() => this._select(k.key_id)}>
                  🔑 <span class="kid">${(k.key_id || '').slice(0, 8)}…</span>
                  <span class="st">${k.state || ''}</span>
                </li>`)}
                ${(this._keys && this._keys.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no keys —</li>` : ''}
              </ul>
              <div class="row">
                <input type="text" placeholder="description (optional)" .value=${this._newDesc || ''}
                  @input=${(e) => (this._newDesc = e.target.value)}
                  @keydown=${(e) => e.key === 'Enter' && this._createKey()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createKey}>+ create</button>
              </div>
            </div>

            <div class="panel">
              <div class="ph">
                Key — ${this._sel ? this._sel.slice(0, 12) + '…' : '(none selected)'}
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${!this._sel || this._busy}
                  @click=${() => this._select(this._sel)}>↻ refresh</button>
              </div>
              ${d ? html`
                <div class="editor" style="padding-bottom:0">
                  <div class="meta">${d.arn || ''}</div>
                  ${d.description ? html`<div class="meta">${d.description}</div>` : ''}
                  <div class="meta">
                    <span class="tag">${d.state || ''}</span>
                    <span class="tag">${d.usage || ''}</span>
                    <span class="tag">${d.spec || ''}</span>
                  </div>

                  <div class="sub" style="margin-top:0">Encrypt → ciphertext</div>
                  <textarea placeholder="plaintext to encrypt" .value=${this._plaintext || ''}
                    @input=${(e) => (this._plaintext = e.target.value)}></textarea>
                  <div class="barr">
                    <button class="act" ?disabled=${this._busy} @click=${this._encrypt}>🔒 encrypt</button>
                  </div>
                  ${this._cipher ? html`
                    <div class="sub">CiphertextBlob (base64)</div>
                    <div class="blob">${this._cipher}</div>
                    <div class="barr">
                      <button class="act" ?disabled=${this._busy} @click=${this._decrypt}>🔓 decrypt</button>
                      <span class="hint">KeyId is NOT supplied — the blob self-identifies its key</span>
                    </div>
                  ` : ''}
                  ${this._decrypted != null ? html`
                    <div class="sub">Decrypted plaintext</div>
                    <div class="blob">${this._decrypted}</div>
                  ` : ''}

                  <div class="sub">Generate data key (envelope encryption)</div>
                  <div class="barr">
                    <button class="ghost" ?disabled=${this._busy} @click=${this._genDataKey}>⚙ generate-data-key AES_256</button>
                  </div>
                  ${this._dataKey ? html`
                    <div class="meta">plaintext data key (base64)</div>
                    <div class="blob">${this._dataKey.plaintext || ''}</div>
                    <div class="meta">wrapped (CiphertextBlob, base64)</div>
                    <div class="blob">${this._dataKey.ciphertext_blob || ''}</div>
                  ` : ''}
                </div>
              ` : html`<div class="meta" style="padding:var(--vy-s3)">Select or create a key to run the crypto playground.</div>`}
            </div>
          </div>
          ${this._msg ? html`<div class="${/(failed|Could not|Invalid)/.test(this._msg) ? 'err' : 'ok'}" style="padding:0 var(--vy-s1)">${this._msg}</div>` : ''}
        </div>

        <div slot="actions">
          <button class="ghost" title="refresh" @click=${() => this._loadKeys()}>refresh</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-kms-crypto-view', KmsCryptoView);
