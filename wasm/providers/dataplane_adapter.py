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
from core import sesv2_core
from core import elbv2_core
from core import ssm_core
from core import azure_servicebus_core, azure_sql_core, azure_iam_core
from core import apigatewayv2_core
from core import stepfunctions_core
from . import aws_core_adapter as A   # share MSG / RDB / IAM singletons

# Compute/registry stores. Lambda + API Gateway share ONE namespace so an
# AWS_PROXY integration reaches the registered functions (the API-GW→Lambda synergy).
from core import nano_registry as _R
_COMPUTE = _R.get()["compute"]
_VPC = _R.get()["vpc_net"]
MSG = A.MSG      # EventBridge + Service Bus + SQS all share this
SQLDB = A.RDB    # Azure SQL shares the SQL store (azuresql: keyspace)
IDN = A.IAM      # Azure RBAC shares the IAM store (_azure_* attrs)


def _lam_json(resp):
    try:
        return json.loads(resp.body.decode("utf-8")) if resp.body else {}
    except Exception:
        return {}


# ── Lambda ──────────────────────────────────────────────────────────────────
def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _fn_row(fn):
    # Legacy keys (name/codeSize) stay for existing callers; the AWS-shaped keys are
    # what the console grid columns read (function_name, memory_size, timeout…).
    return {"name": fn["name"], "runtime": fn.get("runtime", "python3.12"),
            "handler": fn.get("handler", "index.handler"), "codeSize": len(fn.get("source", "")),
            "function_name": fn["name"], "function_arn": fn.get("arn", ""),
            "memory_size": fn.get("memory_size", 128), "timeout": fn.get("timeout", 3),
            "state": "Active", "package_type": "Zip",
            "created": fn.get("created") or fn.get("last_modified") or "",
            "last_modified": fn.get("last_modified") or fn.get("created") or ""}


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
    fn = _COMPUTE._lambda_functions[name]
    fn["memory_size"] = int(p.get("memory_size") or p.get("memory") or 128)
    fn["timeout"] = int(p.get("timeout") or 3)
    fn["created"] = fn["last_modified"] = _now()
    return {"ok": True, **_fn_row(fn)}


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
    return {"ok": True, "apis": [_api_row(a) for a in apis.values()]}


def _api_row(a):
    return {"id": a["id"], "name": a["name"], "routes": len(a["resources"]) - 1,
            "stages": list(a["deployments"].keys()),
            "rest_api_id": a["id"], "description": a.get("description", ""),
            "endpoint_type": "REGIONAL", "created": a.get("created", ""), "status": "available"}


def _api_find(key):
    apis = getattr(_COMPUTE, "_apigateway_apis", {})
    return apis.get(key) or next((a for a in apis.values() if a["name"] == key), None)


def apigw_get(p):
    a = _api_find(str(p.get("name") or p.get("id") or ""))
    return {"ok": True, **_api_row(a)} if a else {"ok": False, "code": "NotFoundException"}


def apigw_resources(p):
    """GET /api/apigateway/apis/{id}/resources — console API detail > Resources tab."""
    a = _api_find(str(p.get("id") or ""))
    if not a:
        return {"ok": False, "code": "NotFoundException"}
    rows = [{"resource_id": r["id"], "path": r.get("path", "/"), "path_part": r.get("pathPart", ""),
             "parent_id": r.get("parentId") or "",
             "resource_methods": {m: {} for m in r.get("methods", {})}}
            for r in a["resources"].values() if r.get("parentId")]
    return {"ok": True, "api_id": a["id"], "resources": rows, "count": len(rows)}


def apigw_stages(p):
    """GET /api/apigateway/apis/{id}/stages — console API detail > Stages tab."""
    a = _api_find(str(p.get("id") or ""))
    if not a:
        return {"ok": False, "code": "NotFoundException"}
    rows = [{"stage_name": n, "deployment_id": d.get("deploymentId", ""), "description": "",
             "invoke_url": f"https://{a['id']}.execute-api.us-east-1.amazonaws.com/{n}",
             "created": a.get("created", "")}
            for n, d in a["deployments"].items()]
    return {"ok": True, "stages": rows, "count": len(rows)}


