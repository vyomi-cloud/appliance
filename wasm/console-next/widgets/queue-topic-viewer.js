// queue-topic-viewer widget (§13 / §14.3) — queue/topic viewer.
//
// Lists queues and topics, sends a message to a queue, peeks/receives messages,
// and wires + shows topic→queue subscriptions so the flagship fan-out (publish to
// a topic → message lands in every subscribed queue) is visible and real. It is
// CLOUD-AGNOSTIC: it reads its endpoint paths from the selected service
// descriptor's `api` block (§15.2) — so the SAME widget serves AWS SQS+SNS
// (/api/console/messaging/*, driving sqs_core + sns_core over ONE shared
// MessagingStore) and GCP Pub/Sub (/api/console/gcp-pubsub/*) with ZERO branching.
// When no `api` block is present it falls back to the AWS messaging defaults, so
// the AWS lens keeps working unchanged.
//
// All against a console-next facade under /api/* (§15.1 #2 — talks ONLY to /api/*,
// no substrate knowledge). On the AWS lens the facade drives the SAME sqs_core +
// sns_core over ONE shared MessagingStore the Nano relay uses, so the behaviour is
// byte-identical across substrates (§15). Rendered inside the common Connect
// contract with the mandatory `⛃ backed by <engine>` badge (§13.1) and a boto3 /
// CLI snippet (also descriptor-driven via the service's `connect` block, SQS/SNS
// defaults preserved).
//
// Honors a deepLink (backend.ref {sqs.queue / sns.topic}) pushed from the glass-box
// Inspector: selecting a SendMessage/Publish call jumps here and selects that
// queue / topic.
//
// API contract (service.api): { listQueues, createQueue, sendMessage, receive,
// peek, purge, listTopics, createTopic, deleteTopic, listSubscriptions, subscribe,
// publish } — path templates with {queue}/{topic_arn} placeholders this widget
// substitutes + URL-encodes.

import { LitElement, html, css } from '../vendor/lit-core.min.js';
import { apiGet, apiSend } from '../api.js';
import '../components/connect-contract.js';

class QueueTopicViewer extends LitElement {
  static properties = {
    caps: { attribute: false },
    service: { attribute: false },
    deepLink: { attribute: false },
    _queues: { state: true },      // [{ queue_name, queue_url, approximate_messages, ... }]
    _topics: { state: true },      // [{ topic_arn, name, subscription_count }]
    _queue: { state: true },       // selected queue name
    _topic: { state: true },       // selected topic arn
    _msgs: { state: true },        // peeked messages of the selected queue
    _subs: { state: true },        // subscriptions of the selected topic
    _sendBody: { state: true },    // SendMessage body draft
    _pubBody: { state: true },     // Publish message draft
    _pubSubject: { state: true },  // Publish subject draft
    _subQueue: { state: true },    // queue to subscribe to the selected topic
    _newQueue: { state: true },    // new-queue name draft
    _newTopic: { state: true },    // new-topic name draft
    _busy: { state: true },
    _msg: { state: true },
  };

