# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""VPC Lattice data-plane EVALUATOR (substrate-independent, pure Python, Pyodide-loadable).

Evaluates what Lattice would do with a request, from the simulator's own control-plane state:

  caller VPC -> its service-network VPC association -> the service must be associated with that same service
  network (otherwise the service DNS name does not resolve there) -> association security groups vs the caller
  -> listener (port + protocol) -> AuthType AWS_IAM (service + service-network auth policies, deny-wins,
  implicit deny) -> rules in ascending priority (method / path exact|prefix / header exact|prefix|contains,
  all conditions AND) -> default rule -> fixedResponse | weighted forward over target groups -> healthy target.

Target health is DERIVED, not probed: the simulator does not send HTTP health checks. An INSTANCE/IP target is
HEALTHY when it resolves to a running EC2 instance in the target group's VPC and one of its security groups admits
the health-check port from the Lattice managed range 169.254.171.0/24 (or a lattice prefix list); a stopped
instance is UNAVAILABLE; an address nothing in the model owns, or a security group that blocks Lattice, is
UNHEALTHY (Target.Timeout). LAMBDA / ALB targets are HEALTHY (their existence is checked at registration).
The health-check path/matcher cannot be evaluated (no application to answer).
"""
from __future__ import annotations

import fnmatch
import ipaddress
import json
import random

LATTICE_SRC = "169.254.171.1"      # first address of the managed health-check / forwarding range 169.254.171.0/24


def _perm_admits(perm: dict, protocol: str, port: int, src_ip: str, src_sgs) -> bool:
    proto = str(perm.get("protocol", "-1"))
    if proto not in ("-1", protocol, "6" if protocol == "tcp" else protocol):
        return False
    if proto != "-1" and perm.get("from_port") is not None and perm.get("to_port") is not None:
        if not (perm["from_port"] <= port <= perm["to_port"]):
            return False
    for cidr in perm.get("cidrs", []) or []:
        try:
            if ipaddress.ip_address(src_ip) in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    if any(sg in (src_sgs or []) for sg in perm.get("sgs", []) or []):
        return True
    for pl in perm.get("prefix_lists", []) or []:      # the managed Lattice prefix list
        if "lattice" in str(pl).lower():
            return True
    return False


def sgs_admit(m: dict, sg_ids, port: int, src_ip: str, src_sgs=()) -> bool:
    for sid in sg_ids or []:
        sg = (m.get("sgs") or {}).get(sid) or {}
        if any(_perm_admits(p, "tcp", port, src_ip, src_sgs) for p in sg.get("ingress", [])):
            return True
    return False


def _find_owner(m: dict, ip: str):
    for inst in (m.get("instances") or {}).values():
        if inst.get("private_ip") == ip:
            return inst
    return None


def target_health(st: dict, tg: dict, target: dict) -> tuple:
    """-> (status, reasonCode|None) for one registered target (no probing; see module doc)."""
    from core import vpc_lattice_core as lc  # local import: avoid a cycle at module load
    if not lc._tg_users(st, tg["id"]):
        return "UNUSED", "Target.NotInUse"
    ttype = tg["type"]
    if ttype in ("LAMBDA", "ALB"):
        return "HEALTHY", None
    hc = tg["config"].get("healthCheck") or {}
    m = st["_m"]
    tid = str(target["id"])
    inst = (m.get("instances") or {}).get(tid) if ttype == "INSTANCE" else _find_owner(m, tid)
    if inst is None:
        return "UNHEALTHY", "Target.Timeout"
    if inst.get("state") != "running":
        return "UNAVAILABLE", "Target.InvalidState"
    vpc = tg["config"].get("vpcIdentifier")
    if inst.get("vpc_id") and vpc and inst["vpc_id"] != vpc:
        return "UNAVAILABLE", "Target.NotInVpc"
    if hc.get("enabled") is False or tg["config"].get("protocol") == "TCP":
        return "HEALTHY", ("Target.HealthCheckDisabled" if hc.get("enabled") is False else None)
    port = int(hc.get("port") or target.get("port") or tg["config"].get("port") or 80)
    if not sgs_admit(m, inst.get("sg_ids") or inst.get("security_group_ids") or [], port, LATTICE_SRC):
        return "UNHEALTHY", "Target.Timeout"
    return "HEALTHY", None


# ── rule matching ────────────────────────────────────────────────────────────────────────
def _s(v, cs):
    return str(v) if cs else str(v).lower()


def rule_matches(match: dict, method: str, path: str, headers: dict) -> bool:
    hm = (match or {}).get("httpMatch") or {}
    if hm.get("method") and hm["method"].upper() != (method or "GET").upper():
        return False
    pm = hm.get("pathMatch")
    if pm:
        cs = pm.get("caseSensitive", True)
        m = pm.get("match") or {}
        p = _s(path or "/", cs)
        if "exact" in m and p != _s(m["exact"], cs):
            return False
        if "prefix" in m and not p.startswith(_s(m["prefix"], cs)):
            return False
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    for h in hm.get("headerMatches") or []:
        val = lower.get(str(h["name"]).lower())
        if val is None:
            return False
        cs = h.get("caseSensitive", True)
        mm = h.get("match") or {}
        v = _s(val, cs)
        if "exact" in mm and v != _s(mm["exact"], cs):
            return False
        if "prefix" in mm and not v.startswith(_s(mm["prefix"], cs)):
            return False
        if "contains" in mm and _s(mm["contains"], cs) not in v:
            return False
    return True


# ── auth policy (AuthType AWS_IAM) ───────────────────────────────────────────────────────
def _listify(x):
    return x if isinstance(x, list) else [x]


def _principal_ok(stmt: dict, principal: str) -> bool:
    p = stmt.get("Principal")
    if p == "*":
        return True
    if isinstance(p, dict):
        for a in _listify(p.get("AWS", [])):
            if a == "*" or (principal and (a == principal or fnmatch.fnmatch(principal, a))):
                return True
    return False


def _cond_ok(cond: dict, ctx: dict):
    """-> True/False, or None when a condition key/operator is not modelled."""
    for op, kv in (cond or {}).items():
        base = op.split(":")[-1]
        for key, vals in kv.items():
            have = ctx.get(key.lower())
            if have is None:
                if base.lower() in ("stringnotequals", "stringnotlike"):
                    continue
                return False if key.lower().startswith("vpc-lattice-svcs:requestheader/") else None
            vs = [str(v) for v in _listify(vals)]
            if base in ("StringEquals", "StringEqualsIgnoreCase"):
                ok = any((str(have) == v) if base == "StringEquals" else str(have).lower() == v.lower() for v in vs)
            elif base == "StringNotEquals":
                ok = all(str(have) != v for v in vs)
            elif base == "StringLike":
                ok = any(fnmatch.fnmatchcase(str(have), v) for v in vs)
            elif base == "StringNotLike":
                ok = all(not fnmatch.fnmatchcase(str(have), v) for v in vs)
            else:
                return None
            if not ok:
                return False
    return True


def auth_decision(policy_json, principal: str, ctx: dict) -> tuple:
    """-> ('allow'|'deny'|'implicit', notes[])  Explicit Deny beats Allow; no Allow = implicit deny."""
    notes, allowed = [], False
    try:
        doc = json.loads(policy_json) if isinstance(policy_json, str) else policy_json
    except ValueError:
        return "implicit", ["policy is not valid JSON"]
    for s in _listify((doc or {}).get("Statement", [])):
        acts = [a for a in _listify(s.get("Action", []))]
        if not any(a in ("*", "vpc-lattice-svcs:*", "vpc-lattice-svcs:Invoke") or fnmatch.fnmatchcase("vpc-lattice-svcs:Invoke", a) for a in acts):
            continue
        if not _principal_ok(s, principal):
            continue
        c = _cond_ok(s.get("Condition") or {}, ctx)
        if c is None:
            notes.append("a Condition key/operator is not modelled; statement skipped")
            continue
        if not c:
            continue
        if s.get("Effect") == "Deny":
            return "deny", notes
        if s.get("Effect") == "Allow":
            allowed = True
    return ("allow" if allowed else "implicit"), notes


# ── the evaluator ──────────────────────────────────────────────────────────────────────────
def _find_service(st: dict, host: str):
    h = (host or "").lower().rstrip(".")
    for s in st["svc"].values():
        if h in (s["id"].lower(), s["name"].lower(), s["dnsEntry"]["domainName"].lower(), str(s.get("customDomainName") or "").lower()):
            return s
    return None


def invoke(st: dict, req: dict) -> dict:
    """Evaluate one request. req: host, port, protocol(HTTP|HTTPS), method, path, headers, principal,
    sourceVpcId | sourceInstanceId, seed. Never raises for a 'denied' outcome: returns the HTTP-level result."""
    m = st["_m"]
    steps = []
    out = {"steps": steps, "statusCode": None, "resolved": False}

    def fin(code, why, **kw):
        out.update({"statusCode": code, "message": why, "outcome": kw.pop("outcome", "RESPONDED" if code else "NO_RESPONSE"), **kw})
        steps.append({"step": "result", "statusCode": code, "detail": why})
        return out

    svc = _find_service(st, req.get("host"))
    if svc is None:
        return fin(None, f"host {req.get('host')!r} does not resolve: no such Lattice service", dnsResult="NXDOMAIN")
    src_inst = (m.get("instances") or {}).get(str(req.get("sourceInstanceId") or ""))
    vpc = req.get("sourceVpcId") or (src_inst or {}).get("vpc_id")
    if not vpc:
        return fin(None, "sourceVpcId or sourceInstanceId is required (Lattice names resolve per VPC)", dnsResult="NXDOMAIN")
    assoc = next((a for a in st["snva"].values() if a["vpcId"] == vpc), None)
    if assoc is None:
        return fin(None, f"VPC {vpc} has no service-network VPC association: the service DNS name does not resolve there", dnsResult="NXDOMAIN")
    link = next((a for a in st["snsa"].values() if a["serviceNetworkId"] == assoc["serviceNetworkId"] and a["serviceId"] == svc["id"]), None)
    if link is None:
        return fin(None, f"service {svc['name']} is not associated with service network {assoc['serviceNetworkName']}", dnsResult="NXDOMAIN")
    out["resolved"] = True
    out.update({"dnsResult": "169.254.171.x (link-local Lattice address)", "serviceId": svc["id"], "serviceNetworkId": assoc["serviceNetworkId"]})
    steps.append({"step": "dns", "detail": f"{svc['name']} resolves in {vpc} via {assoc['id']}"})

    proto0 = (req.get("protocol") or "").upper()
    port = int(req.get("port") or (443 if proto0 == "HTTPS" else 80))
    proto = proto0 or ("HTTPS" if port == 443 else "HTTP")
    src_ip = (src_inst or {}).get("private_ip") or req.get("sourceIp") or "10.0.0.1"
    if assoc.get("securityGroupIds") and not sgs_admit(m, assoc["securityGroupIds"], port, src_ip, (src_inst or {}).get("sg_ids") or []):
        return fin(None, f"association security groups {assoc['securityGroupIds']} do not allow {src_ip} to port {port}: connection timed out", connection="TIMEOUT")
    steps.append({"step": "association-security-groups", "detail": "allowed" if assoc.get("securityGroupIds") else "no SGs on the association (all allowed)"})

    lis = next((l for l in st["listener"].values() if l["serviceId"] == svc["id"] and l["port"] == port and
                (l["protocol"] == proto or (l["protocol"] == "TLS_PASSTHROUGH" and proto == "HTTPS"))), None)
    if lis is None:
        return fin(None, f"service {svc['name']} has no {proto} listener on port {port}: connection refused", connection="REFUSED")
    steps.append({"step": "listener", "listenerId": lis["id"], "detail": f"{lis['protocol']}:{lis['port']}"})

    method, path, headers = (req.get("method") or "GET").upper(), req.get("path") or "/", req.get("headers") or {}
    # auth: the service's own policy AND the service network's policy are both evaluated
    if svc["authType"] == "AWS_IAM" or st["sn"][assoc["serviceNetworkId"]]["authType"] == "AWS_IAM":
        principal = req.get("principal") or ""
        ctx = {"vpc-lattice-svcs:requestmethod": method, "vpc-lattice-svcs:port": str(port), "vpc-lattice-svcs:requestpath": path,
               "vpc-lattice-svcs:servicenetworkarn": assoc["serviceNetworkArn"],
               "vpc-lattice-svcs:servicearn": svc["arn"], "vpc-lattice-svcs:sourcevpc": vpc, "aws:principalarn": principal,
               "aws:sourcevpc": vpc}
        for hk, hv in headers.items():
            ctx[f"vpc-lattice-svcs:requestheader/{hk.lower()}"] = hv
        notes = []
        for owner in (svc, st["sn"][assoc["serviceNetworkId"]]):
            if owner["authType"] != "AWS_IAM":
                continue
            if not principal:
                return fin(403, "AccessDeniedException: request is not SigV4-signed (authType AWS_IAM requires a principal)", authDecision="no-principal")
            pol = st["_L"]["authpol"].get(owner["arn"])
            dec, n = auth_decision(pol["policy"], principal, ctx) if pol else ("implicit", ["no auth policy attached"])
            notes += n
            steps.append({"step": "auth", "on": owner["arn"], "decision": dec})
            if dec != "allow":
                return fin(403, f"AccessDeniedException: {'explicit deny' if dec == 'deny' else 'implicit deny'} by the auth policy on {owner['name']}", authDecision=dec, notes=notes)

    rules = sorted((r for r in st["rule"].values() if r["listenerId"] == lis["id"] and not r["isDefault"]), key=lambda r: r["priority"])
    if lis["protocol"] == "TLS_PASSTHROUGH":
        rules = []
    chosen = next((r for r in rules if rule_matches(r["match"], method, path, headers)), None)
    if chosen is None:
        chosen = next(r for r in st["rule"].values() if r["listenerId"] == lis["id"] and r["isDefault"])
    out["matchedRule"] = {"id": chosen["id"], "name": chosen["name"], "priority": chosen["priority"], "isDefault": chosen["isDefault"]}
    steps.append({"step": "rule", **out["matchedRule"]})
    act = chosen["action"]
    if act.get("fixedResponse"):
        return fin(act["fixedResponse"]["statusCode"], "fixed response from rule " + chosen["name"], action="fixedResponse")
    rng = random.Random(req.get("seed")) if req.get("seed") is not None else random.Random()
    cands = []
    for t in act["forward"]["targetGroups"]:
        tg = st["tg"].get(t["targetGroupIdentifier"])
        if tg is None or t["weight"] <= 0:
            continue
        healthy = [x for x in tg["targets"].values() if target_health(st, tg, x)[0] == "HEALTHY"]
        steps.append({"step": "target-group", "targetGroupId": tg["id"], "weight": t["weight"], "registered": len(tg["targets"]), "healthy": len(healthy)})
        if healthy:
            cands.append((tg, t["weight"], healthy))
    if not cands:
        return fin(503, "no healthy targets in any weighted target group (Lattice answers 503)", action="forward")
    tg, _, healthy = rng.choices(cands, weights=[c[1] for c in cands])[0]
    tgt = rng.choice(healthy)
    return fin(None, f"forwarded to {tgt['id']}" + (f":{tgt['port']}" if tgt.get("port") else ""), action="forward",
               targetGroupId=tg["id"], target=tgt, outcome="FORWARDED")
