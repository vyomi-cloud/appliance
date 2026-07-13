"""Console data-plane adapter (v2.9.0) — wires the SPA/console to the REAL v2.5.0–
2.8.0 data-plane cores, so the dashboard drives the same proven logic the native
SDK/relay path does (not the generic name-only catalog CRUD it used before).

Every function here is a thin (params) -> console-dict call into a core. Stores are
SHARED with `aws_core_adapter` (its module-level singletons) so cross-service flows
work in the console exactly as they do over the wire:
  - EventBridge PutEvents delivers into the SAME SQS queues the SQS view shows.
  - Service Bus topics live in the shared messaging store.
  - API Gateway AWS_PROXY integrations invoke functions from the SAME Lambda registry.

Services covered: lambda, apigateway, vpc, eventbridge (AWS) + servicebus, azuresql,
azurerbac (Azure). Pure core calls, no fastapi/boto3 — loads under Pyodide.
"""
from __future__ import annotations

import json
import types

from core import lambda_core, apigateway_core, vpc_core, eventbridge_core
from core import azure_servicebus_core, azure_sql_core, azure_iam_core
from . import aws_core_adapter as A   # share MSG / RDB / IAM singletons

# Compute/registry stores. Lambda + API Gateway share ONE namespace so an
# AWS_PROXY integration reaches the registered functions (the API-GW→Lambda synergy).
_COMPUTE = types.SimpleNamespace()
_VPC = types.SimpleNamespace()
MSG = A.MSG      # EventBridge + Service Bus + SQS all share this
SQLDB = A.RDB    # Azure SQL shares the SQL store (azuresql: keyspace)
IDN = A.IAM      # Azure RBAC shares the IAM store (_azure_* attrs)


def _lam_json(resp):
    try:
        return json.loads(resp.body.decode("utf-8")) if resp.body else {}
    except Exception:
        return {}


# ── Lambda ──────────────────────────────────────────────────────────────────
def _fn_row(fn):
    return {"name": fn["name"], "runtime": fn.get("runtime", "python3.12"),
            "handler": fn.get("handler", "index.handler"), "codeSize": len(fn.get("source", ""))}


def lambda_list(p=None):
    return {"ok": True, "functions": [_fn_row(f) for f in getattr(_COMPUTE, "_lambda_functions", {}).values()]}


def lambda_create(p):
    name = str(p.get("name") or "").strip()
    source = p.get("code") or p.get("source") or "def handler(event, context):\n    return {'ok': True, 'event': event}"
    body = {"FunctionName": name, "Runtime": p.get("runtime", "python3.12"),
            "Handler": p.get("handler", "index.handler"), "Code": {"Source": source}}
    r = lambda_core.dispatch(_COMPUTE, "POST", "/2015-03-31/functions", {}, {}, json.dumps(body).encode())
    if r.status >= 400:
        return {"ok": False, "code": "CreateFailed", **_lam_json(r)}
    return {"ok": True, **_fn_row(_COMPUTE._lambda_functions[name])}


def lambda_get(p):
    fns = getattr(_COMPUTE, "_lambda_functions", {})
    fn = fns.get(str(p.get("name") or ""))
    return {"ok": True, **_fn_row(fn)} if fn else {"ok": False, "code": "ResourceNotFound"}


def lambda_delete(p):
    r = lambda_core.dispatch(_COMPUTE, "DELETE", f"/2015-03-31/functions/{p.get('name','')}", {}, {}, b"")
    return {"ok": r.status < 400, "name": p.get("name")}


def lambda_invoke(p):
    name = str(p.get("name") or "")
    payload = p.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload) if payload.strip() else {}
        except Exception:
            payload = {}
    r = lambda_core.dispatch(_COMPUTE, "POST", f"/2015-03-31/functions/{name}/invocations",
                             {}, {}, json.dumps(payload or {}).encode())
    out = _lam_json(r)
    if r.headers.get("X-Amz-Function-Error"):
        return {"ok": True, "functionError": out.get("errorType"), "result": out}
    return {"ok": True, "statusCode": r.status, "result": out}