  static styles = css`
    :host { display: block; }
    .cols { display: grid; grid-template-columns: 240px 240px 1fr; gap: var(--vy-s4); }
    .panel { background: var(--vy-panel); border: 1px solid var(--vy-border); border-radius: var(--vy-radius); }
    .panel .ph {
      padding: var(--vy-s2) var(--vy-s3); border-bottom: 1px solid var(--vy-border-soft);
      color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase; letter-spacing: .06em;
      display: flex; align-items: center; gap: var(--vy-s2);
    }
    ul { list-style: none; margin: 0; padding: var(--vy-s1); max-height: 260px; overflow: auto; }
    li { padding: var(--vy-s1) var(--vy-s2); border-radius: var(--vy-radius); cursor: pointer;
      display: flex; align-items: center; gap: var(--vy-s2); color: var(--vy-fg-muted); font-size: var(--vy-fs-sm); }
    li:hover { background: var(--vy-bg-elev); color: var(--vy-fg); }
    li.sel { background: var(--vy-bg-elev-2); color: var(--vy-fg); }
    .sz { margin-left: auto; color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); }
    .row { display: flex; align-items: center; gap: var(--vy-s2); padding: var(--vy-s2) var(--vy-s3); }
    input[type=text] {
      flex: 1; background: var(--vy-bg); color: var(--vy-fg);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: var(--vy-s1) var(--vy-s2); font-size: var(--vy-fs-sm); outline: none; min-width: 0;
    }
    input[type=text]:focus { border-color: var(--vy-accent); }
    textarea {
      width: 100%; box-sizing: border-box; min-height: 72px; resize: vertical;
      background: var(--vy-bg); color: var(--vy-fg); font-family: var(--vy-mono);
      font-size: var(--vy-fs-sm); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: var(--vy-s2); outline: none;
    }
    textarea:focus { border-color: var(--vy-accent); }
    select.pick { background: var(--vy-bg-elev-2); color: var(--vy-fg); border: 1px solid var(--vy-border);
      border-radius: var(--vy-radius); padding: 2px var(--vy-s2); font-size: var(--vy-fs-sm); }
    .barr { display: flex; align-items: center; gap: var(--vy-s2); margin-top: var(--vy-s2); flex-wrap: wrap; }
    button.act { background: var(--vy-accent); color: var(--vy-accent-fg); border: 0;
      border-radius: var(--vy-radius); padding: var(--vy-s1) var(--vy-s3); cursor: pointer; font-size: var(--vy-fs-sm); }
    button.act:disabled { opacity: .5; cursor: default; }
    button.ghost {
      background: transparent; color: var(--vy-fg-muted);
      border: 1px solid var(--vy-border); border-radius: var(--vy-radius);
      padding: 1px var(--vy-s2); cursor: pointer; font-size: var(--vy-fs-xs);
    }
    .mono { font-family: var(--vy-mono); }
    .msglist { list-style: none; margin: 0; padding: 0; max-height: 240px; overflow: auto; }
    .msglist li { display: block; cursor: default; padding: var(--vy-s2) var(--vy-s3);
      border-bottom: 1px solid var(--vy-border-soft); color: var(--vy-fg); }
    .msglist li:hover { background: transparent; }
    .msgbody { font-family: var(--vy-mono); font-size: var(--vy-fs-sm); white-space: pre-wrap; word-break: break-all; }
    .tag { font-size: var(--vy-fs-xs); padding: 0 var(--vy-s1); border-radius: var(--vy-radius);
      border: 1px solid var(--vy-border-soft); color: var(--vy-fg-dim); }
    .tag.sns { color: var(--vy-accent); border-color: var(--vy-accent); }
    .tag.hidden { color: var(--vy-fg-dim); }
    .mmeta { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: 2px; display: flex; gap: var(--vy-s2); flex-wrap: wrap; }
    .sub { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); text-transform: uppercase;
      letter-spacing: .06em; margin: var(--vy-s3) 0 var(--vy-s1); }
    .subline { font-family: var(--vy-mono); font-size: var(--vy-fs-xs); color: var(--vy-fg-muted);
      padding: 1px var(--vy-s3); }
    .subline .q { color: var(--vy-accent); }
    .hint { color: var(--vy-fg-dim); font-size: var(--vy-fs-xs); margin-top: var(--vy-s2); }
    .ok { color: var(--vy-ok); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); }
    .err { color: var(--vy-err); font-size: var(--vy-fs-sm); margin-top: var(--vy-s2); font-family: var(--vy-mono); }
    .editor { padding: var(--vy-s3); }
  `;

  // ── Endpoint resolution (§15.2): read paths from the service descriptor's `api`
  //    block, falling back to the AWS messaging (SQS+SNS) REST defaults so the AWS
  //    lens works unchanged. The widget is thereby cloud-agnostic — the GCP lens
  //    supplies Pub/Sub paths of the same shape and NOTHING below changes.
  //    Placeholders: {queue} (queue name) and {topic_arn} (topic identifier). The
  //    topic identifier travels in the path here (URL-encoded) — the AWS SNS ARN
  //    contains ':' but encodeURIComponent handles that; the facades that carry the
  //    ARN in the query string simply ignore the {topic_arn} placeholder. ──
  static _MSG_DEFAULTS = {
    listQueues: '/api/console/messaging/queues',
    createQueue: '/api/console/messaging/queues',
    sendMessage: '/api/console/messaging/queues/{queue}/send',
    receive: '/api/console/messaging/queues/{queue}/receive',
    peek: '/api/console/messaging/queues/{queue}/peek',
    purge: '/api/console/messaging/queues/{queue}/purge',
    listTopics: '/api/console/messaging/topics',
    createTopic: '/api/console/messaging/topics',
    listSubscriptions: '/api/console/messaging/topics/subscriptions',
    subscribe: '/api/console/messaging/topics/subscribe',
    publish: '/api/console/messaging/topics/publish',
  };

