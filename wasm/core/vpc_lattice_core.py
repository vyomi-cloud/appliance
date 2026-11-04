# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Amazon VPC Lattice control plane (SigV4 signing name `vpc-lattice`, rest-json) — substrate-independent.

Service networks, services, listeners + rules, target groups (+ targets), resource gateways, resource configurations,
service-network VPC / service / resource associations, domain verifications, access-log subscriptions, auth policies,
resource policies and tags, with the real REST shapes (`/servicenetworks`, `/services/{id}/listeners/{id}/rules`,
`/targetgroups/{id}/registertargets`, `/authpolicy/{id}`, `/tags/{arn}`, ...), id/ARN formats and error codes.
Cross-resource checks are real: VPCs / subnets / security groups / instances are validated against the simulator's own
EC2 model (state is kept inside the same model so it persists with it), a VPC can sit in only ONE service network,
target groups / gateways / networks that are still referenced cannot be deleted, rule priorities and listener ports
are unique, the default rule cannot be removed.
Pure Python (no fastapi/boto3) — loads under Pyodide.

Data plane: core/vpc_lattice_dataplane.py EVALUATES requests (simulator verb POST /vyomi/invoke) - DNS-per-VPC
scoping, association SGs, listeners, auth policies, rule priority/match, weighted forwarding, derived target health.
Honest limits: no HTTP bytes are proxied (the evaluator answers where a request would go), target health is derived
from instance state + security groups rather than probed, and a domain verification stays PENDING (no DNS TXT check).
"""
from __future__ import annotations

import ipaddress
import json
import re
import secrets
import urllib.parse
import uuid
from datetime import datetime, timezone

_ACCOUNT = "123456789012"
_DEFAULT_REGION = "us-east-1"
_NAME_RE = re.compile(r"^(?!snsw-)(?!-)(?![a-z0-9-]*--)(?!.*-$)[a-z0-9-]{3,63}$")
_AUTH = ("NONE", "AWS_IAM")


class _Err(Exception):
    def __init__(self, code, message, status):
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _rid(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(9)[:17]}"


def _region(headers) -> str:
    a = (headers or {}).get("authorization") or (headers or {}).get("Authorization") or ""
    m = re.search(r"Credential=[^/]*/[^/]*/([a-z0-9-]+)/", a)
    return m.group(1) if m else _DEFAULT_REGION


def _arn(region, kind, rid):
    return f"arn:aws:vpc-lattice:{region}:{_ACCOUNT}:{kind}/{rid}"


_KINDS = {"sn": ("servicenetworks", "servicenetwork"), "svc": ("services", "service"), "tg": ("targetgroups", "targetgroup"),
          "rgw": ("resourcegateways", "resourcegateway"), "rcfg": ("resourceconfigurations", "resourceconfiguration")}


def _vm(store) -> dict:
    from core import vpc_core
    return vpc_core._model(store)


def _st(store) -> dict:
    m = _vm(store)
    L = m.setdefault("lattice", {})
    for k in ("sn", "svc", "listener", "rule", "tg", "rgw", "rcfg", "snva", "snsa", "snra", "dv", "als", "authpol", "respol", "tags"):
        L.setdefault(k, {})
    return {**L, "_m": m, "_L": L}


def _validate_name(name, maxlen=63, what="name"):
    n = str(name or "")
    if not n or len(n) > maxlen or not _NAME_RE.match(n) or len(n) < 3:
        raise _Err("ValidationException", f"Invalid {what} '{n}': 3-{maxlen} lowercase letters, digits and hyphens; cannot start or end with a hyphen, contain '--' or start with 'snsw-'.", 400)
    return n


def _auth_type(v, default="NONE"):
    v = v or default
    if v not in _AUTH:
        raise _Err("ValidationException", f"authType must be one of {list(_AUTH)}.", 400)
    return v


def _tags_in(body):
    t = body.get("tags") or {}
    if not isinstance(t, dict) or len(t) > 50:
        raise _Err("ValidationException", "tags must be a map of at most 50 entries.", 400)
    return {str(k): str(v) for k, v in t.items()}


def _get(st, coll, ident, what, accept_arn=True):
    ident = str(ident or "")
    if accept_arn and ident.startswith("arn:"):
        ident = ident.rsplit("/", 1)[-1]
    o = st[coll].get(ident)
    if o is None:
        raise _Err("ResourceNotFoundException", f"{what} {ident} not found.", 404)
    return o


def _dup_name(st, coll, name, what):
    if any(o["name"] == name for o in st[coll].values()):
        raise _Err("ConflictException", f"A {what} named '{name}' already exists.", 409)


def _page(items, query, key="items"):
    q = query or {}
    try:
        mx = int(q.get("maxResults") or 1000)
    except (TypeError, ValueError):
        mx = 1000
    if not 1 <= mx <= 1000:
        raise _Err("ValidationException", "maxResults must be between 1 and 1000.", 400)
    start = 0
    if q.get("nextToken"):
        try:
            start = int(q["nextToken"])
        except ValueError:
            raise _Err("ValidationException", "Invalid nextToken.", 400)
    out = {key: items[start:start + mx]}
    if start + mx < len(items):
        out["nextToken"] = str(start + mx)
    return 200, out


def _q1(query, name):
    v = (query or {}).get(name)
    if isinstance(v, list):
        v = v[0] if v else None
    return v


def _resource_tags(st, arn):
    return st["_L"]["tags"].setdefault(arn, {})


def _drop_tags(st, arn):
    st["_L"]["tags"].pop(arn, None)
    st["_L"]["authpol"].pop(arn, None)
    st["_L"]["respol"].pop(arn, None)


# ── service networks ─────────────────────────────────────────────────────────────────
def _sn_assoc_counts(st, sid):
    return (sum(1 for a in st["snva"].values() if a["serviceNetworkId"] == sid),
            sum(1 for a in st["snsa"].values() if a["serviceNetworkId"] == sid),
            sum(1 for a in st["snra"].values() if a["serviceNetworkId"] == sid))


def _sn_view(st, o, summary=False):
    v, s, r = _sn_assoc_counts(st, o["id"])
    base = {"id": o["id"], "arn": o["arn"], "name": o["name"], "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    if summary:
        return {**base, "numberOfAssociatedVPCs": v, "numberOfAssociatedServices": s, "numberOfAssociatedResourceConfigurations": r}
    return {**base, "authType": o["authType"], "sharingConfig": o["sharingConfig"],
            "numberOfAssociatedVPCs": v, "numberOfAssociatedServices": s, "numberOfAssociatedResourceConfigurations": r}


def _create_service_network(st, g, body, query, region):
    name = _validate_name(body.get("name"), 63)
    _dup_name(st, "sn", name, "service network")
    rid = _rid("sn")
    sc = body.get("sharingConfig") or {"enabled": False}
    o = {"id": rid, "arn": _arn(region, "servicenetwork", rid), "name": name, "authType": _auth_type(body.get("authType")),
         "sharingConfig": {"enabled": bool(sc.get("enabled"))}, "createdAt": _now(), "lastUpdatedAt": _now()}
    st["sn"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 201, {k: o[k] for k in ("id", "arn", "name", "authType", "sharingConfig")}


def _update_service_network(st, g, body, query, region):
    o = _get(st, "sn", g[0], "Service network")
    o["authType"] = _auth_type(body.get("authType"))
    o["lastUpdatedAt"] = _now()
    return 200, {"id": o["id"], "arn": o["arn"], "name": o["name"], "authType": o["authType"]}


def _delete_service_network(st, g, body, query, region):
    o = _get(st, "sn", g[0], "Service network")
    if any(_sn_assoc_counts(st, o["id"])):
        raise _Err("ConflictException", f"Service network {o['id']} still has associations; delete them first.", 409)
    del st["sn"][o["id"]]
    _drop_tags(st, o["arn"])
    return 202, {"id": o["id"], "arn": o["arn"], "name": o["name"], "status": "DELETE_IN_PROGRESS"}


# ── services / listeners / rules ─────────────────────────────────────────────────────
def _svc_dns(region, name, rid):
    return f"{name}-{rid.split('-', 1)[1][:17]}.{secrets.token_hex(4)}.vpc-lattice-svcs.{region}.on.aws"


def _svc_view(o, summary=False):
    base = {"id": o["id"], "arn": o["arn"], "name": o["name"], "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    if o.get("customDomainName"):
        base["customDomainName"] = o["customDomainName"]
    base["dnsEntry"] = o["dnsEntry"]
    if summary:
        return {**base, "status": o["status"]}
    out = {**base, "authType": o["authType"], "status": o["status"]}
    if o.get("certificateArn"):
        out["certificateArn"] = o["certificateArn"]
    return out


def _create_service(st, g, body, query, region):
    name = _validate_name(body.get("name"), 40)
    _dup_name(st, "svc", name, "service")
    cert = body.get("certificateArn")
    if cert and not str(cert).startswith("arn:aws:acm:"):
        raise _Err("ValidationException", "certificateArn must be an ACM certificate ARN.", 400)
    cd = body.get("customDomainName")
    if cd and not re.fullmatch(r"([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", str(cd)):
        raise _Err("ValidationException", "customDomainName is not a valid domain name.", 400)
    rid = _rid("svc")
    o = {"id": rid, "arn": _arn(region, "service", rid), "name": name, "authType": _auth_type(body.get("authType")), "status": "ACTIVE",
         "certificateArn": cert, "customDomainName": cd, "createdAt": _now(), "lastUpdatedAt": _now(),
         "dnsEntry": {"domainName": _svc_dns(region, name, rid), "hostedZoneId": "Z09127221KTH2CZ0XBWAI"}}
    st["svc"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    out = {k: o[k] for k in ("id", "arn", "name", "authType", "status", "dnsEntry")}
    if cert:
        out["certificateArn"] = cert
    if cd:
        out["customDomainName"] = cd
    return 201, out


def _update_service(st, g, body, query, region):
    o = _get(st, "svc", g[0], "Service")
    if "authType" in body:
        o["authType"] = _auth_type(body["authType"])
    if "certificateArn" in body:
        o["certificateArn"] = body["certificateArn"]
    o["lastUpdatedAt"] = _now()
    return 200, {k: o[k] for k in ("id", "arn", "name", "authType") if k in o} | ({"certificateArn": o["certificateArn"]} if o.get("certificateArn") else {})


def _delete_service(st, g, body, query, region):
    o = _get(st, "svc", g[0], "Service")
    if any(a["serviceId"] == o["id"] for a in st["snsa"].values()):
        raise _Err("ConflictException", f"Service {o['id']} is associated with a service network; delete the association first.", 409)
    for l in [l for l in st["listener"].values() if l["serviceId"] == o["id"]]:
        _drop_listener(st, l)
    del st["svc"][o["id"]]
    _drop_tags(st, o["arn"])
    return 202, {"id": o["id"], "arn": o["arn"], "name": o["name"], "status": "DELETE_IN_PROGRESS"}


def _action(st, action, protocol):
    """Validate + normalise a listener/rule action."""
    if not isinstance(action, dict) or bool(action.get("forward")) == bool(action.get("fixedResponse")):
        raise _Err("ValidationException", "action must contain exactly one of forward or fixedResponse.", 400)
    if action.get("fixedResponse"):
        sc = action["fixedResponse"].get("statusCode")
        if not isinstance(sc, int) or not 100 <= sc <= 599:
            raise _Err("ValidationException", "fixedResponse.statusCode must be an HTTP status code.", 400)
        return {"fixedResponse": {"statusCode": sc}}
    tgs = (action["forward"] or {}).get("targetGroups") or []
    if not tgs or len(tgs) > 10:
        raise _Err("ValidationException", "forward.targetGroups must list 1-10 target groups.", 400)
    out = []
    for t in tgs:
        tg = _get(st, "tg", t.get("targetGroupIdentifier"), "Target group")
        w = t.get("weight", 100)
        if not isinstance(w, int) or not 0 <= w <= 999:
            raise _Err("ValidationException", "weight must be 0-999.", 400)
        out.append({"targetGroupIdentifier": tg["id"], "weight": w})
    return {"forward": {"targetGroups": out}}


def _action_tg_ids(action):
    return [t["targetGroupIdentifier"] for t in (action.get("forward") or {}).get("targetGroups", [])]


def _listener_view(o, summary=False):
    base = {"id": o["id"], "arn": o["arn"], "name": o["name"], "port": o["port"], "protocol": o["protocol"],
            "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    if summary:
        return base
    return {**base, "serviceId": o["serviceId"], "serviceArn": o["serviceArn"], "defaultAction": o["defaultAction"]}


def _create_listener(st, g, body, query, region):
    svc = _get(st, "svc", g[0], "Service")
    name = _validate_name(body.get("name"), 63)
    proto = body.get("protocol")
    if proto not in ("HTTP", "HTTPS", "TLS_PASSTHROUGH"):
        raise _Err("ValidationException", "protocol must be HTTP, HTTPS or TLS_PASSTHROUGH.", 400)
    port = body.get("port", 80 if proto == "HTTP" else 443)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise _Err("ValidationException", "port must be 1-65535.", 400)
    for l in st["listener"].values():
        if l["serviceId"] == svc["id"] and (l["name"] == name or l["port"] == port):
            raise _Err("ConflictException", f"Service {svc['id']} already has a listener with that name or port.", 409)
    default = _action(st, body.get("defaultAction"), proto)
    rid = _rid("listener")
    o = {"id": rid, "arn": f"arn:aws:vpc-lattice:{region}:{_ACCOUNT}:service/{svc['id']}/listener/{rid}", "name": name, "port": port,
         "protocol": proto, "serviceId": svc["id"], "serviceArn": svc["arn"], "defaultAction": default, "createdAt": _now(), "lastUpdatedAt": _now()}
    st["listener"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    rrid = "rule-default-" + rid.split("-", 1)[1]
    st["rule"][rrid] = {"id": rrid, "arn": f"{o['arn']}/rule/{rrid}", "name": "default", "listenerId": rid, "serviceId": svc["id"],
                        "isDefault": True, "priority": None, "match": {}, "action": default, "createdAt": _now(), "lastUpdatedAt": _now()}
    return 201, {k: o[k] for k in ("id", "arn", "name", "port", "protocol", "serviceId", "serviceArn", "defaultAction")}


def _listener_of(st, sid, lid):
    svc = _get(st, "svc", sid, "Service")
    l = st["listener"].get(str(lid).rsplit("/", 1)[-1])
    if l is None or l["serviceId"] != svc["id"]:
        raise _Err("ResourceNotFoundException", f"Listener {lid} not found.", 404)
    return l


def _update_listener(st, g, body, query, region):
    l = _listener_of(st, g[0], g[1])
    l["defaultAction"] = _action(st, body.get("defaultAction"), l["protocol"])
    l["lastUpdatedAt"] = _now()
    for r in st["rule"].values():
        if r["listenerId"] == l["id"] and r["isDefault"]:
            r["action"] = l["defaultAction"]
    return 200, {k: l[k] for k in ("id", "arn", "name", "port", "protocol", "serviceId", "serviceArn", "defaultAction")}


def _drop_listener(st, l):
    for rid in [r["id"] for r in st["rule"].values() if r["listenerId"] == l["id"]]:
        del st["rule"][rid]
    st["listener"].pop(l["id"], None)
    _drop_tags(st, l["arn"])


def _delete_listener(st, g, body, query, region):
    l = _listener_of(st, g[0], g[1])
    _drop_listener(st, l)
    return 204, {}


def _list_listeners(st, g, body, query, region):
    svc = _get(st, "svc", g[0], "Service")
    return _page([_listener_view(l, True) for l in st["listener"].values() if l["serviceId"] == svc["id"]], query)


def _validate_match(match, listener):
    if listener["protocol"] == "TLS_PASSTHROUGH":
        raise _Err("ValidationException", "Rules are not supported on TLS_PASSTHROUGH listeners.", 400)
    hm = (match or {}).get("httpMatch")
    if not isinstance(hm, dict) or not hm:
        raise _Err("ValidationException", "match.httpMatch is required.", 400)
    pm = hm.get("pathMatch")
    if pm is not None:
        m = (pm or {}).get("match") or {}
        if bool(m.get("exact")) == bool(m.get("prefix")):
            raise _Err("ValidationException", "pathMatch.match needs exactly one of exact or prefix.", 400)
        if not str(m.get("exact") or m.get("prefix")).startswith("/"):
            raise _Err("ValidationException", "Path matches must begin with '/'.", 400)
    for h in hm.get("headerMatches") or []:
        if not h.get("name") or not isinstance(h.get("match"), dict) or not any(k in h["match"] for k in ("exact", "prefix", "contains")):
            raise _Err("ValidationException", "headerMatches entries need a name and match.exact|prefix|contains.", 400)
    if hm.get("method") and hm["method"] not in ("GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"):
        raise _Err("ValidationException", "match.httpMatch.method is not a valid HTTP method.", 400)
    if not (hm.get("method") or pm or hm.get("headerMatches")):
        raise _Err("ValidationException", "httpMatch needs at least one of method, pathMatch, headerMatches.", 400)
    return match


def _rule_view(o, summary=False):
    base = {"id": o["id"], "arn": o["arn"], "name": o["name"], "isDefault": o["isDefault"], "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    if o["priority"] is not None:
        base["priority"] = o["priority"]
    if summary:
        return base
    return {**base, "match": o["match"], "action": o["action"]}


def _check_priority(st, l, prio, own=None):
    if not isinstance(prio, int) or not 1 <= prio <= 100:
        raise _Err("ValidationException", "priority must be 1-100.", 400)
    if any(r["listenerId"] == l["id"] and r["priority"] == prio and r["id"] != own for r in st["rule"].values()):
        raise _Err("ConflictException", f"A rule with priority {prio} already exists on this listener.", 409)


def _create_rule(st, g, body, query, region):
    l = _listener_of(st, g[0], g[1])
    name = _validate_name(body.get("name"), 63)
    if any(r["listenerId"] == l["id"] and r["name"] == name for r in st["rule"].values()):
        raise _Err("ConflictException", f"A rule named '{name}' already exists on this listener.", 409)
    _check_priority(st, l, body.get("priority"))
    match = _validate_match(body.get("match"), l)
    action = _action(st, body.get("action"), l["protocol"])
    rid = _rid("rule")
    o = {"id": rid, "arn": f"{l['arn']}/rule/{rid}", "name": name, "listenerId": l["id"], "serviceId": l["serviceId"], "isDefault": False,
         "priority": body["priority"], "match": match, "action": action, "createdAt": _now(), "lastUpdatedAt": _now()}
    st["rule"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 201, {k: o[k] for k in ("id", "arn", "name", "priority", "match", "action")}


def _rule_of(st, g):
    l = _listener_of(st, g[0], g[1])
    r = st["rule"].get(str(g[2]).rsplit("/", 1)[-1])
    if r is None or r["listenerId"] != l["id"]:
        raise _Err("ResourceNotFoundException", f"Rule {g[2]} not found.", 404)
    return l, r


def _update_rule(st, g, body, query, region):
    l, r = _rule_of(st, g)
    if r["isDefault"]:
        if "match" in body or "priority" in body:
            raise _Err("ValidationException", "The default rule's match and priority cannot be changed.", 400)
    else:
        if "priority" in body:
            _check_priority(st, l, body["priority"], r["id"])
            r["priority"] = body["priority"]
        if "match" in body:
            r["match"] = _validate_match(body["match"], l)
    if "action" in body:
        r["action"] = _action(st, body["action"], l["protocol"])
        if r["isDefault"]:
            l["defaultAction"] = r["action"]
    r["lastUpdatedAt"] = _now()
    return 200, _rule_view(r) | {"isDefault": r["isDefault"]}


def _delete_rule(st, g, body, query, region):
    l, r = _rule_of(st, g)
    if r["isDefault"]:
        raise _Err("ValidationException", "The default rule cannot be deleted; delete the listener instead.", 400)
    del st["rule"][r["id"]]
    _drop_tags(st, r["arn"])
    return 204, {}


def _batch_update_rule(st, g, body, query, region):
    l = _listener_of(st, g[0], g[1])
    ok, bad = [], []
    for u in body.get("rules") or []:
        try:
            r = st["rule"].get(str(u.get("ruleIdentifier")).rsplit("/", 1)[-1])
            if r is None or r["listenerId"] != l["id"]:
                raise _Err("ResourceNotFoundException", "Rule not found.", 404)
            code, out = _update_rule(st, [g[0], g[1], r["id"]], {k: v for k, v in u.items() if k != "ruleIdentifier"}, query, region)
            ok.append({"id": r["id"], "arn": r["arn"], "name": r["name"], "isDefault": r["isDefault"], **({"priority": r["priority"]} if r["priority"] else {}),
                       "match": r["match"], "action": r["action"]})
        except _Err as e:
            bad.append({"ruleIdentifier": u.get("ruleIdentifier"), "failureCode": e.code, "failureMessage": e.message})
    return 200, {"successful": ok, "unsuccessful": bad}


# ── target groups ────────────────────────────────────────────────────────────────────
_TG_TYPES = ("IP", "LAMBDA", "INSTANCE", "ALB")


def _tg_users(st, tgid):
    """(listeners/rules whose action forwards to this target group)"""
    out = []
    for l in st["listener"].values():
        if tgid in _action_tg_ids(l["defaultAction"]):
            out.append(l)
    for r in st["rule"].values():
        if not r["isDefault"] and tgid in _action_tg_ids(r["action"]):
            out.append(r)
    return out


def _tg_service_arns(st, tgid):
    ids = {u["serviceId"] for u in _tg_users(st, tgid)}
    return sorted(st["svc"][i]["arn"] for i in ids if i in st["svc"])


def _hc(h, protocol):
    h = h or {}
    out = {"enabled": h.get("enabled", True), "protocol": h.get("protocol", protocol if protocol in ("HTTP", "HTTPS") else "HTTP"),
           "protocolVersion": h.get("protocolVersion", "HTTP1"), "path": h.get("path", "/"), "port": h.get("port"),
           "healthCheckIntervalSeconds": h.get("healthCheckIntervalSeconds", 30), "healthCheckTimeoutSeconds": h.get("healthCheckTimeoutSeconds", 5),
           "healthyThresholdCount": h.get("healthyThresholdCount", 5), "unhealthyThresholdCount": h.get("unhealthyThresholdCount", 2),
           "matcher": h.get("matcher") or {"httpCode": "200"}}
    if not 5 <= out["healthCheckIntervalSeconds"] <= 300 or not 1 <= out["healthCheckTimeoutSeconds"] <= 120:
        raise _Err("ValidationException", "Health check interval must be 5-300s and timeout 1-120s.", 400)
    if not 2 <= out["healthyThresholdCount"] <= 10 or not 2 <= out["unhealthyThresholdCount"] <= 10:
        raise _Err("ValidationException", "Health/unhealthy threshold counts must be 2-10.", 400)
    return out


def _create_target_group(st, g, body, query, region):
    name = _validate_name(body.get("name"), 128)
    ttype = body.get("type")
    if ttype not in _TG_TYPES:
        raise _Err("ValidationException", f"type must be one of {list(_TG_TYPES)}.", 400)
    _dup_name(st, "tg", name, "target group")
    cfg = body.get("config")
    if ttype == "LAMBDA":
        if cfg and any(k in cfg for k in ("port", "protocol", "vpcIdentifier")):
            raise _Err("ValidationException", "LAMBDA target groups do not take port, protocol or vpcIdentifier.", 400)
        config = {"lambdaEventStructureVersion": (cfg or {}).get("lambdaEventStructureVersion", "V1")}
    else:
        cfg = cfg or {}
        proto = cfg.get("protocol")
        if proto not in ("HTTP", "HTTPS", "TCP"):
            raise _Err("ValidationException", "config.protocol must be HTTP, HTTPS or TCP.", 400)
        if ttype == "ALB" and proto == "TCP":
            raise _Err("ValidationException", "ALB target groups support HTTP and HTTPS only.", 400)
        port = cfg.get("port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise _Err("ValidationException", "config.port must be 1-65535.", 400)
        vpc = cfg.get("vpcIdentifier")
        if not vpc or vpc not in st["_m"]["vpcs"]:
            raise _Err("ValidationException", f"config.vpcIdentifier {vpc!r} is not an existing VPC.", 400)
        ipt = cfg.get("ipAddressType", "IPV4")
        if ipt not in ("IPV4", "IPV6"):
            raise _Err("ValidationException", "config.ipAddressType must be IPV4 or IPV6.", 400)
        config = {"port": port, "protocol": proto, "protocolVersion": cfg.get("protocolVersion", "HTTP1") if proto != "TCP" else "HTTP1",
                  "ipAddressType": ipt, "vpcIdentifier": vpc}
        if proto != "TCP":
            config["healthCheck"] = _hc(cfg.get("healthCheck"), proto)
    rid = _rid("tg")
    o = {"id": rid, "arn": _arn(region, "targetgroup", rid), "name": name, "type": ttype, "config": config, "status": "ACTIVE", "targets": {},
         "createdAt": _now(), "lastUpdatedAt": _now()}
    st["tg"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 201, {"id": rid, "arn": o["arn"], "name": name, "type": ttype, "config": config, "status": "ACTIVE"}


def _update_target_group(st, g, body, query, region):
    o = _get(st, "tg", g[0], "Target group")
    if o["type"] == "LAMBDA" or "healthCheck" not in o["config"]:
        raise _Err("ValidationException", "This target group has no health check to update.", 400)
    o["config"]["healthCheck"] = _hc(body.get("healthCheck"), o["config"]["protocol"])
    o["lastUpdatedAt"] = _now()
    return 200, {"id": o["id"], "arn": o["arn"], "name": o["name"], "type": o["type"], "config": o["config"], "status": o["status"]}


def _delete_target_group(st, g, body, query, region):
    o = _get(st, "tg", g[0], "Target group")
    if _tg_users(st, o["id"]):
        raise _Err("ConflictException", f"Target group {o['id']} is referenced by a listener or rule; remove it from the action first.", 409)
    del st["tg"][o["id"]]
    _drop_tags(st, o["arn"])
    return 202, {"id": o["id"], "arn": o["arn"], "status": "DELETE_IN_PROGRESS"}


def _check_target(st, tg, t):
    tid, port = str(t.get("id") or ""), t.get("port")
    tt = tg["type"]
    if tt == "LAMBDA":
        if not re.fullmatch(r"arn:aws:lambda:[a-z0-9-]+:\d{12}:function:[\w.\-]+(:[\w$\-]+)?", tid):
            return "InvalidTarget", "A LAMBDA target must be a Lambda function ARN."
        if port is not None:
            return "InvalidTarget", "LAMBDA targets take no port."
        return None
    if tt == "ALB" and not re.fullmatch(r"arn:aws:elasticloadbalancing:[a-z0-9-]+:\d{12}:loadbalancer/app/.+", tid):
        return "InvalidTarget", "An ALB target must be an Application Load Balancer ARN."
    if tt == "INSTANCE":
        inst = st["_m"]["instances"].get(tid)
        if inst is None:
            return "TargetNotFound", f"Instance {tid} does not exist."
        if inst.get("vpc_id") and inst["vpc_id"] != tg["config"]["vpcIdentifier"]:
            return "InvalidTarget", f"Instance {tid} is not in VPC {tg['config']['vpcIdentifier']}."
    if tt == "IP":
        try:
            ip = ipaddress.ip_address(tid)
        except ValueError:
            return "InvalidTarget", f"'{tid}' is not an IP address."
        if (ip.version == 6) != (tg["config"]["ipAddressType"] == "IPV6"):
            return "InvalidTarget", "The address family does not match the target group's ipAddressType."
        if not (ip.is_private or ip.is_link_local):
            return "InvalidTarget", "IP targets must be private (RFC 1918 / ULA) addresses."
    if tt in ("INSTANCE", "IP", "ALB"):
        if port is not None and (not isinstance(port, int) or not 1 <= port <= 65535):
            return "InvalidTarget", "port must be 1-65535."
    return None


def _target_status(st, tg):
    return "INITIAL" if _tg_users(st, tg["id"]) else "UNUSED"


def _register_targets(st, g, body, query, region):
    tg = _get(st, "tg", g[0], "Target group")
    ts = body.get("targets") or []
    if not ts or len(ts) > 100:
        raise _Err("ValidationException", "targets must list 1-100 targets.", 400)
    ok, bad = [], []
    for t in ts:
        err = _check_target(st, tg, t)
        if not err and tg["type"] == "LAMBDA" and tg["targets"] and f"{t['id']}:" not in {f"{k.split('|')[0]}:" for k in tg["targets"]}:
            err = ("InvalidTarget", "A LAMBDA target group can have only one target.")
        if err:
            bad.append({"id": t.get("id"), **({"port": t["port"]} if t.get("port") else {}), "failureCode": err[0], "failureMessage": err[1]})
            continue
        port = t.get("port") if t.get("port") is not None else (tg["config"].get("port") if tg["type"] != "LAMBDA" else None)
        tg["targets"][f"{t['id']}|{port}"] = {"id": t["id"], **({"port": port} if port else {})}
        ok.append({"id": t["id"], **({"port": port} if port else {})})
    tg["lastUpdatedAt"] = _now()
    return 207, {"successful": ok, "unsuccessful": bad}


def _deregister_targets(st, g, body, query, region):
    tg = _get(st, "tg", g[0], "Target group")
    ok, bad = [], []
    for t in body.get("targets") or []:
        port = t.get("port") if t.get("port") is not None else (tg["config"].get("port") if tg["type"] != "LAMBDA" else None)
        key = f"{t.get('id')}|{port}"
        if key in tg["targets"]:
            del tg["targets"][key]
            ok.append({"id": t["id"], **({"port": port} if port else {})})
        else:
            bad.append({"id": t.get("id"), **({"port": port} if port else {}), "failureCode": "TargetNotRegistered", "failureMessage": "The target is not registered."})
    return 207, {"successful": ok, "unsuccessful": bad}


def _list_targets(st, g, body, query, region):
    tg = _get(st, "tg", g[0], "Target group")
    ids = {t.get("id") for t in (body.get("targets") or [])}
    from core import vpc_lattice_dataplane as dp
    items = []
    for t in tg["targets"].values():
        if ids and t["id"] not in ids:
            continue
        status, reason = dp.target_health(st, tg, t)      # derived from instance state + SG reachability (no probe)
        items.append({**t, "status": status, **({"reasonCode": reason} if reason else {})})
    return _page(items, query)


def _invoke(st, g, body, query, region):
    """Simulator data-plane verb (not a real Lattice API): evaluate one request through the service network."""
    from core import vpc_lattice_dataplane as dp
    if not body.get("host"):
        raise _Err("ValidationException", "host is required.", 400)
    return 200, dp.invoke(st, body)


# ── VPC / service / resource associations ────────────────────────────────────────────
def _assoc_arn(region, kind, rid):
    return _arn(region, kind, rid)


def _check_sgs(st, sgs, vpc_id):
    if sgs is None:
        return []
    if not isinstance(sgs, list) or len(sgs) > 5:
        raise _Err("ValidationException", "securityGroupIds must list up to 5 groups.", 400)
    for s in sgs:
        sg = st["_m"]["sgs"].get(s)
        if sg is None:
            raise _Err("ValidationException", f"Security group {s} does not exist.", 400)
        if sg.get("vpc_id") != vpc_id:
            raise _Err("ValidationException", f"Security group {s} is not in VPC {vpc_id}.", 400)
    return list(sgs)


def _snva_view(o, summary=False):
    base = {"id": o["id"], "arn": o["arn"], "status": o["status"], "serviceNetworkId": o["serviceNetworkId"], "serviceNetworkArn": o["serviceNetworkArn"],
            "serviceNetworkName": o["serviceNetworkName"], "vpcId": o["vpcId"], "createdAt": o["createdAt"]}
    if summary:
        return {**base, "createdBy": _ACCOUNT, "lastUpdatedAt": o["lastUpdatedAt"]}
    return {**base, "securityGroupIds": o["securityGroupIds"], "createdBy": _ACCOUNT, "lastUpdatedAt": o["lastUpdatedAt"]}


def _create_snva(st, g, body, query, region):
    sn = _get(st, "sn", body.get("serviceNetworkIdentifier"), "Service network")
    vpc = str(body.get("vpcIdentifier") or "")
    if vpc not in st["_m"]["vpcs"]:
        raise _Err("ValidationException", f"VPC {vpc!r} does not exist.", 400)
    for a in st["snva"].values():
        if a["vpcId"] == vpc:
            raise _Err("ConflictException", f"VPC {vpc} is already associated with service network {a['serviceNetworkId']}; a VPC can belong to only one service network.", 409)
    sgs = _check_sgs(st, body.get("securityGroupIds"), vpc)
    rid = _rid("snva")
    o = {"id": rid, "arn": _arn(region, "servicenetworkvpcassociation", rid), "status": "ACTIVE", "serviceNetworkId": sn["id"], "serviceNetworkArn": sn["arn"],
         "serviceNetworkName": sn["name"], "vpcId": vpc, "securityGroupIds": sgs, "createdAt": _now(), "lastUpdatedAt": _now()}
    st["snva"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 202, {"id": rid, "arn": o["arn"], "status": o["status"], "securityGroupIds": sgs, "createdBy": _ACCOUNT}


def _update_snva(st, g, body, query, region):
    o = _get(st, "snva", g[0], "Association")
    o["securityGroupIds"] = _check_sgs(st, body.get("securityGroupIds") or [], o["vpcId"])
    o["lastUpdatedAt"] = _now()
    return 200, {"id": o["id"], "arn": o["arn"], "status": o["status"], "securityGroupIds": o["securityGroupIds"], "createdBy": _ACCOUNT}


def _delete_assoc(coll):
    def fn(st, g, body, query, region):
        o = _get(st, coll, g[0], "Association")
        del st[coll][o["id"]]
        _drop_tags(st, o["arn"])
        return 202, {"id": o["id"], "arn": o["arn"], "status": "DELETE_IN_PROGRESS"}
    return fn


def _list_snva(st, g, body, query, region):
    sn, vpc = _q1(query, "serviceNetworkIdentifier"), _q1(query, "vpcIdentifier")
    sid = _get(st, "sn", sn, "Service network")["id"] if sn else None
    return _page([_snva_view(a, True) for a in st["snva"].values() if (not sid or a["serviceNetworkId"] == sid) and (not vpc or a["vpcId"] == vpc)], query)


def _snsa_view(o):
    return {"id": o["id"], "arn": o["arn"], "status": o["status"], "serviceId": o["serviceId"], "serviceArn": o["serviceArn"], "serviceName": o["serviceName"],
            "serviceNetworkId": o["serviceNetworkId"], "serviceNetworkArn": o["serviceNetworkArn"], "serviceNetworkName": o["serviceNetworkName"],
            "dnsEntry": o["dnsEntry"], "createdAt": o["createdAt"], "createdBy": _ACCOUNT}


def _create_snsa(st, g, body, query, region):
    sn = _get(st, "sn", body.get("serviceNetworkIdentifier"), "Service network")
    svc = _get(st, "svc", body.get("serviceIdentifier"), "Service")
    if any(a["serviceNetworkId"] == sn["id"] and a["serviceId"] == svc["id"] for a in st["snsa"].values()):
        raise _Err("ConflictException", "That service is already associated with the service network.", 409)
    rid = _rid("snsa")
    o = {"id": rid, "arn": _arn(region, "servicenetworkserviceassociation", rid), "status": "ACTIVE", "serviceId": svc["id"], "serviceArn": svc["arn"], "serviceName": svc["name"],
         "serviceNetworkId": sn["id"], "serviceNetworkArn": sn["arn"], "serviceNetworkName": sn["name"], "dnsEntry": svc["dnsEntry"], "createdAt": _now()}
    st["snsa"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 202, {"id": rid, "arn": o["arn"], "status": o["status"], "customDomainName": svc.get("customDomainName"), "dnsEntry": svc["dnsEntry"], "createdBy": _ACCOUNT}


def _list_snsa(st, g, body, query, region):
    sn, svc = _q1(query, "serviceNetworkIdentifier"), _q1(query, "serviceIdentifier")
    sid = _get(st, "sn", sn, "Service network")["id"] if sn else None
    vid = _get(st, "svc", svc, "Service")["id"] if svc else None
    return _page([_snsa_view(a) for a in st["snsa"].values() if (not sid or a["serviceNetworkId"] == sid) and (not vid or a["serviceId"] == vid)], query)


def _snra_view(o):
    return {"id": o["id"], "arn": o["arn"], "status": o["status"], "resourceConfigurationId": o["resourceConfigurationId"], "resourceConfigurationArn": o["resourceConfigurationArn"],
            "resourceConfigurationName": o["resourceConfigurationName"], "serviceNetworkId": o["serviceNetworkId"], "serviceNetworkArn": o["serviceNetworkArn"],
            "serviceNetworkName": o["serviceNetworkName"], "createdAt": o["createdAt"], "createdBy": _ACCOUNT}


def _create_snra(st, g, body, query, region):
    sn = _get(st, "sn", body.get("serviceNetworkIdentifier"), "Service network")
    rc = _get(st, "rcfg", body.get("resourceConfigurationIdentifier"), "Resource configuration")
    if rc["type"] == "CHILD":
        raise _Err("ValidationException", "A CHILD resource configuration is associated through its group, not directly.", 400)
    if any(a["serviceNetworkId"] == sn["id"] and a["resourceConfigurationId"] == rc["id"] for a in st["snra"].values()):
        raise _Err("ConflictException", "That resource configuration is already associated with the service network.", 409)
    rid = _rid("snra")
    o = {"id": rid, "arn": _arn(region, "servicenetworkresourceassociation", rid), "status": "ACTIVE", "resourceConfigurationId": rc["id"], "resourceConfigurationArn": rc["arn"],
         "resourceConfigurationName": rc["name"], "serviceNetworkId": sn["id"], "serviceNetworkArn": sn["arn"], "serviceNetworkName": sn["name"], "createdAt": _now()}
    st["snra"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 202, {"id": rid, "arn": o["arn"], "status": o["status"], "createdBy": _ACCOUNT}


def _list_snra(st, g, body, query, region):
    sn, rc = _q1(query, "serviceNetworkIdentifier"), _q1(query, "resourceConfigurationIdentifier")
    sid = _get(st, "sn", sn, "Service network")["id"] if sn else None
    rid = _get(st, "rcfg", rc, "Resource configuration")["id"] if rc else None
    return _page([_snra_view(a) for a in st["snra"].values() if (not sid or a["serviceNetworkId"] == sid) and (not rid or a["resourceConfigurationId"] == rid)], query)


# ── resource gateways / configurations ───────────────────────────────────────────────
def _rgw_view(o, summary=False):
    base = {"id": o["id"], "arn": o["arn"], "name": o["name"], "status": o["status"], "vpcIdentifier": o["vpcIdentifier"], "subnetIds": o["subnetIds"],
            "ipAddressType": o["ipAddressType"], "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    if summary:
        return base
    return {**base, "securityGroupIds": o["securityGroupIds"], "ipv4AddressesPerEni": o["ipv4AddressesPerEni"]}


def _create_rgw(st, g, body, query, region):
    name = _validate_name(body.get("name"), 40)
    _dup_name(st, "rgw", name, "resource gateway")
    vpc = str(body.get("vpcIdentifier") or "")
    if vpc not in st["_m"]["vpcs"]:
        raise _Err("ValidationException", f"VPC {vpc!r} does not exist.", 400)
    subs = body.get("subnetIds") or []
    if not isinstance(subs, list) or not 1 <= len(subs) <= 20:
        raise _Err("ValidationException", "subnetIds must list 1-20 subnets.", 400)
    azs = set()
    for s in subs:
        sub = st["_m"]["subnets"].get(s)
        if sub is None or sub.get("vpc_id") != vpc:
            raise _Err("ValidationException", f"Subnet {s} does not exist in VPC {vpc}.", 400)
        if sub.get("az") in azs:
            raise _Err("ValidationException", "Choose at most one subnet per Availability Zone.", 400)
        azs.add(sub.get("az"))
    ipt = body.get("ipAddressType", "IPV4")
    if ipt not in ("IPV4", "IPV6", "DUALSTACK"):
        raise _Err("ValidationException", "ipAddressType must be IPV4, IPV6 or DUALSTACK.", 400)
    per = body.get("ipv4AddressesPerEni", 16)
    if not isinstance(per, int) or not 1 <= per <= 62:
        raise _Err("ValidationException", "ipv4AddressesPerEni must be 1-62.", 400)
    rid = _rid("rgw")
    o = {"id": rid, "arn": _arn(region, "resourcegateway", rid), "name": name, "status": "ACTIVE", "vpcIdentifier": vpc, "subnetIds": list(subs),
         "securityGroupIds": _check_sgs(st, body.get("securityGroupIds"), vpc), "ipAddressType": ipt, "ipv4AddressesPerEni": per, "createdAt": _now(), "lastUpdatedAt": _now()}
    st["rgw"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 201, {k: o[k] for k in ("id", "arn", "name", "status", "vpcIdentifier", "subnetIds", "securityGroupIds", "ipAddressType", "ipv4AddressesPerEni")}


def _update_rgw(st, g, body, query, region):
    o = _get(st, "rgw", g[0], "Resource gateway")
    if "securityGroupIds" in body:
        o["securityGroupIds"] = _check_sgs(st, body["securityGroupIds"], o["vpcIdentifier"])
    o["lastUpdatedAt"] = _now()
    return 200, {k: o[k] for k in ("id", "arn", "name", "status", "vpcIdentifier", "subnetIds", "securityGroupIds", "ipAddressType")}


def _delete_rgw(st, g, body, query, region):
    o = _get(st, "rgw", g[0], "Resource gateway")
    if any(c.get("resourceGatewayId") == o["id"] for c in st["rcfg"].values()):
        raise _Err("ConflictException", f"Resource gateway {o['id']} is used by a resource configuration.", 409)
    del st["rgw"][o["id"]]
    _drop_tags(st, o["arn"])
    return 202, {"id": o["id"], "arn": o["arn"], "name": o["name"], "status": "DELETE_IN_PROGRESS"}


_PORTS_RE = re.compile(r"^\d{1,5}(-\d{1,5})?$")
_DOMAIN_RE = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


def _rcfg_view(o, summary=False):
    base = {"id": o["id"], "arn": o["arn"], "name": o["name"], "type": o["type"], "status": o["status"], "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    if o.get("resourceGatewayId"):
        base["resourceGatewayId"] = o["resourceGatewayId"]
    if o.get("resourceConfigurationGroupId"):
        base["resourceConfigurationGroupId"] = o["resourceConfigurationGroupId"]
    if summary:
        return base
    out = {**base, "resourceConfigurationDefinition": o.get("resourceConfigurationDefinition"), "portRanges": o.get("portRanges"), "protocol": o.get("protocol"),
           "allowAssociationToShareableServiceNetwork": o["allowAssociation"], "amazonManaged": False}
    if o.get("customDomainName"):
        out["customDomainName"] = o["customDomainName"]
    return out


def _create_rcfg(st, g, body, query, region):
    name = _validate_name(body.get("name"), 40)
    _dup_name(st, "rcfg", name, "resource configuration")
    rtype = body.get("type")
    if rtype not in ("GROUP", "CHILD", "SINGLE", "ARN"):
        raise _Err("ValidationException", "type must be GROUP, CHILD, SINGLE or ARN.", 400)
    gw = None
    if rtype in ("SINGLE", "GROUP", "CHILD"):
        gw = _get(st, "rgw", body.get("resourceGatewayIdentifier"), "Resource gateway") if body.get("resourceGatewayIdentifier") else None
        if rtype != "CHILD" and gw is None:
            raise _Err("ValidationException", f"resourceGatewayIdentifier is required for {rtype} resource configurations.", 400)
    defn = body.get("resourceConfigurationDefinition")
    group_id = None
    if rtype == "GROUP":
        if defn:
            raise _Err("ValidationException", "GROUP resource configurations take no definition.", 400)
    else:
        if not isinstance(defn, dict) or sum(k in defn for k in ("dnsResource", "ipResource", "arnResource")) != 1:
            raise _Err("ValidationException", "resourceConfigurationDefinition needs exactly one of dnsResource, ipResource, arnResource.", 400)
        if rtype == "ARN" and "arnResource" not in defn:
            raise _Err("ValidationException", "ARN resource configurations need arnResource.", 400)
        if rtype in ("SINGLE", "CHILD") and "arnResource" in defn:
            raise _Err("ValidationException", "arnResource is only valid for type ARN.", 400)
        if "dnsResource" in defn:
            d = defn["dnsResource"] or {}
            if not _DOMAIN_RE.match(str(d.get("domainName") or "")):
                raise _Err("ValidationException", "dnsResource.domainName is not a valid domain name.", 400)
            if d.get("ipAddressType") not in ("IPV4", "IPV6", "DUALSTACK"):
                raise _Err("ValidationException", "dnsResource.ipAddressType must be IPV4, IPV6 or DUALSTACK.", 400)
        if "ipResource" in defn:
            try:
                ipaddress.ip_address(str((defn["ipResource"] or {}).get("ipAddress") or ""))
            except ValueError:
                raise _Err("ValidationException", "ipResource.ipAddress is not an IP address.", 400)
        if "arnResource" in defn and not str((defn["arnResource"] or {}).get("arn") or "").startswith("arn:"):
            raise _Err("ValidationException", "arnResource.arn is not an ARN.", 400)
    if rtype == "CHILD":
        group_id = body.get("resourceConfigurationGroupIdentifier")
        grp = _get(st, "rcfg", group_id, "Resource configuration group") if group_id else None
        if grp is None or grp["type"] != "GROUP":
            raise _Err("ValidationException", "CHILD resource configurations need resourceConfigurationGroupIdentifier of a GROUP configuration.", 400)
        group_id = grp["id"]
        gw = _get(st, "rgw", grp["resourceGatewayId"], "Resource gateway")
    ports = body.get("portRanges")
    proto = body.get("protocol")
    if rtype in ("SINGLE", "CHILD", "GROUP"):
        if not ports or not isinstance(ports, list):
            raise _Err("ValidationException", "portRanges is required.", 400)
        for pr in ports:
            if not _PORTS_RE.match(str(pr)) or any(not 1 <= int(x) <= 65535 for x in str(pr).split("-")) or (
                    "-" in str(pr) and int(str(pr).split("-")[0]) > int(str(pr).split("-")[1])):
                raise _Err("ValidationException", f"Invalid port range '{pr}'.", 400)
        if proto not in (None, "TCP"):
            raise _Err("ValidationException", "protocol must be TCP.", 400)
        proto = proto or "TCP"
    cd = body.get("customDomainName")
    if cd and not _DOMAIN_RE.match(str(cd)):
        raise _Err("ValidationException", "customDomainName is not a valid domain name.", 400)
    rid = _rid("rcfg")
    o = {"id": rid, "arn": _arn(region, "resourceconfiguration", rid), "name": name, "type": rtype, "status": "ACTIVE", "resourceGatewayId": gw["id"] if gw else None,
         "resourceConfigurationGroupId": group_id, "resourceConfigurationDefinition": defn, "portRanges": ports, "protocol": proto, "customDomainName": cd,
         "allowAssociation": bool(body.get("allowAssociationToShareableServiceNetwork", True)), "createdAt": _now(), "lastUpdatedAt": _now()}
    st["rcfg"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    out = {k: o[k] for k in ("id", "arn", "name", "type", "status") if o.get(k) is not None}
    for k in ("resourceGatewayId", "resourceConfigurationGroupId", "resourceConfigurationDefinition", "portRanges", "protocol", "customDomainName"):
        if o.get(k):
            out[k] = o[k]
    out["allowAssociationToShareableServiceNetwork"] = o["allowAssociation"]
    return 201, out


def _update_rcfg(st, g, body, query, region):
    o = _get(st, "rcfg", g[0], "Resource configuration")
    if "allowAssociationToShareableServiceNetwork" in body:
        o["allowAssociation"] = bool(body["allowAssociationToShareableServiceNetwork"])
    if "portRanges" in body:
        for pr in body["portRanges"]:
            if not _PORTS_RE.match(str(pr)):
                raise _Err("ValidationException", f"Invalid port range '{pr}'.", 400)
        o["portRanges"] = body["portRanges"]
    if "resourceConfigurationDefinition" in body and o["type"] != "GROUP":
        o["resourceConfigurationDefinition"] = body["resourceConfigurationDefinition"]
    o["lastUpdatedAt"] = _now()
    return 200, _rcfg_view(o, False)


def _delete_rcfg(st, g, body, query, region):
    o = _get(st, "rcfg", g[0], "Resource configuration")
    if any(a["resourceConfigurationId"] == o["id"] for a in st["snra"].values()):
        raise _Err("ConflictException", f"Resource configuration {o['id']} is associated with a service network; delete the association first.", 409)
    if o["type"] == "GROUP" and any(c.get("resourceConfigurationGroupId") == o["id"] for c in st["rcfg"].values()):
        raise _Err("ConflictException", "Delete the CHILD resource configurations of this group first.", 409)
    del st["rcfg"][o["id"]]
    _drop_tags(st, o["arn"])
    return 202, {}


# ── domain verifications ─────────────────────────────────────────────────────────────
def _dv_view(o):
    return {"id": o["id"], "arn": o["arn"], "domainName": o["domainName"], "status": o["status"], "txtMethodConfig": o["txtMethodConfig"],
            "createdAt": o["createdAt"], **({"lastVerifiedTime": o["lastVerifiedTime"]} if o.get("lastVerifiedTime") else {})}


def _start_dv(st, g, body, query, region):
    dn = str(body.get("domainName") or "").lower()
    if not _DOMAIN_RE.match(dn):
        raise _Err("ValidationException", "domainName is not a valid domain name.", 400)
    if any(d["domainName"] == dn for d in st["dv"].values()):
        raise _Err("ConflictException", f"A verification for {dn} already exists.", 409)
    rid = _rid("dv")
    o = {"id": rid, "arn": _arn(region, "domainverification", rid), "domainName": dn, "status": "PENDING", "createdAt": _now(),
         "txtMethodConfig": {"name": f"_vpc-lattice.{dn}", "value": f"vpc-lattice-verification={uuid.uuid4().hex}"}}
    st["dv"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 201, {k: _dv_view(o)[k] for k in ("id", "arn", "domainName", "status", "txtMethodConfig")}


def _delete_dv(st, g, body, query, region):
    o = _get(st, "dv", g[0], "Domain verification")
    if any(c.get("customDomainName") == o["domainName"] for c in st["rcfg"].values()) and o["status"] == "VERIFIED":
        raise _Err("ConflictException", "The domain is in use by a resource configuration.", 409)
    del st["dv"][o["id"]]
    _drop_tags(st, o["arn"])
    return 204, {}


# ── access log subscriptions ─────────────────────────────────────────────────────────
def _create_als(st, g, body, query, region):
    ident = str(body.get("resourceIdentifier") or "")
    res = None
    for coll in ("sn", "svc"):
        res = res or st[coll].get(ident.rsplit("/", 1)[-1])
    if res is None:
        raise _Err("ResourceNotFoundException", f"Resource {ident} not found.", 404)
    dest = str(body.get("destinationArn") or "")
    if not re.match(r"^arn:aws:(s3|logs|firehose):", dest):
        raise _Err("ValidationException", "destinationArn must be an S3 bucket, CloudWatch log group or Firehose stream ARN.", 400)
    if any(a["resourceId"] == res["id"] and a["destinationArn"] == dest for a in st["als"].values()):
        raise _Err("ConflictException", "That access log subscription already exists.", 409)
    rid = _rid("als")
    o = {"id": rid, "arn": _arn(region, "accesslogsubscription", rid), "resourceId": res["id"], "resourceArn": res["arn"], "destinationArn": dest,
         "createdAt": _now(), "lastUpdatedAt": _now()}
    st["als"][rid] = o
    _resource_tags(st, o["arn"]).update(_tags_in(body))
    return 201, {k: o[k] for k in ("id", "arn", "resourceId", "resourceArn", "destinationArn")}


def _als_view(o):
    return {k: o[k] for k in ("id", "arn", "resourceId", "resourceArn", "destinationArn", "createdAt", "lastUpdatedAt")}


# ── auth policies / resource policies / tags ─────────────────────────────────────────
def _policy_doc(p):
    try:
        d = json.loads(p) if isinstance(p, str) else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not d.get("Statement"):
        raise _Err("ValidationException", "policy must be a JSON policy document with a Statement.", 400)
    return p


def _auth_target(st, ident):
    ident = str(ident)
    rid = ident.rsplit("/", 1)[-1]
    o = st["svc"].get(rid) or st["sn"].get(rid)
    if o is None:
        raise _Err("ResourceNotFoundException", f"Resource {ident} not found.", 404)
    return o


def _put_auth_policy(st, g, body, query, region):
    o = _auth_target(st, g[0])
    if o["authType"] != "AWS_IAM":
        raise _Err("ValidationException", f"Auth policies apply only when authType is AWS_IAM (currently {o['authType']}).", 400)
    st["_L"]["authpol"][o["arn"]] = {"policy": _policy_doc(body.get("policy")), "createdAt": _now(), "lastUpdatedAt": _now()}
    return 200, {"policy": body["policy"], "state": "Active"}


def _get_auth_policy(st, g, body, query, region):
    o = _auth_target(st, g[0])
    p = st["_L"]["authpol"].get(o["arn"])
    if p is None:
        raise _Err("ResourceNotFoundException", f"No auth policy is set on {o['id']}.", 404)
    return 200, {"policy": p["policy"], "state": "Active" if o["authType"] == "AWS_IAM" else "Inactive", "createdAt": p["createdAt"], "lastUpdatedAt": p["lastUpdatedAt"]}


def _delete_auth_policy(st, g, body, query, region):
    o = _auth_target(st, g[0])
    if st["_L"]["authpol"].pop(o["arn"], None) is None:
        raise _Err("ResourceNotFoundException", f"No auth policy is set on {o['id']}.", 404)
    return 204, {}


_SHAREABLE = ("sn", "svc", "rcfg")


def _res_by_arn(st, arn):
    arn = str(arn)
    rid = arn.rsplit("/", 1)[-1]
    for coll in _SHAREABLE:
        o = st[coll].get(rid)
        if o is not None and o["arn"] == arn:
            return o
    raise _Err("ResourceNotFoundException", f"Resource {arn} not found.", 404)


def _put_res_policy(st, g, body, query, region):
    o = _res_by_arn(st, g[0])
    st["_L"]["respol"][o["arn"]] = _policy_doc(body.get("policy"))
    return 200, {}


def _get_res_policy(st, g, body, query, region):
    o = _res_by_arn(st, g[0])
    p = st["_L"]["respol"].get(o["arn"])
    if p is None:
        raise _Err("ResourceNotFoundException", f"No resource policy is set on {o['id']}.", 404)
    return 200, {"policy": p}


def _delete_res_policy(st, g, body, query, region):
    o = _res_by_arn(st, g[0])
    if st["_L"]["respol"].pop(o["arn"], None) is None:
        raise _Err("ResourceNotFoundException", f"No resource policy is set on {o['id']}.", 404)
    return 204, {}


def _taggable(st, arn):
    arn = str(arn)
    if not arn.startswith("arn:aws:vpc-lattice:"):
        raise _Err("ValidationException", "resourceArn must be a VPC Lattice ARN.", 400)
    rid = arn.rsplit("/", 1)[-1]
    for coll in ("sn", "svc", "listener", "rule", "tg", "rgw", "rcfg", "snva", "snsa", "snra", "dv", "als"):
        o = st[coll].get(rid)
        if o is not None and o["arn"] == arn:
            return arn
    raise _Err("ResourceNotFoundException", f"Resource {arn} not found.", 404)


def _tag_list(st, g, body, query, region):
    return 200, {"tags": dict(_resource_tags(st, _taggable(st, g[0])))}


def _tag_put(st, g, body, query, region):
    arn = _taggable(st, g[0])
    new = _tags_in(body)
    cur = _resource_tags(st, arn)
    if len({**cur, **new}) > 50:
        raise _Err("ValidationException", "A resource can have at most 50 tags.", 400)
    cur.update(new)
    return 200, {}


def _tag_del(st, g, body, query, region):
    arn = _taggable(st, g[0])
    keys = (query or {}).get("tagKeys") or []
    for k in ([keys] if isinstance(keys, str) else keys):
        _resource_tags(st, arn).pop(k, None)
    return 200, {}


def _get_of(coll, what, view):
    def fn(st, g, body, query, region):
        return 200, view(st, _get(st, coll, g[0], what))
    return fn


def _list_of(coll, view, flt=None):
    def fn(st, g, body, query, region):
        items = [view(st, o) for o in st[coll].values() if not flt or flt(o, query)]
        return _page(items, query)
    return fn


def _tg_get(st, o):
    return {"id": o["id"], "arn": o["arn"], "name": o["name"], "type": o["type"], "config": o["config"], "status": o["status"],
            "serviceArns": _tg_service_arns(st, o["id"]), "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}


def _tg_summary(st, o):
    s = {"id": o["id"], "arn": o["arn"], "name": o["name"], "type": o["type"], "status": o["status"], "serviceArns": _tg_service_arns(st, o["id"]),
         "createdAt": o["createdAt"], "lastUpdatedAt": o["lastUpdatedAt"]}
    for k in ("port", "protocol", "ipAddressType", "vpcIdentifier"):
        if o["config"].get(k) is not None:
            s[k] = o["config"][k]
    return s


_ROUTES = []


def _route(method, pattern, fn):
    _ROUTES.append((method, re.compile("^" + pattern + "$"), fn))


_ID = r"([^/]+)"
_route("POST", "/servicenetworks", _create_service_network)
_route("GET", "/servicenetworks", _list_of("sn", lambda st, o: _sn_view(st, o, True)))
_route("GET", f"/servicenetworks/{_ID}", _get_of("sn", "Service network", lambda st, o: _sn_view(st, o)))
_route("PATCH", f"/servicenetworks/{_ID}", _update_service_network)
_route("DELETE", f"/servicenetworks/{_ID}", _delete_service_network)
_route("POST", "/services", _create_service)
_route("GET", "/services", _list_of("svc", lambda st, o: _svc_view(o, True)))
_route("GET", f"/services/{_ID}", _get_of("svc", "Service", lambda st, o: _svc_view(o)))
_route("PATCH", f"/services/{_ID}", _update_service)
_route("DELETE", f"/services/{_ID}", _delete_service)
_route("POST", f"/services/{_ID}/listeners", _create_listener)
_route("GET", f"/services/{_ID}/listeners", _list_listeners)
_route("GET", f"/services/{_ID}/listeners/{_ID}", lambda st, g, b, q, r: (200, _listener_view(_listener_of(st, g[0], g[1]))))
_route("PATCH", f"/services/{_ID}/listeners/{_ID}", _update_listener)
_route("DELETE", f"/services/{_ID}/listeners/{_ID}", _delete_listener)
_route("POST", f"/services/{_ID}/listeners/{_ID}/rules", _create_rule)
_route("PATCH", f"/services/{_ID}/listeners/{_ID}/rules", _batch_update_rule)
_route("GET", f"/services/{_ID}/listeners/{_ID}/rules",
       lambda st, g, b, q, r: _page([_rule_view(x, True) for x in sorted((x for x in st["rule"].values() if x["listenerId"] == _listener_of(st, g[0], g[1])["id"]),
                                                                          key=lambda x: (x["priority"] is None, x["priority"] or 0))], q))
_route("GET", f"/services/{_ID}/listeners/{_ID}/rules/{_ID}", lambda st, g, b, q, r: (200, _rule_view(_rule_of(st, g)[1])))
_route("PATCH", f"/services/{_ID}/listeners/{_ID}/rules/{_ID}", _update_rule)
_route("DELETE", f"/services/{_ID}/listeners/{_ID}/rules/{_ID}", _delete_rule)
_route("POST", "/targetgroups", _create_target_group)
_route("GET", "/targetgroups", _list_of("tg", _tg_summary, lambda o, q: (not _q1(q, "targetGroupType") or o["type"] == _q1(q, "targetGroupType"))
                                         and (not _q1(q, "vpcIdentifier") or o["config"].get("vpcIdentifier") == _q1(q, "vpcIdentifier"))))
_route("GET", f"/targetgroups/{_ID}", _get_of("tg", "Target group", _tg_get))
_route("PATCH", f"/targetgroups/{_ID}", _update_target_group)
_route("DELETE", f"/targetgroups/{_ID}", _delete_target_group)
_route("POST", f"/targetgroups/{_ID}/registertargets", _register_targets)
_route("POST", f"/targetgroups/{_ID}/deregistertargets", _deregister_targets)
_route("POST", f"/targetgroups/{_ID}/listtargets", _list_targets)
_route("POST", "/vyomi/invoke", _invoke)
_route("POST", "/servicenetworkvpcassociations", _create_snva)
_route("GET", "/servicenetworkvpcassociations", _list_snva)
_route("GET", f"/servicenetworkvpcassociations/{_ID}", _get_of("snva", "Association", lambda st, o: _snva_view(o)))
_route("PATCH", f"/servicenetworkvpcassociations/{_ID}", _update_snva)
_route("DELETE", f"/servicenetworkvpcassociations/{_ID}", _delete_assoc("snva"))
_route("POST", "/servicenetworkserviceassociations", _create_snsa)
_route("GET", "/servicenetworkserviceassociations", _list_snsa)
_route("GET", f"/servicenetworkserviceassociations/{_ID}", _get_of("snsa", "Association", lambda st, o: _snsa_view(o)))
_route("DELETE", f"/servicenetworkserviceassociations/{_ID}", _delete_assoc("snsa"))
_route("POST", "/servicenetworkresourceassociations", _create_snra)
_route("GET", "/servicenetworkresourceassociations", _list_snra)
_route("GET", f"/servicenetworkresourceassociations/{_ID}", _get_of("snra", "Association", lambda st, o: _snra_view(o)))
_route("DELETE", f"/servicenetworkresourceassociations/{_ID}", _delete_assoc("snra"))
_route("POST", "/resourcegateways", _create_rgw)
_route("GET", "/resourcegateways", _list_of("rgw", lambda st, o: _rgw_view(o, True)))
_route("GET", f"/resourcegateways/{_ID}", _get_of("rgw", "Resource gateway", lambda st, o: _rgw_view(o)))
_route("PATCH", f"/resourcegateways/{_ID}", _update_rgw)
_route("DELETE", f"/resourcegateways/{_ID}", _delete_rgw)
_route("POST", "/resourceconfigurations", _create_rcfg)
_route("GET", "/resourceconfigurations", _list_of("rcfg", lambda st, o: _rcfg_view(o, True), lambda o, q: (not _q1(q, "resourceGatewayIdentifier") or o.get("resourceGatewayId") == _q1(q, "resourceGatewayIdentifier").rsplit("/", 1)[-1])))
_route("GET", f"/resourceconfigurations/{_ID}", _get_of("rcfg", "Resource configuration", lambda st, o: _rcfg_view(o)))
_route("PATCH", f"/resourceconfigurations/{_ID}", _update_rcfg)
_route("DELETE", f"/resourceconfigurations/{_ID}", _delete_rcfg)
_route("POST", "/domainverifications", _start_dv)
_route("GET", "/domainverifications", _list_of("dv", lambda st, o: _dv_view(o)))
_route("GET", f"/domainverifications/{_ID}", _get_of("dv", "Domain verification", lambda st, o: _dv_view(o)))
_route("DELETE", f"/domainverifications/{_ID}", _delete_dv)
_route("POST", "/accesslogsubscriptions", _create_als)
_route("GET", "/accesslogsubscriptions", lambda st, g, b, q, r: _page([_als_view(a) for a in st["als"].values()
                                                                        if not _q1(q, "resourceIdentifier") or a["resourceId"] == _q1(q, "resourceIdentifier").rsplit("/", 1)[-1]], q))
_route("GET", f"/accesslogsubscriptions/{_ID}", _get_of("als", "Access log subscription", lambda st, o: _als_view(o)))
_route("DELETE", f"/accesslogsubscriptions/{_ID}", lambda st, g, b, q, r: (st["als"].pop(_get(st, "als", g[0], "Access log subscription")["id"]) and (204, {})))
_route("PUT", "/authpolicy/(.+)", _put_auth_policy)
_route("GET", "/authpolicy/(.+)", _get_auth_policy)
_route("DELETE", "/authpolicy/(.+)", _delete_auth_policy)
_route("PUT", "/resourcepolicy/(.+)", _put_res_policy)
_route("GET", "/resourcepolicy/(.+)", _get_res_policy)
_route("DELETE", "/resourcepolicy/(.+)", _delete_res_policy)
_route("GET", "/tags/(.+)", _tag_list)
_route("POST", "/tags/(.+)", _tag_put)
_route("DELETE", "/tags/(.+)", _tag_del)

_MUTATING = {"POST", "PUT", "DELETE", "PATCH"}


def dispatch(store, method: str, raw_path: str, query: dict, headers: dict, body: bytes) -> dict:
    path = urllib.parse.unquote(raw_path.split("?", 1)[0])
    method = (method or "GET").upper()
    region = _region(headers)

    def resp(status, doc, err=None):
        h = {"content-type": "application/json", "x-amzn-requestid": uuid.uuid4().hex}
        if err:
            h["x-amzn-errortype"] = err
        return {"status": status, "headers": h, "body": (json.dumps(doc).encode() if status != 204 else b"")}

    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return resp(400, {"message": "The request body must be a JSON object"}, "ValidationException")
    st = _st(store)
    for m, rx, fn in _ROUTES:
        mt = rx.match(path)
        if m == method and mt:
            try:
                out = fn(st, list(mt.groups()), p, dict(query or {}), region)
            except _Err as e:
                return resp(e.status, {"message": e.message}, e.code)
            return resp(out[0], out[1])
    return resp(404, {"message": f"Unknown VPC Lattice operation: {method} {path}"}, "ResourceNotFoundException")
