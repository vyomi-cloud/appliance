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


  /* ── Redoc-style API reference (three panes: nav | description + parameters | samples) ───────────────────────── */
  var RD_IC = [
    [/machine|ai\b|ai \+/i, 'M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z'],
    [/analytic/i, 'M4 20V10M10 20V4M16 20v-7M22 20H2'],
    [/integration|messag/i, 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'],
    [/ci\/cd/i, 'M17 4l3 3-3 3M20 7H9a5 5 0 0 0-5 5M7 20l-3-3 3-3M4 17h11a5 5 0 0 0 5-5'],
    [/compute/i, 'M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4'],
    [/container/i, 'M12 3l8 4v10l-8 4-8-4V7zM4 7l8 4 8-4M12 11v10'],
    [/database/i, 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6'],
    [/identity|security/i, 'M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z'],
    [/manage|operation|observ/i, 'M4 6h16M4 12h16M4 18h16M8 4v4M16 10v4M10 16v4'],
    [/network/i, 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18'],
    [/serverless/i, 'M13 2L4 14h7l-1 8 9-12h-7z'],
    [/storage/i, 'M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3H4zM4 14h16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM7 8h.01M7 17h.01'],
    [/additional/i, 'M12 5v14M5 12h14'],
    [/./, 'M4 5h16v14H4zM4 10h16']
  ];
  function rdIcon(c) { for (var i = 0; i < RD_IC.length; i++) if (RD_IC[i][0].test(c)) return '<svg viewBox="0 0 24 24" class="rd-ic" aria-hidden="true"><path d="' + RD_IC[i][1] + '"/></svg>'; return ''; }
  function rdOp(cloud, a, o, EP, id) {
    var sn = snips(cloud, a, o, EP), ct = codeTabs(sn);
    var left = '<h3 class="rd-h"><span class="api-m ' + o.m.toLowerCase() + '">' + o.m + '</span> ' + esc(o.n) + '</h3>' +
      (o.d ? '<p class="rd-d">' + esc(o.d) + '</p>' : '') +
      (o.llm ? '<p class="rd-d">Needs the local model: start it with <code>vyomi llm start</code>; answers 503 until then.</p>' : '') +
      '<div class="rd-k">Parameters</div>' + paramTable(cloud, o);
    var right = '<div class="rd-wire"><code>' + esc(wireLine(cloud, a, o)) + '</code></div>' +
      (o['in'] && Object.keys(o['in']).length ? '<div class="rd-k">Request example</div><pre class="api-pre"><code>' + esc(J(o['in'])) + '</code></pre>' : '') +
      '<div class="rd-k">Response example</div><pre class="api-pre"><code>' + esc(J(o.out && Object.keys(o.out).length ? o.out : {})) + '</code></pre>' +
      '<div class="rd-k">CLI &amp; SDKs</div>' + ct.html;
    return { html: '<section class="rd-op" id="' + id + '"><div class="rd-l">' + left + '</div><div class="rd-r">' + right + '</div></section>', wire: ct.wire };
  }
  function renderRedoc(el, cloud, filter, EP, want) {
    el.innerHTML = '<div class="api-empty">Loading ' + esc(cloud.toUpperCase()) + ' reference…</div>';
    index().then(function (ix) {
      var list = (ix.clouds[cloud] || []).filter(function (s) { return s.o > 0 || s.ft > 0; }), q = (filter || '').toLowerCase();
      var cats = {}; list.forEach(function (s) { if (!q || s.t.toLowerCase().indexOf(q) >= 0) (cats[s.c] = cats[s.c] || []).push(s); });
      var shown = list.filter(function (s) { return !q || s.t.toLowerCase().indexOf(q) >= 0; });
      var nav = '<nav class="rd-nav" aria-label="Services">' + (Object.keys(cats).sort().map(function (c) {
        return '<div class="rd-grp" data-c="' + esc(c) + '"><button type="button" class="rd-cat" aria-expanded="true" title="' + esc(c) + '">' + rdIcon(c) + '<span>' + esc(c) + '</span><i class="rd-chev"></i></button><div class="rd-grp-b">' + cats[c].map(function (s) {
          return '<button type="button" class="rd-svc" data-f="' + esc(s.f) + '"><span>' + esc(s.t) + '</span><em>' + s.o + '</em></button><div class="rd-ops" data-f="' + esc(s.f) + '" hidden></div>';
        }).join('') + '</div></div>';
      }).join('') || '<p class="am-none">No services match.</p>') + '</nav>';
      el.innerHTML = '<div class="rd">' + nav + '<div class="rd-main"><button type="button" class="rd-tog" title="Hide / show the service list" aria-label="Toggle service list" aria-expanded="true"></button><div class="rd-intro"><h2>' + esc(cloud === 'aws' ? 'AWS' : cloud === 'gcp' ? 'Google Cloud' : 'Azure') + ' API reference</h2>' +
        '<p>' + list.length + ' services · ' + list.reduce(function (n, s) { return n + s.o; }, 0) + ' operations that answer on this simulator · endpoint <code>' + esc(EP) + '</code>. Pick a service on the left.</p></div><div class="rd-body"></div></div></div>';
      var body = el.querySelector('.rd-body'), main = el.querySelector('.rd-main'), rd = el.querySelector('.rd');
      function setGrp(g, openIt) { g.classList.toggle('shut', !openIt); g.querySelector('.rd-cat').setAttribute('aria-expanded', openIt); }
      el.querySelectorAll('.rd-grp').forEach(function (g) {
        g.querySelector('.rd-cat').addEventListener('click', function () { if (rd.classList.contains('rd-hide')) { rd.classList.remove('rd-hide'); tog.setAttribute('aria-expanded', 'true'); setGrp(g, true); return; } setGrp(g, g.classList.contains('shut')); });
        if (g.dataset.c === 'Additional wired APIs') setGrp(g, false);   // long tail of small APIs: collapsed until wanted
      });
      var tog = el.querySelector('.rd-tog');
      tog.addEventListener('click', function () { var c = rd.classList.toggle('rd-hide'); tog.setAttribute('aria-expanded', !c); });
      var LIM = 60;
      function open(f, all) {
        LIM = all ? 1e9 : 60;
        el.querySelectorAll('.rd-svc').forEach(function (b) { b.classList.toggle('on', b.dataset.f === f); });
        el.querySelectorAll('.rd-ops').forEach(function (d) { d.hidden = d.dataset.f !== f; });
        var og = el.querySelector('.rd-svc[data-f="' + f + '"]'); if (og && og.closest('.rd-grp')) setGrp(og.closest('.rd-grp'), true);
        body.innerHTML = '<p class="am-none">Loading…</p>';
        service(cloud, f).then(function (d) {
          var h = '', wires = [], n = 0, idx = '';
          d.apis.forEach(function (a, ai) {
            var ops = a.ops; if (!ops.length) return;
            h += '<h2 class="rd-api" id="rd-a' + ai + '">' + esc(a.title) + (a.version && cloud !== 'aws' ? ' ' + esc(a.version) : '') + ' <small>' + (a.style ? esc(a.style) + ' · ' : '') + a.wired + ' of ' + a.total + ' operations served</small></h2>';
            idx += '<a href="#rd-a' + ai + '" class="rd-api-l">' + esc(a.title) + '</a>';
            ops.slice(0, LIM).forEach(function (o, oi) { var id = 'rd-' + ai + '-' + oi, r = rdOp(cloud, a, o, EP, id); h += r.html; wires.push(r.wire); n++; idx += '<a href="#' + id + '"><i class="api-m ' + o.m.toLowerCase() + '">' + o.m + '</i>' + esc(o.n) + '</a>'; });
            if (ops.length > LIM) h += '<p class="rd-more">Showing the first ' + LIM + ' of ' + ops.length + ' operations. <button type="button" class="nd-tab rd-all" data-f="' + esc(f) + '">Show all ' + ops.length + '</button></p>';
            if ((a.unwired || []).length) h += '<details class="nd-unw"><summary>' + a.unwired.length + ' operations of this API are not served by this simulator yet</summary><p>' + a.unwired.map(esc).join(' · ') + '</p></details>';
          });
          if (d.data && d.data.length) h += '<h2 class="rd-api">Data plane</h2><table class="am-t"><tr><th>API</th><th>Example</th><th>Client</th></tr>' + d.data.map(function (x) { return '<tr><td>' + esc(x.n) + '</td><td><code class="am-inline">' + esc(x.u.replace('{EP}', EP)) + '</code></td><td>' + esc(x.c || '') + '</td></tr>'; }).join('') + '</table>';
          body.innerHTML = '<h1 class="rd-title">' + esc(d.title) + '</h1>' + h;
          wires.forEach(function (w) { w(body); });
          var ob = el.querySelector('.rd-ops[data-f="' + f + '"]'); ob.innerHTML = idx;
          ob.onclick = function (e) { var a = e.target.closest('a'); if (!a) return; e.preventDefault(); var t = body.querySelector(a.getAttribute('href')); if (t) t.scrollIntoView({ block: 'start' }); };
          body.querySelectorAll('.rd-all').forEach(function (b) { b.onclick = function () { open(b.dataset.f, true); }; });
          main.scrollTop = 0; try { el.closest('#app-main, body').scrollTop = 0; } catch (_) {}
        });
      }
      el.querySelectorAll('.rd-svc').forEach(function (b) { b.addEventListener('click', function () { open(b.dataset.f); }); });
      var firstReal = shown.filter(function (s) { return s.c !== 'Additional wired APIs'; })[0] || shown[0];
      if (shown.length) open((want && shown.filter(function (s) { return s.f === want; })[0] ? want : firstReal.f));
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
  // SDK & CLI usage shows exactly three tabs: CLI, SDK, curl. The per-language SDK snippets (Python, JavaScript) are stacked in
  // the one SDK tab; a CLI entry with several flavours (e.g. Azure az rest + native) is stacked in the CLI tab. No new tab widget.
  function threeTabs(list) {
    var cli = [], sdk = [], curl = [];
    list.forEach(function (s) {
      var l = s[0] || '', head = (/^(Python|JavaScript)/.test(l) ? (l.indexOf('Python') === 0 ? '# ' : '// ') + l + '\n' : (/CLI|gcloud/i.test(l) && !/^(AWS CLI|gcloud)$/.test(l) ? '# ' + l + '\n' : ''));
      if (/curl/i.test(l)) curl.push(s[1]);
      else if (/^(Python|JavaScript)/.test(l)) sdk.push(head + s[1]);
      else cli.push(head + s[1]);
    });
    var out = [];
    if (cli.length) out.push(['CLI', cli.join('\n\n')]);
    if (sdk.length) out.push(['SDK', sdk.join('\n\n')]);
    if (curl.length) out.push(['curl', curl.join('\n\n')]);
    return out.length ? out : list;
  }
  // Same markup as the first SDK & CLI usage card (clouds.html cardHtml): underline tabs + copy icon + bordered code block,
  // so the host's existing .u-strip / .u-tab / .u-cp / pre.u-code styles apply unchanged (light + dark).
  function usageTabs(list) {
    var h = '<div class="u-strip" role="tablist">' + list.map(function (s, i) {
      return '<button class="u-tab" type="button" role="tab" data-i="' + i + '" aria-selected="' + (i === 0) + '">' + esc(s[0]) + '</button>'; }).join('') +
      '<button class="u-cp" type="button" title="Copy" aria-label="Copy"><span class="material-icons">content_copy</span></button></div>' +
      '<pre class="u-code"><code>' + esc(list[0][1]) + '</code></pre>';
    return { html: h, wire: function (root) {
      var strip = root.querySelector('.u-strip'), code = root.querySelector('pre.u-code code'), cp = root.querySelector('.u-cp'), cur = 0;
      strip.querySelectorAll('.u-tab').forEach(function (t) {
        t.addEventListener('click', function () {
          cur = +t.dataset.i; strip.querySelectorAll('.u-tab').forEach(function (x) { x.setAttribute('aria-selected', String(x === t)); }); code.textContent = list[cur][1];
        });
      });
      cp.addEventListener('click', function () {
        var ic = cp.querySelector('.material-icons');
        if (navigator.clipboard) navigator.clipboard.writeText(list[cur][1]).then(function () { ic.textContent = 'check'; cp.style.color = '#60a5fa'; setTimeout(function () { ic.textContent = 'content_copy'; cp.style.color = ''; }, 1400); });
      });
    } };
  }
  // Service-specific icon for a registry card: same markup as the first cards (clouds.html svcIcon). AWS/Azure use Vyomi's icon set
  // (service-icons.js); services without their own artwork get the set's generic glyph in the matching category colour. GCP uses Material glyphs.
  var AWS_ID = [[/ec2|instance/, 'ec2'], [/lambda/, 'lambda'], [/\bs3\b|simple storage/, 's3'], [/dynamo/, 'dynamodb'], [/\brds\b|aurora/, 'rds'], [/api ?gateway|apigateway/, 'apigateway'],
    [/\biam\b|identity/, 'iam'], [/\bkms\b|key management/, 'kms'], [/secrets/, 'secretsmanager'], [/\bsqs\b|queue/, 'sqs'], [/\bsns\b|notification/, 'sns'],
    [/eventbridge/, 'eventbridge'], [/cloudwatch/, 'cloudwatch'], [/cloudformation/, 'cloudformation'], [/\bvpc\b/, 'vpc']];
  var AWS_CAT = [[/s3|storage|efs|ebs|backup|glacier|fsx/, 'storage'], [/rds|dynamo|redis|elasticache|neptune|database|documentdb|timestream|memorydb|keyspaces/, 'database'],
    [/ec2|lambda|batch|ecs|eks|container|fargate|lightsail|apprunner|app runner|compute|bedrock|sagemaker/, 'compute'], [/vpc|route ?53|cloudfront|elb|load balanc|gateway|dns|network|direct connect/, 'networking'],
    [/athena|glue|kinesis|emr|opensearch|quicksight|redshift|analytics|firehose|msk/, 'analytics'], [/iam|kms|cognito|waf|shield|guardduty|secrets|security|acm|certificate|inspector|macie/, 'security'],
    [/sns|sqs|eventbridge|step|\bmq\b|appsync|messag|pipes|scheduler/, 'integration'], [/cloudwatch|cloudformation|ssm|config|trail|organizations|x-ray|systems|marketplace|service catalog/, 'management']];
  var AZ_ID = [[/blob|storage/, 'storage'], [/virtual machine|\bvms?\b/, 'vms'], [/\bsql\b/, 'sql'], [/cosmos/, 'cosmos'], [/key ?vault/, 'keyvaults'], [/service ?bus/, 'servicebus'],
    [/function/, 'functionapp'], [/app ?service/, 'appservices'], [/virtual network|vnet/, 'vnets'], [/\bnsg|security group/, 'nsgs'], [/resource group/, 'resourcegroups'],
    [/container registry|\bacr\b/, 'acr'], [/kubernetes|\baks\b/, 'aks'], [/api management|apim/, 'apim'], [/event ?grid/, 'eventgrid'], [/monitor|insights|log analytics/, 'monitor'],
    [/entra|active directory|identity/, 'entra'], [/subscription/, 'subscriptions'], [/cost/, 'cost']];
  var GCP_GL = [[/bigquery/, 'table_chart'], [/vertex|gemini|\bai\b|ml\b|model/, 'auto_awesome'], [/pub ?\/?sub/, 'hub'], [/firestore|datastore|spanner|bigtable|\bsql\b|database|alloydb/, 'storage'],
    [/compute|\bvm\b|instance|gce/, 'memory'], [/function/, 'functions'], [/cloud run|\brun\b/, 'play_circle_filled'], [/build/, 'build'], [/deploy/, 'publish'], [/schedul/, 'schedule'],
    [/artifact|registry/, 'inventory_2'], [/monitor|logging|trace|operations/, 'show_chart'], [/\biam\b|kms|secret|security|credential/, 'lock'], [/redis|memorystore/, 'bolt'],
    [/network|vpc|dns|load ?balanc|armor/, 'lan'], [/kubernetes|gke|container/, 'dns'], [/storage|bucket/, 'cloud']];
  function pick(table, t) { for (var i = 0; i < table.length; i++) if (table[i][0].test(t)) return table[i][1]; return null; }
  function iconFor(cloud, title, file) {
    var t = ((title || '') + ' ' + (file || '')).toLowerCase(), lib = window.VyomiServiceIcons, id;
    if (cloud === 'gcp') return '<span class="u-svc-ic" aria-hidden="true"><span class="material-icons">' + (pick(GCP_GL, t) || 'cloud') + '</span></span>';
    if (!lib) return '';
    if (cloud === 'aws') { id = pick(AWS_ID, t); return '<span class="u-svc-ic" aria-hidden="true"><svg viewBox="0 0 24 24">' + lib.aws(id || 'other', id ? undefined : (pick(AWS_CAT, t) || 'other')) + '</svg></span>'; }
    id = pick(AZ_ID, t); return '<span class="u-svc-ic" aria-hidden="true"><svg viewBox="0 0 24 24">' + lib.azure(id || 'other') + '</svg></span>';
  }
  function renderUsage(el, cloud, EP) {
    el.innerHTML ='<p class="sc-desc" style="margin:14px 0">Loading every ' + esc(cloud.toUpperCase()) + ' service…</p>';
    index().then(function (ix) {
      var list = (ix.clouds[cloud] || []).filter(function (s) { return s.o > 0; });
      return Promise.all(list.map(function (s) { return service(cloud, s.f); })).then(function (docs) {
        var h = '<div class="u-cloud-head" style="margin-top:22px"><span class="material-icons">menu_book</span>All ' + docs.length + ' services — CLI &amp; SDK examples generated from the registry</div><div class="u-grid">';
        docs.forEach(function (d, di) {
          var a = d.apis.filter(function (x) { return x.ops.length; })[0]; if (!a) return;
          var ops = pickOps(a); if (!ops.length) ops = [a.ops[0]];
          var list2 = []; ops.forEach(function (o) { snips(cloud, a, o, EP).forEach(function (s) { var ex = list2.filter(function (e) { return e[0] === s[0]; })[0]; if (ex) ex[1] += '\n\n' + s[1]; else list2.push([s[0], s[1]]); }); });
          var c = usageTabs(threeTabs(list2));
          h += '<div class="u-card nd-ucard" data-i="' + di + '"><div class="u-head"><h3>' + iconFor(cloud, d.title, (list[di] || {}).f) + esc(d.title) + '</h3></div>' + c.html + '<div class="u-note">' + d.ops + ' operations · ' + ops.map(function (o) { return esc(o.n); }).join(', ') + ' shown — all in <b>API reference</b></div></div>';
          d._w = c.wire;
        });
        h += '</div>';
        var wrap = document.createElement('div'); wrap.id = 'nd-usage-all'; wrap.innerHTML = h;
        el.innerHTML = ''; el.appendChild(wrap);
        wrap.querySelectorAll('.nd-ucard').forEach(function (card) { docs[+card.dataset.i]._w(card); });
      });
    }).catch(function () { el.innerHTML = ''; });
  }

  window.NanoDocs = { renderApi: renderApi, renderRedoc: renderRedoc, renderUsage: renderUsage, _icon: iconFor, _snips: snips, _index: index, _service: service };
})();
