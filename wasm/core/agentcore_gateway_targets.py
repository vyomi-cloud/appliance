# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AgentCore gateway: real inbound JWT validation, callable openApiSchema / mcpServer targets, credential providers (API key,
OAuth2 client-credentials), and the runtime MCP / A2A JSON-RPC protocol variants. Thin adapters over existing engines:

  * JWT        = core/gateway_common.jwt_validate + make_rs256_verifier (RS256 via `cryptography`; Cognito pools of this simulator
                 resolve their JWKS in-process through core/identity_core.local_jwks, any other issuer via OIDC discovery of the
                 gateway's discoveryUrl). Not PyJWT: the verifier already exists and PyJWT is not in Pyodide.
  * OpenAPI    = json (stdlib) or PyYAML (when importable) to parse the spec, urllib to call the upstream API.
  * mcpServer  = a minimal MCP streamable-HTTP client (JSON or SSE replies) over urllib.
  * Outbound HTTP needs network egress: unavailable inside Nano's browser sandbox (declared; tools return isError there).
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from core import bedrock_agents_core as B
    from core import gateway_common as gc
except ImportError:  # Pyodide flat layout
    import bedrock_agents_core as B  # type: ignore
    import gateway_common as gc  # type: ignore

_NANO = sys.platform == "emscripten"
_DISC_SUFFIX = "/.well-known/openid-configuration"
_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
_VERIFIER = []
_DISC: dict = {}
_UP_TIMEOUT = 10.0


# ═════════════════════════ inbound CUSTOM_JWT validation ═════════════════════════
def _bearer(headers):
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    for k in ("authorization", "x-amzn-bedrock-agentcore-runtime-custom-authorization"):   # the second is what SigV4-signed SDK callers use to carry the JWT
        a = (h.get(k) or "").strip()
        if a.lower().startswith("bearer "):
            return a[7:].strip()
    return ""


def _http_json(url, timeout=5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - operator-configured discovery URL
        return json.load(r)


def _discover(discovery_url):
    """-> (issuer, jwks_uri | None). Cognito pools hosted by this simulator need no network (local_jwks)."""
    hit = _DISC.get(discovery_url)
    if hit and hit[0] > time.time():
        return hit[1]
    issuer = discovery_url[:-len(_DISC_SUFFIX)] if discovery_url.endswith(_DISC_SUFFIX) else None
    out = None
    if issuer and gc._local_jwks(issuer) is not None:
        out = (issuer, None)
    else:
        doc = _http_json(discovery_url)
        out = (doc.get("issuer") or issuer, doc.get("jwks_uri"))
    _DISC[discovery_url] = (time.time() + 300, out)
    return out


def _verifier():
    if not _VERIFIER:
        _VERIFIER.append(gc.make_rs256_verifier())
    return _VERIFIER[0]


def _deny(status, msg, kind="invalid_token"):
    hdr = {"www-authenticate": f'Bearer error="{kind}"'} if status == 401 else {}
    return {"status": status, "headers": {"content-type": "application/json", "x-amzn-errortype": "UnauthorizedException" if status == 401 else "AccessDeniedException", **hdr},
            "body": json.dumps({"message": msg}).encode()}


def validate_inbound(gw, headers, now=None):
    """CUSTOM_JWT gateway auth. -> (claims, None) when admitted, else (None, error response dict).
    401: no / malformed token, bad signature, expired, wrong issuer, unverifiable. 403: valid token but audience / client / scope not allowed."""
    cfg = ((gw.get("authorizerConfiguration") or {}).get("customJWTAuthorizer")) or {}
    tok = _bearer(headers)
    if not tok:
        return None, _deny(401, "Missing Authentication Token", "invalid_request")
    ver = _verifier()
    if ver is None:
        return None, _deny(401, "JWT verification is unavailable on this substrate (needs `cryptography`); failing closed")
    try:
        issuer, jwks_uri = _discover(cfg["discoveryUrl"])
    except Exception as e:  # noqa: BLE001 - unreachable issuer: never admit
        return None, _deny(401, f"Unable to discover the token issuer: {type(e).__name__}")
    vcfg = {"issuer": issuer}
    if jwks_uri:
        vcfg["jwks_uri"] = jwks_uri
    claims, _ = gc.jwt_validate(tok, vcfg, verify_sig=ver, now=now)
    if claims is None:
        return None, _deny(401, "Invalid or expired token")
    auds = cfg.get("allowedAudience") or []
    if auds:
        got = claims.get("aud")
        got = got if isinstance(got, list) else [got] if got is not None else []
        if not set(auds) & set(got):
            return None, _deny(403, "Token audience is not allowed for this gateway")
    clients = cfg.get("allowedClients") or []
    if clients and str(claims.get("client_id", claims.get("azp", ""))) not in clients:
        return None, _deny(403, "Token client is not allowed for this gateway")
    scopes = cfg.get("allowedScopes") or []
    if scopes:
        have = claims.get("scope", claims.get("scp", []))
        have = have.split() if isinstance(have, str) else list(have or [])
        if not set(scopes) & set(have):
            return None, _deny(403, "Token scope is not allowed for this gateway")
    return claims, None


# ═════════════════════════ credential providers (token vault) ═════════════════════════
_PROV = {"apikey": ("apikeycredentialprovider", "ApiKey"), "oauth2": ("oauth2credentialprovider", "Oauth2")}


def _vault(st):
    return st.setdefault("credential_providers", {"apikey": {}, "oauth2": {}})


def _parn(kind, name):
    return f"arn:aws:bedrock-agentcore:{B._REGION}:{B._ACCT}:token-vault/default/{_PROV[kind][0]}/{name}"


def _view(kind, p):
    out = {k: v for k, v in p.items() if not k.startswith("_")}
    return out


def _providers(st, method, segs, body):
    """POST /identities/{Create|Get|Update|Delete|List}{ApiKey|Oauth2}Credential{Provider|Providers}."""
    m = re.match(r"^(Create|Get|Update|Delete|List)(ApiKey|Oauth2)CredentialProviders?$", segs[1])
    if not m or method != "POST":
        return None
    verb, kk = m.groups()
    kind = "apikey" if kk == "ApiKey" else "oauth2"
    vault = _vault(st)[kind]
    p = B._body(body)
    if verb == "List":
        items = [{k: v for k, v in _view(kind, x).items() if k in ("name", "credentialProviderArn", "credentialProviderVendor", "createdTime", "lastUpdatedTime")}
                 for x in vault.values()]
        return B._j(200, {"credentialProviders": items})
    name = p.get("name")
    if not name or not re.match(r"^[a-zA-Z0-9\-_]+$", name) or len(name) > 128:
        raise B._bad("name is required and must match [a-zA-Z0-9\\-_]+")
    if verb == "Create":
        if name in vault:
            raise B._conflict(f"Credential provider {name} already exists")
        now = time.time()
        if kind == "apikey":
            if not p.get("apiKey"):
                raise B._bad("apiKey is required")
            rec = {"name": name, "credentialProviderArn": _parn(kind, name), "createdTime": now, "lastUpdatedTime": now, "_apiKey": p["apiKey"]}
        else:
            vendor = p.get("credentialProviderVendor")
            cfg = p.get("oauth2ProviderConfigInput") or {}
            c = next(iter(cfg.values()), None) if len(cfg) == 1 else None
            if not vendor or not isinstance(c, dict) or not c.get("clientId") or not c.get("clientSecret"):
                raise B._bad("credentialProviderVendor and oauth2ProviderConfigInput with clientId and clientSecret are required")
            disc = c.get("oauthDiscovery") or {}
            if not disc.get("discoveryUrl") and not (disc.get("authorizationServerMetadata") or {}).get("tokenEndpoint"):
                raise B._bad("oauthDiscovery.discoveryUrl or authorizationServerMetadata.tokenEndpoint is required")
            rec = {"name": name, "credentialProviderArn": _parn(kind, name), "credentialProviderVendor": vendor, "createdTime": now, "lastUpdatedTime": now,
                   "callbackUrl": f"https://bedrock-agentcore.{B._REGION}.amazonaws.com/identities/oauth2/callback/{B._rid(12, B._LOWER)}",
                   "_cfg": c, "_vendor": vendor}
            rec["oauth2ProviderConfigOutput"] = {next(iter(cfg)): {"oauthDiscovery": disc, "clientId": c["clientId"]}}
        vault[name] = rec
        return B._j(200, _view(kind, rec) if kind == "oauth2" else {"name": name, "credentialProviderArn": rec["credentialProviderArn"]})
    rec = vault.get(name)
    if not rec:
        raise B._nf(f"Credential provider {name} not found")
    if verb == "Get":
        return B._j(200, _view(kind, rec))
    if verb == "Delete":
        del vault[name]
        return B._j(200, {})
    if kind == "apikey":
        if not p.get("apiKey"):
            raise B._bad("apiKey is required")
        rec["_apiKey"] = p["apiKey"]
    else:
        cfg = p.get("oauth2ProviderConfigInput") or {}
        c = next(iter(cfg.values()), None) if len(cfg) == 1 else None
        if not isinstance(c, dict) or not c.get("clientId") or not c.get("clientSecret"):
            raise B._bad("oauth2ProviderConfigInput with clientId and clientSecret is required")
        rec["_cfg"] = c
        rec["oauth2ProviderConfigOutput"] = {next(iter(cfg)): {"oauthDiscovery": c.get("oauthDiscovery") or {}, "clientId": c["clientId"]}}
    rec["lastUpdatedTime"] = time.time()
    return B._j(200, _view(kind, rec))


_TOK: dict = {}


def _find_provider(st, kind, ref):
    name = (ref or "").rsplit("/", 1)[-1]
    return _vault(st)[kind].get(name)


def oauth_token(rec, scopes, now=None):
    """OAuth2 client-credentials against the provider's token endpoint. -> access token (cached until ~30 s before expiry)."""
    now = now if now is not None else time.time()
    key = (rec["name"], tuple(scopes or []))
    hit = _TOK.get(key)
    if hit and hit[0] > now:
        return hit[1]
    if _NANO:
        raise RuntimeError("OAuth token exchange needs outbound network, unavailable in Nano's browser sandbox")
    c = rec["_cfg"]
    disc = c.get("oauthDiscovery") or {}
    ep = (disc.get("authorizationServerMetadata") or {}).get("tokenEndpoint")
    if not ep:
        ep = _http_json(disc["discoveryUrl"])["token_endpoint"]
    form = {"grant_type": "client_credentials"}
    if scopes:
        form["scope"] = " ".join(scopes)
    hdrs = {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"}
    if (c.get("clientAuthenticationMethod") or "CLIENT_SECRET_BASIC") == "CLIENT_SECRET_POST":
        form.update(client_id=c["clientId"], client_secret=c["clientSecret"])
    else:
        import base64
        hdrs["authorization"] = "Basic " + base64.b64encode(f"{urllib.parse.quote(c['clientId'], safe='')}:{urllib.parse.quote(c['clientSecret'], safe='')}".encode()).decode()
    req = urllib.request.Request(ep, data=urllib.parse.urlencode(form).encode(), headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=_UP_TIMEOUT) as r:  # noqa: S310 - operator-configured token endpoint
        doc = json.load(r)
    tok = doc.get("access_token")
    if not tok:
        raise RuntimeError("token endpoint returned no access_token")
    _TOK[key] = (now + max(float(doc.get("expires_in", 300)) - 30, 1), tok)
    return tok


def data_plane(st, method, segs, body):
    """bedrock-agentcore: POST /identities/api-key and /identities/oauth2/token (workload identity token is required but not verified: declared)."""
    p = B._body(body)
    if segs[1:] == ["api-key"] and method == "POST":
        if not p.get("workloadIdentityToken"):
            raise B._bad("workloadIdentityToken is required")
        rec = _vault(st)["apikey"].get(p.get("resourceCredentialProviderName", ""))
        if not rec:
            raise B._nf(f"Credential provider {p.get('resourceCredentialProviderName')} not found")
        return B._j(200, {"apiKey": rec["_apiKey"]})
    if segs[1:] == ["oauth2", "token"] and method == "POST":
        if not p.get("workloadIdentityToken"):
            raise B._bad("workloadIdentityToken is required")
        rec = _vault(st)["oauth2"].get(p.get("resourceCredentialProviderName", ""))
        if not rec:
            raise B._nf(f"Credential provider {p.get('resourceCredentialProviderName')} not found")
        if p.get("oauth2Flow") != "M2M":
            raise B._bad("only oauth2Flow M2M (client credentials) is supported; USER_FEDERATION needs a browser consent flow")
        try:
            return B._j(200, {"accessToken": oauth_token(rec, p.get("scopes") or [])})
        except Exception as e:  # noqa: BLE001
            raise B._Err("ServiceException", f"Token exchange failed: {e}", 500)
    return None


def dispatch(st, method, segs, body):
    if segs[0] != "identities" or len(segs) < 2:
        return None
    try:
        return _providers(st, method, segs, body) or data_plane(st, method, segs, body)
    except B._Err as e:
        return B._err_resp(e)


def apply_credentials(st, target, headers, query, inbound_headers=None):
    """Resolve a gateway target's credentialProviderConfigurations into outbound headers / query params (mutates both)."""
    for c in target.get("credentialProviderConfigurations") or []:
        t = c.get("credentialProviderType")
        cp = c.get("credentialProvider") or {}
        if t == "API_KEY":
            a = cp.get("apiKeyCredentialProvider") or {}
            rec = _find_provider(st, "apikey", a.get("providerArn"))
            if not rec:
                raise RuntimeError(f"API key credential provider {a.get('providerArn')} not found")
            val = (a.get("credentialPrefix") or "") + rec["_apiKey"]
            name = a.get("credentialParameterName") or "Authorization"
            (query if a.get("credentialLocation") == "QUERY_PARAMETER" else headers)[name] = val
        elif t == "OAUTH":
            o = cp.get("oauthCredentialProvider") or {}
            rec = _find_provider(st, "oauth2", o.get("providerArn"))
            if not rec:
                raise RuntimeError(f"OAuth credential provider {o.get('providerArn')} not found")
            headers["Authorization"] = "Bearer " + oauth_token(rec, o.get("scopes") or [])
        elif t == "JWT_PASSTHROUGH":
            tok = _bearer(inbound_headers)
            if tok:
                headers["Authorization"] = "Bearer " + tok


def check_target_providers(st, p):
    """Create-time validation: a referenced credential provider must exist."""
    for c in p.get("credentialProviderConfigurations") or []:
        t, cp = c.get("credentialProviderType"), c.get("credentialProvider") or {}
        for key, kind in (("apiKeyCredentialProvider", "apikey"), ("oauthCredentialProvider", "oauth2")):
            ref = (cp.get(key) or {}).get("providerArn")
            if ref and not _find_provider(st, kind, ref):
                raise B._bad(f"Credential provider {ref} does not exist")
        if t == "API_KEY" and not (cp.get("apiKeyCredentialProvider") or {}).get("providerArn"):
            raise B._bad("credentialProvider.apiKeyCredentialProvider.providerArn is required for API_KEY")
        if t == "OAUTH" and not (cp.get("oauthCredentialProvider") or {}).get("providerArn"):
            raise B._bad("credentialProvider.oauthCredentialProvider.providerArn is required for OAUTH")


# ═════════════════════════ openApiSchema targets ═════════════════════════
def _load_spec(mcp_cfg, s3):
    o = mcp_cfg["openApiSchema"]
    raw = o.get("inlinePayload")
    if raw is None and (o.get("s3") or {}).get("uri") and s3 is not None:
        m = re.match(r"^s3://([^/]+)/(.+)$", o["s3"]["uri"])
        if m:
            from core import s3_object_core as so
            r = so.get_object(s3, m.group(1), m.group(2), {}, {})
            raw = r.body.decode("utf-8", "replace") if r.status == 200 else None
    if raw is None:
        raise B._bad("openApiSchema needs inlinePayload (or a readable s3 uri)")
    try:
        return json.loads(raw)
    except ValueError:
        pass
    try:
        import yaml
        d = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001
        d = None
    if not isinstance(d, dict):
        raise B._bad("openApiSchema is neither valid JSON nor YAML")
    return d


def _deref(spec, node, depth=0):
    if isinstance(node, dict) and "$ref" in node and depth < 8:
        cur = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = (cur or {}).get(part.replace("~1", "/").replace("~0", "~")) if isinstance(cur, dict) else None
        return _deref(spec, cur or {}, depth + 1)
    return node


def openapi_operations(spec):
    """-> [{tool, description, inputSchema, method, path, params:[(name,in)], body_keys, body_whole}] for every operation with an operationId."""
    ops = []
    for path, item in (spec.get("paths") or {}).items():
        item = _deref(spec, item)
        shared = [_deref(spec, x) for x in item.get("parameters") or []]
        for meth in _METHODS:
            op = item.get(meth)
            if not isinstance(op, dict) or not op.get("operationId"):
                continue
            props, req, params = {}, [], []
            for prm in shared + [_deref(spec, x) for x in op.get("parameters") or []]:
                if prm.get("in") not in ("path", "query", "header"):
                    continue
                sch = dict(_deref(spec, prm.get("schema") or {"type": "string"}))
                if prm.get("description"):
                    sch.setdefault("description", prm["description"])
                props[prm["name"]] = sch
                params.append((prm["name"], prm["in"]))
                if prm.get("required") or prm["in"] == "path":
                    req.append(prm["name"])
            body_keys, whole = [], False
            rb = _deref(spec, op.get("requestBody") or {})
            js = _deref(spec, ((rb.get("content") or {}).get("application/json") or {}).get("schema") or {}) if rb else {}
            if js.get("type") == "object" or "properties" in js:
                for k, v in (js.get("properties") or {}).items():
                    props[k] = _deref(spec, v)
                    body_keys.append(k)
                req += [k for k in js.get("required") or [] if k in props]
            elif js:
                props["body"] = js
                whole = True
                if rb.get("required"):
                    req.append("body")
            ops.append({"tool": op["operationId"], "description": op.get("summary") or op.get("description") or f"{meth.upper()} {path}",
                        "inputSchema": {"type": "object", "properties": props, **({"required": sorted(set(req))} if req else {})},
                        "method": meth.upper(), "path": path, "params": params, "body_keys": body_keys, "body_whole": whole})
    return ops


def validate_openapi(mcp_cfg, s3=None):
    spec = _load_spec(mcp_cfg, s3)
    if not (spec.get("servers") or [{}])[0].get("url", "").startswith(("http://", "https://")):
        raise B._bad("openApiSchema must declare servers[0].url (an absolute http(s) URL)")
    if not openapi_operations(spec):
        raise B._bad("openApiSchema declares no operations with an operationId")
    return spec


def _http(method, url, headers, data=None):
    """-> (status, content-type, bytes). HTTP errors are returned, not raised."""
    if _NANO:
        raise RuntimeError("outbound HTTP needs network egress, which Nano's browser sandbox does not provide (use the Mesh appliance)")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_UP_TIMEOUT) as r:  # noqa: S310 - operator-configured upstream
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


def call_openapi(st, target, spec_ops, base, tool, args, inbound_headers):
    op = next(o for o in spec_ops if o["tool"] == tool)
    args = dict(args or {})
    path = op["path"]
    q, h = {}, {"accept": "application/json"}
    for name, where in op["params"]:
        if name not in args:
            continue
        v = args.pop(name)
        if where == "path":
            path = path.replace("{" + name + "}", urllib.parse.quote(str(v), safe=""))
        elif where == "query":
            q[name] = v
        else:
            h[name] = str(v)
    data = None
    if op["body_whole"] and "body" in args:
        data = json.dumps(args.pop("body")).encode()
    elif op["body_keys"]:
        data = json.dumps({k: args[k] for k in op["body_keys"] if k in args}).encode()
    if data is not None:
        h["content-type"] = "application/json"
    apply_credentials(st, target, h, q, inbound_headers)
    url = base.rstrip("/") + path + (("?" + urllib.parse.urlencode(q, doseq=True)) if q else "")
    status, ctype, raw = _http(op["method"], url, h, data)
    txt = raw.decode("utf-8", "replace")
    res = {"isError": status >= 400, "content": [{"type": "text", "text": txt}]}
    if status >= 400:
        res["content"][0]["text"] = f"HTTP {status}: {txt}"
    elif "json" in ctype:
        try:
            res["structuredContent"] = json.loads(txt)
        except ValueError:
            pass
    return res


# ═════════════════════════ mcpServer targets (proxy) ═════════════════════════
def _mcp_post(url, headers, payload, session=None):
    h = {"content-type": "application/json", "accept": "application/json, text/event-stream", **headers}
    if session:
        h["mcp-session-id"] = session
    status, ctype, raw = _http("POST", url, h, json.dumps(payload).encode())
    sid = None
    if status >= 400:
        raise RuntimeError(f"upstream MCP server returned HTTP {status}")
    txt = raw.decode("utf-8", "replace")
    if "event-stream" in ctype:
        msgs = [json.loads(ln[5:].strip()) for ln in txt.splitlines() if ln.startswith("data:") and ln[5:].strip()]
        doc = next((m for m in msgs if m.get("id") == payload.get("id")), None)
    else:
        doc = json.loads(txt) if txt.strip() else None
    return doc, sid


def mcp_upstream(st, target, method, params, inbound_headers):
    """Forward one JSON-RPC request to the target's mcpServer endpoint after a stateless initialize handshake."""
    url = ((target["targetConfiguration"].get("mcp") or {}).get("mcpServer") or {}).get("endpoint")
    h, q = {}, {}
    apply_credentials(st, target, h, q, inbound_headers)
    if q:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    init, _ = _mcp_post(url, h, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "vyomi-gateway", "version": "1.0"}}})
    if not init or "result" not in init:
        raise RuntimeError(f"upstream MCP initialize failed: {init}")
    try:
        _mcp_post(url, h, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    except Exception:  # noqa: BLE001 - notifications may 202 with an empty body
        pass
    doc, _ = _mcp_post(url, h, {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}})
    if not doc:
        raise RuntimeError("upstream MCP server sent no reply")
    if "error" in doc:
        raise RuntimeError(f"upstream MCP error: {doc['error'].get('message')}")
    return doc.get("result") or {}


