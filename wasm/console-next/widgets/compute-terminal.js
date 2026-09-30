// compute-terminal widget (§13) — cloud-agnostic compute connect surface.
//
// Lists compute instances (id, state, type, IP) and, for a RUNNING instance, surfaces
// the real native access path: the SSH command, a `.pem` download, and the app URL,
// all pulled from the appliance's existing connect-info endpoints. It is CLOUD-AGNOSTIC
// (§15.2): it reads its endpoint paths (list, connect-info, key download, exec) AND its
// connect snippet/CLI from the SELECTED service descriptor's `api` / `connect` blocks —
// so the SAME widget serves AWS EC2 and GCP Compute Engine (GCE) with ZERO branching.
// When no descriptor block is present it falls back to the AWS EC2 defaults, so the AWS
// lens keeps working unchanged:
//   GET  /api/ec2/instances                              (list — {instances:[…]})
//   GET  /api/aws/ec2/instances/{id}/connect-info        (the _docker_connect_info shape)
//   GET  /api/aws/ec2/instances/{id}/private-key.pem     (the shared instance key)
//   POST /api/ec2/instances/{id}/console/exec            (in-console exec)
// so nothing here reinvents SSH provisioning. Rendered inside the common Connect
// contract with the mandatory `⛃ backed by <engine>` badge (§13.1) + native SDK/CLI.
//
// It talks ONLY to /api/* (§15.1 #2) — no substrate/backend knowledge; the compute
// backend (Docker / LXD) is surfaced purely as the `backed_by` DATA from the manifest.
//
// API contract (service.api): { listInstances, connectInfo, keyDownload, exec } — path
// templates with an {instance_id} placeholder this widget substitutes + URL-encodes.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend, apiUrl } from '../api.js';
import '../components/connect-contract.js';