def apigw_create(p):
    """Create an API and, if a lambdaTarget/mockBody is given, wire a working
    endpoint (resource + method + integration + deployment) in one console action."""
    name = str(p.get("name") or "").strip()
    api = _lam_json(apigateway_core.dispatch(_COMPUTE, "POST", "/restapis", {}, {}, json.dumps({"name": name}).encode()))
    api_id, root = api["id"], api["rootResourceId"]
    _COMPUTE._apigateway_apis[api_id]["created"] = _now()
    _COMPUTE._apigateway_apis[api_id]["description"] = str(p.get("description") or "")
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
    a = _api_find(str(p.get("name") or p.get("id") or ""))
    if a:
        getattr(_COMPUTE, "_apigateway_apis", {}).pop(a["id"], None)
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
            "vpcs": [_vpc_row(v, m) for v in m.get("vpcs", {}).values()],
            "subnets": [{"id": s["id"], "vpcId": s["vpc_id"], "cidr": s["cidr"]} for s in m.get("subnets", {}).values()],
            "securityGroups": [{"id": g["id"], "vpcId": g["vpc_id"],
                                "ingressRules": len(g["ingress"])} for g in m.get("sgs", {}).values()]}


def _vpc_row(v, m):
    return {"id": v["id"], "cidr": v["cidr"],
            "vpc_id": v["id"], "name": v.get("name") or v["id"], "cidr_block": v["cidr"],
            "state": "available", "tenancy": "default", "created": v.get("created", ""),
            "dhcp_options_id": "dopt-" + v["id"].split("-", 1)[-1][:8],
            "main_route_table_id": next((r["id"] for r in m.get("route_tables", {}).values()
                                         if r.get("vpc_id") == v["id"] and r.get("main")), ""),
            "default_security_group_id": next((g["id"] for g in m.get("sgs", {}).values()
                                               if g.get("vpc_id") == v["id"] and g.get("name") == "default"), ""),
            "internet_gateway_id": v.get("igw") or "",
            "subnet_count": sum(1 for s in m.get("subnets", {}).values() if s.get("vpc_id") == v["id"])}


def vpc_get(p):
    m = getattr(_VPC, "_vpc_model", {"vpcs": {}, "subnets": {}})
    key = str(p.get("name") or p.get("id") or "")
    v = m.get("vpcs", {}).get(key) or next((x for x in m.get("vpcs", {}).values() if x.get("name") == key), None)
    return {"ok": True, **_vpc_row(v, m)} if v else {"ok": False, "code": "InvalidVpcID.NotFound"}


def vpc_list_sgs(p=None):
    """Security-groups list for the EC2/VPC console SG page (GET /api/vpc/security-groups).
    Shape matches the console's snake_case `security_groups` array + id/name/description/vpc_id columns."""
    m = getattr(_VPC, "_vpc_model", {"sgs": {}})
    return {"ok": True, "security_groups": [
        {"id": g["id"], "name": g.get("name", ""), "description": g.get("description", ""),
         "vpc_id": g.get("vpc_id", ""), "ingress_rules": len(g.get("ingress", []))}
        for g in m.get("sgs", {}).values()]}


def vpc_list_subnets(p=None):
    """GET /api/vpc/subnets — console VPC > Subnets tab."""
    m = getattr(_VPC, "_vpc_model", {"subnets": {}})
    rows = [{"id": s["id"], "subnet_id": s["id"], "name": s.get("name") or s["id"],
             "vpc_id": s["vpc_id"], "cidr_block": s["cidr"],
             "availability_zone": s.get("az") or "us-east-1a", "state": "available"}
            for s in m.get("subnets", {}).values()]
    return {"ok": True, "subnets": rows, "count": len(rows)}


def vpc_list_route_tables(p=None):
    """GET /api/vpc/route-tables — console VPC > Route tables tab."""
    m = getattr(_VPC, "_vpc_model", {"route_tables": {}})
    rows = [{"id": r["id"], "route_table_id": r["id"], "name": r.get("name") or r["id"],
             "vpc_id": r["vpc_id"], "is_main": bool(r.get("main")),
             "routes": [{"destination": x.get("dest"), "target": x.get("target")} for x in r.get("routes", [])],
             "associations": [{"subnet_id": sid} for sid in r.get("subnets", [])]}
            for r in m.get("route_tables", {}).values()]
    return {"ok": True, "route_tables": rows, "count": len(rows)}