# ═════════════════════════ runtime protocol variants (MCP / A2A over the agent spec) ═════════════════════════
def _rpc_ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_err(rid, code, msg):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def runtime_mcp(spec, req, ag, name="agent"):
    """AgentCore runtime with serverProtocol MCP: the agent spec's tools are the MCP server's tools."""
    rid, method, prm = req.get("id"), req.get("method"), req.get("params") or {}
    tools = {t["name"]: t for t in spec.get("tools") or []}
    if method == "initialize":
        return _rpc_ok(rid, {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": name, "version": "1.0.0"}})
    if method == "ping":
        return _rpc_ok(rid, {})
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _rpc_ok(rid, {"tools": [{"name": n, "description": t.get("description", ""), "inputSchema": t.get("parameters") or {"type": "object", "properties": {}}} for n, t in tools.items()]})
    if method == "tools/call":
        t = tools.get(prm.get("name"))
        if not t:
            return _rpc_err(rid, -32602, f"Unknown tool: {prm.get('name')}")
        res, err = ag.exec_tool(t, prm.get("arguments") or {})
        return _rpc_ok(rid, {"isError": bool(err), "content": [{"type": "text", "text": res if isinstance(res, str) else json.dumps(res, default=str)}]})
    return _rpc_err(rid, -32601, f"Method not found: {method}")


def a2a_card(rt, spec):
    return {"name": rt["agentRuntimeName"], "description": rt.get("description") or (spec.get("instructions") or "")[:200],
            "url": rt["agentRuntimeArn"], "version": "1.0.0", "protocolVersion": "0.3.0", "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": False}, "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
            "skills": [{"id": t["name"], "name": t["name"], "description": t.get("description", ""), "tags": []} for t in spec.get("tools") or []]}


def runtime_a2a(rt, spec, req, run_agent, tasks):
    """A2A JSON-RPC: message/send runs the agent and returns a completed Task; tasks/get; agent/getAuthenticatedExtendedCard."""
    rid, method, prm = req.get("id"), req.get("method"), req.get("params") or {}
    if method == "message/send":
        msg = prm.get("message") or {}
        text = " ".join(p.get("text", "") for p in msg.get("parts") or [] if p.get("kind", "text") == "text").strip()
        if not text:
            return _rpc_err(rid, -32602, "message.parts needs a text part")
        ctx = msg.get("contextId") or "ctx-" + B._rid(16, B._LOWER)
        out = run_agent(text, ctx)
        tid = "task-" + B._rid(16, B._LOWER)
        task = {"kind": "task", "id": tid, "contextId": ctx, "status": {"state": "completed", "timestamp": B._iso()},
                "artifacts": [{"artifactId": "art-" + B._rid(8, B._LOWER), "name": "response", "parts": [{"kind": "text", "text": out}]}],
                "history": [msg, {"kind": "message", "role": "agent", "messageId": "m-" + B._rid(10, B._LOWER), "contextId": ctx, "parts": [{"kind": "text", "text": out}]}]}
        tasks[tid] = task
        return _rpc_ok(rid, task)
    if method == "tasks/get":
        t = tasks.get(prm.get("id"))
        return _rpc_ok(rid, t) if t else _rpc_err(rid, -32001, "Task not found")
    if method in ("agent/getAuthenticatedExtendedCard", "agent/card"):
        return _rpc_ok(rid, a2a_card(rt, spec))
    return _rpc_err(rid, -32601, f"Method not found: {method}")