class ComputeTerminal extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _instances: { state: true },   // [{ instance_id, state, instance_type, public_ip, private_ip, ... }]
    _sel: { state: true },         // selected instance_id
    _connInfo: { state: true },    // connect-info result (ssh/alternatives/lxc)
    _busy: { state: true },
    _msg: { state: true },
    _cmd: { state: true },         // terminal command input
    _term: { state: true },        // terminal output lines [{ prompt, cmd, out, code }]
    _running: { state: true },     // a console-exec is in flight
    _launchImage: { state: true }, // Launch form: image / AMI input
    _launchType: { state: true },  // Launch form: instance-type input
    _launching: { state: true },   // a launch (RunInstances) is in flight
  };

  static styles = css`
    :host { display: block; }
    .cols { display: grid; grid-template-columns: 280px 1fr; gap: var(--vy-s4); }
    .panel { background: var(--vy-panel); border: 1px solid var(--vy-border); border-radius: var(--vy-radius); }
    .panel .ph {
      padding: var(--vy-s2) var(--vy-s3); border-bottom: 1px solid var(--vy-border-soft);
      color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase; letter-spacing: .06em;
      display: flex; align-items: center; gap: var(--vy-s2);
    }
    ul { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 340px; overflow: auto; }
    li { padding: var(--vy-s1) var(--vy-s2); border-radius: var(--vy-radius); cursor: pointer;
      display: flex; align-items: center; gap: var(--vy-s2); color: var(--vy-fg-muted); font-size: var(--vy-fs-sm); }
    li:hover { background: var(--vy-bg-elev); color: var(--vy-fg); }
    li.sel { background: var(--vy-bg-elev-2); color: var(--vy-fg); }
    li .iid { font-family: var(--vy-mono); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--vy-fg-dim); flex: none; }
    .dot.running { background: var(--vy-ok); }
    .dot.stopped, .dot.stopping { background: var(--vy-fg-dim); }
    .dot.pending, .dot.rebooting { background: var(--vy-info); }
    .dot.terminated, .dot.shutting-down { background: var(--vy-err); }
    .st { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .editor { padding: var(--vy-s3); }
    .meta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin: var(--vy-s1) 0; }
    .sub { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin: var(--vy-s3) 0 var(--vy-s1); }
    .kv { display: grid; grid-template-columns: 120px 1fr; gap: var(--vy-s1) var(--vy-s2);
      font-size: var(--vy-fs-sm); margin: var(--vy-s1) 0; }
    .kv .k { color: var(--vy-fg-dim); }
    .kv .v { color: var(--vy-fg); font-family: var(--vy-mono); word-break: break-all; }
    .cmd {
      display: flex; align-items: center; gap: var(--vy-s2); margin: var(--vy-s1) 0;
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); color: var(--vy-fg);
      background: var(--vy-bg); border: 1px solid var(--vy-border-soft);
      border-radius: var(--vy-radius); padding: var(--vy-s2) var(--vy-s3);
    }
    .cmd .txt { flex: 1; word-break: break-all; }
    button.act { background: var(--vy-accent); color: var(--vy-accent-fg); border: 0;
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s3); cursor: pointer; font-size: var(--vy-fs-sm); }
    button.act:disabled { opacity: .5; cursor: default; }
    button.ghost {
      background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); cursor: pointer; font-size: var(--vy-fs-xs);
    }
    a.link { color: var(--vy-accent); text-decoration: none; font-family: var(--vy-mono); font-size: var(--vy-fs-sm); }
    a.link:hover { text-decoration: underline; }
    .barr { display: flex; align-items: center; gap: var(--vy-s2); margin-top: var(--vy-s2); flex-wrap: wrap; }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
    .term-out {
      background: var(--vy-bg); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: var(--vy-s2) var(--vy-s3);
      font-family: var(--vy-mono); font-size: var(--vy-fs-sm); color: var(--vy-fg);
      min-height: 120px; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-all;
    }
    .term-out .p { color: var(--vy-accent); }
    .term-out .c { color: var(--vy-fg); }
    .term-out .o { color: var(--vy-fg-muted); }
    .term-out .nz { color: var(--vy-err); }
    .term-in { display: flex; align-items: center; gap: var(--vy-s2); margin-top: var(--vy-s2); }
    .term-in .p { color: var(--vy-accent); font-family: var(--vy-mono); font-size: var(--vy-fs-sm); }
    .term-in input {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg); font-family: var(--vy-mono);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none;
    }
    .term-in input:focus { border-color: var(--vy-accent); }
    .launch { padding: var(--vy-s2); border-top: 1px solid var(--vy-border-soft); }
    .launch .lh { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin-bottom: var(--vy-s1); }
    .launch input {
      width: 100%; box-sizing: border-box; background: var(--vy-bg); color: var(--vy-fg);
      font-family: var(--vy-mono); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s2);
      font-size: var(--vy-fs-sm); outline: none; margin-bottom: var(--vy-s1);
    }
    .launch input:focus { border-color: var(--vy-accent); }
    .launch button.act { width: 100%; }
  `;

  // ── Endpoint resolution (§15.2): read paths from the service descriptor's `api`
  //    block, falling back to the AWS EC2 defaults so the AWS lens works unchanged.
  //    The widget is thereby cloud-agnostic — the GCP lens supplies GCE paths of the
  //    same shape and NOTHING below changes. The only placeholder is {instance_id}
  //    (connect-info / key / exec), which the widget URL-encodes. ──
  static _EC2_DEFAULTS = {
    listInstances: '/api/ec2/instances',
    connectInfo: '/api/aws/ec2/instances/{instance_id}/connect-info',
    keyDownload: '/api/aws/ec2/instances/{instance_id}/private-key.pem',
    exec: '/api/ec2/instances/{instance_id}/console/exec',
    // RunInstances (create) — AWS EC2 default so the AWS lens can launch even
    // without a descriptor. This lives OUTSIDE the capability check below so
    // clouds that supply their own `api` block (GCE / Azure VM) do NOT inherit
    // it: launch is a per-descriptor capability, not a widget-wide default.
    launch: '/api/ec2/instances',
  };

  _tpl(name) {
    const api = (this.service && this.service.api) || {};
    return api[name] || ComputeTerminal._EC2_DEFAULTS[name];
  }

  // Capability check (§15.2 — no if(cloud)): the "Launch instance" control shows
  // ONLY when the SELECTED descriptor advertises a create endpoint. When a lens
  // supplies its own `api` block, the capability is read STRICTLY from it (so a
  // GCE / Azure VM descriptor without `launch` hides the button); the AWS lens
  // with no descriptor falls back to the EC2 default so it keeps launching.
  _launchPath() {
    const api = this.service && this.service.api;
    if (api) return api.launch || null;
    return ComputeTerminal._EC2_DEFAULTS.launch;  // AWS default (no descriptor)
  }

  _canLaunch() { return !!this._launchPath(); }

  // Substitute + URL-encode the {instance_id} placeholder in a template.
  _apiPath(name, { instanceId } = {}) {
    let p = this._tpl(name);
    if (instanceId != null) p = p.replace('{instance_id}', encodeURIComponent(instanceId));
    return p;
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadInstances();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced instance.
    if (changed.has('deepLink') && this.deepLink && this.deepLink.instance &&
        this.deepLink.instance !== this._sel) {
      this._select(this.deepLink.instance);
    }
  }

  async _loadInstances() {
    try {
      const r = await apiGet(this._apiPath('listInstances'));
      this._instances = r.instances || [];
      if (!this._sel && this._instances.length) this._select(this._iid(this._instances[0]));
    } catch (e) {
      this._msg = 'Could not list instances: ' + e.message;
    }
  }

  // Launch a new instance (RunInstances) — POST to the descriptor's create
  // endpoint, then refresh the list and select the freshly-created instance.
  // Cloud-agnostic: the path comes from service.api.launch (§15.2). The request
  // body carries the common shape the EC2 create endpoint accepts (name +
  // instance_type + ami); other lenses that later gain a create endpoint supply
  // their own path and this SAME body maps through their EC2InstanceRequest-shaped
  // model. Image/type default to sensible values when the inputs are blank.
  async _launch() {
    const path = this._launchPath();
    if (!path || this._launching) return;
    const ami = (this._launchImage || '').trim() || 'sim-ubuntu-22.04';
    const instanceType = (this._launchType || '').trim() || 't3.micro';
    this._launching = true;
    this._msg = '';
    try {
      const r = await apiSend('POST', path, {
        name: `vy-${Date.now().toString(36)}`,
        ami,
        instance_type: instanceType,
      });
      await this._loadInstances();
      // Select the new instance if the create response surfaced its id.
      const newId = this._iid(r && (r.instance || r)) || (r && (r.instance_id || r.instanceId || r.id));
      if (newId && this._find(newId)) await this._select(newId);
      this._msg = `Launched ${newId || 'instance'} (${instanceType}, ${ami})`;
    } catch (e) {
      this._msg = 'Launch failed: ' + e.message;
    } finally {
      this._launching = false;
    }
  }

  _iid(inst) { return inst && (inst.instance_id || inst.instanceId || inst.id); }
  _state(inst) { return String((inst && inst.state) || '').toLowerCase(); }

  _find(id) { return (this._instances || []).find((i) => this._iid(i) === id) || null; }

  async _select(id) {
    this._sel = id;
    this._connInfo = null;
    this._term = [];
    this._cmd = '';
    this._msg = '';
    const inst = this._find(id);
    // Connect info only exists for a running instance — fetch lazily on select.
    if (inst && this._state(inst) === 'running') {
      await this._loadConnect(id);
    }
  }

  async _loadConnect(id) {
    this._busy = true;
    try {
      this._connInfo = await apiGet(this._apiPath('connectInfo', { instanceId: id }));
    } catch (e) {
      this._connInfo = null;
      this._msg = 'Connect info unavailable: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  // Best-effort app URL: an http service on the instance's routable IP / advertise host.
  _appUrl(inst, c) {
    const host = (c && c.ssh && c.ssh.host) || (inst && (inst.public_ip || inst.private_ip));
    if (!host) return null;
    return `http://${host}/`;
  }

  // The connect snippet/CLI are descriptor-driven too (§15.2): a service may carry a
  // `connect` block { snippet, cli } — templates with {ep} and {instance_id}
  // placeholders. Absent → the AWS EC2 (boto3) defaults, so the AWS lens is unchanged;
  // the GCP lens supplies a GCE variant with NO widget branching.
  static _EC2_CONNECT = {
    snippet:
      'import boto3\nec2 = boto3.client("ec2", endpoint_url="{ep}",\n' +
      '    aws_access_key_id="test", aws_secret_access_key="test")\n' +
      'ec2.describe_instances()\n' +
      'ec2.run_instances(ImageId="ami-ubuntu-24.04", InstanceType="t2.micro",\n' +
      '    MinCount=1, MaxCount=1)',
    cli: 'aws --endpoint-url {ep} ec2 describe-instances --instance-ids {instance_id}',
  };

  _connectTpl(name) {
    const c = (this.service && this.service.connect) || {};
    return c[name] || ComputeTerminal._EC2_CONNECT[name];
  }

  _fill(tpl) {
    return String(tpl).split('{ep}').join(this._endpoint())
      .split('{instance_id}').join(this._sel || 'i-XXXX');
  }

  _snippet() { return this._fill(this._connectTpl('snippet')); }
  _cli() { return this._fill(this._connectTpl('cli')); }

  _connectBlock(inst) {
    const running = this._state(inst) === 'running';
    if (!running) {
      return html`<div class="meta">Instance is <strong>${this._state(inst) || 'unknown'}</strong> —
        start it to reveal SSH connect info.</div>`;
    }
    const c = this._connInfo;
    if (this._busy && !c) return html`<div class="meta">Fetching connect info…</div>`;
    if (!c || !c.ok) {
      return html`<div class="meta">${(c && (c.reason || c.note)) || 'Connect info unavailable.'}</div>`;
    }
    const ssh = c.ssh || {};
    // Prefer the server-supplied key URL; else fall back to the descriptor's
    // keyDownload template so the .pem link stays cloud-agnostic (§15.2).
    const keyUrl = ssh.key_download_url
      ? apiUrl(ssh.key_download_url)
      : apiUrl(this._apiPath('keyDownload', { instanceId: this._sel }));
    const appUrl = this._appUrl(inst, c);
    return html`
      <div class="sub" style="margin-top:0">SSH</div>
      <div class="cmd">
        <span class="txt">${ssh.command || '(no ssh command)'}</span>
        <button class="ghost" title="copy" @click=${() => this._copy(ssh.command || '')}>⧉</button>
      </div>
      ${ssh.setup_command ? html`
        <div class="hint">Goes through one-time jump host <code>${ssh.jump_host}</code> — set it up once from the “One-time SSH setup” banner (or run <code>${ssh.setup_command}</code>). Reaches this instance at its console private IP; the same setup covers every instance.</div>
      ` : ''}
      <div class="kv">
        <span class="k">user@host</span><span class="v">${ssh.user || 'ubuntu'}@${ssh.host || '?'}</span>
        <span class="k">port</span><span class="v">${ssh.port != null ? ssh.port : '22'}</span>
      </div>
      ${(c.alternatives || []).length ? html`
        <div class="sub">Alternatives</div>
        ${(c.alternatives || []).map((a) => html`<div class="cmd">
          <span class="txt">${a.command}</span>
          <button class="ghost" title="copy" @click=${() => this._copy(a.command)}>⧉</button>
        </div>`)}
      ` : ''}
      <div class="barr">
        ${keyUrl ? html`<a class="act" href=${keyUrl} download=${ssh.key_local_filename || 'vyomi.pem'}>⬇ download .pem</a>` : ''}
        ${appUrl ? html`<a class="link" href=${appUrl} target="_blank" rel="noopener">↗ ${appUrl}</a>` : ''}
      </div>
      ${c.lxc && c.lxc.command ? html`
        <div class="sub">Fallback (on the appliance host)</div>
        <div class="cmd">
          <span class="txt">${c.lxc.command}</span>
          <button class="ghost" title="copy" @click=${() => this._copy(c.lxc.command)}>⧉</button>
        </div>
        ${c.lxc.note ? html`<div class="hint">${c.lxc.note}</div>` : ''}
      ` : ''}
      ${c.note ? html`<div class="hint">${c.note}</div>` : ''}
    `;
  }

  _copy(text) { navigator.clipboard?.writeText(text || '').catch(() => {}); }

  // In-browser terminal: POST the command to the descriptor's exec endpoint
  //   POST {exec}  { command }  → { output, exit_code, cwd }   (default is the AWS EC2
  //   console-exec path; the GCP lens supplies the GCE exec facade — §15.2)
  // and append it to the scrollback. Kept minimal (no xterm dependency) — a command
  // input + output pane. SSH remains the primary access path (shown above); this is
  // the in-console convenience terminal, exactly what the classic console offers.
  async _run() {
    const id = this._sel;
    const cmd = (this._cmd || '').trim();
    if (!id || !cmd || this._running) return;
    this._running = true;
    this._cmd = '';
    const cwd = (this._term && this._term.length && this._term[this._term.length - 1].cwd) || '~';
    try {
      const r = await apiSend('POST', this._apiPath('exec', { instanceId: id }), { command: cmd });
      let out = (r && r.output) || '';
      if (out === '\f') { this._term = []; this._running = false; return; }  // clear
      this._term = [...(this._term || []), {
        cwd, cmd, out, code: (r && r.exit_code) || 0,
      }];
    } catch (e) {
      this._term = [...(this._term || []), { cwd, cmd, out: (e.message || 'error') + '\n', code: 1 }];
    } finally {
      this._running = false;
      await this.updateComplete;
      const pane = this.renderRoot && this.renderRoot.querySelector('.term-out');
      if (pane) pane.scrollTop = pane.scrollHeight;
    }
  }

  _terminalBlock(inst) {
    if (this._state(inst) !== 'running') return '';
    return html`
      <div class="sub">Terminal — runs inside the instance (in-console convenience; SSH above is primary)</div>
      <div class="term-out">
        ${(this._term || []).map((l) => html`<div
          ><span class="p">${l.cwd} $ </span><span class="c">${l.cmd}</span>
          <div class="${l.code ? 'nz' : 'o'}">${l.out}</div></div>`)}
        ${(!this._term || !this._term.length)
          ? html`<span class="o">Type a command (e.g. \`uname -a\`, \`ls\`, \`whoami\`) and press Enter.</span>` : ''}
      </div>
      <div class="term-in">
        <span class="p">$</span>
        <input type="text" placeholder=${this._running ? 'running…' : 'command'}
          .value=${this._cmd || ''} ?disabled=${this._running}
          @input=${(e) => (this._cmd = e.target.value)}
          @keydown=${(e) => { if (e.key === 'Enter') this._run(); }} />
        <button class="act" ?disabled=${this._running || !(this._cmd || '').trim()} @click=${this._run}>▸ run</button>
      </div>
    `;
  }

  render() {
    const svc = this.service || {};
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const inst = this._find(this._sel);
    return html`
      <vyomi-connect-contract
        .resourceId=${this._sel || 'EC2'}
        .resourceKind=${'instance'}
        .backedBy=${svc.backed_by || 'Docker/LXD'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <div class="panel">
              <div class="ph">Instances</div>
              <ul>
                ${(this._instances || []).map((i) => {
                  const id = this._iid(i);
                  const st = this._state(i);
                  return html`<li class=${id === this._sel ? 'sel' : ''} @click=${() => this._select(id)}>
                    <span class="dot ${st}"></span>
                    <span class="iid">${id}</span>
                    <span class="st">${i.instance_type || i.instanceType || ''}</span>
                  </li>`;
                })}
                ${(this._instances && this._instances.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no instances —</li>` : ''}
              </ul>
              ${this._canLaunch() ? html`
                <div class="launch">
                  <div class="lh">Launch instance</div>
                  <input type="text" placeholder="image / AMI (sim-ubuntu-22.04)"
                    .value=${this._launchImage || ''} ?disabled=${this._launching}
                    @input=${(e) => (this._launchImage = e.target.value)}
                    @keydown=${(e) => { if (e.key === 'Enter') this._launch(); }} />
                  <input type="text" placeholder="instance type (t3.micro)"
                    .value=${this._launchType || ''} ?disabled=${this._launching}
                    @input=${(e) => (this._launchType = e.target.value)}
                    @keydown=${(e) => { if (e.key === 'Enter') this._launch(); }} />
                  <button class="act" ?disabled=${this._launching} @click=${this._launch}>
                    ${this._launching ? 'launching…' : '▸ launch instance'}</button>
                </div>
              ` : ''}
            </div>

            <div class="panel">
              <div class="ph">
                Instance — ${this._sel || '(none selected)'}
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${!this._sel || this._busy}
                  @click=${() => this._select(this._sel)}>↻ refresh</button>
              </div>
              ${inst ? html`
                <div class="editor">
                  <div class="kv">
                    <span class="k">state</span><span class="v">${this._state(inst)}</span>
                    <span class="k">type</span><span class="v">${inst.instance_type || inst.instanceType || '—'}</span>
                    <span class="k">public IP</span><span class="v">${inst.public_ip || inst.publicIp || '—'}</span>
                    <span class="k">private IP</span><span class="v">${inst.private_ip || inst.privateIp || '—'}</span>
                  </div>
                  <div class="sub">Connect</div>
                  ${this._connectBlock(inst)}
                  ${this._terminalBlock(inst)}
                  ${this._msg ? html`<div class=${/(failed|unavailable|Could not)/.test(this._msg) ? 'err' : 'ok'}>${this._msg}</div>` : ''}
                </div>
              ` : html`<div class="meta" style="padding:var(--vy-s3)">
                  ${this._msg ? html`<div class=${/(failed|unavailable|Could not)/.test(this._msg) ? 'err' : 'ok'}>${this._msg}</div>` : ''}
                  Select an instance to view connect info.</div>`}
            </div>
          </div>
        </div>

        <div slot="actions">
          <button class="ghost" title="refresh" @click=${() => this._loadInstances()}>refresh</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-compute-terminal', ComputeTerminal);