# ── API Gateway ─────────────────────────────────────────────────────────────
def apigw_list(p=None):
    apis = getattr(_COMPUTE, "_apigateway_apis", {})
    return {"ok": True, "apis": [{"id": a["id"], "name": a["name"],
                                  "routes": len(a["resources"]) - 1,
                                  "stages": list(a["deployments"].keys())} for a in apis.values()]}


def apigw_create(p):
    """Create an API and, if a lambdaTarget/mockBody is given, wire a working
    endpoint (resource + method + integration + deployment) in one console action."""
    name = str(p.get("name") or "").strip()
    api = _lam_json(apigateway_core.dispatch(_COMPUTE, "POST", "/restapis", {}, {}, json.dumps({"name": name}).encode()))
    api_id, root = api["id"], api["rootResourceId"]
    path_part = str(p.get("path") or "hello").strip("/")
    method = str(p.get("method") or "GET").upper()
    res = _lam_json(apigateway_core.dispatch(_COMPUTE, "POST", f"/restapis/{api_id}/resources/{root}",
                                             {}, {}, json.dumps({"pathPart": path_part}).encode()))
    apigateway_core.dispatch(_COMPUTE, "PUT", f"/restapis/{api_id}/resources/{res['id']}/methods/{method}",
                             {}, {}, json.dumps({"authorizationType": "NONE"}).encode())
    if p.get("lambdaTarget"):
        integ = {"type": "AWS_PROXY", "uri": f"arn:aws:lambda:us-east-1:0:function:{p['lambdaTarget']}/invocations"}
    else:
        integ = {"type": "MOCK", "mockStatus": 200, "mockBody": p.get("mockBody", "OK from API Gateway")}
    apigateway_core.dispatch(_COMPUTE, "PUT", f"/restapis/{api_id}/resources/{res['id']}/methods/{method}/integration",
                             {}, {}, json.dumps(integ).encode())
    apigateway_core.dispatch(_COMPUTE, "POST", f"/restapis/{api_id}/deployments",
                             {}, {}, json.dumps({"stageName": p.get("stage", "prod")}).encode())
    return {"ok": True, "id": api_id, "name": name,
            "endpoint": f"/{p.get('stage','prod')}/{path_part}", "method": method}


def apigw_delete(p):
    getattr(_COMPUTE, "_apigateway_apis", {}).pop(str(p.get("name") or p.get("id") or ""), None)
    return {"ok": True}


def apigw_invoke(p):
    api_id = str(p.get("id") or p.get("name") or "")
    r = apigateway_core.invoke(_COMPUTE, api_id, str(p.get("stage", "prod")),
                               str(p.get("method", "GET")).upper(), str(p.get("path", "/")),
                               headers={}, body=(p.get("body") or "").encode(), lambda_store=_COMPUTE)
    return {"ok": True, "statusCode": r.status,
            "body": r.body.decode("utf-8", "ignore"), "headers": dict(r.headers or {})}


# ── VPC (topology + reachability analyzer) ─────────────────────────────────
def _vpc_q(action, params):
    return vpc_core.dispatch(_VPC, {"Action": action, **params})


def vpc_list(p=None):
    m = getattr(_VPC, "_vpc_model", {"vpcs": {}, "subnets": {}, "sgs": {}})
    return {"ok": True,
            "vpcs": [{"id": v["id"], "cidr": v["cidr"]} for v in m.get("vpcs", {}).values()],
            "subnets": [{"id": s["id"], "vpcId": s["vpc_id"], "cidr": s["cidr"]} for s in m.get("subnets", {}).values()],
            "securityGroups": [{"id": g["id"], "vpcId": g["vpc_id"],
                                "ingressRules": len(g["ingress"])} for g in m.get("sgs", {}).values()]}


def vpc_create(p):
    import re
    body = _vpc_q("CreateVpc", {"CidrBlock": str(p.get("cidr") or "10.0.0.0/16")}).body
    vid = re.search(r"<vpcId>(.*?)</vpcId>", body)
    return {"ok": bool(vid), "id": vid.group(1) if vid else None, "cidr": p.get("cidr")}


