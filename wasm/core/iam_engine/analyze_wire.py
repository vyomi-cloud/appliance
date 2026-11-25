"""Native-wire routes of the IAM analysis APIs, substrate-neutral (pure Python, Pyodide-safe: no fastapi / socket).

  match(method, path, query, headers, body) -> route | None      which analysis API (if any) this request is
  handle(route, spec, host)                  -> {status, headers, body}   the native response

Mesh calls it from core/aws_wire_router.AwsWireRouter._handle_raw (through core/iam_analyze_host.py); Nano calls it from
core/iam_engine/nano_bridge.analyze (JS: wasm/nano-iam-hook.js answers these routes in the page / relay worker before dispatch).

`host` supplies the live state; the engine never imports a store:
  host.aws()                                  -> {"store", "state", "audit", "region"}      (access_analyzer ctx)
  host.state(cloud, headers, query, path)     -> (engine state, calling principal)

Routes (each answered by the engine, not stubbed):
  AWS     access-analyzer REST (CreateAnalyzer ... ValidatePolicy / CheckNoNewAccess / CheckAccessNotGranted)  [core/iam_engine/access_analyzer.py]
          (SimulatePrincipalPolicy / SimulateCustomPolicy / GetContextKeysFor*Policy are IAM Query actions served by core/iam_core.py)
  GCP     POST /v1/iam:troubleshoot, POST /v3/iam:troubleshoot (policytroubleshooter), GET /v1/{scope}:analyzeIamPolicy (cloudasset)
  Azure   POST {scope}/providers/Microsoft.Authorization/checkAccess (native PascalCase body -> array), GET .../permissions,
          GET .../roleAssignments?$filter=atScope()|principalId eq ''|assignedTo(''), GET .../roleEligibilitySchedules[Instances],
          GET .../roleAssignmentSchedules[Instances]"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from . import access_analyzer, analyze_azure, analyze_gcp, azure_identity, azure_pim, routing

_AUTHZ = re.compile(r"^(?P<scope>.*?)/providers/Microsoft\.Authorization/(?P<res>[A-Za-z]+)/?$", re.I)
_PIM = re.compile(r"^(?P<scope>.*?)/providers/Microsoft\.Authorization/(?P<res>[A-Za-z]+)/(?P<name>[^/]+)(?:/(?P<verb>cancel))?/?$", re.I)
_GCP_TS = re.compile(r"^/(v1|v3)/iam:troubleshoot$")
_GCP_AN = re.compile(r"^/v1/((?:projects|folders|organizations)/[^/:]+):analyzeIamPolicy$")


def _qd(query):
    if not query:
        return {}
    if isinstance(query, str):
        return parse_qs(query.lstrip("?"), keep_blank_values=True)
    return {str(k): v for k, v in dict(query).items()}


def _q1(q, key):
    v = q.get(key)
    return (v[0] if isinstance(v, list) and v else v) if v is not None else None


def _json_body(body):
    try:
        d = json.loads(bytes(body).decode("utf-8")) if body else {}
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def match(method, path, query=None, headers=None, body=b""):
    """-> ("aws","accessanalyzer") | ("gcp","troubleshoot",ver) | ("gcp","analyze",scope) | ("azure", kind, scope[, extra]) | None."""
    method = str(method or "GET").upper()
    p = routing.strip_wire(str(path or "/").split("?", 1)[0])
    if access_analyzer.matches(method, p, headers):
        return ("aws", "accessanalyzer", p)
    if azure_identity.match_imds(method, p):                              # managed-identity token (IMDS)
        return ("azure", "imds", "/")
    if method == "POST" and re.search(r"/oauth2(?:/v2\.0)?/token$", p) and b"client_assertion=" in bytes(body or b""):
        return ("azure", "fedtoken", p)                                   # federated-credential exchange (workload identity)
    m = _GCP_TS.match(p)
    if m and method == "POST":
        return ("gcp", "troubleshoot", m.group(1))
    m = _GCP_AN.match(p)
    if m and method == "GET":
        return ("gcp", "analyze", m.group(1))
    m = _PIM.match(p)
    if m and azure_pim.kind_of(m.group("res")):          # PIM: requests (PUT / GET / POST .../cancel) and a single schedule (GET)
        k = azure_pim.kind_of(m.group("res"))
        if (method == "PUT" and k in (azure_pim.ELIG_REQ, azure_pim.ACT_REQ)) or method == "GET" \
                or (method == "POST" and m.group("verb") and k in (azure_pim.ELIG_REQ, azure_pim.ACT_REQ)):
            return ("azure", "pim", m.group("scope") or "/", k, m.group("name"), (m.group("verb") or "").lower())
    m = _AUTHZ.match(p)
    if m:
        res, scope = m.group("res").lower(), m.group("scope") or "/"
        q = _qd(query)
        if res == "checkaccess" and method == "POST":
            b = _json_body(body)
            if b is not None and any(str(k).lower() in ("subject", "resource") for k in b) and any(str(k).lower() == "actions" for k in b):
                return ("azure", "checkAccess", scope)
        elif res == "customrolechecks" and method == "POST":
            return ("azure", "customRoleChecks", scope)
        elif res == "permissions" and method == "GET":
            return ("azure", "permissions", scope)
        elif res == "roleassignments" and method == "GET" and _q1(q, "$filter"):
            try:
                analyze_azure.parse_filter(_q1(q, "$filter"))
            except analyze_azure.AzError:
                return None            # not one of the three forms: leave it to the store's own list
            return ("azure", "roleAssignments", scope)
        elif method == "GET" and analyze_azure.schedule_kind(res):
            return ("azure", "schedules", scope, res)
        elif azure_pim.kind_of(res) in (azure_pim.ELIG_REQ, azure_pim.ACT_REQ) and method == "GET":
            return ("azure", "pim", scope, azure_pim.kind_of(res), "", "")
    return None


def _json(status, obj):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(obj).encode()}


def _gerr(e):
    return _json(e.status, {"error": {"code": e.status, "message": str(e), "status": e.code}})


def _aerr(e):
    return _json(e.status, {"error": {"code": e.code, "message": str(e)}})


def handle(route, spec, host):
    method, path, headers = spec.get("method", "GET"), spec.get("path", "/"), spec.get("headers") or {}
    body, q = spec.get("body") or b"", _qd(spec.get("query"))
    cloud, kind = route[0], route[1]
    if cloud == "aws":
        ctx = host.aws()
        h = {str(k).lower(): str(v) for k, v in headers.items()}
        m = re.search(r"Credential=[^/]+/\d+/([^/]+)/", h.get("authorization", ""))
        if m:
            ctx = dict(ctx, region=m.group(1))
        return access_analyzer.dispatch(method, routing.strip_wire(str(path).split("?", 1)[0]), q, bytes(body), ctx)
    if kind in ("imds", "fedtoken"):
        return _identity_route(route, spec, host)
    state, principal = host.state(cloud, {str(k).lower(): v for k, v in headers.items()}, spec.get("query") if isinstance(spec.get("query"), str) else "", path)
    if cloud == "gcp":
        try:
            if kind == "troubleshoot":
                b = _json_body(body)
                if b is None:
                    return _json(400, {"error": {"code": 400, "message": "Invalid JSON payload.", "status": "INVALID_ARGUMENT"}})
                tup = b.get("accessTuple")
                return _json(200, analyze_gcp.troubleshoot_v3(tup, state) if route[2] == "v3" else analyze_gcp.troubleshoot_v1(tup, state))
            flat = {k: v for k, v in q.items()}
            return _json(200, analyze_gcp.analyze_iam_policy(route[2], flat, state))
        except analyze_gcp.GcpError as e:
            return _gerr(e)
    try:
        scope = route[2]
        if kind == "checkAccess":
            b = _json_body(body) or {}
            if not (analyze_azure._ci(analyze_azure._ci(b, "Resource") or {}, "Id")):
                b = dict(b, Resource={"Id": scope})
            return _json(200, analyze_azure.check_access(b, state, principal))
        if kind == "customRoleChecks":
            return _json(200, analyze_azure.check_custom_role(_json_body(body) or {}, state))
        if kind == "permissions":
            return _json(200, analyze_azure.effective_permissions(scope, principal, state))
        if kind == "roleAssignments":
            return _json(200, analyze_azure.role_assignments(scope, _q1(q, "$filter"), state))
        if kind == "pim":
            try:
                out = _pim_route(route, body, _q1(q, "$filter"), host, principal, method, state)
            except azure_pim.PimError as e:
                _pim_event(spec, e.status, principal, body)
                raise
            _pim_event(spec, out["status"], principal, body)
            return out
        return _json(200, analyze_azure.schedules(route[3], scope, _q1(q, "$filter"), state, principal))
    except analyze_azure.AzError as e:
        return _aerr(e)
    except azure_pim.PimError as e:
        return _aerr(e)


def _pim_route(route, body, flt, host, principal, method, state):
    """PIM requests / schedules over the space's ARM records (host.azure_arm()); see core/iam_engine/azure_pim.py."""
    scope, kind, name, verb = route[2], route[3], route[4], route[5]
    arm = host.azure_arm()
    if arm is None:
        return _json(501, {"error": {"code": "NotImplemented", "message": "No ARM record store is available for PIM schedules."}})
    if method == "PUT":
        b = _json_body(body)
        if b is None:
            return _json(400, {"error": {"code": "InvalidRequestContent", "message": "The request content is not valid JSON."}})
        st, doc = azure_pim.put_request(arm, scope, kind, name, b, principal)
        getattr(host, "persist", lambda: None)()
        return _json(st, doc)
    if method == "POST":                                    # .../cancel: requests are provisioned synchronously, so there is nothing pending
        azure_pim.get_record(arm, scope, kind, name)
        return _json(400, {"error": {"code": "RoleAssignmentRequestAlreadyCompleted", "message": "The request is already Provisioned and cannot be cancelled."}})
    if name:
        return _json(200, azure_pim.get_record(arm, scope, kind, name))
    who = None
    if flt:
        f_kind, w = analyze_azure.parse_filter(flt.replace("$filter=", ""))
        who = str((principal or {}).get("object_id") or "") if f_kind == "asTarget" else (w if f_kind == "principalId" else None)
    return _json(200, {"value": azure_pim.list_records(arm, scope, kind, who=who)})