def vpc_list_igws(p=None):
    """GET /api/vpc/internet-gateways — console VPC > Internet gateways tab."""
    m = getattr(_VPC, "_vpc_model", {"igws": {}})
    rows = [{"id": g["id"], "internet_gateway_id": g["id"], "name": g.get("name") or g["id"],
             "attachments": ([{"vpc_id": g["vpc_id"], "state": "available"}] if g.get("vpc_id") else []),
             "state": "attached" if g.get("vpc_id") else "detached"}
            for g in m.get("igws", {}).values()]
    return {"ok": True, "internet_gateways": rows, "count": len(rows)}


def vpc_create(p):
    import re
    cidr = str(p.get("cidr_block") or p.get("cidr") or "10.0.0.0/16")
    body = _vpc_q("CreateVpc", {"CidrBlock": cidr}).body
    vid = re.search(r"<vpcId>(.*?)</vpcId>", body)
    if vid:
        rec = _VPC._vpc_model["vpcs"][vid.group(1)]
        rec["name"] = str(p.get("name") or "")
        rec["created"] = _now()
        # Every real VPC is created with a default security group.
        sg = re.search(r"<groupId>(.*?)</groupId>", _vpc_q("CreateSecurityGroup", {"VpcId": vid.group(1)}).body)
        if sg:
            _VPC._vpc_model["sgs"][sg.group(1)].update(name="default", description="default VPC security group")
    return {"ok": bool(vid), "id": vid.group(1) if vid else None, "cidr": cidr}


def vpc_create_subnet(p):
    import re
    body = _vpc_q("CreateSubnet", {"VpcId": str(p.get("vpcId") or ""), "CidrBlock": str(p.get("cidr") or "")}).body
    sid = re.search(r"<subnetId>(.*?)</subnetId>", body)
    return {"ok": bool(sid), "id": sid.group(1) if sid else None}


def vpc_create_sg(p):
    import re
    body = _vpc_q("CreateSecurityGroup", {"VpcId": str(p.get("vpcId") or "")}).body
    gid = re.search(r"<groupId>(.*?)</groupId>", body)
    if gid:
        _VPC._vpc_model["sgs"][gid.group(1)].update(
            name=str(p.get("name") or p.get("groupName") or gid.group(1)), description=str(p.get("description") or ""))
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


# ── AWS console "extras" — EC2/VPC sub-resources (volumes, snapshots, launch
# templates, spot requests, endpoint services, …). ONE generic in-memory CRUD
# keyed by the console's fullKey ("ec2/volumes"), returning the {value:[...]}
# envelope the console expects. Console-only (not native-wire); session-scoped
# (reload-persistence is a follow-up — would live in nano_registry).
# Held in the persisted registry ("extras": public dicts `items` / `cfg`) so the
# rows survive a page reload like every other store.
_XNS = _R.get()["extras"]
_EXTRAS = _XNS.items
_EXTRAS_CFG = _XNS.cfg


def _extras_vals(p):
    return {k: v for k, v in (p or {}).items() if k not in ("key", "name")}


def extras_list(p):
    return {"ok": True, "value": list(_EXTRAS.get(p.get("key", ""), {}).values())}


def extras_create(p):
    key = p.get("key", "")
    vals = _extras_vals(p)
    leaf = key.split("/")[-1].rstrip("s") or "resource"
    name = str(p.get("name") or vals.get("Name") or "")
    if not name:
        n = len(_EXTRAS.get(key, {})) + 1
        while f"{leaf}-{n:08x}" in _EXTRAS.get(key, {}):
            n += 1
        name = f"{leaf}-{n:08x}"
    item = {"name": name, "id": vals.get("id") or name, "state": vals.get("state", "available"), **vals}
    item["name"] = name
    item.setdefault("created", _now())
    if key.endswith("eventbridge/rules"):
        item.setdefault("target_count", 0)   # a new rule has no targets yet
    _EXTRAS.setdefault(key, {})[name] = item
    return {"ok": True, **item}


