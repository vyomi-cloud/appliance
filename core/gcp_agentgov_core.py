"""Agent Platform governance on GCP: Gateways, MCP servers (registry), Policies, Security (Model Armor) and Provisioned Throughput.
Substrate-independent, Pyodide-loadable, pure Python. A thin WIRE ADAPTER: no engine is hand-built here.

  Security            modelarmor.googleapis.com v1  templates / templates:sanitizeUserPrompt / :sanitizeModelResponse
                      engine = core/bedrock_guardrails_core.evaluate (content filters, prompt-attack, PII regexes) - the same engine Bedrock Guardrails use.
  Gateways            agentGateways  -> an AgentCore gateway (core/bedrock_agents_core: MCP data plane at /gateways/{id}/mcp, targets, JWT auth)
  MCP servers         mcpServers (registry) -> catalogue entries; attaching one to a gateway creates a real AgentCore mcpServer target
  Policies            agentPolicies  -> an AgentCore policy engine + one Cedar policy (core/agentcore_ext_core, cedarpy); attach to a gateway ENFORCE / LOG_ONLY
  Provisioned         provisionedThroughputs -> BOOKKEEPING ONLY (a record with units and a term); nothing is reserved, metered or billed
  Throughput          (the same honest scope as Bedrock's Provisioned Throughput; Google exposes no public create API to model, so this path is a Vyomi extension).

Honest limits: Google's Agent Gateway / Agent Registry / policy control planes are not public APIs, so those resource shapes are Vyomi's own (modelled on
the console fields and the AgentCore engines) and every record says so (`vyomiExtension`). A GCP gateway is an AgentCore gateway: it also appears in the AWS
console of the same account (names are prefixed `gcp-`). Model Armor: malicious-URI detection (Safe Browsing) and advanced SDP (Cloud DLP templates) are
reported EXECUTION_SKIPPED; the content / prompt-attack detection is the keyword and embedding engine of Bedrock Guardrails, so it is toy-grade, not Google's models.
Cedar policy decisions use cedarpy (Mesh/host) or the same Cedar core as WebAssembly (Nano, core/cedar_wasm_shim); if the evaluator is not loaded an ENFORCE gateway fails closed.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone

try:
    from core import agentcore_ext_core as ext
    from core import agentcore_gateway_targets as gt
    from core import bedrock_agents_core as B
    from core import bedrock_guardrails_core as G
except ImportError:  # Pyodide flat layout
    import agentcore_ext_core as ext  # type: ignore
    import agentcore_gateway_targets as gt  # type: ignore
    import bedrock_agents_core as B  # type: ignore
    import bedrock_guardrails_core as G  # type: ignore

_V = r"(?:v1|v1alpha|v1beta1|v1beta|v1alpha1)"
_LOC = r"^/(%s)/projects/([^/]+)/locations/([^/]+)/" % _V
RX = {
    "templates": re.compile(_LOC + r"templates(?:/([^/:]+))?(:sanitizeUserPrompt|:sanitizeModelResponse|:recentFindings)?/?$"),
    "provisionedThroughputs": re.compile(_LOC + r"provisionedThroughputs(?:/([^/:]+))?/?$"),
    "mcpServers": re.compile(_LOC + r"mcpServers(?:/([^/:]+))?(:listTools)?/?$"),
    "agentGateways": re.compile(_LOC + r"agentGateways(?:/([^/:]+))?(:attachMcpServer|:detachMcpServer|:attachPolicy|:detachPolicy|:listTools|:callTool)?/?$"),
    "agentPolicies": re.compile(_LOC + r"agentPolicies(?:/([^/:]+))?(:test)?/?$"),
}
_ROLE = "arn:aws:iam::123456789012:role/vyomi-gcp-agent-gateway"
_ID = re.compile(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")
_CONF = {"LOW_AND_ABOVE": "HIGH", "MEDIUM_AND_ABOVE": "MEDIUM", "HIGH": "LOW"}   # Model Armor confidence threshold -> guardrail filter strength
_RAI = {"SEXUALLY_EXPLICIT": "SEXUAL", "HATE_SPEECH": "HATE", "HARASSMENT": "INSULTS", "DANGEROUS": "VIOLENCE"}
_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
_CONF_OUT = {"LOW": "LOW_AND_ABOVE", "MEDIUM": "MEDIUM_AND_ABOVE", "HIGH": "HIGH"}
_SDP = {"CREDIT_CARD_NUMBER": "CREDIT_DEBIT_CARD_NUMBER", "US_SOCIAL_SECURITY_NUMBER": "US_SOCIAL_SECURITY_NUMBER", "FINANCIAL_ACCOUNT_NUMBER": "US_BANK_ACCOUNT_NUMBER",
        "PASSWORD": "PASSWORD", "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "PHONE", "AWS_CREDENTIALS": "AWS_ACCESS_KEY"}
_SDP_BASIC = ["CREDIT_CARD_NUMBER", "US_SOCIAL_SECURITY_NUMBER", "FINANCIAL_ACCOUNT_NUMBER", "PASSWORD"]
_GCP_KEY = r"AIza[0-9A-Za-z_\-]{35}"


class _Err(Exception):
    def __init__(self, status, st, msg):
        self.status, self.st, self.msg = status, st, msg


def handles(path):
    p = path.split("?", 1)[0]
    return any(r.match(p) for r in RX.values())


def _iso(t=None):
    return datetime.fromtimestamp(t if t is not None else time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _out(status, doc):
    return {"status": status, "headers": {"content-type": "application/json; charset=UTF-8"}, "body": json.dumps(doc).encode()}


def _gerr(e):
    return _out(e.status, {"error": {"code": e.status, "message": e.msg, "status": e.st}})


def _body(raw):
    if not raw:
        return {}
    try:
        p = json.loads(raw)
    except ValueError:
        raise _Err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(p, dict):
        raise _Err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    return p


def _state(store):
    st = store.account.setdefault("agent_governance", {})
    for k in ("templates", "pt", "mcp", "gateways", "policies"):
        st.setdefault(k, {})
    st.setdefault("findings", [])
    return st


def _page(items, q, key):
    size = max(1, min(int(q.get("pageSize") or 100), 1000))
    start = int(q.get("pageToken") or 0)
    out = {key: items[start:start + size]}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _new_id(q, p, field, existing, prefix):
    rid = q.get(field) or p.get(field) or (prefix + "-" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8)))
    if not _ID.match(rid):
        raise _Err(400, "INVALID_ARGUMENT", f"{field} must match [a-z]([a-z0-9-]{{0,61}}[a-z0-9])?.")
    if rid in existing:
        raise _Err(409, "ALREADY_EXISTS", f"Resource '{rid}' already exists.")
    return rid


def _qv(q, k):
    v = (q or {}).get(k)
    return v[0] if isinstance(v, list) else v


# ═════════════════════════════ entry point ═════════════════════════════
def dispatch(store, lam, method, path, query=None, headers=None, body=b"", host=""):
    method = method.upper()
    path = path.split("?", 1)[0]
    q = {k: _qv(query, k) for k in (query or {})}
    try:
        st = _state(store)
        for kind, rx in RX.items():
            m = rx.match(path)
            if m:
                fn = {"templates": _templates, "provisionedThroughputs": _pt, "mcpServers": _mcp, "agentGateways": _gateways, "agentPolicies": _policies}[kind]
                r = fn(store, st, lam, method, m, _body(body), q, host)
                return _out(200, r)
        raise _Err(404, "NOT_FOUND", "Unsupported Agent Platform governance path: " + path)
    except _Err as e:
        return _gerr(e)
    except B._Err as e:
        return _out({"ResourceNotFoundException": 404, "ConflictException": 409}.get(e.code, 400), {"error": {"code": 400, "message": e.msg, "status": "FAILED_PRECONDITION"}})
    except G.GErr as e:
        return _gerr(_Err(e.status, "INVALID_ARGUMENT", e.msg))


def _in(r, parent):
    """A list under location `-` spans every location of the project."""
    return r["_parent"] == parent or (parent.endswith("/locations/-") and r["_parent"].startswith(parent[:-1]))


def _parent(m):
    return f"projects/{m.group(2)}/locations/{m.group(3)}"


# ═════════════════════════════ Provisioned Throughput: bookkeeping ═════════════════════════════
def _pt(store, st, lam, method, m, p, q, host):
    parent, pid = _parent(m), m.group(4)
    coll = st["pt"]
    note = ("Vyomi bookkeeping: this record states an intent (units and a term). No serving capacity is reserved, no quota is enforced and nothing is "
            "billed - a local model has no shared capacity to commit.")
    if pid is None:
        if method == "GET":
            return _page([_view(r) for r in coll.values() if _in(r, parent)], q, "provisionedThroughputs")
        if method == "POST":
            if not p.get("model"):
                raise _Err(400, "INVALID_ARGUMENT", "model is required (publishers/google/models/<id> or a tuned model).")
            units = int(p.get("generativeModelUnits") or 1)
            if units < 1:
                raise _Err(400, "INVALID_ARGUMENT", "generativeModelUnits must be at least 1.")
            term = p.get("commitmentTerm") or "ONE_WEEK"
            if term not in ("ONE_WEEK", "ONE_MONTH", "THREE_MONTHS", "ONE_YEAR"):
                raise _Err(400, "INVALID_ARGUMENT", "commitmentTerm must be ONE_WEEK, ONE_MONTH, THREE_MONTHS or ONE_YEAR.")
            rid = _new_id(q, p, "provisionedThroughputId", {k.rsplit("/", 1)[-1] for k in coll}, "pt")
            now = time.time()
            days = {"ONE_WEEK": 7, "ONE_MONTH": 30, "THREE_MONTHS": 90, "ONE_YEAR": 365}[term]
            r = {"name": f"{parent}/provisionedThroughputs/{rid}", "displayName": p.get("displayName") or rid, "model": p["model"], "generativeModelUnits": units,
                 "commitmentTerm": term, "state": "ACTIVE", "createTime": _iso(now), "startTime": _iso(now), "endTime": _iso(now + days * 86400),
                 "vyomiExtension": True, "vyomiNote": note, "_parent": parent}
            coll[r["name"]] = r
            return _view(r)
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{parent}/provisionedThroughputs/{pid}"
    r = coll.get(name)
    if not r:
        raise _Err(404, "NOT_FOUND", f"Provisioned throughput `{name}` not found.")
    if method == "GET":
        return _view(r)
    if method == "DELETE":
        del coll[name]
        return {}
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


# ═════════════════════════════ Security: Model Armor over the guardrails engine ═════════════════════════════
def _check_filters(fc):
    if not isinstance(fc, dict) or not fc:
        raise _Err(400, "INVALID_ARGUMENT", "filterConfig is required and must enable at least one filter.")
    for f in (fc.get("raiSettings") or {}).get("raiFilters") or []:
        if f.get("filterType") not in _RAI:
            raise _Err(400, "INVALID_ARGUMENT", f"raiFilters.filterType must be one of {sorted(_RAI)}.")
        if f.get("confidenceLevel", "MEDIUM_AND_ABOVE") not in _CONF:
            raise _Err(400, "INVALID_ARGUMENT", "confidenceLevel must be LOW_AND_ABOVE, MEDIUM_AND_ABOVE or HIGH.")
    pj = fc.get("piAndJailbreakFilterSettings") or {}
    if pj and pj.get("filterEnforcement", "ENABLED") not in ("ENABLED", "DISABLED"):
        raise _Err(400, "INVALID_ARGUMENT", "filterEnforcement must be ENABLED or DISABLED.")


def _enabled(s):
    return bool(s) and (s.get("filterEnforcement", "ENABLED") == "ENABLED")


def _policy_for(fc, source):
    """Model Armor filterConfig -> a guardrail policy dict (detect-only PII, blocking content / prompt-attack filters)."""
    filters = []
    for f in (fc.get("raiSettings") or {}).get("raiFilters") or []:
        filters.append({"type": _RAI[f["filterType"]], "inputStrength": _CONF[f.get("confidenceLevel", "MEDIUM_AND_ABOVE")], "outputStrength": _CONF[f.get("confidenceLevel", "MEDIUM_AND_ABOVE")]})
    pj = fc.get("piAndJailbreakFilterSettings")
    if _enabled(pj) and source == "INPUT":
        lvl = _CONF[pj.get("confidenceLevel", "MEDIUM_AND_ABOVE")]
        filters.append({"type": "PROMPT_ATTACK", "inputStrength": lvl, "outputStrength": "NONE"})
    pii = []
    sdp = ((fc.get("sdpSettings") or {}).get("basicConfig")) or {}
    if _enabled(sdp):
        pii = [{"type": _SDP[k], "action": "NONE"} for k in _SDP_BASIC]
    pol = {"blockedInputMessaging": "blocked", "blockedOutputsMessaging": "blocked"}
    if filters:
        pol["contentPolicyConfig"] = {"filtersConfig": filters}
    sip = {}
    if pii:
        sip["piiEntitiesConfig"] = pii
        sip["regexesConfig"] = [{"name": "GCP_API_KEY", "pattern": _GCP_KEY, "action": "NONE"}]
    if sip:
        pol["sensitiveInformationPolicyConfig"] = sip
    return pol


def sanitize(fc, text, source):
    """-> Model Armor SanitizationResult for one text. source INPUT = user prompt, OUTPUT = model response."""
    pol = _policy_for(fc, source)
    res = G.evaluate(pol, text, source) if (pol.get("contentPolicyConfig") or pol.get("sensitiveInformationPolicyConfig")) else {"assessment": {}}
    a = res.get("assessment") or {}
    results, any_match = {}, False
    rai = (fc.get("raiSettings") or {}).get("raiFilters") or []
    if rai:
        hit = {x["type"]: x for x in (a.get("contentPolicy") or {}).get("filters", [])}
        by = {}
        for f in rai:
            h = hit.get(_RAI[f["filterType"]])
            by[f["filterType"]] = {"confidenceLevel": _CONF_OUT.get(h["confidence"], "HIGH") if h else "CONFIDENCE_LEVEL_UNSPECIFIED", "matchState": "MATCH_FOUND" if h else "NO_MATCH_FOUND"}
        m = any(v["matchState"] == "MATCH_FOUND" for v in by.values())
        any_match |= m
        results["rai"] = {"raiFilterResult": {"executionState": "EXECUTION_SUCCESS", "matchState": "MATCH_FOUND" if m else "NO_MATCH_FOUND", "raiFilterTypeResults": by}}
    pj = fc.get("piAndJailbreakFilterSettings")
    if _enabled(pj):
        if source == "INPUT":
            h = next((x for x in (a.get("contentPolicy") or {}).get("filters", []) if x["type"] == "PROMPT_ATTACK"), None)
            any_match |= bool(h)
            results["pi_and_jailbreak"] = {"piAndJailbreakFilterResult": {"executionState": "EXECUTION_SUCCESS", "matchState": "MATCH_FOUND" if h else "NO_MATCH_FOUND",
                                                                         **({"confidenceLevel": _CONF_OUT.get(h["confidence"], "HIGH")} if h else {})}}
        else:
            results["pi_and_jailbreak"] = {"piAndJailbreakFilterResult": {"executionState": "EXECUTION_SKIPPED", "matchState": "NO_MATCH_FOUND",
                                                                         "messageItems": [{"message": "Prompt injection and jailbreak detection apply to user prompts only.", "messageType": "INFO"}]}}
    if _enabled(fc.get("maliciousUriFilterSettings")):
        results["malicious_uris"] = {"maliciousUriFilterResult": {"executionState": "EXECUTION_SKIPPED", "matchState": "NO_MATCH_FOUND",
                                                                 "messageItems": [{"message": "Malicious URI detection needs Google Safe Browsing, which Vyomi does not simulate.", "messageType": "INFO"}]}}
    sdpc = fc.get("sdpSettings") or {}
    if _enabled(sdpc.get("basicConfig")):
        finds = []
        sip = a.get("sensitiveInformationPolicy") or {}
        rev = {v: k for k, v in _SDP.items()}
        for e in sip.get("piiEntities", []):
            i = text.find(e["match"])
            finds.append({"infoType": rev.get(e["type"], e["type"]), "likelihood": "LIKELY", "location": {"byteRange": {"start": str(len(text[:i].encode())), "end": str(len(text[:i + len(e["match"])].encode()))}}})
        for e in sip.get("regexes", []):
            i = text.find(e["match"])
            finds.append({"infoType": "GCP_API_KEY", "likelihood": "LIKELY", "location": {"byteRange": {"start": str(len(text[:i].encode())), "end": str(len(text[:i + len(e["match"])].encode()))}}})
        any_match |= bool(finds)
        results["sdp"] = {"sdpFilterResult": {"inspectResult": {"executionState": "EXECUTION_SUCCESS", "matchState": "MATCH_FOUND" if finds else "NO_MATCH_FOUND", "findings": finds}}}
    elif sdpc.get("advancedConfig"):
        results["sdp"] = {"sdpFilterResult": {"inspectResult": {"executionState": "EXECUTION_SKIPPED", "matchState": "NO_MATCH_FOUND",
                                                               "messageItems": [{"message": "Advanced SDP uses Cloud DLP templates, which Vyomi does not simulate. Use basicConfig.", "messageType": "INFO"}]}}}
    return {"filterMatchState": "MATCH_FOUND" if any_match else "NO_MATCH_FOUND", "filterResults": results, "invocationResult": "SUCCESS"}


def _templates(store, st, lam, method, m, p, q, host):
    parent, tid, verb = _parent(m), m.group(4), m.group(5)
    coll = st["templates"]
    if tid is None:
        if method == "GET":
            return _page([_view(r) for r in coll.values() if _in(r, parent)], q, "templates")
        if method == "POST":
            _check_filters(p.get("filterConfig"))
            rid = _new_id(q, p, "templateId", {k.rsplit("/", 1)[-1] for k in coll if k.startswith(parent)}, "template")
            now = _iso()
            r = {"name": f"{parent}/templates/{rid}", "createTime": now, "updateTime": now, "labels": p.get("labels") or {}, "filterConfig": p["filterConfig"],
                 "templateMetadata": p.get("templateMetadata") or {}, "_parent": parent}
            coll[r["name"]] = r
            return _view(r)
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{parent}/templates/{tid}"
    r = coll.get(name)
    if not r:
        raise _Err(404, "NOT_FOUND", f"Template `{name}` not found.")
    if verb in (":sanitizeUserPrompt", ":sanitizeModelResponse"):
        if method != "POST":
            raise _Err(405, "METHOD_NOT_ALLOWED", "Use POST.")
        user = verb == ":sanitizeUserPrompt"
        data = p.get("userPromptData" if user else "modelResponseData") or {}
        text = data.get("text")
        if not isinstance(text, str) or not text:
            raise _Err(400, "INVALID_ARGUMENT", ("userPromptData" if user else "modelResponseData") + ".text is required (byteItem inputs are not supported).")
        res = sanitize(r["filterConfig"], text, "INPUT" if user else "OUTPUT")
        st["findings"].append({"time": _iso(), "template": name, "kind": "userPrompt" if user else "modelResponse", "matchState": res["filterMatchState"],
                               "matched": sorted(k for k, v in res["filterResults"].items() if "MATCH_FOUND" in json.dumps(v)), "chars": len(text)})
        del st["findings"][:-200]
        return {"sanitizationResult": res}
    if verb == ":recentFindings":
        return {"findings": [f for f in reversed(st["findings"]) if f["template"] == name][:50], "vyomiExtension": True}
    if method == "GET":
        return _view(r)
    if method == "PATCH":
        if "filterConfig" in p:
            _check_filters(p["filterConfig"])
            r["filterConfig"] = p["filterConfig"]
        for f in ("labels", "templateMetadata"):
            if f in p:
                r[f] = p[f]
        r["updateTime"] = _iso()
        return _view(r)
    if method == "DELETE":
        del coll[name]
        return {}
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


# ═════════════════════════════ MCP servers (registry) ═════════════════════════════
def _mcp(store, st, lam, method, m, p, q, host):
    _use(store)
    parent, sid, verb = _parent(m), m.group(4), m.group(5)
    coll = st["mcp"]
    if sid is None:
        if method == "GET":
            return _page([_mcp_view(r) for r in coll.values() if _in(r, parent)], q, "mcpServers")
        if method == "POST":
            ep = str(p.get("endpoint") or "")
            if not ep.startswith(("http://", "https://")):
                raise _Err(400, "INVALID_ARGUMENT", "endpoint must be an http(s) URL of a streamable-HTTP MCP server.")
            rid = _new_id(q, p, "mcpServerId", {k.rsplit("/", 1)[-1] for k in coll if k.startswith(parent)}, "mcp")
            auth = p.get("authentication") or {}
            if auth and not (auth.get("apiKey") or {}).get("value"):
                raise _Err(400, "INVALID_ARGUMENT", "authentication.apiKey.value is required when authentication is set (header defaults to Authorization).")
            r = {"name": f"{parent}/mcpServers/{rid}", "displayName": p.get("displayName") or rid, "description": p.get("description", ""), "endpoint": ep,
                 "state": "ACTIVE", "createTime": _iso(), "vyomiExtension": True, "_parent": parent, "_auth": auth.get("apiKey") or None}
            coll[r["name"]] = r
            return _mcp_view(r)
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{parent}/mcpServers/{sid}"
    r = coll.get(name)
    if not r:
        raise _Err(404, "NOT_FOUND", f"MCP server `{name}` not found.")
    if verb == ":listTools":
        return {"tools": _upstream_tools(st, r), "vyomiExtension": True}
    if method == "GET":
        return _mcp_view(r)
    if method == "DELETE":
        if any(name in g["mcpServers"] for g in st["gateways"].values()):
            raise _Err(400, "FAILED_PRECONDITION", "The MCP server is attached to a gateway; detach it first.")
        del coll[name]
        return {}
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _mcp_view(r):
    v = _view(r)
    v["authentication"] = {"apiKey": {"header": (r["_auth"] or {}).get("header", "Authorization")}} if r.get("_auth") else {}
    return v


def _hdr(r):
    a = r.get("_auth")
    return {(a.get("header") or "Authorization"): a["value"]} if a else {}


def _upstream_tools(st, r):
    tgt = {"targetConfiguration": {"mcp": {"mcpServer": {"endpoint": r["endpoint"]}}}, "credentialProviderConfigurations": []}
    try:
        return gt.mcp_upstream(_ac_state(), tgt, "tools/list", {}, None, extra=_hdr(r)).get("tools") or []
    except Exception as e:  # noqa: BLE001 - surfaced as a modeled error, not a 500
        raise _Err(502, "UNAVAILABLE", f"Could not list tools from {r['endpoint']}: {e}")


_AC = []


def _ac_state():
    return _AC[0]


def _use(store):
    _AC[:] = [B._state(store)]
    return _AC[0]


# ═════════════════════════════ Gateways over AgentCore gateways ═════════════════════════════
def _ac(store, lam, method, path, doc=None, q=None):
    r = B.agentcore_dispatch(store, lam, method, path, q or {}, {}, json.dumps(doc).encode() if doc is not None else b"")
    body = json.loads(r["body"] or b"{}") if r.get("body") else {}
    if r["status"] >= 400:
        raise _Err(r["status"] if r["status"] in (400, 404, 409) else 400, "FAILED_PRECONDITION" if r["status"] != 404 else "NOT_FOUND", body.get("message") or str(body))
    return body


def _gw_view(store, st, g, host):
    ac = B._state(store)["gateways"].get(g["_acId"])
    if ac:
        B._ac_ready(ac)
    ready = bool(ac) and ac.get("status") == "READY"
    base = f"http://{host}" if host else ""
    v = _view(g)
    v.update(state="ACTIVE" if ready else "CREATING", mcpEndpoint=f"{base}/gateways/{g['_acId']}/mcp", agentCoreGatewayId=g["_acId"],
             attachedMcpServers=list(g["mcpServers"]), attachedPolicy=g.get("policy"))
    return v


def _gateways(store, st, lam, method, m, p, q, host):
    _use(store)
    parent, gid, verb = _parent(m), m.group(4), m.group(5)
    coll = st["gateways"]
    if gid is None:
        if method == "GET":
            return _page([_gw_view(store, st, g, host) for g in coll.values() if _in(g, parent)], q, "agentGateways")
        if method == "POST":
            rid = _new_id(q, p, "agentGatewayId", {k.rsplit("/", 1)[-1] for k in coll if k.startswith(parent)}, "gateway")
            auth = p.get("authorization") or {"type": "NONE"}
            if auth.get("type") not in ("NONE", "JWT"):
                raise _Err(400, "INVALID_ARGUMENT", "authorization.type must be NONE or JWT.")
            ac_doc = {"name": "gcp-" + rid, "roleArn": _ROLE, "protocolType": "MCP", "authorizerType": "NONE", "description": p.get("description", "")}
            if auth["type"] == "JWT":
                jwt = auth.get("jwt") or {}
                if not jwt.get("discoveryUrl"):
                    raise _Err(400, "INVALID_ARGUMENT", "authorization.jwt.discoveryUrl is required for JWT.")
                ac_doc["authorizerType"] = "CUSTOM_JWT"
                ac_doc["authorizerConfiguration"] = {"customJWTAuthorizer": {"discoveryUrl": jwt["discoveryUrl"], **({"allowedAudience": jwt["allowedAudiences"]} if jwt.get("allowedAudiences") else {})}}
            created = _ac(store, lam, "POST", "/gateways", ac_doc)
            g = {"name": f"{parent}/agentGateways/{rid}", "displayName": p.get("displayName") or rid, "description": p.get("description", ""), "protocols": ["MCP"],
                 "authorization": auth, "createTime": _iso(), "vyomiExtension": True, "mcpServers": [], "policy": None, "_parent": parent, "_acId": created["gatewayId"], "_targets": {}}
            coll[g["name"]] = g
            return _gw_view(store, st, g, host)
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{parent}/agentGateways/{gid}"
    g = coll.get(name)
    if not g:
        raise _Err(404, "NOT_FOUND", f"Agent gateway `{name}` not found.")
    if verb == ":attachMcpServer":
        srv = st["mcp"].get(p.get("mcpServer") or "")
        if not srv:
            raise _Err(404, "NOT_FOUND", f"MCP server `{p.get('mcpServer')}` not found.")
        if srv["name"] in g["mcpServers"]:
            raise _Err(409, "ALREADY_EXISTS", "The MCP server is already attached to this gateway.")
        tname = srv["name"].rsplit("/", 1)[-1]
        creds = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
        if srv.get("_auth"):
            pname = f"gcp-{gid}-{tname}"
            vault = gt._vault(B._state(store))["apikey"]
            vault[pname] = {"name": pname, "credentialProviderArn": gt._parn("apikey", pname), "createdTime": time.time(), "lastUpdatedTime": time.time(), "_apiKey": srv["_auth"]["value"]}
            creds = [{"credentialProviderType": "API_KEY", "credentialProvider": {"apiKeyCredentialProvider": {
                "providerArn": vault[pname]["credentialProviderArn"], "credentialParameterName": srv["_auth"].get("header") or "Authorization", "credentialLocation": "HEADER"}}}]
        t = _ac(store, lam, "POST", f"/gateways/{g['_acId']}/targets", {"name": tname, "targetConfiguration": {"mcp": {"mcpServer": {"endpoint": srv["endpoint"]}}}, "credentialProviderConfigurations": creds})
        g["_targets"][srv["name"]] = t["targetId"]
        g["mcpServers"].append(srv["name"])
        return _gw_view(store, st, g, host)
    if verb == ":detachMcpServer":
        sname = p.get("mcpServer") or ""
        if sname not in g["mcpServers"]:
            raise _Err(404, "NOT_FOUND", "The MCP server is not attached to this gateway.")
        _ac(store, lam, "DELETE", f"/gateways/{g['_acId']}/targets/{g['_targets'].pop(sname)}")
        g["mcpServers"].remove(sname)
        return _gw_view(store, st, g, host)
    if verb in (":attachPolicy", ":detachPolicy"):
        ac = B._state(store)["gateways"][g["_acId"]]
        if verb == ":detachPolicy":
            ac.pop("policyEngineConfiguration", None)
            g["policy"] = None
        else:
            pol = st["policies"].get(p.get("policy") or "")
            if not pol:
                raise _Err(404, "NOT_FOUND", f"Agent policy `{p.get('policy')}` not found.")
            eng = B._state(store)["policy_engines"][pol["_engineId"]]
            ac["policyEngineConfiguration"] = {"arn": eng["policyEngineArn"], "mode": pol["enforcementMode"] if pol["enforcementMode"] in ("ENFORCE", "LOG_ONLY") else "ENFORCE"}
            g["policy"] = pol["name"]
        return _gw_view(store, st, g, host)
    if verb == ":listTools":
        _ac_ready_wait(B._state(store)["gateways"][g["_acId"]])
        r = B._mcp(B._state(store), lam, g["_acId"], {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {}, internal="admin")
        doc = json.loads(r["body"] or b"{}")
        if "error" in doc:
            raise _Err(502, "UNAVAILABLE", doc["error"]["message"])
        return {"tools": (doc.get("result") or {}).get("tools") or [], "vyomiExtension": True}
    if verb == ":callTool":
        _ac_ready_wait(B._state(store)["gateways"][g["_acId"]])
        if not p.get("tool"):
            raise _Err(400, "INVALID_ARGUMENT", "tool (<target>___<tool>) is required.")
        r = B._mcp(B._state(store), lam, g["_acId"], {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": p["tool"], "arguments": p.get("arguments") or {}}}, {}, internal="admin")
        doc = json.loads(r["body"] or b"{}")
        if "error" in doc:
            return {"isError": True, "denied": True, "content": [{"type": "text", "text": doc["error"]["message"]}], "vyomiExtension": True}
        return dict(doc.get("result") or {}, vyomiExtension=True)
    if method == "GET":
        return _gw_view(store, st, g, host)
    if method == "DELETE":
        ac = B._state(store)["gateways"].get(g["_acId"])
        for tid in list(g["_targets"].values()):
            _ac(store, lam, "DELETE", f"/gateways/{g['_acId']}/targets/{tid}")
        if ac:
            ac["targets"].clear()
            _ac(store, lam, "DELETE", f"/gateways/{g['_acId']}")
        del coll[name]
        return {}
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _ac_ready_wait(ac):
    """The AgentCore engine flips CREATING -> READY on a clock (~1 s); a control-plane read right after create waits for it."""
    B._ac_ready(ac)
    if ac.get("status") != "READY":
        ac["_readyAt"] = 0
        B._ac_ready(ac)
        for t in ac["targets"].values():
            t["_readyAt"] = 0
            B._ac_ready(t)


# ═════════════════════════════ Policies over AgentCore policy engines (Cedar) ═════════════════════════════
def _policies(store, st, lam, method, m, p, q, host):
    _use(store)
    parent, pid, verb = _parent(m), m.group(4), m.group(5)
    coll = st["policies"]
    if pid is None:
        if method == "GET":
            return _page([_pol_view(store, x) for x in coll.values() if _in(x, parent)], q, "agentPolicies")
        if method == "POST":
            stmt = p.get("cedarPolicy")
            if not stmt or not isinstance(stmt, str):
                raise _Err(400, "INVALID_ARGUMENT", "cedarPolicy (Cedar policy text) is required.")
            mode = p.get("enforcementMode") or "ENFORCE"
            if mode not in ("ENFORCE", "LOG_ONLY"):
                raise _Err(400, "INVALID_ARGUMENT", "enforcementMode must be ENFORCE or LOG_ONLY.")
            rid = _new_id(q, p, "agentPolicyId", {k.rsplit("/", 1)[-1] for k in coll if k.startswith(parent)}, "policy")
            ename = "gcp_" + rid.replace("-", "_")
            eng = _ac(store, lam, "POST", "/policy-engines", {"name": ename, "description": p.get("description", "")})
            try:
                _ac(store, lam, "POST", f"/policy-engines/{eng['policyEngineId']}/policies", {"name": "main", "definition": {"cedar": {"statement": stmt}}})
            except _Err:
                B._state(store)["policy_engines"].pop(eng["policyEngineId"], None)
                raise
            x = {"name": f"{parent}/agentPolicies/{rid}", "displayName": p.get("displayName") or rid, "description": p.get("description", ""), "cedarPolicy": stmt,
                 "enforcementMode": mode, "state": "ACTIVE", "createTime": _iso(), "vyomiExtension": True, "_parent": parent, "_engineId": eng["policyEngineId"]}
            coll[x["name"]] = x
            return _pol_view(store, x)
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{parent}/agentPolicies/{pid}"
    x = coll.get(name)
    if not x:
        raise _Err(404, "NOT_FOUND", f"Agent policy `{name}` not found.")
    if verb == ":test":
        eng = B._state(store)["policy_engines"][x["_engineId"]]
        claims = dict(p.get("claims") or {})
        if p.get("principal"):
            claims["sub"] = p["principal"]
        gw = {"policyEngineConfiguration": {"arn": eng["policyEngineArn"], "mode": "ENFORCE"}, "gatewayArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test", "gatewayId": "test"}
        tool = p.get("tool")
        if not tool:
            raise _Err(400, "INVALID_ARGUMENT", "tool (<target>___<tool>) is required.")
        allowed, why = ext.authorize(B._state(store), gw, claims, tool, p.get("arguments") or {}, probe=True)
        return {"decision": "ALLOW" if allowed else "DENY", "reason": why, "engine": "cedar"}
    if method == "GET":
        return _pol_view(store, x)
    if method == "PATCH":
        if "cedarPolicy" in p:
            eng = B._state(store)["policy_engines"][x["_engineId"]]
            pol = next(iter(eng["policies"].values()))
            _ac(store, lam, "PATCH", f"/policy-engines/{eng['policyEngineId']}/policies/{pol['policyId']}", {"definition": {"cedar": {"statement": p["cedarPolicy"]}}})
            x["cedarPolicy"] = p["cedarPolicy"]
        if p.get("enforcementMode") in ("ENFORCE", "LOG_ONLY"):
            x["enforcementMode"] = p["enforcementMode"]
            for g in st["gateways"].values():
                if g.get("policy") == name:
                    B._state(store)["gateways"][g["_acId"]]["policyEngineConfiguration"]["mode"] = p["enforcementMode"]
        for f in ("displayName", "description"):
            if f in p:
                x[f] = p[f]
        return _pol_view(store, x)
    if method == "DELETE":
        if any(g.get("policy") == name for g in st["gateways"].values()):
            raise _Err(400, "FAILED_PRECONDITION", "The policy is attached to a gateway; detach it first.")
        eng = B._state(store)["policy_engines"].get(x["_engineId"])
        if eng:
            eng["policies"].clear()
            B._state(store)["policy_engines"].pop(x["_engineId"], None)
        del coll[name]
        return {}
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _pol_view(store, x):
    v = _view(x)
    v["attachedGateways"] = [g["name"] for g in _state(store)["gateways"].values() if g.get("policy") == x["name"]]
    v["engine"] = "cedar"
    return v
