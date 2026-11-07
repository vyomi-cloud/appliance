/* nano-docs.js — renders the generated per-service docs (wasm/docs/, from scripts/gen_nano_docs.py) into the
 * clouds.html "API reference" and "SDK & CLI usage" views. Plain script, no dependencies.
 *   NanoDocs.renderApi(el, cloud, filter, endpoint)    operation reference, examples, CLI/SDK snippets
 *   NanoDocs.renderUsage(el, cloud, endpoint)          one card per service: CLI · Python · JS · curl
 * Everything shown is generated data + the templates below; nothing is hand-written per service. */
(function () {
  'use strict';
  var BASE = new URL('docs/', document.baseURI).href;
  var cache = {}, indexP = null;

  function xhr(url) {
    return new Promise(function (res, rej) {
      var x = new XMLHttpRequest(); x.open('GET', url);   // XHR (not fetch): the Nano base-path shim patches fetch only
      x.onload = function () { if (x.status >= 200 && x.status < 300) { try { res(JSON.parse(x.responseText)); } catch (e) { rej(e); } } else rej(new Error('HTTP ' + x.status)); };
      x.onerror = function () { rej(new Error('network')); }; x.send();
    });
  }
  function index() { return indexP || (indexP = xhr(BASE + 'index.json')); }
  function service(cloud, f) { var k = cloud + '/' + f; return cache[k] || (cache[k] = xhr(BASE + cloud + '/' + f)); }
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function J(v, ind) { try { return JSON.stringify(v, null, ind == null ? 2 : ind); } catch (e) { return String(v); } }
  function pyval(v, ind) {   // JSON -> Python literal
    ind = ind || 0; var pad = new Array(ind + 5).join(' '), pad0 = new Array(ind + 1).join(' ');
    if (v === null) return 'None'; if (v === true) return 'True'; if (v === false) return 'False';
    if (typeof v === 'string') return JSON.stringify(v);
    if (typeof v === 'number') return String(v);
    if (Array.isArray(v)) return v.length ? '[' + v.map(function (x) { return pyval(x, ind + 4); }).join(', ') + ']' : '[]';
    var ks = Object.keys(v); if (!ks.length) return '{}';
    return '{\n' + ks.map(function (k) { return pad + JSON.stringify(k) + ': ' + pyval(v[k], ind + 4); }).join(',\n') + '\n' + pad0 + '}';
  }
  function kwargs(o, ind) {
    var ks = Object.keys(o || {}); if (!ks.length) return '';
    return ks.map(function (k) { return new Array((ind || 4) + 1).join(' ') + k + '=' + pyval(o[k], ind || 4); }).join(',\n');
  }
  function sh1(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
  function camel(s) { return s.charAt(0).toLowerCase() + s.slice(1); }
  var GCP_VAL = { project: 'vyomi-project', projectId: 'vyomi-project', projectsId: 'vyomi-project', location: 'us-central1', locationsId: 'us-central1', zone: 'us-central1-a', region: 'us-central1', bucket: 'my-bucket', object: 'my-object', instance: 'my-instance', name: 'my-name', parent: 'my-parent' };
  function gval(p) { return GCP_VAL[p] || 'my-' + p.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase(); }

  /* ── snippet templates ─────────────────────────────────────────────────── */
  var AWS_ENV = 'export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""\n';

  function awsSnips(a, o, EP) {
    var inp = o['in'] || {}, hasIn = Object.keys(inp).length;
    var cli = AWS_ENV + 'aws --endpoint-url ' + EP + ' ' + a.cli + ' ' + o.cli + (hasIn ? " \\\n  --cli-input-json " + sh1(J(inp, 0)) : '');
    var py = 'import boto3\n\nclient = boto3.client("' + a.py_client + '", endpoint_url="' + EP + '",\n    aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1")\n' +
      'resp = client.' + o.py + '(' + (hasIn ? '\n' + kwargs(inp, 4) + '\n' : '') + ')\nprint(resp)';
    var cmd = o.n + 'Command', pkg = a.js_pkg;
    var js = 'import { ' + a.js_client + ', ' + cmd + ' } from "' + pkg + '";\n\nconst client = new ' + a.js_client + '({\n  endpoint: "' + EP + '", region: "us-east-1",' +
      (a.id === 's3' ? ' forcePathStyle: true,' : '') + '\n  credentials: { accessKeyId: "test", secretAccessKey: "test" },\n});\n' +
      'const resp = await client.send(new ' + cmd + '(' + (hasIn ? J(inp) : '{}') + '));\nconsole.log(resp);';
    var curl;
    if (a.protocol === 'json' && o.t) curl = 'curl -s -X POST ' + EP + '/ \\\n  -H "X-Amz-Target: ' + o.t + '" \\\n  -H "Content-Type: application/x-amz-json-' + (a.json || '1.0') + '" \\\n  -d ' + sh1(J(inp, 0));
    else if (a.protocol === 'query' || a.protocol === 'ec2') {
      var f = ['Action=' + o.n, 'Version=' + a.version];
      Object.keys(inp).forEach(function (k) { if (typeof inp[k] !== 'object') f.push(k + '=' + encodeURIComponent(inp[k])); });
      curl = 'curl -s -X POST ' + EP + '/ \\\n  -H "Content-Type: application/x-www-form-urlencoded" \\\n  -d ' + sh1(f.join('&'));
    } else curl = 'curl -s -X ' + o.m + ' "' + EP + o.u + '"' + (hasIn && o.m !== 'GET' ? ' \\\n  -H "Content-Type: application/json" \\\n  -d ' + sh1(J(inp, 0)) : '') + '   # {Label} segments in the path are the operation\'s URI parameters';
    return [['AWS CLI', cli], ['Python (boto3)', py], ['JavaScript (SDK v3)', js], ['curl (wire)', curl]];
  }

  var GC_VERB = { create: 'create', insert: 'create', get: 'describe', list: 'list', delete: 'delete', patch: 'update' };
  var GC_ENV = { sqladmin: 'SQL' };
  function gcpSnips(a, o, EP) {
    var parts = (o.sdk || '|').split('|'), chain = parts[0] ? parts[0].split('.') : [], meth = parts[1];
    var inp = o['in'], hasBody = inp && Object.keys(inp).length;
    var args = {}; (o.p || []).forEach(function (p) { if (p[1] === 'path' || p[3]) args[p[0]] = p[4] || gval(p[0]); });
    var full = Object.keys(args).map(function (k) { return k; });
    var py = 'from googleapiclient.discovery import build\nfrom google.auth.credentials import AnonymousCredentials\n\n' +
      'svc = build("' + a.id + '", "' + a.version + '", credentials=AnonymousCredentials(),\n            client_options={"api_endpoint": "' + EP + '"}, static_discovery=True)\n' +
      'resp = svc.' + chain.map(function (c) { return c + '()'; }).join('.') + (chain.length ? '.' : '') + meth + '(' + (full.length || hasBody ? '\n' +
        full.map(function (k) { return '    ' + k + '=' + JSON.stringify(args[k]); }).concat(hasBody ? ['    body=' + pyval(inp, 4)] : []).join(',\n') + '\n' : '') + ').execute()\nprint(resp)';
    var js = 'const { google } = require("googleapis");\n\nconst svc = google.' + a.id + '({ version: "' + a.version + '", rootUrl: "' + EP + '/" });\n' +
      'const res = await svc.' + chain.concat([meth]).join('.') + '({' + (full.length || hasBody ? '\n' + full.map(function (k) { return '  ' + k + ': ' + JSON.stringify(args[k]) + ','; }).concat(hasBody ? ['  requestBody: ' + J(inp, 2).replace(/\n/g, '\n  ') + ','] : []).join('\n') + '\n' : '') + '});\nconsole.log(res.data);';
    var url = EP + o.ex + ((o.p || []).some(function (p) { return p[1] === 'query'; }) ? '?' + (o.p || []).filter(function (p) { return p[1] === 'query'; }).map(function (p) { return p[0] + '=' + (p[4] || gval(p[0])); }).join('&') : '');
    var curl = 'curl -s -X ' + o.m + ' "' + url + '"' + (hasBody ? ' \\\n  -H "Content-Type: application/json" \\\n  -d ' + sh1(J(inp, 0)) : '');
    var out = [];
    var verb = GC_VERB[meth], res = chain.length ? chain[chain.length - 1] : '';
    if (a.gcloud && verb && res) {
      var grp = a.gcloud + ' ' + res.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
      var env = 'export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true\nexport CLOUDSDK_API_ENDPOINT_OVERRIDES_' + (GC_ENV[a.id] || a.id.toUpperCase()) + '=' + EP + '/\n';
      out.push(['gcloud', env + 'gcloud ' + grp + ' ' + verb + (verb === 'list' ? '' : ' my-' + res.replace(/s$/, '').toLowerCase()) + ' --project=vyomi-project\n# derived command: confirm the exact flags with  gcloud ' + grp + ' ' + verb + ' --help']);
    }
    return out.concat([['Python (google-api-python-client)', py], ['JavaScript (googleapis)', js], ['curl (REST)', curl]]);
  }

  function azSnips(a, o, EP) {
    var sub = '00000000-0000-0000-0000-cloudlearn01';
    var url = o.u.replace('{subscriptionId}', sub).replace('{resourceGroupName}', 'my-rg').replace('{name}', 'my-resource');
    var inp = o['in'], hasBody = inp && Object.keys(inp).length;
    var az = 'az rest --skip-authorization-header --headers "Authorization=Bearer dev" --method ' + o.m.toLowerCase() + ' \\\n  --url "' + EP + url + '"' + (hasBody ? " \\\n  --body " + sh1(J(inp, 0)) : '');
    var out = [['Azure CLI (az rest)', az]];
    if (a.az && o.az) out.push(['Azure CLI (native)', '# one-time: point az at this environment (ARM endpoint) — then the native verbs work\naz cloud register -n vyomi --endpoint-resource-manager ' + EP + ' --endpoint-active-directory-resource-id ' + EP + '\naz cloud set -n vyomi\naz account set --subscription ' + sub + '\naz ' + a.az + ' ' + o.az.replace('{rg}', 'my-rg').replace('{name}', 'my-resource')]);
    if (a.py_client && o.py) {
      var pc = a.py_client.split('.'), cls = pc.pop(), mod = pc.join('.');
      var call = 'client.' + a.py_attr + '.' + o.py + '(' + (o.n === 'List by subscription' ? '' : o.n === 'List by resource group' ? '"my-rg"' : o.n === 'Create or update' ? '"my-rg", "my-resource", ' + pyval(inp || {}, 0) : '"my-rg", "my-resource"') + ')';
      var lro = /^begin_/.test(o.py);
      out.push(['Python (azure-mgmt)', 'from ' + mod + ' import ' + cls + '\nfrom azure.core.credentials import AccessToken\n\nclass DevCredential:   # the simulator accepts any token\n    def get_token(self, *scopes, **kw):\n        return AccessToken("dev", 4102444800)\n\n' +
        'client = ' + cls + '(DevCredential(), "' + sub + '", base_url="' + EP + '",\n    credential_scopes=["https://management.azure.com/.default"])\nresult = ' + call + (lro ? '.result()' : '') + '\nprint(result' + (/^list/.test(o.py) ? ' if False else list(result)' : '') + ')']);
    }
    if (a.js_pkg) {
      var cn = a.js_pkg.replace('@azure/arm-', ''); cn = cn.charAt(0).toUpperCase() + cn.slice(1);
      out.push(['JavaScript (@azure/arm)', '// npm i ' + a.js_pkg + '\nimport { ' + cn + 'ManagementClient } from "' + a.js_pkg + '";   // class name per package; see its README\nconst cred = { getToken: async () => ({ token: "dev", expiresOnTimestamp: 4102444800000 }) };\nconst client = new ' + cn + 'ManagementClient(cred, "' + sub + '", { endpoint: "' + EP + '" });\n// REST: ' + o.m + ' ' + o.u]);
    }
    out.push(['curl (ARM REST)', 'curl -s -X ' + o.m + ' "' + EP + url + '" \\\n  -H "Authorization: Bearer dev"' + (hasBody ? ' \\\n  -H "Content-Type: application/json" \\\n  -d ' + sh1(J(inp, 0)) : '')]);
    return out;
  }
  function snips(cloud, a, o, EP) {
    if (o.s) return o.s.map(function (x) { return [x[0], x[1].split('{EP}').join(EP)]; });   // hand-authored ops carry their own runnable snippets
    return cloud === 'aws' ? awsSnips(a, o, EP) : cloud === 'gcp' ? gcpSnips(a, o, EP) : azSnips(a, o, EP); }

  /* ── shared widgets ────────────────────────────────────────────────────── */
  function codeTabs(list) {
    var id = 'nd' + Math.random().toString(36).slice(2, 8);
    var h = '<div class="nd-tabs" data-id="' + id + '">' + list.map(function (s, i) { return '<button type="button" class="nd-tab' + (i ? '' : ' on') + '" data-i="' + i + '">' + esc(s[0]) + '</button>'; }).join('') + '<button type="button" class="nd-cp" title="Copy">Copy</button></div>';
    h += '<pre class="api-pre nd-code" data-id="' + id + '"><code>' + esc(list[0][1]) + '</code></pre>';
    return { html: h, wire: function (root) {
      var tabs = root.querySelector('.nd-tabs[data-id="' + id + '"]'), pre = root.querySelector('.nd-code[data-id="' + id + '"] code'), cur = 0;
      tabs.addEventListener('click', function (e) {
        var b = e.target.closest('button'); if (!b) return;
        if (b.classList.contains('nd-cp')) { if (navigator.clipboard) navigator.clipboard.writeText(list[cur][1]).then(function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1200); }); return; }
        cur = +b.dataset.i; tabs.querySelectorAll('.nd-tab').forEach(function (t) { t.classList.toggle('on', t === b); }); pre.textContent = list[cur][1];
      });
    } };
  }
  function paramTable(cloud, o) {
    if (!o.p || !o.p.length) return '<p class="am-none">No required parameters.</p>';
    if (cloud === 'gcp') return '<table class="am-t"><tr><th>Name</th><th>In</th><th>Type</th></tr>' + o.p.map(function (p) { return '<tr><td>' + esc(p[0]) + (p[3] ? ' <span class="am-req">required</span>' : '') + '</td><td>' + esc(p[1]) + '</td><td><code class="am-inline">' + esc(p[2]) + '</code></td></tr>'; }).join('') + '</table>';
    return '<table class="am-t"><tr><th>Name</th><th>Type</th></tr>' + o.p.map(function (p) { return '<tr><td>' + esc(p[0]) + (p[2] ? ' <span class="am-req">required</span>' : '') + '</td><td><code class="am-inline">' + esc(p[1]) + '</code></td></tr>'; }).join('') + '</table>';
  }
  function wireLine(cloud, a, o) {
    if (o.w) return o.w;
    if (cloud === 'aws') return (a.protocol === 'json' && o.t) ? 'POST /   X-Amz-Target: ' + o.t : (a.protocol === 'query' || a.protocol === 'ec2') ? 'POST /   Action=' + o.n : o.m + ' ' + o.u;
    return o.m + ' ' + (cloud === 'gcp' ? o.ex : o.u);
  }
  function opDetail(cloud, a, o, EP) {
    var h = '';
    if (o.d) h += '<p class="am-none" style="color:#cdd8e6;margin:0 0 8px">' + esc(o.d) + '</p>';
    if (o.llm) h += '<p class="am-none">Needs the local model: start it with <code>vyomi llm start</code> (offline appliance); answers 503 until then.</p>';
    h += '<div class="am-sec-h">Wire request</div><pre class="api-pre"><code>' + esc(wireLine(cloud, a, o)) + '</code></pre>';
    h += '<div class="am-sec-h">Parameters</div>' + paramTable(cloud, o);
    if (o['in'] && Object.keys(o['in']).length) h += '<div class="am-sec-h">Request example</div><pre class="api-pre"><code>' + esc(J(o['in'])) + '</code></pre>';
    h += '<div class="am-sec-h">Response example</div><pre class="api-pre"><code>' + esc(J(o.out && Object.keys(o.out).length ? o.out : {})) + '</code></pre>';
    var ct = codeTabs(snips(cloud, a, o, EP));
    h += '<div class="am-sec-h">Use it from the CLI &amp; SDKs — pointed at this endpoint</div>' + ct.html;
    return { html: h, wire: ct.wire };
  }

  /* ── API reference ─────────────────────────────────────────────────────── */
  function renderApi(el, cloud, filter, EP) {
    el.innerHTML = '<div class="api-empty">Loading ' + esc(cloud.toUpperCase()) + ' reference…</div>';
    index().then(function (ix) {
      var list = (ix.clouds[cloud] || []).filter(function (s) { return s.o > 0 || s.ft > 0; });
      var q = (filter || '').toLowerCase();
      var need = q ? Promise.all(list.map(function (s) { return service(cloud, s.f).then(function (d) { s._d = d; }); })) : Promise.resolve();
      return need.then(function () {
        var cats = {}; list.forEach(function (s) { (cats[s.c] = cats[s.c] || []).push(s); });
        var tot = list.reduce(function (n, s) { return n + s.o; }, 0), html = '', shown = 0;
        html += '<p class="sc-desc" style="text-align:center;color:#8b8ba7;margin:-6px 0 18px">' + list.length + ' services · ' + tot + ' operations that answer on this simulator · endpoint <code>' + esc(EP) + '</code></p>';
        Object.keys(cats).sort().forEach(function (c) {
          var rows = '';
          cats[c].forEach(function (s) {
            var match = true;
            if (q) { var d = s._d; match = s.t.toLowerCase().indexOf(q) >= 0 || d.apis.some(function (a) { return a.ops.some(function (o) { return (o.n + ' ' + (o.u || '') + ' ' + (o.d || '')).toLowerCase().indexOf(q) >= 0; }); }) || d.features.some(function (f) { return (f.t + ' ' + f.a.join(' ')).toLowerCase().indexOf(q) >= 0; }); }
            if (!match) return; shown++;
            rows += '<div class="api-op-wrap nd-svc" data-f="' + esc(s.f) + '"><button class="api-op" type="button" aria-expanded="false"><span class="material-icons" style="color:#7c8cf8;font-size:19px">folder</span><span class="col"><span class="p">' + esc(s.t) + '</span><span class="s">' + s.o + ' operations · ' + s.ft + ' console features' + (s.n > s.o ? ' · ' + (s.n - s.o) + ' not served' : '') + '</span></span><span class="material-icons api-caret">expand_more</span></button><div class="api-detail nd-body" hidden></div></div>';
          });
          if (rows) html += '<section class="api-group"><div class="api-tag-head"><span class="api-tag-title"><span class="material-icons">category</span>' + esc(c) + '</span></div><div class="api-grid">' + rows + '</div></section>';
        });
        if (!shown) html += '<div class="api-empty">No services or operations match “' + esc(filter) + '”.</div>';
        el.innerHTML = html;
        el.querySelectorAll('.nd-svc > .api-op').forEach(function (b) {
          b.addEventListener('click', function () {
            var wrap = b.parentNode, body = wrap.querySelector('.nd-body');
            if (!body.hidden) { body.hidden = true; wrap.classList.remove('open'); b.setAttribute('aria-expanded', 'false'); return; }
            wrap.classList.add('open'); b.setAttribute('aria-expanded', 'true'); body.hidden = false;
            if (!body.getAttribute('data-f')) { body.setAttribute('data-f', '1'); body.innerHTML = '<p class="am-none">Loading…</p>'; service(cloud, wrap.dataset.f).then(function (d) { svcBody(body, cloud, d, EP, q); }); }
          });
        });
        if (q && shown && shown <= 3) el.querySelectorAll('.nd-svc > .api-op').forEach(function (b) { b.click(); });
      });
    }).catch(function () { el.innerHTML = '<div class="api-empty">Could not load the ' + esc(cloud.toUpperCase()) + ' reference (docs/index.json).</div>'; });
  }

  function svcBody(body, cloud, d, EP, q) {
    var h = '';
    d.apis.forEach(function (a, ai) {
      var ops = a.ops.filter(function (o) { return !q || d.title.toLowerCase().indexOf(q) >= 0 || (o.n + ' ' + (o.u || '') + ' ' + (o.d || '')).toLowerCase().indexOf(q) >= 0; });
      if (!ops.length && !(a.unwired || []).length) return;
      h += '<div class="am-sec-h">' + esc(a.title) + (a.version && cloud !== 'aws' ? ' ' + esc(a.version) : '') + ' <span class="am-schema">' + (a.style ? esc(a.style) + ' · ' : '') + a.wired + ' of ' + a.total + ' operations served</span></div>';
      h += '<div class="api-grid">' + ops.map(function (o, oi) {
        return '<div class="api-op-wrap nd-op" data-a="' + ai + '" data-o="' + a.ops.indexOf(o) + '"><button class="api-op" type="button" aria-expanded="false"><span class="api-m ' + o.m.toLowerCase() + '">' + o.m + '</span><span class="col"><span class="p">' + esc(o.n) + '</span><span class="s">' + esc(o.d || wireLine(cloud, a, o)) + '</span></span><span class="material-icons api-caret">expand_more</span></button><div class="api-detail" hidden></div></div>';
      }).join('') + '</div>';
      if ((a.unwired || []).length && !q) h += '<details class="nd-unw"><summary>' + a.unwired.length + ' operations of this API are not served by this simulator yet</summary><p>' + a.unwired.map(esc).join(' · ') + '</p></details>';
    });
    if (d.data && d.data.length) {
      h += '<div class="am-sec-h">Data plane</div><table class="am-t"><tr><th>API</th><th>Example</th><th>Client</th></tr>' + d.data.map(function (x) { return '<tr><td>' + esc(x.n) + '</td><td><code class="am-inline">' + esc(x.u.replace('{EP}', EP)) + '</code></td><td>' + esc(x.c) + '</td></tr>'; }).join('') + '</table>';
    }
    if (d.features && d.features.length) {
      h += '<div class="am-sec-h">Console features → API operations (registry)</div><table class="am-t"><tr><th>Feature</th><th>Nano</th><th>API operations</th></tr>' +
        d.features.filter(function (f) { return !q || (f.t + ' ' + f.a.join(' ')).toLowerCase().indexOf(q) >= 0 || d.title.toLowerCase().indexOf(q) >= 0; }).map(function (f) { return '<tr><td>' + esc(f.t) + '</td><td>' + esc(f.l) + '</td><td>' + (f.a.length ? '<code class="am-inline">' + f.a.map(esc).join(', ') + '</code>' : '<span class="am-none">console-only</span>') + '</td></tr>'; }).join('') + '</table>';
    }
    body.innerHTML = h || '<p class="am-none">Nothing matches.</p>';
    body.querySelectorAll('.nd-op > .api-op').forEach(function (b) {
      b.addEventListener('click', function () {
        var wrap = b.parentNode, det = wrap.querySelector('.api-detail');
        if (!det.hidden) { det.hidden = true; wrap.classList.remove('open'); b.setAttribute('aria-expanded', 'false'); return; }
        if (!det.getAttribute('data-filled')) { var a = d.apis[+wrap.dataset.a], r = opDetail(cloud, a, a.ops[+wrap.dataset.o], EP); det.innerHTML = r.html; r.wire(det); det.setAttribute('data-filled', '1'); }
        det.hidden = false; wrap.classList.add('open'); b.setAttribute('aria-expanded', 'true');
      });
    });
  }

  /* ── SDK & CLI usage ───────────────────────────────────────────────────── */
  function pickOps(a) {   // deterministic representative ops: first read-style op, then first create-style op
    var rd = null, cr = null;
    a.ops.forEach(function (o) {
      var n = o.n.toLowerCase();
      if (!rd && /(^|\.)(list|describe|get)/.test(n.split('.').pop()) || (!rd && /list|get$/.test(n))) rd = rd || o;
      if (!cr && /(^|\.)(create|put|insert|run|publish|send)/.test(n.split('.').pop())) cr = o;
    });
    return [rd, cr].filter(function (x, i, arr) { return x && arr.indexOf(x) === i; });
  }
  function renderUsage(el, cloud, EP) {
    el.innerHTML = '<p class="sc-desc" style="margin:14px 0">Loading every ' + esc(cloud.toUpperCase()) + ' service…</p>';
    index().then(function (ix) {
      var list = (ix.clouds[cloud] || []).filter(function (s) { return s.o > 0; });
      return Promise.all(list.map(function (s) { return service(cloud, s.f); })).then(function (docs) {
        var h = '<div class="u-cloud-head" style="margin-top:22px"><span class="material-icons">menu_book</span>All ' + docs.length + ' services — CLI &amp; SDK examples generated from the registry</div><div class="u-grid">';
        docs.forEach(function (d, di) {
          var a = d.apis.filter(function (x) { return x.ops.length; })[0]; if (!a) return;
          var ops = pickOps(a); if (!ops.length) ops = [a.ops[0]];
          var list2 = []; ops.forEach(function (o) { snips(cloud, a, o, EP).forEach(function (s) { var ex = list2.filter(function (e) { return e[0] === s[0]; })[0]; if (ex) ex[1] += '\n\n' + s[1]; else list2.push([s[0], s[1]]); }); });
          var c = codeTabs(list2);
          h += '<div class="u-card nd-ucard" data-i="' + di + '"><div class="u-head"><h3>' + esc(d.title) + '</h3></div>' + c.html + '<div class="u-note">' + d.ops + ' operations · ' + ops.map(function (o) { return esc(o.n); }).join(', ') + ' shown — all in <b>API reference</b></div></div>';
          d._w = c.wire;
        });
        h += '</div>';
        var wrap = document.createElement('div'); wrap.id = 'nd-usage-all'; wrap.innerHTML = h;
        el.innerHTML = ''; el.appendChild(wrap);
        wrap.querySelectorAll('.nd-ucard').forEach(function (card) { docs[+card.dataset.i]._w(card); });
      });
    }).catch(function () { el.innerHTML = ''; });
  }

  window.NanoDocs = { renderApi: renderApi, renderUsage: renderUsage, _snips: snips, _index: index, _service: service };
})();