def extras_delete(p):
    key, name = p.get("key", ""), p.get("name", "")
    existed = _EXTRAS.get(key, {}).pop(name, None) is not None
    return {"ok": existed, "name": name, "code": None if existed else "NotFound"}


def extras_config_get(p):
    return {"ok": True, "value": _EXTRAS_CFG.get(p.get("key", ""), {})}


def extras_config_put(p):
    _EXTRAS_CFG[p.get("key", "")] = _extras_vals(p)
    return {"ok": True}


# ── Amazon SES v2 (core/sesv2_core.py) — shared store with the native wire ──
def ses_console(p):
    from core import nano_registry
    store = nano_registry.get()["sesv2"]
    status, out = sesv2_core.console_dispatch(store, str(p.get("method") or "GET"), str(p.get("path") or ""),
                                              dict(p.get("query") or {}), dict(p.get("body") or {}))
    if status >= 400:
        return {"ok": False, "code": out.get("code", "Error"), "message": out.get("error", ""), "status": status}
    store.persist()
    return out
# ── API Gateway V2 (HTTP/WebSocket APIs) — core/apigatewayv2_core.py ────────
# Store = the shared registry's `apigwv2`, the SAME one the native /v2 relay wire
# reads/writes, so console-created APIs are visible to the CLI/SDK and vice-versa.
def _apigwv2():
    from core import nano_registry
    return nano_registry.get()["apigwv2"]


def _v2(method, path, body=None):
    r = apigatewayv2_core.dispatch(_apigwv2(), method, path, {}, {},
                                   json.dumps(body).encode() if body is not None else b"")
    return r.status, _lam_json(r)


def apigwv2_list(p=None):
    apis = sorted((apigatewayv2_core.console_view(a) for a in _apigwv2().apis.values()),
                  key=lambda a: (a["created"], a["name"]))
    return {"ok": True, "apis": apis, "count": len(apis)}


def apigwv2_create(p):
    name = str(p.get("name") or "").strip()
    if not name:
        return {"ok": False, "code": "BadRequestException", "message": "name is required"}
    body = {"name": name, "protocolType": str(p.get("protocol_type") or p.get("protocolType") or "HTTP").upper()}
    if p.get("description"):
        body["description"] = p["description"]
    if body["protocolType"] == "WEBSOCKET":
        body["routeSelectionExpression"] = p.get("route_selection_expression") or "$request.body.action"
    elif p.get("target"):
        body["target"] = p["target"]
    st, out = _v2("POST", "/v2/apis", body)
    if st >= 300:
        return {"ok": False, "code": "BadRequestException", "message": out.get("message", "")}
    return {"ok": True, **apigatewayv2_core.console_view(_apigwv2().apis[out["apiId"]])}


def apigwv2_get(p):
    api = _apigwv2().apis.get(str(p.get("id") or p.get("name") or ""))
    if not api:
        return {"ok": False, "code": "NotFoundException"}
    return {"ok": True, **apigatewayv2_core.console_view(api)}


def apigwv2_delete(p):
    st, out = _v2("DELETE", f"/v2/apis/{p.get('id') or p.get('name') or ''}")
    return {"ok": st < 300, "message": out.get("message", "")}


def apigwv2_patch(p):
    api = _apigwv2().apis.get(str(p.get("id") or p.get("name") or ""))
    if not api:
        return {"ok": False, "code": "NotFoundException"}
    if isinstance(p.get("tags"), dict):
        api["tags"] = {str(k): str(v) for k, v in p["tags"].items()}
    if p.get("description") is not None:
        api["description"] = p["description"]
    return {"ok": True, **apigatewayv2_core.console_view(api)}


def apigwv2_children(p):
    """GET /api/apigatewayv2/apis/{id}/{routes|integrations|stages|deployments|authorizers|models}."""
    st, out = _v2("GET", f"/v2/apis/{p.get('id')}/{p.get('kind')}")
    return {"ok": st < 300, **out}