  _tpl(name) {
    const api = (this.service && this.service.api) || {};
    return api[name] || QueueTopicViewer._MSG_DEFAULTS[name];
  }

  // Substitute + URL-encode the {queue}/{topic_arn} placeholders in a template.
  _path(name, { queue, topicArn } = {}) {
    let p = this._tpl(name);
    if (queue != null) p = p.replace('{queue}', encodeURIComponent(queue));
    if (topicArn != null) p = p.replace('{topic_arn}', encodeURIComponent(topicArn));
    return p;
  }

  connectedCallback() {
    super.connectedCallback();
    this._reloadAll();
  }

  updated(changed) {
    // Deep-link from the Inspector: select the referenced queue or topic.
    if (changed.has('deepLink') && this.deepLink) {
      const d = this.deepLink;
      if (d.queue && d.queue !== this._queue) this._selectQueue(d.queue);
      if (d.topic && d.topic !== this._topic) this._selectTopic(d.topic);
    }
  }

  async _reloadAll() {
    await Promise.all([this._loadQueues(), this._loadTopics()]);
  }

  async _loadQueues() {
    try {
      const r = await apiGet(this._path('listQueues'));
      this._queues = r.queues || [];
      if (!this._queue && this._queues.length) {
        this._selectQueue(this._queues[0].queue_name);
      }
    } catch (e) {
      this._msg = 'Could not list queues: ' + e.message;
    }
  }

  async _loadTopics() {
    try {
      const r = await apiGet(this._path('listTopics'));
      this._topics = r.topics || [];
      if (!this._topic && this._topics.length) {
        this._selectTopic(this._topics[0].topic_arn);
      }
    } catch (e) {
      this._msg = 'Could not list topics: ' + e.message;
    }
  }

  async _selectQueue(name) {
    this._queue = name;
    this._msg = '';
    await this._peek(name);
  }

  async _peek(name) {
    if (!name) return;
    try {
      const r = await apiGet(this._path('peek', { queue: name }));
      this._msgs = r.messages || [];
    } catch (e) {
      this._msgs = [];
      this._msg = 'Could not peek queue: ' + e.message;
    }
  }

  async _selectTopic(arn) {
    this._topic = arn;
    this._msg = '';
    await this._loadSubs(arn);
  }

  async _loadSubs(arn) {
    if (!arn) return;
    try {
      // The subscriptions listing needs the topic identifier. If the template
      // carries a {topic_arn} placeholder (a path-style facade) it's substituted;
      // otherwise (the AWS messaging default) the arn travels as a query param.
      let path = this._tpl('listSubscriptions');
      path = path.includes('{topic_arn}')
        ? path.replace('{topic_arn}', encodeURIComponent(arn))
        : `${path}?topic_arn=${encodeURIComponent(arn)}`;
      const r = await apiGet(path);
      this._subs = r.subscriptions || [];
    } catch (e) {
      this._subs = [];
      this._msg = 'Could not load subscriptions: ' + e.message;
    }
  }