def _identity_route(route, spec, host):
    arm = host.azure_arm() or {}
    if route[1] == "imds":
        st, doc = azure_identity.imds_token(arm, spec.get("query"), spec.get("headers") or {})
        return _json(st, doc)
    from urllib.parse import parse_qs
    form = {k: v[0] for k, v in parse_qs(bytes(spec.get("body") or b"").decode("utf-8", "replace"), keep_blank_values=True).items()}
    seg = [x for x in route[2].split("/") if x]
    tid = seg[0] if seg and re.fullmatch(r"[0-9a-fA-F-]{36}", seg[0]) else ""
    ident = azure_identity.find_identity(arm, client_id=form.get("client_id"))
    out = azure_identity.federated_exchange(arm, form, tid or (ident or {}).get("tenantId") or azure_identity.TENANT_FALLBACK, "v2.0" in seg)
    if out is None:
        return _json(400, {"error": "invalid_client", "error_description": f"AADSTS700016: Application with identifier '{form.get('client_id', '')}' was not found "
                                                                            "in the directory (federated credentials are supported for user-assigned managed identities)."})
    return _json(*out)


def _pim_event(spec, status, principal, body):
    """PIM requests are IAM changes: they land in the Activity Log feed with the caller (core/iam_events_core.py)."""
    if str(spec.get("method", "")).upper() not in ("PUT", "POST"):
        return
    try:
        try:
            from core import iam_events_core as ev
        except ImportError:   # pragma: no cover
            import iam_events_core as ev  # type: ignore
        who = str((principal or {}).get("object_id") or "")
        ev.record_azure(spec.get("method"), str(spec.get("path", "")).split("?", 1)[0], status,
                        {"x-cloudlearn-principal": who} if who and who != "root" else None, body)
    except Exception:
        pass