# ── CloudWatch Logs (core/logs_core.py) ─────────────────────────────────────
def logs_console(p):
    """Console REST for CloudWatch Logs: the SAME logs_core.console_dispatch the
    offline appliance serves, on the shared registry store (so the console and an
    SDK/CLI on the relay see one set of log groups)."""
    from core import logs_core, nano_registry
    status, body = logs_core.console_dispatch(
        nano_registry.get()["logs"], p.get("method") or "GET", p.get("path") or "",
        p.get("query") or {}, p.get("body") or {})
    return {"ok": status < 400, "__http": {"status": status, "headers": {}, "body": body}}
# ── ELBv2 (core/elbv2_core.py) — shared store with the native wire ──────────
def _elb_store():
    from core import nano_registry
    return nano_registry.get()["elbv2"]


def _elb_call(fn, *a):
    try:
        return fn(_elb_store(), *a)
    except elbv2_core.Elbv2Error as e:
        return {"ok": False, "code": e.code, "message": e.message}


def elb_list(p=None):
    return _elb_call(elbv2_core.console_list)


def elb_create(p):
    return _elb_call(elbv2_core.console_create, dict(p or {}))


def elb_get(p):
    return _elb_call(elbv2_core.console_get, str(p.get("name") or ""))


def elb_delete(p):
    return _elb_call(elbv2_core.console_delete, str(p.get("name") or ""))


def elb_tags(p):
    return _elb_call(elbv2_core.console_set_tags, str(p.get("name") or ""), p.get("tags") or {})


def elb_children(p):
    return _elb_call(elbv2_core.console_children, str(p.get("kind") or ""))


def elb_child_create(p):
    return _elb_call(elbv2_core.console_child_create, str(p.get("kind") or ""), dict(p))


def elb_child_delete(p):
    return _elb_call(elbv2_core.console_child_delete, str(p.get("kind") or ""), str(p.get("name") or ""))
# ── Systems Manager Parameter Store — core/ssm_core.py ─────────────────────
# Store = the shared registry's `ssm`, the SAME one the native AmazonSSM relay wire
# reads/writes, so console-created parameters are visible to the CLI/SDK and vice-versa.
def _ssm():
    from core import nano_registry
    return nano_registry.get()["ssm"]


def _ssm_call(op, body):
    r = ssm_core.dispatch(_ssm(), "AmazonSSM." + op, body)
    return r.status, r.body


def ssm_list(p=None):
    items = [ssm_core.console_view(n, r) for n, r in sorted(_ssm().parameters.items())]
    return {"ok": True, "items": items, "parameters": items, "count": len(items)}


def ssm_put(p, overwrite):
    name = str(p.get("name") or "").strip()
    cur = _ssm().parameters.get(name)
    if overwrite and cur:
        v = ssm_core.console_view(name, cur)
        p = {"name": name, "value": p.get("value", v["value"]), "type": v["type"],
             "description": p.get("description", v["description"]), "tier": v["tier"]}
    body = {"Name": name, "Value": str(p.get("value") if p.get("value") is not None else ""),
            "Type": p.get("type") or "String", "Overwrite": bool(overwrite)}
    if p.get("description"):
        body["Description"] = p["description"]
    if p.get("tier"):
        body["Tier"] = p["tier"]
    st, out = _ssm_call("PutParameter", body)
    if st >= 300:
        return {"ok": False, "code": out.get("__type", "ValidationException"), "message": out.get("message", "")}
    return {"ok": True, **ssm_core.console_view(name, _ssm().parameters[name])}


def ssm_get(p):
    name = str(p.get("name") or p.get("id") or "")
    rec = _ssm().parameters.get(name)
    if not rec:
        return {"ok": False, "code": "ParameterNotFound", "message": f"Parameter {name} not found."}
    return {"ok": True, **ssm_core.console_view(name, rec)}


def ssm_tag(p):
    name = str(p.get("name") or p.get("id") or "")
    rec = _ssm().parameters.get(name)
    if not rec:
        return {"ok": False, "code": "ParameterNotFound"}
    if isinstance(p.get("tags"), dict):
        rec["tags"] = {str(k): str(v) for k, v in p["tags"].items()}
    return {"ok": True, **ssm_core.console_view(name, rec)}