def vpc_create_subnet(p):
    import re
    body = _vpc_q("CreateSubnet", {"VpcId": str(p.get("vpcId") or ""), "CidrBlock": str(p.get("cidr") or "")}).body
    sid = re.search(r"<subnetId>(.*?)</subnetId>", body)
    return {"ok": bool(sid), "id": sid.group(1) if sid else None}


def vpc_create_sg(p):
    import re
    body = _vpc_q("CreateSecurityGroup", {"VpcId": str(p.get("vpcId") or "")}).body
    gid = re.search(r"<groupId>(.*?)</groupId>", body)
    return {"ok": bool(gid), "id": gid.group(1) if gid else None}


def vpc_authorize(p):
    _vpc_q("AuthorizeSecurityGroupIngress", {
        "GroupId": str(p.get("sgId") or ""), "IpProtocol": str(p.get("protocol") or "tcp"),
        "FromPort": str(p.get("port") or 0), "ToPort": str(p.get("port") or 0),
        "CidrIp": p.get("cidr", ""), "SourceSecurityGroupId": p.get("sourceSg", "")})
    return {"ok": True}


def vpc_analyze(p):
    def _ep(prefix):
        sgs = p.get(prefix + "Sgs") or p.get(prefix + "SecurityGroupIds") or []
        if isinstance(sgs, str):
            sgs = [s for s in sgs.split(",") if s.strip()]
        return {"ip": str(p.get(prefix + "Ip") or ""), "security_group_ids": sgs}
    res = vpc_core.analyze_reachability(_VPC, _ep("source"), _ep("dest"),
                                        int(p.get("port") or 0), str(p.get("protocol") or "tcp"))
    return {"ok": True, **res}


# ── EventBridge (rules → SQS delivery) ─────────────────────────────────────
def _eb(action, body):
    return eventbridge_core.dispatch(MSG, "AWSEvents." + action, body)


def eb_list(p=None):
    rules = getattr(MSG, "event_rules", {})
    return {"ok": True, "rules": [{"name": r["name"], "pattern": r.get("pattern", {}),
                                   "targets": list(r["targets"].keys())} for r in rules.values()]}


def eb_create(p):
    name = str(p.get("name") or "").strip()
    pattern = p.get("pattern")
    if isinstance(pattern, str):
        try:
            pattern = json.loads(pattern)
        except Exception:
            pattern = {}
    _eb("PutRule", {"Name": name, "EventPattern": json.dumps(pattern or {})})
    if p.get("targetQueue"):
        q = MSG.get_queue(str(p["targetQueue"]))
        if q:
            _eb("PutTargets", {"Rule": name, "Targets": [{"Id": "t1", "Arn": q["queue_arn"]}]})
    return {"ok": True, "name": name}


def eb_delete(p):
    _eb("DeleteRule", {"Name": str(p.get("name") or "")})
    return {"ok": True}


def eb_put_event(p):
    detail = p.get("detail")
    if isinstance(detail, dict):
        detail = json.dumps(detail)
    r = _eb("PutEvents", {"Entries": [{"Source": str(p.get("source") or ""),
                                       "DetailType": str(p.get("detailType") or ""),
                                       "Detail": detail or "{}"}]})
    return {"ok": True, "eventId": (r.body.get("Entries") or [{}])[0].get("EventId")}


# ── Azure Service Bus (topics + subscriptions + send/receive) ──────────────
def _sb(method, path, body=b"", headers=None):
    return azure_servicebus_core.dispatch(MSG, method, path, {}, headers or {}, body if isinstance(body, bytes) else str(body).encode())


def sb_list(p=None):
    topics = [t for t in MSG.topics.values() if "subscriptions" in t and "topic_arn" not in t]
    return {"ok": True, "topics": [{"name": t["name"],
                                    "subscriptions": list(t.get("subscriptions", {}).keys())} for t in topics]}


