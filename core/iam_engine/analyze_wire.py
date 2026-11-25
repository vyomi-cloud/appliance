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

from . import access_analyzer, analyze_azure, analyze_gcp, routing

_AUTHZ = re.compile(r"^(?P<scope>.*?)/providers/Microsoft\.Authorization/(?P<res>[A-Za-z]+)/?$", re.I)
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
    m = _GCP_TS.match(p)
    if m and method == "POST":
        return ("gcp", "troubleshoot", m.group(1))
    m = _GCP_AN.match(p)
    if m and method == "GET":
        return ("gcp", "analyze", m.group(1))
    m = _AUTHZ.match(p)
    if m:
        res, scope = m.group("res").lower(), m.group("scope") or "/"
        q = _qd(query)
        if res == "checkaccess" and method == "POST":
            b = _json_body(body)
            if b is not None and any(str(k).lower() in ("subject", "resource") for k in b) and any(str(k).lower() == "actions" for k in b):
                return ("azure", "checkAccess", scope)
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
        if kind == "permissions":
            return _json(200, analyze_azure.effective_permissions(scope, principal, state))
        if kind == "roleAssignments":
            return _json(200, analyze_azure.role_assignments(scope, _q1(q, "$filter"), state))
        return _json(200, analyze_azure.schedules(route[3], scope, _q1(q, "$filter"), state))
    except analyze_azure.AzError as e:
        return _aerr(e)