def ssm_delete(p):
    name = str(p.get("name") or p.get("id") or "")
    st, out = _ssm_call("DeleteParameter", {"Name": name})
    return {"ok": st < 300, "message": out.get("message", "")}


def ssm_history(p):
    name = str(p.get("name") or p.get("id") or "")
    rec = _ssm().parameters.get(name)
    if not rec:
        return {"ok": False, "code": "ParameterNotFound"}
    return {"ok": True, "history": ssm_core.console_history(name, rec)}


# ── Step Functions (state machines + executions) — core/stepfunctions_core.py ───
# Store = the shared registry's `sfn`, the SAME one the native relay wire reads/writes,
# so console-created state machines are visible to the CLI/SDK and vice-versa.
def _sfn():
    from core import nano_registry
    return nano_registry.get()["sfn"]


def _sfn_call(op, **body):
    r = stepfunctions_core.dispatch(_sfn(), "AWSStepFunctions." + op, body, lambda_store=_COMPUTE)
    return r.status, r.body


def _sfn_view(name):
    return stepfunctions_core.machine_view(_sfn().machines[name], _sfn())


def _sfn_err(body):
    return {"ok": False, "code": body.get("__type", "Error"), "message": body.get("message", "")}


def sfn_list(p=None):
    ms = sorted((stepfunctions_core.machine_view(m, _sfn()) for m in _sfn().machines.values()),
                key=lambda m: (m["created"], m["name"]))
    return {"ok": True, "items": ms, "count": len(ms)}


def sfn_create(p):
    name = str(p.get("name") or "").strip()
    st, out = _sfn_call("CreateStateMachine", name=name,
                        definition=p.get("definition") or stepfunctions_core.default_definition(),
                        roleArn=p.get("role_arn") or stepfunctions_core.default_role_arn(),
                        type=str(p.get("type") or "STANDARD").upper())
    if st >= 300:
        return _sfn_err(out)
    return {"ok": True, **_sfn_view(name)}


def sfn_get(p):
    name = str(p.get("id") or p.get("name") or "")
    return {"ok": True, **_sfn_view(name)} if name in _sfn().machines else {"ok": False, "code": "StateMachineDoesNotExist"}


def sfn_patch(p):
    name = str(p.get("id") or p.get("name") or "")
    sm = _sfn().machines.get(name)
    if not sm:
        return {"ok": False, "code": "StateMachineDoesNotExist"}
    upd = {k: p[k] for k in ("definition", "roleArn") if p.get(k)}
    if upd:
        _sfn_call("UpdateStateMachine", stateMachineArn=sm["stateMachineArn"], **upd)
    if isinstance(p.get("tags"), dict):
        _sfn().tags[sm["stateMachineArn"]] = {str(k): str(v) for k, v in p["tags"].items()}
    return {"ok": True, **_sfn_view(name)}


def sfn_delete(p):
    name = str(p.get("id") or p.get("name") or "")
    sm = _sfn().machines.get(name)
    if not sm:
        return {"ok": False, "code": "StateMachineDoesNotExist"}
    st, out = _sfn_call("DeleteStateMachine", stateMachineArn=sm["stateMachineArn"])
    return {"ok": st < 300, "message": out.get("message", "")}


def sfn_start(p):
    name = str(p.get("id") or p.get("name") or "")
    sm = _sfn().machines.get(name)
    if not sm:
        return {"ok": False, "code": "StateMachineDoesNotExist"}
    st, out = _sfn_call("StartExecution", stateMachineArn=sm["stateMachineArn"], input=p.get("input") or "{}")
    if st >= 300:
        return _sfn_err(out)
    return {"ok": True, **stepfunctions_core.execution_view(_sfn().executions[out["executionArn"]])}


def sfn_children(p):
    """GET /api/stepfunctions/machines/{id}/{executions|versions|aliases}."""
    sm = _sfn().machines.get(str(p.get("id") or ""))
    if not sm:
        return {"ok": False, "code": "StateMachineDoesNotExist"}
    return {"ok": True, **stepfunctions_core.children(_sfn(), sm, p.get("kind"))}
