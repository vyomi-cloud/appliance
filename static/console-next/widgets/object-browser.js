// object-browser widget (§13.3 / §14.3) — the data-plane vertical.
//
// Lists buckets + objects, views an object, uploads a file. It is CLOUD-AGNOSTIC:
// it reads its endpoint paths from the selected service descriptor's `api` block
// (§15.2) — so the SAME widget serves S3 (AWS lens) and Cloud Storage (GCP lens)
// with ZERO branching. When no `api` block is present it falls back to the S3
// defaults, so the AWS lens keeps working unchanged. Rendered inside the common
// Connect contract with the mandatory `⛃ backed by …` badge (§13.1).
//
// It talks ONLY to /api/* (§15.1 #2); it has no substrate/cloud knowledge. It also
// honors a deepLink (backend.ref) pushed from the glass-box Inspector — clicking
// a PutObject/HeadObject call jumps here and selects that bucket/object.
//
// API contract (service.api): { listBuckets, createBucket, listObjects,
// uploadObject, objectMeta, objectDownload } — path templates with {bucket}/{key}
// placeholders this widget substitutes + URL-encodes.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend, apiUrl, cliForAction } from '../api.js';
import '../components/connect-contract.js';

class ObjectBrowser extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _buckets: { state: true },
    _bucket: { state: true },
    _objects: { state: true },
    _viewing: { state: true },   // { key, meta, text }
    _busy: { state: true },
    _msg: { state: true },
    _newBucket: { state: true },
  };

  static styles = css`
    :host { display: block; }
    .cols { display: grid; grid-template-columns: 240px 1fr; gap: var(--vy-s4); margin-bottom: var(--vy-s4); }
    .panel { background: var(--vy-panel); border: 1px solid var(--vy-border); border-radius: var(--vy-radius); }
    .panel .ph {
      padding: var(--vy-s2) var(--vy-s3); border-bottom: 1px solid var(--vy-border-soft);
      color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase; letter-spacing: .06em;
      display: flex; align-items: center; gap: var(--vy-s2);
    }
    ul { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 320px; overflow: auto; }
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
    button.act {
      background: var(--vy-accent); color: var(--vy-accent-fg); border: 0;
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s3);
      cursor: pointer; font-size: var(--vy-fs-sm);
    }
    button.act:disabled { opacity: .5; cursor: default; }
    button.ghost {
      background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); cursor: pointer; font-size: var(--vy-fs-xs);
    }
    .viewer { margin-top: var(--vy-s3); }
    pre {
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); color: var(--vy-fg);
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s3); max-height: 260px; overflow: auto;
      white-space: pre-wrap; word-break: break-all;
    }
    .meta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin: var(--vy-s2) 0; }
    .msg { color: var(--vy-fg-muted); font-size: var(--vy-fs-sm); padding: 0 var(--vy-s3) var(--vy-s2); }
    .err { color: var(--vy-err); }
    img.preview { max-width: 100%; max-height: 260px; border: 1px solid var(--vy-border-soft); border-radius: var(--vy-radius); }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._loadBuckets();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced bucket/object.
    if (changed.has('deepLink') && this.deepLink && this.deepLink.bucket) {
      const b = this.deepLink.bucket;
      const k = this.deepLink.key;
      if (b !== this._bucket) {
        this._selectBucket(b).then(() => { if (k) this._view(k); });
      } else if (k) {
        this._view(k);
      }
    }
  }

  // ── Endpoint resolution (§15.2): read paths from the service descriptor's `api`
  //    block, falling back to the S3 defaults so the AWS lens works unchanged. The
  //    widget is thereby cloud-agnostic — the GCP lens supplies GCS paths of the
  //    same shape and NOTHING below changes. ──
  static _S3_DEFAULTS = {
    listBuckets: '/api/s3/buckets',
    createBucket: '/api/s3/buckets/{bucket}',
    listObjects: '/api/s3/buckets/{bucket}/objects',
    uploadObject: '/api/s3/buckets/{bucket}/objects',
    objectMeta: '/api/s3/buckets/{bucket}/objects/{key}/meta',
    objectDownload: '/api/s3/buckets/{bucket}/objects/{key}/download',
  };

  _tpl(name) {
    const api = (this.service && this.service.api) || {};
    return api[name] || ObjectBrowser._S3_DEFAULTS[name];
  }

  // Substitute + URL-encode {bucket}/{key} placeholders in a path template.
  _path(name, { bucket, key } = {}) {
    let p = this._tpl(name);
    if (bucket != null) p = p.replace('{bucket}', encodeURIComponent(bucket));
    if (key != null) p = p.replace('{key}', encodeURIComponent(key));
    return p;
  }

  _backedBy() {
    return (this.service && this.service.backed_by) || 'MinIO';
  }

  async _loadBuckets() {
    try {
      const r = await apiGet(this._path('listBuckets'));
      this._buckets = r.buckets || [];
      if (!this._bucket && this._buckets.length) {
        this._selectBucket(this._buckets[0].name);
      }
    } catch (e) {
      this._msg = 'Could not list buckets: ' + e.message;
    }
  }

  async _selectBucket(name) {
    this._bucket = name;
    this._viewing = null;
    this._msg = '';
    try {
      const r = await apiGet(this._path('listObjects', { bucket: name }));
      this._objects = r.objects || [];
    } catch (e) {
      this._objects = [];
      this._msg = 'Could not list objects: ' + e.message;
    }
  }

  async _createBucket() {
    const name = (this._newBucket || '').trim();
    if (!name) return;
    this._busy = true;
    try {
      await apiSend('POST', this._path('createBucket', { bucket: name }));
      this._newBucket = '';
      await this._loadBuckets();
      await this._selectBucket(name);
    } catch (e) {
      this._msg = 'Create failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _upload(e) {
    const file = e.target.files && e.target.files[0];
    if (!file || !this._bucket) return;
    this._busy = true;
    this._msg = `Uploading ${file.name}…`;
    try {
      const fd = new FormData();
      fd.append('file', file, file.name);
      await apiSend('POST', this._path('uploadObject', { bucket: this._bucket }), fd, true);
      this._msg = `Uploaded ${file.name} → ${this._backedBy()}`;
      await this._selectBucket(this._bucket);
    } catch (err) {
      this._msg = 'Upload failed: ' + err.message;
    } finally {
      this._busy = false;
      e.target.value = '';
    }
  }

  async _view(key) {
    if (!this._bucket) return;
    this._msg = '';
    try {
      const meta = await apiGet(this._path('objectMeta', { bucket: this._bucket, key }));
      const url = apiUrl(this._path('objectDownload', { bucket: this._bucket, key }));
      const ct = (meta.content_type || '').toLowerCase();
      let text = null;
      let imageUrl = null;
      if (ct.startsWith('image/')) {
        imageUrl = url;
      } else {
        const resp = await fetch(url);
        const buf = await resp.arrayBuffer();
        text = this._renderBytes(buf, ct);
      }
      this._viewing = { key, meta, text, imageUrl, url };
    } catch (e) {
      this._msg = 'View failed: ' + e.message;
    }
  }

  _renderBytes(buf, ct) {
    const bytes = new Uint8Array(buf);
    const textual = ct.includes('text') || ct.includes('json') || ct.includes('xml') || ct.includes('csv') || ct === '';
    if (textual) {
      try { return new TextDecoder('utf-8', { fatal: false }).decode(bytes); } catch (_) { /* hex */ }
    }
    // hex preview (first 512 bytes)
    const n = Math.min(bytes.length, 512);
    let out = '';
    for (let i = 0; i < n; i += 16) {
      const slice = bytes.slice(i, i + 16);
      const hex = [...slice].map((b) => b.toString(16).padStart(2, '0')).join(' ');
      out += hex.padEnd(48) + '\n';
    }
    return out + (bytes.length > n ? `… (+${bytes.length - n} bytes)` : '');
  }

  _snippet() {
    const ep = (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
    const b = this._bucket || 'my-bucket';
    return `import boto3\ns3 = boto3.client("s3", endpoint_url="${ep}",\n    aws_access_key_id="test", aws_secret_access_key="test")\ns3.list_objects_v2(Bucket="${b}")`;
  }

  _cli() {
    const b = this._bucket || 'my-bucket';
    const ep = (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
    return `aws --endpoint-url ${ep} s3 cp ./report.csv s3://${b}/`;
  }

  // Per-action reveal-CLI lines (§12.8) via the shared cliForAction() helper — reuses
  // the descriptor's connect.cli where present, else these action templates, and fills
  // in the current bucket/key context. The shared Connect contract renders each as a
  // uniform "↳ reveal CLI" affordance.
  _revealActions() {
    const ep = (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
    const b = this._bucket || 'my-bucket';
    return [
      { label: 'upload object',
        command: cliForAction(this.service, {
          command: `aws --endpoint-url {ep} s3 cp ./report.csv s3://{bucket}/`,
          ctx: { ep, bucket: b } }) },
      { label: 'create bucket',
        command: cliForAction(this.service, {
          command: `aws --endpoint-url {ep} s3 mb s3://{bucket}`,
          ctx: { ep, bucket: b } }) },
    ];
  }

  render() {
    const ep = (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    return html`
      <vyomi-connect-contract
        .resourceId=${this._bucket || (this.service && this.service.label) || 'S3'}
        .resourceKind=${(this.service && this.service.terminology) || 'bucket'}
        .backedBy=${this._backedBy()}
        .connectMode=${mode}
        .endpoint=${ep}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
        .revealActions=${this._revealActions()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Buckets</div>
              <ul>
                ${(this._buckets || []).map(
                  (b) => html`<li class=${b.name === this._bucket ? 'sel' : ''}
                    @click=${() => this._selectBucket(b.name)}>▤ ${b.name}</li>`
                )}
              </ul>
              <div class="row">
                <input type="text" placeholder="new-bucket" .value=${this._newBucket || ''}
                  @input=${(e) => (this._newBucket = e.target.value)}
                  @keydown=${(e) => e.key === 'Enter' && this._createBucket()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createBucket}>+ create</button>
              </div>
            </div>

            <div class="panel">
              <div class="ph">
                Objects — ${this._bucket || '(no bucket)'}
                <span style="flex:1"></span>
                <label class="ghost" style="cursor:pointer">↑ upload real file
                  <input type="file" style="display:none" @change=${this._upload} ?disabled=${!this._bucket || this._busy} />
                </label>
              </div>
              <ul>
                ${(this._objects || []).map(
                  (o) => html`<li class=${this._viewing && this._viewing.key === o.key ? 'sel' : ''}
                    @click=${() => this._view(o.key)}>
                    ▢ ${o.key}<span class="sz">${o.size_human || o.size}</span>
                  </li>`
                )}
                ${(this._objects && this._objects.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— empty —</li>` : ''}
              </ul>
            </div>
          </div>

          ${this._msg ? html`<div class="msg ${/(failed|Could not)/.test(this._msg) ? 'err' : ''}">${this._msg}</div>` : ''}

          ${this._viewing
            ? html`<div class="viewer panel">
                <div class="ph">view: ${this._viewing.key}
                  <span style="flex:1"></span>
                  <a class="ghost" href=${this._viewing.url} target="_blank" rel="noopener">download ▸</a>
                </div>
                <div class="meta">
                  ${this._viewing.meta.content_type} ·
                  ${this._viewing.meta.size_human} ·
                  etag ${(this._viewing.meta.etag || '').slice(0, 12)} ·
                  real bytes from ${this._backedBy()}
                </div>
                ${this._viewing.imageUrl
                  ? html`<img class="preview" src=${this._viewing.imageUrl} alt=${this._viewing.key} />`
                  : html`<pre>${this._viewing.text}</pre>`}
              </div>`
            : ''}
        </div>

        <div slot="actions">
          <button class="ghost" title="empty bucket (stub)">empty</button>
          <button class="ghost" title="delete bucket (stub)">delete bucket</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-object-browser', ObjectBrowser);