def sb_create(p):
    _sb("PUT", f"/{p.get('name','')}")
    return {"ok": True, "name": p.get("name")}


def sb_create_sub(p):
    _sb("PUT", f"/{p.get('topic','')}/subscriptions/{p.get('name','')}")
    return {"ok": True}


def sb_delete(p):
    _sb("DELETE", f"/{p.get('name','')}")
    return {"ok": True}


def sb_send(p):
    r = _sb("POST", f"/{p.get('topic','')}/messages", str(p.get("message") or ""),
            {"content-type": "text/plain"})
    return {"ok": r.status < 400, "status": r.status}


def sb_receive(p):
    r = _sb("DELETE", f"/{p.get('topic','')}/subscriptions/{p.get('subscription','')}/messages/head")
    if r.status == 204:
        return {"ok": True, "empty": True}
    bp = json.loads(r.headers.get("BrokerProperties", "{}"))
    return {"ok": True, "message": r.body.decode("utf-8", "ignore"), "messageId": bp.get("MessageId")}


# ── Azure SQL (servers + databases + query) ─────────────────────────────────
def _sql(method, path, body=None):
    return azure_sql_core.dispatch(SQLDB, method, path, {}, {}, json.dumps(body or {}).encode() if body is not None else b"")


def sql_list(p=None):
    srv = getattr(SQLDB, "_azure_sql_servers", {})
    return {"ok": True, "servers": [{"name": s["name"], "databases": s["databases"]} for s in srv.values()]}


def sql_create_server(p):
    _sql("PUT", f"/servers/{p.get('name','')}")
    return {"ok": True, "name": p.get("name")}


def sql_create_db(p):
    _sql("PUT", f"/servers/{p.get('server','')}/databases/{p.get('name','')}")
    return {"ok": True}


def sql_delete_server(p):
    srv = getattr(SQLDB, "_azure_sql_servers", {})
    srv.pop(str(p.get("name") or ""), None)
    return {"ok": True}


def sql_query(p):
    r = _sql("POST", f"/servers/{p.get('server','')}/databases/{p.get('database','')}/query",
             {"sql": str(p.get("sql") or ""), "params": p.get("params")})
    body = json.loads(r.body.decode("utf-8", "ignore") or "{}")
    if r.status >= 400:
        return {"ok": False, "error": body.get("error", {}).get("message", "query failed")}
    return {"ok": True, "columns": body.get("columns", []), "rows": body.get("rows", []),
            "rowCount": body.get("rowCount", 0)}


# ── Azure RBAC (role assignments + checkAccess) ────────────────────────────
_AUTH = "/providers/Microsoft.Authorization"


def _rbac(method, path, body=None):
    return azure_iam_core.dispatch(IDN, method, path, {}, {}, json.dumps(body or {}).encode())


def rbac_list(p=None):
    return {"ok": True, "assignments": [{"name": a["name"], "principalId": a["principalId"],
                                         "role": a["roleDefinition"], "scope": a["scope"]}
                                        for a in getattr(IDN, "_azure_role_assignments", {}).values()]}


def rbac_create(p):
    import uuid
    name = str(p.get("name") or uuid.uuid4().hex[:8])
    _rbac("PUT", f"{_AUTH}/roleAssignments/{name}", {"properties": {
        "principalId": str(p.get("principalId") or ""), "roleName": str(p.get("role") or "Reader"),
        "scope": str(p.get("scope") or "/")}})
    return {"ok": True, "name": name}


def rbac_delete(p):
    _rbac("DELETE", f"{_AUTH}/roleAssignments/{p.get('name','')}")
    return {"ok": True}


def rbac_check(p):
    r = _rbac("POST", f"{_AUTH}/checkAccess", {"principalId": str(p.get("principalId") or ""),
                                               "action": str(p.get("action") or ""),
                                               "scope": str(p.get("scope") or "/")})
    body = json.loads(r.body.decode("utf-8", "ignore") or "{}")
    v = (body.get("value") or [{}])[0]
    return {"ok": True, "decision": v.get("accessDecision"), "roles": v.get("roles", [])}