  async _createQueue() {
    const name = (this._newQueue || '').trim();
    if (!name) return;
    this._busy = true;
    try {
      await apiSend('POST', this._path('createQueue'), { name });
      this._newQueue = '';
      await this._loadQueues();
      await this._selectQueue(name);
    } catch (e) {
      this._msg = 'Create queue failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _createTopic() {
    const name = (this._newTopic || '').trim();
    if (!name) return;
    this._busy = true;
    try {
      const r = await apiSend('POST', this._path('createTopic'), { name });
      this._newTopic = '';
      await this._loadTopics();
      if (r && r.topic_arn) await this._selectTopic(r.topic_arn);
    } catch (e) {
      this._msg = 'Create topic failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _send() {
    const name = this._queue;
    if (!name) { this._msg = 'Select a queue first'; return; }
    const body = this._sendBody || '';
    if (!body.trim()) { this._msg = 'Enter a message body'; return; }
    this._busy = true;
    this._msg = '';
    try {
      const r = await apiSend('POST',
        this._path('sendMessage', { queue: name }), { body });
      this._msg = `Sent (MessageId ${r.message_id || '—'})`;
      await this._peek(name);
      await this._loadQueues();
    } catch (e) {
      this._msg = 'Send failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _receive() {
    const name = this._queue;
    if (!name) return;
    this._busy = true;
    this._msg = '';
    try {
      const r = await apiSend('POST',
        this._path('receive', { queue: name }),
        { max: 10, visibility: 30 });
      this._msg = `Received ${r.count} message(s) — leased for 30s (hidden on refresh)`;
      await this._peek(name);
      await this._loadQueues();
    } catch (e) {
      this._msg = 'Receive failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _purge() {
    const name = this._queue;
    if (!name) return;
    this._busy = true;
    try {
      await apiSend('POST', this._path('purge', { queue: name }), {});
      this._msg = 'Purged';
      await this._peek(name);
      await this._loadQueues();
    } catch (e) {
      this._msg = 'Purge failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _subscribe() {
    const arn = this._topic;
    const queue = (this._subQueue || '').trim();
    if (!arn) { this._msg = 'Select a topic first'; return; }
    if (!queue) { this._msg = 'Pick a queue to subscribe'; return; }
    this._busy = true;
    this._msg = '';
    try {
      await apiSend('POST', this._path('subscribe', { topicArn: arn }),
        { topic_arn: arn, queue });
      this._msg = `Subscribed ${queue} → topic`;
      await this._loadSubs(arn);
      await this._loadTopics();
    } catch (e) {
      this._msg = 'Subscribe failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  async _publish() {
    const arn = this._topic;
    if (!arn) { this._msg = 'Select a topic first'; return; }
    const message = this._pubBody || '';
    if (!message.trim()) { this._msg = 'Enter a message to publish'; return; }
    this._busy = true;
    this._msg = '';
    try {
      const subject = (this._pubSubject || '').trim();
      const r = await apiSend('POST', this._path('publish', { topicArn: arn }),
        { topic_arn: arn, message, ...(subject ? { subject } : {}) });
      this._msg = `Published → fanned out to ${r.fanned_out_to} queue(s)`;
      // Refresh queues + the selected queue so the fan-out is visible immediately.
      await this._loadQueues();
      if (this._queue) await this._peek(this._queue);
    } catch (e) {
      this._msg = 'Publish failed: ' + e.message;
    } finally {
      this._busy = false;
    }
  }

  _endpoint() {
    return (this.caps && this.caps.workspace && this.caps.workspace.endpoint) || location.origin;
  }

  // The connect snippet/CLI are descriptor-driven too (§15.2): a service may carry a
  // `connect` block { snippet, cli } — templates with {ep} and {queue} placeholders.
  // Absent → the AWS SQS+SNS (boto3) defaults, so the AWS lens is unchanged; the GCP
  // lens supplies a Pub/Sub variant with NO widget branching.
  static _MSG_CONNECT = {
    snippet:
      'import boto3\nsqs = boto3.client("sqs", endpoint_url="{ep}",\n' +
      '    aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1")\n' +
      'sns = boto3.client("sns", endpoint_url="{ep}",\n' +
      '    aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1")\n' +
      'q = sqs.create_queue(QueueName="{queue}")["QueueUrl"]\n' +
      't = sns.create_topic(Name="events")["TopicArn"]\n' +
      'arn = sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]\n' +
      'sns.subscribe(TopicArn=t, Protocol="sqs", Endpoint=arn)\n' +
      'sns.publish(TopicArn=t, Message="hello")   # fans out to {queue}\n' +
      'print(sqs.receive_message(QueueUrl=q))',
    cli: 'aws --endpoint-url {ep} sqs list-queues\naws --endpoint-url {ep} sns list-topics',
  };

  _connect(name) {
    const c = (this.service && this.service.connect) || {};
    return c[name] || QueueTopicViewer._MSG_CONNECT[name];
  }

  _fill(tpl) {
    return String(tpl).split('{ep}').join(this._endpoint())
      .split('{queue}').join(this._queue || 'jobs');
  }

  _snippet() { return this._fill(this._connect('snippet')); }
  _cli() { return this._fill(this._connect('cli')); }

  // Cosmetic parentheticals on the two rail panels + subscribe button. Descriptor
  // may override via service.labels { queues, topics, subscribe }; AWS defaults keep
  // the SQS/SNS wording (no widget branching — just data).
  _labels() {
    const l = (this.service && this.service.labels) || {};
    return {
      queues: l.queues || 'SQS',
      topics: l.topics || 'SNS',
      subscribe: l.subscribe || 'sqs',
    };
  }

  render() {
    const svc = this.service || {};
    const lbl = this._labels();
    const mode = (this.caps && this.caps.connect && this.caps.connect.mode) || 'endpoint';
    const q = this._queue;
    const topic = this._topic;
    const topicName = topic ? topic.split(':').pop() : '';
    return html`
      <vyomi-connect-contract
        .resourceId=${q || (topic ? topicName : 'SQS + SNS')}
        .resourceKind=${'queue / topic'}
        .backedBy=${svc.backed_by || 'in-proc messaging'}
        .connectMode=${mode}
        .endpoint=${this._endpoint()}
        .snippet=${this._snippet()}
        .cliReveal=${this._cli()}
      >
        <div slot="live">
          <div class="cols">
            <!-- Queues (SQS) -->
            <div class="panel">
              <div class="ph">Queues (${lbl.queues})
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${this._busy} @click=${this._loadQueues}>↻</button>
              </div>
              <ul>
                ${(this._queues || []).map((qq) => html`<li
                  class=${qq.queue_name === q ? 'sel' : ''}
                  @click=${() => this._selectQueue(qq.queue_name)}>
                  ⇄ ${qq.queue_name}${qq.fifo ? html`<span class="tag">FIFO</span>` : ''}
                  <span class="sz">${qq.approximate_messages ?? 0}</span>
                </li>`)}
                ${(this._queues && this._queues.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no queues —</li>` : ''}
              </ul>
              <div class="row">
                <input type="text" placeholder="new-queue" .value=${this._newQueue || ''}
                  @input=${(e) => (this._newQueue = e.target.value)}
                  @keydown=${(e) => e.key === 'Enter' && this._createQueue()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createQueue}>+ create</button>
              </div>
            </div>

            <!-- Topics (SNS) -->
            <div class="panel">
              <div class="ph">Topics (${lbl.topics})
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${this._busy} @click=${this._loadTopics}>↻</button>
              </div>
              <ul>
                ${(this._topics || []).map((tp) => html`<li
                  class=${tp.topic_arn === topic ? 'sel' : ''}
                  @click=${() => this._selectTopic(tp.topic_arn)}>
                  ⛿ ${tp.name}
                  <span class="sz">${tp.subscription_count ?? 0} sub</span>
                </li>`)}
                ${(this._topics && this._topics.length === 0)
                  ? html`<li style="cursor:default;color:var(--vy-fg-dim)">— no topics —</li>` : ''}
              </ul>
              <div class="row">
                <input type="text" placeholder="new-topic" .value=${this._newTopic || ''}
                  @input=${(e) => (this._newTopic = e.target.value)}
                  @keydown=${(e) => e.key === 'Enter' && this._createTopic()} />
                <button class="ghost" ?disabled=${this._busy} @click=${this._createTopic}>+ create</button>
              </div>
            </div>

            <!-- Messages of the selected queue -->
            <div class="panel">
              <div class="ph">
                Messages — ${q || '(no queue)'}
                <span style="flex:1"></span>
                <button class="ghost" ?disabled=${!q || this._busy} @click=${() => this._peek(q)}>↻ peek</button>
                <button class="ghost" ?disabled=${!q || this._busy} @click=${this._receive} title="lease up to 10 (30s)">receive</button>
                <button class="ghost" ?disabled=${!q || this._busy} @click=${this._purge}>purge</button>
              </div>
              <ul class="msglist">
                ${(this._msgs || []).map((m) => html`<li>
                  <div class="msgbody">${m.Body}</div>
                  <div class="mmeta">
                    <span class="mono">${(m.MessageId || '').slice(0, 12)}…</span>
                    ${m.is_notification ? html`<span class="tag sns">SNS notification</span>` : ''}
                    ${m.visible ? '' : html`<span class="tag hidden">in flight</span>`}
                    <span>recv ${m.receive_count ?? 0}×</span>
                  </div>
                </li>`)}
                ${(this._msgs && this._msgs.length === 0)
                  ? html`<li style="color:var(--vy-fg-dim)">— no messages —</li>` : ''}
              </ul>
            </div>
          </div>

          <!-- Send to a queue -->
          ${q ? html`
            <div class="panel editor" style="margin-top:var(--vy-s4)">
              <div class="sub" style="margin-top:0">Send message — ${q}</div>
              <textarea .value=${this._sendBody || ''} @input=${(e) => (this._sendBody = e.target.value)}
                placeholder='{"order": 42}'
                @keydown=${(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this._send(); }}></textarea>
              <div class="barr">
                <button class="act" ?disabled=${this._busy} @click=${this._send}>▸ send</button>
                <span class="hint">⌘/Ctrl+Enter · goes straight into ${q}</span>
              </div>
            </div>
          ` : ''}

          <!-- Topic: subscriptions + publish (SNS→SQS fan-out) -->
          ${topic ? html`
            <div class="panel editor" style="margin-top:var(--vy-s4)">
              <div class="sub" style="margin-top:0">Subscriptions — ${topicName} (fan-out)</div>
              ${(this._subs || []).map((s) => html`<div class="subline">
                ${s.protocol === 'sqs'
                  ? html`⇢ <span class="q">${s.queue}</span> <span style="color:var(--vy-fg-dim)">(sqs)</span>`
                  : html`⇢ ${s.endpoint} <span style="color:var(--vy-fg-dim)">(${s.protocol})</span>`}
              </div>`)}
              ${(this._subs && this._subs.length === 0)
                ? html`<div class="subline" style="color:var(--vy-fg-dim)">— no subscriptions — wire one below —</div>` : ''}
              <div class="barr">
                <select class="pick" .value=${this._subQueue || ''}
                  @change=${(e) => (this._subQueue = e.target.value)}>
                  <option value="">— pick a queue —</option>
                  ${(this._queues || []).map((qq) => html`<option .value=${qq.queue_name}
                    ?selected=${qq.queue_name === this._subQueue}>${qq.queue_name}</option>`)}
                </select>
                <button class="ghost" ?disabled=${this._busy} @click=${this._subscribe}>+ subscribe (${lbl.subscribe})</button>
              </div>

              <div class="sub">Publish — ${topicName}</div>
              <div class="barr" style="margin-top:0">
                <input type="text" placeholder="subject (optional)" .value=${this._pubSubject || ''}
                  @input=${(e) => (this._pubSubject = e.target.value)} style="max-width:260px" />
              </div>
              <textarea .value=${this._pubBody || ''} @input=${(e) => (this._pubBody = e.target.value)}
                placeholder="a message to fan out to every subscribed queue"
                @keydown=${(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') this._publish(); }}></textarea>
              <div class="barr">
                <button class="act" ?disabled=${this._busy} @click=${this._publish}>▸ publish</button>
                <span class="hint">⌘/Ctrl+Enter · delivers to every subscribed SQS queue (real fan-out)</span>
              </div>
            </div>
          ` : ''}

          ${this._msg ? html`<div class="${/(failed|Could not|Enter|Select|Pick|Invalid)/.test(this._msg) ? 'err' : 'ok'}">${this._msg}</div>` : ''}
        </div>

        <div slot="actions">
          <button class="ghost" title="refresh" @click=${this._reloadAll}>refresh</button>
          <button class="ghost" title="snapshot — P2" disabled>snapshot</button>
          <button class="ghost" title="fork — P2" disabled>fork</button>
        </div>
      </vyomi-connect-contract>
    `;
  }
}

customElements.define('vyomi-queue-topic-viewer', QueueTopicViewer);
