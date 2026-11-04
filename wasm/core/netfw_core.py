# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Network Firewall control plane (JSON 1.0, X-Amz-Target NetworkFirewall_20201112.*) over the
shared VPC model (m["netfw"]), merged into AwsWireRouter like every other JSON core.

Real state + validation: firewalls (VPC/subnet mappings must exist, one subnet per AZ, protection
flags honoured, endpoints reported per AZ), firewall policies (required stateless default actions,
rule-group references must exist and match their type), rule groups (stateless priority/match
attributes, stateful 5-tuple rules, domain lists, Suricata-compatible rule strings parsed and
validated, capacity enforced), TLS inspection configurations, resource policies, logging
configurations, VPC endpoint associations, tags. Every Update* needs the current UpdateToken
(optimistic concurrency, InvalidTokenException) exactly like AWS.

`evaluate_packet()` is a real rule evaluator (stateless priority order + default actions, then the
stateful engine: 5-tuple rules, domain allow/deny lists, Suricata pass/drop/reject/alert) used by
the tests; the netsim path does NOT insert the firewall endpoint into routing (see
core/capabilities/aws/vpc.json `aws.vpc.network-firewall`)."""
from __future__ import annotations

import ipaddress
import json
import re
import uuid
from dataclasses import dataclass, field

ACCOUNT = "123456789012"
REGION = "us-east-1"


@dataclass
class NfwResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class NfwError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _V():
    from core import vpc_core
    return vpc_core


def _st(store) -> dict:
    m = _V()._model(store)
    n = m.setdefault("netfw", {})
    for k in ("firewalls", "policies", "rule_groups", "tls", "resource_policies", "logging", "assocs", "tags"):
        n.setdefault(k, {})
    return n


def _arn(kind, name):
    return f"arn:aws:network-firewall:{REGION}:{ACCOUNT}:{kind}/{name}"


def _now():
    import time
    return time.time()


def _tok():
    return str(uuid.uuid4())


def _tags_in(p):
    return {t["Key"]: t.get("Value", "") for t in (p.get("Tags") or [])}


def _tags_out(d):
    return [{"Key": k, "Value": v} for k, v in (d or {}).items()]


def _need(p, key):
    v = p.get(key)
    if v in (None, "", [], {}):
        raise NfwError("InvalidRequestException", f"{key} is required")
    return v


_NAME = re.compile(r"^[a-zA-Z0-9-]{1,128}$")


def _check_name(name, what):
    if not _NAME.match(str(name or "")):
        raise NfwError("InvalidRequestException", f"{what} must be 1-128 characters of letters, numbers and hyphens")


def _lookup(coll, arn=None, name=None, what="resource"):
    for k, v in coll.items():
        if (arn and v["arn"] == arn) or (name and v["name"] == name):
            return v
    raise NfwError("ResourceNotFoundException", f"{what} {arn or name} not found", 400)


def _check_token(res, token):
    if token != res["token"]:
        raise NfwError("InvalidTokenException", "The token you provided is stale or is not valid for the resource.")


def _bump(res):
    res["token"] = _tok()
    res["updated"] = _now()


# ── rule validation ──────────────────────────────────────────────────────
_PROTOS = {"IP": None, "TCP": 6, "UDP": 17, "ICMP": 1, "HTTP": 6, "TLS": 6, "DNS": 17, "FTP": 6, "SMB": 6, "SSH": 6, "SMTP": 6, "IMAP": 6, "NTP": 17, "DCERPC": 6, "DHCP": 17,
           "KRB5": 17, "SNMP": 17, "TFTP": 17, "IKEV2": 17, "MSN": 6, "HTTP2": 6, "QUIC": 17}
_SURI_RE = re.compile(r"^(?P<action>pass|drop|reject|alert)\s+(?P<proto>\S+)\s+(?P<src>\S+)\s+(?P<sport>\S+)\s+(?P<dir>->|<>)\s+(?P<dst>\S+)\s+(?P<dport>\S+)\s*\((?P<opts>.*)\)\s*$", re.S)


def parse_suricata(text):
    """Parse a Suricata-compatible rule string (one rule per line, # comments) into rule dicts; validate."""
    rules = []
    for n, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _SURI_RE.match(line)
        if not m:
            raise NfwError("InvalidRequestException", f"Rules string line {n}: not a valid Suricata rule header: {line[:60]}")
        d = m.groupdict()
        if d["proto"].upper() not in _PROTOS:
            raise NfwError("InvalidRequestException", f"Rules string line {n}: unsupported protocol {d['proto']}")
        opts = [o.strip() for o in re.split(r";(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", d["opts"]) if o.strip()]
        kv = {}
        for o in opts:
            k, _, v = o.partition(":")
            kv.setdefault(k.strip(), []).append(v.strip().strip('"'))
        if "sid" not in kv:
            raise NfwError("InvalidRequestException", f"Rules string line {n}: every rule needs a sid option")
        if not kv["sid"][0].isdigit():
            raise NfwError("InvalidRequestException", f"Rules string line {n}: sid must be a number")
        rules.append({"action": d["action"], "proto": d["proto"].upper(), "src": d["src"], "sport": d["sport"], "bidir": d["dir"] == "<>",
                      "dst": d["dst"], "dport": d["dport"], "sid": int(kv["sid"][0]), "opts": kv})
    if len({r["sid"] for r in rules}) != len(rules):
        raise NfwError("InvalidRequestException", "Rules string has duplicate sid values")
    return rules


def _validate_addr(a, what):
    t = a.get("AddressDefinition", "")
    try:
        ipaddress.ip_network(t, strict=False)
    except ValueError:
        raise NfwError("InvalidRequestException", f"{what} address {t!r} is not a valid CIDR")


def _validate_ports(r, what):
    for pr in r or []:
        lo, hi = pr.get("FromPort"), pr.get("ToPort")
        if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi <= 65535):
            raise NfwError("InvalidRequestException", f"{what} port range {lo}-{hi} is invalid")


def _validate_stateless(rg):
    rules = (rg.get("RulesSource", {}).get("StatelessRulesAndCustomActions") or {}).get("StatelessRules") or []
    seen = set()
    for r in rules:
        pr = r.get("Priority")
        if not isinstance(pr, int) or pr < 1 or pr > 65535:
            raise NfwError("InvalidRequestException", "Stateless rule Priority must be 1-65535")
        if pr in seen:
            raise NfwError("InvalidRequestException", f"Duplicate stateless rule priority {pr}")
        seen.add(pr)
        ma = r.get("RuleDefinition", {}).get("MatchAttributes", {})
        for a in ma.get("Sources", []): _validate_addr(a, "source")
        for a in ma.get("Destinations", []): _validate_addr(a, "destination")
        _validate_ports(ma.get("SourcePorts"), "source"); _validate_ports(ma.get("DestinationPorts"), "destination")
        acts = r.get("RuleDefinition", {}).get("Actions") or []
        if not acts:
            raise NfwError("InvalidRequestException", "A stateless rule needs at least one action")
        defs = {a["ActionName"] for a in (rg.get("RulesSource", {}).get("StatelessRulesAndCustomActions", {}).get("CustomActions") or [])}
        for a in acts:
            if a not in ("aws:pass", "aws:drop", "aws:forward_to_sfe") and a not in defs:
                raise NfwError("InvalidRequestException", f"Unknown stateless action {a}")
    return len(rules)


def _validate_stateful(rg):
    src = rg.get("RulesSource", {})
    if sum(k in src for k in ("RulesString", "RulesSourceList", "StatefulRules")) != 1:
        raise NfwError("InvalidRequestException", "RulesSource needs exactly one of RulesString, RulesSourceList or StatefulRules")
    if "RulesString" in src:
        return len(parse_suricata(src["RulesString"]))
    if "RulesSourceList" in src:
        rl = src["RulesSourceList"]
        if rl.get("GeneratedRulesType") not in ("ALLOWLIST", "DENYLIST") or not rl.get("Targets") or not set(rl.get("TargetTypes") or []) <= {"HTTP_HOST", "TLS_SNI"} or not rl.get("TargetTypes"):
            raise NfwError("InvalidRequestException", "RulesSourceList needs GeneratedRulesType (ALLOWLIST|DENYLIST), Targets and TargetTypes (HTTP_HOST|TLS_SNI)")
        return len(rl["Targets"]) * len(rl["TargetTypes"])
    rules = src["StatefulRules"]
    for r in rules:
        if r.get("Action") not in ("PASS", "DROP", "ALERT", "REJECT"):
            raise NfwError("InvalidRequestException", "Stateful rule Action must be PASS, DROP, ALERT or REJECT")
        h = r.get("Header", {})
        if str(h.get("Protocol", "")).upper() not in _PROTOS or h.get("Direction") not in ("FORWARD", "ANY"):
            raise NfwError("InvalidRequestException", "Stateful rule Header needs a supported Protocol and Direction FORWARD|ANY")
        for k in ("Source", "Destination"):
            v = h.get(k, "")
            if v != "ANY":
                try: ipaddress.ip_network(v, strict=False)
                except ValueError: raise NfwError("InvalidRequestException", f"Stateful rule {k} {v!r} is not ANY or a CIDR")
    return len(rules)


# ── firewall policies ────────────────────────────────────────────────────
def _validate_policy(n, fp):
    for k in ("StatelessDefaultActions", "StatelessFragmentDefaultActions"):
        if not fp.get(k):
            raise NfwError("InvalidRequestException", f"FirewallPolicy.{k} is required")
        if sum(a in ("aws:pass", "aws:drop", "aws:forward_to_sfe") for a in fp[k]) != 1:
            custom = {a["ActionName"] for a in fp.get("StatelessCustomActions", [])}
            if not all(a in custom or a.startswith("aws:") for a in fp[k]):
                raise NfwError("InvalidRequestException", f"{k} contains an unknown action")
    prios = set()
    for ref in fp.get("StatelessRuleGroupReferences", []):
        rg = next((x for x in n["rule_groups"].values() if x["arn"] == ref.get("ResourceArn")), None)
        if rg is None:
            raise NfwError("ResourceNotFoundException", f"Rule group {ref.get('ResourceArn')} not found")
        if rg["type"] != "STATELESS":
            raise NfwError("InvalidRequestException", "StatelessRuleGroupReferences must reference STATELESS rule groups")
        if ref.get("Priority") in prios:
            raise NfwError("InvalidRequestException", f"Duplicate stateless rule group priority {ref.get('Priority')}")
        prios.add(ref.get("Priority"))
    for ref in fp.get("StatefulRuleGroupReferences", []):
        rg = next((x for x in n["rule_groups"].values() if x["arn"] == ref.get("ResourceArn")), None)
        if rg is None:
            raise NfwError("ResourceNotFoundException", f"Rule group {ref.get('ResourceArn')} not found")
        if rg["type"] != "STATEFUL":
            raise NfwError("InvalidRequestException", "StatefulRuleGroupReferences must reference STATEFUL rule groups")
    order = fp.get("StatefulEngineOptions", {}).get("RuleOrder", "DEFAULT_ACTION_ORDER")
    if fp.get("StatefulDefaultActions") and order != "STRICT_ORDER":
        raise NfwError("InvalidRequestException", "StatefulDefaultActions requires StatefulEngineOptions.RuleOrder=STRICT_ORDER")
    return fp


def _create_policy(store, p):
    n = _st(store); name = _need(p, "FirewallPolicyName"); _check_name(name, "FirewallPolicyName")
    if any(x["name"] == name for x in n["policies"].values()):
        raise NfwError("InvalidRequestException", f"A firewall policy named {name} already exists")
    fp = _validate_policy(n, _need(p, "FirewallPolicy"))
    rid = str(uuid.uuid4())
    r = {"id": rid, "name": name, "arn": _arn("firewall-policy", name), "policy": fp, "description": p.get("Description", ""), "token": _tok(), "tags": _tags_in(p), "updated": _now()}
    n["policies"][rid] = r
    return {"UpdateToken": r["token"], "FirewallPolicyResponse": _pol_resp(n, r)}


def _pol_resp(n, r):
    return {"FirewallPolicyName": r["name"], "FirewallPolicyArn": r["arn"], "FirewallPolicyId": r["id"], "Description": r["description"], "FirewallPolicyStatus": "ACTIVE",
            "Tags": _tags_out(r["tags"]), "ConsumedStatelessRuleCapacity": sum(_cap(n, x["ResourceArn"]) for x in r["policy"].get("StatelessRuleGroupReferences", [])),
            "ConsumedStatefulRuleCapacity": sum(_cap(n, x["ResourceArn"]) for x in r["policy"].get("StatefulRuleGroupReferences", [])),
            "NumberOfAssociations": sum(1 for f in n["firewalls"].values() if f["policy_arn"] == r["arn"])}


def _cap(n, arn):
    rg = next((x for x in n["rule_groups"].values() if x["arn"] == arn), None)
    return rg["capacity"] if rg else 0


def _pol_find(n, p):
    return _lookup(n["policies"], p.get("FirewallPolicyArn"), p.get("FirewallPolicyName"), "Firewall policy")


def _describe_policy(store, p):
    n = _st(store); r = _pol_find(n, p)
    return {"UpdateToken": r["token"], "FirewallPolicyResponse": _pol_resp(n, r), "FirewallPolicy": r["policy"]}


def _list_policies(store, p):
    n = _st(store)
    return {"FirewallPolicies": [{"Name": r["name"], "Arn": r["arn"]} for r in n["policies"].values()]}


def _update_policy(store, p):
    n = _st(store); r = _pol_find(n, p); _check_token(r, p.get("UpdateToken"))
    r["policy"] = _validate_policy(n, _need(p, "FirewallPolicy"))
    if "Description" in p: r["description"] = p["Description"]
    _bump(r)
    return {"UpdateToken": r["token"], "FirewallPolicyResponse": _pol_resp(n, r)}


def _delete_policy(store, p):
    n = _st(store); r = _pol_find(n, p)
    if any(f["policy_arn"] == r["arn"] for f in n["firewalls"].values()):
        raise NfwError("InvalidOperationException", "The firewall policy is associated with a firewall and cannot be deleted.")
    n["policies"].pop(r["id"])
    return {"FirewallPolicyResponse": _pol_resp(n, r)}


# ── rule groups ──────────────────────────────────────────────────────────
def _rg_resp(r):
    return {"RuleGroupName": r["name"], "RuleGroupArn": r["arn"], "RuleGroupId": r["id"], "Description": r["description"], "Type": r["type"], "Capacity": r["capacity"],
            "RuleGroupStatus": "ACTIVE", "Tags": _tags_out(r["tags"]), "ConsumedCapacity": r["consumed"], "NumberOfAssociations": r.get("assoc", 0)}


def _rg_body(p, typ):
    rg = p.get("RuleGroup")
    if not rg and p.get("Rules"):
        rg = {"RulesSource": {"RulesString": p["Rules"]}}
    if not rg:
        raise NfwError("InvalidRequestException", "RuleGroup or Rules is required")
    consumed = _validate_stateless(rg) if typ == "STATELESS" else _validate_stateful(rg)
    if typ == "STATELESS" and "RulesSource" not in rg:
        raise NfwError("InvalidRequestException", "RuleGroup.RulesSource is required")
    return rg, consumed


def _create_rg(store, p):
    n = _st(store); name = _need(p, "RuleGroupName"); _check_name(name, "RuleGroupName")
    typ = _need(p, "Type")
    if typ not in ("STATELESS", "STATEFUL"):
        raise NfwError("InvalidRequestException", "Type must be STATELESS or STATEFUL")
    cap = p.get("Capacity")
    if not isinstance(cap, int) or not (1 <= cap <= 30000):
        raise NfwError("InvalidRequestException", "Capacity must be an integer 1-30000")
    if any(x["name"] == name and x["type"] == typ for x in n["rule_groups"].values()):
        raise NfwError("InvalidRequestException", f"A rule group named {name} already exists")
    rg, consumed = _rg_body(p, typ)
    if consumed > cap:
        raise NfwError("InvalidRequestException", f"The rules need capacity {consumed} but the rule group capacity is {cap}")
    rid = str(uuid.uuid4())
    r = {"id": rid, "name": name, "arn": _arn("stateless-rulegroup" if typ == "STATELESS" else "stateful-rulegroup", name), "type": typ, "capacity": cap, "rg": rg, "consumed": consumed,
         "description": p.get("Description", ""), "token": _tok(), "tags": _tags_in(p), "updated": _now()}
    n["rule_groups"][rid] = r
    return {"UpdateToken": r["token"], "RuleGroupResponse": _rg_resp(r)}


def _rg_find(n, p):
    return _lookup(n["rule_groups"], p.get("RuleGroupArn"), p.get("RuleGroupName"), "Rule group")


def _refs(n, arn):
    return sum(1 for pol in n["policies"].values() for ref in pol["policy"].get("StatelessRuleGroupReferences", []) + pol["policy"].get("StatefulRuleGroupReferences", []) if ref["ResourceArn"] == arn)


def _describe_rg(store, p):
    n = _st(store); r = _rg_find(n, p); r["assoc"] = _refs(n, r["arn"])
    return {"UpdateToken": r["token"], "RuleGroup": r["rg"], "RuleGroupResponse": _rg_resp(r)}


def _list_rgs(store, p):
    n = _st(store)
    rows = [r for r in n["rule_groups"].values() if not p.get("Type") or r["type"] == p["Type"]]
    return {"RuleGroups": [{"Name": r["name"], "Arn": r["arn"]} for r in rows]}


def _update_rg(store, p):
    n = _st(store); r = _rg_find(n, p); _check_token(r, p.get("UpdateToken"))
    rg, consumed = _rg_body(p, r["type"])
    cap = p.get("Capacity", r["capacity"])
    if cap != r["capacity"] and _refs(n, r["arn"]):
        raise NfwError("InvalidOperationException", "Capacity cannot be changed while the rule group is used by a policy")
    if consumed > cap:
        raise NfwError("InvalidRequestException", f"The rules need capacity {consumed} but the rule group capacity is {cap}")
    r.update({"rg": rg, "consumed": consumed, "capacity": cap})
    if "Description" in p: r["description"] = p["Description"]
    _bump(r)
    return {"UpdateToken": r["token"], "RuleGroupResponse": _rg_resp(r)}


def _delete_rg(store, p):
    n = _st(store); r = _rg_find(n, p)
    if _refs(n, r["arn"]):
        raise NfwError("InvalidOperationException", "The rule group is referenced by a firewall policy and cannot be deleted.")
    n["rule_groups"].pop(r["id"])
    return {"RuleGroupResponse": _rg_resp(r)}



# ── firewalls ────────────────────────────────────────────────────────────
def _vpc_model(store):
    return _V()._model(store)


def _mappings(m, vpc_id, maps):
    out, azs = [], set()
    if not maps:
        raise NfwError("InvalidRequestException", "SubnetMappings is required")
    for sm in maps:
        sid = sm.get("SubnetId")
        sn = m["subnets"].get(sid)
        if not sn:
            raise NfwError("InvalidRequestException", f"Subnet {sid} does not exist")
        if sn["vpc_id"] != vpc_id:
            raise NfwError("InvalidRequestException", f"Subnet {sid} is not in VPC {vpc_id}")
        if sn["az"] in azs:
            raise NfwError("InvalidRequestException", f"Only one firewall subnet is allowed per Availability Zone ({sn['az']})")
        azs.add(sn["az"])
        out.append({"SubnetId": sid, "IPAddressType": sm.get("IPAddressType", "IPV4"), "az": sn["az"], "endpoint": "vpce-" + uuid.uuid4().hex[:17]})
    return out


def _fw_resp(n, f):
    sync = {x["az"]: {"Attachment": {"SubnetId": x["SubnetId"], "EndpointId": x["endpoint"], "Status": "READY"}, "Config": {pol: {"SyncStatus": "IN_SYNC", "UpdateToken": f["token"]} for pol in [f["policy_arn"]]}} for x in f["subnets"]}
    return {"FirewallName": f["name"], "FirewallArn": f["arn"], "FirewallId": f["id"], "FirewallPolicyArn": f["policy_arn"], "VpcId": f["vpc_id"], "SubnetMappings": [{"SubnetId": x["SubnetId"], "IPAddressType": x["IPAddressType"]} for x in f["subnets"]],
            "DeleteProtection": f["delete_protection"], "SubnetChangeProtection": f["subnet_change_protection"], "FirewallPolicyChangeProtection": f["policy_change_protection"], "Description": f["description"],
            "Tags": _tags_out(f["tags"]), "NumberOfAssociations": 0}, {"Status": "READY", "ConfigurationSyncStateSummary": "IN_SYNC", "SyncStates": sync}


def _fw_out(n, f):
    fw, status = _fw_resp(n, f)
    return {"UpdateToken": f["token"], "Firewall": fw, "FirewallStatus": status}


def _fw_find(n, p):
    return _lookup(n["firewalls"], p.get("FirewallArn"), p.get("FirewallName"), "Firewall")


def _create_firewall(store, p):
    n = _st(store); m = _vpc_model(store); name = _need(p, "FirewallName"); _check_name(name, "FirewallName")
    if any(x["name"] == name for x in n["firewalls"].values()):
        raise NfwError("InvalidRequestException", f"A firewall named {name} already exists")
    pol = _lookup(n["policies"], arn=_need(p, "FirewallPolicyArn"), what="Firewall policy")
    vpc = _need(p, "VpcId")
    if vpc not in m["vpcs"]:
        raise NfwError("InvalidRequestException", f"VPC {vpc} does not exist")
    fid = str(uuid.uuid4())
    f = {"id": fid, "name": name, "arn": _arn("firewall", name), "policy_arn": pol["arn"], "vpc_id": vpc, "subnets": _mappings(m, vpc, p.get("SubnetMappings")),
         "delete_protection": bool(p.get("DeleteProtection", False)), "subnet_change_protection": bool(p.get("SubnetChangeProtection", False)),
         "policy_change_protection": bool(p.get("FirewallPolicyChangeProtection", False)), "description": p.get("Description", ""), "token": _tok(), "tags": _tags_in(p), "updated": _now()}
    n["firewalls"][fid] = f
    return _fw_out(n, f)


def _describe_firewall(store, p):
    n = _st(store)
    return _fw_out(n, _fw_find(n, p))


def _list_firewalls(store, p):
    n = _st(store)
    rows = [f for f in n["firewalls"].values() if not p.get("VpcIds") or f["vpc_id"] in p["VpcIds"]]
    return {"Firewalls": [{"FirewallName": f["name"], "FirewallArn": f["arn"]} for f in rows]}


def _delete_firewall(store, p):
    n = _st(store); f = _fw_find(n, p)
    if f["delete_protection"]:
        raise NfwError("InvalidOperationException", "The firewall has delete protection enabled.")
    n["firewalls"].pop(f["id"])
    for a in [k for k, v in n["assocs"].items() if v["firewall_arn"] == f["arn"]]:
        n["assocs"].pop(a)
    n["logging"].pop(f["arn"], None)
    fw, status = _fw_resp(n, f)
    return {"Firewall": fw, "FirewallStatus": dict(status, Status="DELETING")}


def _fw_update(field, flag):
    def op(store, p):
        n = _st(store); f = _fw_find(n, p); _check_token(f, p.get("UpdateToken"))
        if flag == "description":
            f["description"] = p.get("Description", "")
        else:
            f[field] = bool(p[flag])
        _bump(f)
        out = {"FirewallArn": f["arn"], "FirewallName": f["name"], "UpdateToken": f["token"]}
        out[{"description": "Description", "delete_protection": "DeleteProtection", "policy_change_protection": "FirewallPolicyChangeProtection", "subnet_change_protection": "SubnetChangeProtection"}[field]] = f[field]
        return out
    return op


def _assoc_policy(store, p):
    n = _st(store); f = _fw_find(n, p); _check_token(f, p.get("UpdateToken"))
    if f["policy_change_protection"]:
        raise NfwError("InvalidOperationException", "The firewall has policy change protection enabled.")
    pol = _lookup(n["policies"], arn=_need(p, "FirewallPolicyArn"), what="Firewall policy")
    f["policy_arn"] = pol["arn"]; _bump(f)
    return {"FirewallArn": f["arn"], "FirewallName": f["name"], "FirewallPolicyArn": pol["arn"], "UpdateToken": f["token"]}


def _assoc_subnets(store, p):
    n = _st(store); m = _vpc_model(store); f = _fw_find(n, p); _check_token(f, p.get("UpdateToken"))
    if f["subnet_change_protection"]:
        raise NfwError("InvalidOperationException", "The firewall has subnet change protection enabled.")
    new = _mappings(m, f["vpc_id"], p.get("SubnetMappings"))
    have = {x["az"] for x in f["subnets"]}
    for x in new:
        if x["az"] in have:
            raise NfwError("InvalidRequestException", f"The firewall already has a subnet in {x['az']}")
    f["subnets"] += new; _bump(f)
    return {"FirewallArn": f["arn"], "FirewallName": f["name"], "SubnetMappings": [{"SubnetId": x["SubnetId"], "IPAddressType": x["IPAddressType"]} for x in f["subnets"]], "UpdateToken": f["token"]}


def _disassoc_subnets(store, p):
    n = _st(store); f = _fw_find(n, p); _check_token(f, p.get("UpdateToken"))
    if f["subnet_change_protection"]:
        raise NfwError("InvalidOperationException", "The firewall has subnet change protection enabled.")
    ids = _need(p, "SubnetIds")
    if not set(ids) <= {x["SubnetId"] for x in f["subnets"]}:
        raise NfwError("InvalidRequestException", "A subnet is not associated with the firewall")
    if len(ids) >= len(f["subnets"]):
        raise NfwError("InvalidRequestException", "A firewall needs at least one subnet association")
    f["subnets"] = [x for x in f["subnets"] if x["SubnetId"] not in ids]; _bump(f)
    return {"FirewallArn": f["arn"], "FirewallName": f["name"], "SubnetMappings": [{"SubnetId": x["SubnetId"], "IPAddressType": x["IPAddressType"]} for x in f["subnets"]], "UpdateToken": f["token"]}


# ── TLS inspection, resource policies, logging, endpoint associations, tags ─
def _tls_resp(r):
    return {"TLSInspectionConfigurationName": r["name"], "TLSInspectionConfigurationArn": r["arn"], "TLSInspectionConfigurationId": r["id"], "TLSInspectionConfigurationStatus": "ACTIVE",
            "Description": r["description"], "Tags": _tags_out(r["tags"]), "LastModifiedTime": r["updated"], "NumberOfAssociations": 0}


def _tls_check(cfg):
    sc = cfg.get("ServerCertificateConfigurations")
    if not sc:
        raise NfwError("InvalidRequestException", "TLSInspectionConfiguration.ServerCertificateConfigurations is required")
    for c in sc:
        for sk in ("ServerCertificates",):
            for x in c.get(sk, []):
                if not str(x.get("ResourceArn", "")).startswith("arn:aws:acm:"):
                    raise NfwError("InvalidRequestException", "ServerCertificates must be ACM certificate ARNs")
        for sp in c.get("Scopes", []):
            if sp.get("Protocols") and not all(isinstance(x, int) and 0 <= x <= 255 for x in sp["Protocols"]):
                raise NfwError("InvalidRequestException", "Scope Protocols must be IP protocol numbers")
    return cfg


def _create_tls(store, p):
    n = _st(store); name = _need(p, "TLSInspectionConfigurationName"); _check_name(name, "TLSInspectionConfigurationName")
    if any(x["name"] == name for x in n["tls"].values()):
        raise NfwError("InvalidRequestException", f"A TLS inspection configuration named {name} already exists")
    cfg = _tls_check(_need(p, "TLSInspectionConfiguration"))
    rid = str(uuid.uuid4())
    r = {"id": rid, "name": name, "arn": _arn("tls-configuration", name), "cfg": cfg, "description": p.get("Description", ""), "token": _tok(), "tags": _tags_in(p), "updated": _now()}
    n["tls"][rid] = r
    return {"UpdateToken": r["token"], "TLSInspectionConfigurationResponse": _tls_resp(r)}


def _tls_find(n, p):
    return _lookup(n["tls"], p.get("TLSInspectionConfigurationArn"), p.get("TLSInspectionConfigurationName"), "TLS inspection configuration")


def _describe_tls(store, p):
    n = _st(store); r = _tls_find(n, p)
    return {"UpdateToken": r["token"], "TLSInspectionConfiguration": r["cfg"], "TLSInspectionConfigurationResponse": _tls_resp(r)}


def _list_tls(store, p):
    return {"TLSInspectionConfigurations": [{"Name": r["name"], "Arn": r["arn"]} for r in _st(store)["tls"].values()]}


def _update_tls(store, p):
    n = _st(store); r = _tls_find(n, p); _check_token(r, p.get("UpdateToken"))
    r["cfg"] = _tls_check(_need(p, "TLSInspectionConfiguration"))
    if "Description" in p: r["description"] = p["Description"]
    _bump(r)
    return {"UpdateToken": r["token"], "TLSInspectionConfigurationResponse": _tls_resp(r)}


def _delete_tls(store, p):
    n = _st(store); r = _tls_find(n, p)
    n["tls"].pop(r["id"])
    return {"TLSInspectionConfigurationResponse": _tls_resp(r)}


def _put_resource_policy(store, p):
    n = _st(store); arn = _need(p, "ResourceArn")
    if not any(x["arn"] == arn for coll in (n["firewalls"], n["policies"], n["rule_groups"]) for x in coll.values()):
        raise NfwError("ResourceNotFoundException", f"{arn} not found")
    try:
        doc = json.loads(_need(p, "Policy"))
        if not isinstance(doc, dict) or not doc.get("Statement"):
            raise ValueError
    except (ValueError, TypeError):
        raise NfwError("InvalidResourcePolicyException", "Policy must be a JSON policy document with a Statement")
    n["resource_policies"][arn] = p["Policy"]
    return {}


def _describe_resource_policy(store, p):
    n = _st(store); arn = _need(p, "ResourceArn")
    if arn not in n["resource_policies"]:
        raise NfwError("ResourceNotFoundException", f"No resource policy for {arn}")
    return {"Policy": n["resource_policies"][arn]}


def _delete_resource_policy(store, p):
    n = _st(store); arn = _need(p, "ResourceArn")
    if n["resource_policies"].pop(arn, None) is None:
        raise NfwError("ResourceNotFoundException", f"No resource policy for {arn}")
    return {}


def _list_resource_policies(store, p):
    return {"ResourcePolicies": list(_st(store)["resource_policies"].keys())} 


_LOG_TYPES = ("ALERT", "FLOW", "TLS")
_LOG_DEST = ("S3", "CloudWatchLogs", "KinesisDataFirehose")


def _update_logging(store, p):
    n = _st(store); f = _fw_find(n, p)
    cfg = p.get("LoggingConfiguration")
    cur = n["logging"].setdefault(f["arn"], [])
    if cfg is None:
        return {"FirewallArn": f["arn"], "FirewallName": f["name"], "LoggingConfiguration": {"LogDestinationConfigs": cur}}
    new = []
    for c in cfg.get("LogDestinationConfigs", []):
        if c.get("LogType") not in _LOG_TYPES or c.get("LogDestinationType") not in _LOG_DEST or not c.get("LogDestination"):
            raise NfwError("InvalidRequestException", "LogDestinationConfigs need LogType (ALERT|FLOW|TLS), LogDestinationType (S3|CloudWatchLogs|KinesisDataFirehose) and LogDestination")
        new.append(c)
    if len({c["LogType"] for c in new}) != len(new):
        raise NfwError("InvalidRequestException", "Only one destination per log type is allowed")
    n["logging"][f["arn"]] = new
    return {"FirewallArn": f["arn"], "FirewallName": f["name"], "LoggingConfiguration": {"LogDestinationConfigs": new}}


def _describe_logging(store, p):
    n = _st(store); f = _fw_find(n, p)
    return {"FirewallArn": f["arn"], "LoggingConfiguration": {"LogDestinationConfigs": n["logging"].get(f["arn"], [])}, "EnableMonitoringDashboard": False}


def _assoc_resp(a):
    return {"VpcEndpointAssociationId": a["id"], "VpcEndpointAssociationArn": a["arn"], "FirewallArn": a["firewall_arn"], "VpcId": a["vpc_id"], "SubnetMapping": a["subnet"], "Description": a["description"], "Tags": _tags_out(a["tags"])}


def _create_assoc(store, p):
    n = _st(store); m = _vpc_model(store)
    fw = _lookup(n["firewalls"], arn=_need(p, "FirewallArn"), what="Firewall")
    vpc = _need(p, "VpcId")
    if vpc not in m["vpcs"]:
        raise NfwError("InvalidRequestException", f"VPC {vpc} does not exist")
    if vpc == fw["vpc_id"]:
        raise NfwError("InvalidRequestException", "The firewall's own VPC cannot be associated; use SubnetMappings of the firewall")
    sm = _mappings(m, vpc, [_need(p, "SubnetMapping")])[0]
    aid = "vpce-assoc-" + uuid.uuid4().hex[:12]
    a = {"id": aid, "arn": f"arn:aws:network-firewall:{REGION}:{ACCOUNT}:vpc-endpoint-association/{aid}", "firewall_arn": fw["arn"], "vpc_id": vpc, "subnet": {"SubnetId": sm["SubnetId"], "IPAddressType": sm["IPAddressType"]},
         "description": p.get("Description", ""), "tags": _tags_in(p), "endpoint": sm["endpoint"]}
    n["assocs"][aid] = a
    return {"VpcEndpointAssociation": _assoc_resp(a), "VpcEndpointAssociationStatus": {"Status": "READY", "AssociationSyncState": {sm["az"]: {"Attachment": {"SubnetId": sm["SubnetId"], "EndpointId": sm["endpoint"], "Status": "READY"}}}}}


def _assoc_find(n, p):
    return _lookup(n["assocs"], p.get("VpcEndpointAssociationArn"), None, "VPC endpoint association")


def _describe_assoc(store, p):
    n = _st(store); a = _assoc_find(n, p)
    return {"VpcEndpointAssociation": _assoc_resp(a), "VpcEndpointAssociationStatus": {"Status": "READY"}}


def _list_assocs(store, p):
    n = _st(store)
    rows = [a for a in n["assocs"].values() if not p.get("FirewallArn") or a["firewall_arn"] == p["FirewallArn"]]
    return {"VpcEndpointAssociations": [{"VpcEndpointAssociationArn": a["arn"]} for a in rows]}


def _delete_assoc(store, p):
    n = _st(store); a = _assoc_find(n, p); n["assocs"].pop(a["id"])
    return {"VpcEndpointAssociation": _assoc_resp(a), "VpcEndpointAssociationStatus": {"Status": "DELETING"}}


def _taggable(n, arn):
    for coll in (n["firewalls"], n["policies"], n["rule_groups"], n["tls"], n["assocs"]):
        for x in coll.values():
            if x["arn"] == arn:
                return x
    raise NfwError("ResourceNotFoundException", f"{arn} not found")


def _tag(store, p):
    x = _taggable(_st(store), _need(p, "ResourceArn")); x["tags"].update(_tags_in(p)); return {}


def _untag(store, p):
    x = _taggable(_st(store), _need(p, "ResourceArn"))
    for k in p.get("TagKeys", []): x["tags"].pop(k, None)
    return {}


def _list_tags(store, p):
    return {"Tags": _tags_out(_taggable(_st(store), _need(p, "ResourceArn"))["tags"])}


def _simulate_traffic(store, p):
    """Simulator verb (not a real Network Firewall API): run one packet through the firewall's policy."""
    n = _st(store); f = _fw_find(n, p)
    pk = p.get("Packet") or {}
    for k in ("Protocol", "SourceIp", "DestinationIp"):
        if not pk.get(k):
            raise NfwError("InvalidRequestException", f"Packet.{k} is required")
    proto = pk["Protocol"] if isinstance(pk["Protocol"], int) else {"tcp": 6, "udp": 17, "icmp": 1}.get(str(pk["Protocol"]).lower())
    if proto is None:
        raise NfwError("InvalidRequestException", "Packet.Protocol must be tcp, udp, icmp or a protocol number")
    out = evaluate_packet_state(n, f["name"], {"proto": proto, "src": pk["SourceIp"], "dst": pk["DestinationIp"], "sport": pk.get("SourcePort"),
                                               "dport": pk.get("DestinationPort"), "http_host": pk.get("HttpHost"), "tls_sni": pk.get("TlsSni")})
    return {"FirewallName": f["name"], "Action": out["action"].upper(), "Stage": out["stage"], "Rule": out["rule"]}


OPS: dict = {
    "SimulateTraffic": _simulate_traffic,
    "CreateFirewallPolicy": _create_policy, "DescribeFirewallPolicy": _describe_policy, "ListFirewallPolicies": _list_policies,
    "UpdateFirewallPolicy": _update_policy, "DeleteFirewallPolicy": _delete_policy,
    "CreateRuleGroup": _create_rg, "DescribeRuleGroup": _describe_rg, "ListRuleGroups": _list_rgs, "UpdateRuleGroup": _update_rg, "DeleteRuleGroup": _delete_rg,
    "CreateFirewall": _create_firewall, "DescribeFirewall": _describe_firewall, "ListFirewalls": _list_firewalls, "DeleteFirewall": _delete_firewall,
    "UpdateFirewallDescription": _fw_update("description", "description"), "UpdateFirewallDeleteProtection": _fw_update("delete_protection", "DeleteProtection"),
    "UpdateFirewallPolicyChangeProtection": _fw_update("policy_change_protection", "FirewallPolicyChangeProtection"),
    "UpdateSubnetChangeProtection": _fw_update("subnet_change_protection", "SubnetChangeProtection"),
    "AssociateFirewallPolicy": _assoc_policy, "AssociateSubnets": _assoc_subnets, "DisassociateSubnets": _disassoc_subnets,
    "CreateTLSInspectionConfiguration": _create_tls, "DescribeTLSInspectionConfiguration": _describe_tls, "ListTLSInspectionConfigurations": _list_tls,
    "UpdateTLSInspectionConfiguration": _update_tls, "DeleteTLSInspectionConfiguration": _delete_tls,
    "PutResourcePolicy": _put_resource_policy, "DescribeResourcePolicy": _describe_resource_policy, "DeleteResourcePolicy": _delete_resource_policy,
    "UpdateLoggingConfiguration": _update_logging, "DescribeLoggingConfiguration": _describe_logging,
    "CreateVpcEndpointAssociation": _create_assoc, "DescribeVpcEndpointAssociation": _describe_assoc, "ListVpcEndpointAssociations": _list_assocs,
    "DeleteVpcEndpointAssociation": _delete_assoc, "TagResource": _tag, "UntagResource": _untag, "ListTagsForResource": _list_tags,
}


def dispatch(store, target: str, payload: dict | None = None) -> NfwResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = OPS.get(action)
    hdr = {"x-amzn-requestid": str(uuid.uuid4())}
    if op is None:
        return NfwResponse(400, {"__type": "UnknownOperationException", "message": f"The action {action} is not implemented."}, hdr)
    try:
        return NfwResponse(200, op(store, body), hdr)
    except NfwError as e:
        return NfwResponse(e.status, {"__type": e.code, "message": e.message}, hdr)


# ── rule evaluator ───────────────────────────────────────────────────────
def _ip_in(ip, spec):
    spec = str(spec).strip()
    if spec in ("any", "ANY", "$HOME_NET", "$EXTERNAL_NET", "!$HOME_NET"):
        return True
    neg = spec.startswith("!")
    spec = spec.lstrip("!")
    items = [x.strip() for x in spec.strip("[]").split(",") if x.strip()]
    hit = any(ipaddress.ip_address(ip) in ipaddress.ip_network(x, strict=False) for x in items if x not in ("any", "ANY"))  or any(x in ("any", "ANY") for x in items)
    return (not hit) if neg else hit


def _port_in(port, spec):
    spec = str(spec).strip()
    if spec in ("any", "ANY") or port is None:
        return spec in ("any", "ANY")
    neg = spec.startswith("!"); spec = spec.lstrip("!")
    hit = False
    for part in spec.strip("[]").split(","):
        part = part.strip()
        if ":" in part:
            lo, _, hi = part.partition(":")
            hit |= int(lo or 0) <= port <= int(hi or 65535)
        elif part.isdigit():
            hit |= port == int(part)
    return (not hit) if neg else hit


def _dom_match(host, targets):
    host = (host or "").lower()
    for t in targets:
        t = t.lower()
        if (t.startswith(".") and (host == t[1:] or host.endswith(t))) or host == t:
            return True
    return False


def _suri_matches(r, pkt):
    proto = r["proto"]
    pnum = _PROTOS.get(proto)
    if proto == "IP":
        pass
    elif proto in ("HTTP", "TLS", "DNS") and pkt.get("app") not in (None, proto.lower()) and pkt.get("app"):
        return False
    elif pnum is not None and pkt.get("proto") != pnum:
        return False
    if not (_ip_in(pkt["src"], r["src"]) and _ip_in(pkt["dst"], r["dst"]) and _port_in(pkt.get("sport"), r["sport"]) and _port_in(pkt.get("dport"), r["dport"])):
        return False
    o = r["opts"]
    for key, field_ in (("tls.sni", "tls_sni"), ("http.host", "http_host"), ("dns.query", "domain")):
        if key in o:
            val = (pkt.get(field_) or "").lower()
            contents = [c.strip('"').lower() for c in o.get("content", [])] or [""]
            if not val or not all(c in val for c in contents):
                return False
    if "flow" in o and "to_server" in o["flow"][0] and pkt.get("direction") == "reply":
        return False
    return True


def _stateful_rules(n, pol):
    out = []
    refs = pol["policy"].get("StatefulRuleGroupReferences", [])
    strict = pol["policy"].get("StatefulEngineOptions", {}).get("RuleOrder") == "STRICT_ORDER"
    for i, ref in enumerate(sorted(refs, key=lambda r: r.get("Priority", 0) if strict else 0)):
        rg = next((x for x in n["rule_groups"].values() if x["arn"] == ref["ResourceArn"]), None)
        if not rg:
            continue
        src = rg["rg"]["RulesSource"]
        if "RulesString" in src:
            for r in parse_suricata(src["RulesString"]):
                r["group"] = rg["name"]; out.append(r)
        elif "RulesSourceList" in src:
            rl = src["RulesSourceList"]
            out.append({"kind": "domain", "allow": rl["GeneratedRulesType"] == "ALLOWLIST", "targets": rl["Targets"], "types": rl["TargetTypes"], "group": rg["name"], "action": "pass" if rl["GeneratedRulesType"] == "ALLOWLIST" else "drop"})
        else:
            for sr in src["StatefulRules"]:
                h = sr["Header"]
                out.append({"action": sr["Action"].lower(), "proto": h["Protocol"].upper(), "src": h["Source"].replace("ANY", "any"), "sport": h.get("SourcePort", "ANY").replace("ANY", "any"), "bidir": h["Direction"] == "ANY",
                            "dst": h["Destination"].replace("ANY", "any"), "dport": h.get("DestinationPort", "ANY").replace("ANY", "any"), "sid": 0, "opts": {}, "group": rg["name"]})
    return out, strict


def evaluate_packet(store, firewall_name, pkt: dict) -> dict:
    """pkt: {proto:int, src, dst, sport, dport, app?:'http'|'tls'|'dns', http_host?, tls_sni?, domain?}.
    -> {'action': 'pass'|'drop'|'reject', 'stage': 'stateless'|'stateful'|'default', 'rule': str}"""
    return evaluate_packet_state(_st(store), firewall_name, pkt)


def firewall_endpoints(n: dict) -> dict:
    """{vpce-id: {'firewall': name, 'subnet': subnet-id, 'vpc': vpc-id}} for every firewall endpoint (own + associated VPC)."""
    out = {}
    for f in n.get("firewalls", {}).values():
        for x in f.get("subnets", []):
            out[x["endpoint"]] = {"firewall": f["name"], "subnet": x["SubnetId"], "vpc": f["vpc_id"]}
    for a in n.get("assocs", {}).values():
        f = n.get("firewalls", {}).get(next((k for k, v in n.get("firewalls", {}).items() if v["arn"] == a["firewall_arn"]), ""))
        if f:
            out[a["endpoint"]] = {"firewall": f["name"], "subnet": a["subnet"]["SubnetId"], "vpc": a["vpc_id"]}
    return out


def evaluate_packet_state(n: dict, firewall_name, pkt: dict) -> dict:
    fw = _lookup(n["firewalls"], name=firewall_name, what="Firewall")
    pol = next(x for x in n["policies"].values() if x["arn"] == fw["policy_arn"])
    fp = pol["policy"]
    sl = []
    for ref in sorted(fp.get("StatelessRuleGroupReferences", []), key=lambda r: r["Priority"]):
        rg = next((x for x in n["rule_groups"].values() if x["arn"] == ref["ResourceArn"]), None)
        if rg:
            sl += [(r, rg["name"]) for r in sorted((rg["rg"]["RulesSource"].get("StatelessRulesAndCustomActions") or {}).get("StatelessRules") or [], key=lambda r: r["Priority"])]
    actions = fp["StatelessDefaultActions"]; stage_rule = "default"
    for r, gname in sl:
        ma = r["RuleDefinition"]["MatchAttributes"]
        ok = (not ma.get("Protocols") or pkt["proto"] in ma["Protocols"]) \
            and (not ma.get("Sources") or any(_ip_in(pkt["src"], a["AddressDefinition"]) for a in ma["Sources"])) \
            and (not ma.get("Destinations") or any(_ip_in(pkt["dst"], a["AddressDefinition"]) for a in ma["Destinations"])) \
            and (not ma.get("SourcePorts") or any(x["FromPort"] <= (pkt.get("sport") or -1) <= x["ToPort"] for x in ma["SourcePorts"])) \
            and (not ma.get("DestinationPorts") or any(x["FromPort"] <= (pkt.get("dport") or -1) <= x["ToPort"] for x in ma["DestinationPorts"]))
        if ok:
            actions = r["RuleDefinition"]["Actions"]; stage_rule = f"{gname}#{r['Priority']}"
            break
    if "aws:drop" in actions:
        return {"action": "drop", "stage": "stateless", "rule": stage_rule}
    if "aws:pass" in actions:
        return {"action": "pass", "stage": "stateless", "rule": stage_rule}
    rules, strict = _stateful_rules(n, pol)
    verdict = None
    order = rules if strict else sorted(rules, key=lambda r: {"pass": 0, "drop": 1, "reject": 2, "alert": 3}.get(r.get("action", "pass"), 3))
    allow_domains = [r for r in rules if r.get("kind") == "domain" and r["allow"]]
    host = pkt.get("tls_sni") or pkt.get("http_host") or pkt.get("domain")
    for r in order:
        if r.get("kind") == "domain":
            if not host or not (("TLS_SNI" in r["types"] and pkt.get("tls_sni")) or ("HTTP_HOST" in r["types"] and pkt.get("http_host"))):
                continue
            hit = _dom_match(host, r["targets"])
            if r["allow"] and not hit:
                continue
            if hit:
                return {"action": r["action"], "stage": "stateful", "rule": r["group"] + ("#allowlist" if r["allow"] else "#denylist")}
            continue
        if _suri_matches(r, pkt) or (r.get("bidir") and _suri_matches(dict(r, src=r["dst"], dst=r["src"], sport=r["dport"], dport=r["sport"]), pkt)):
            if r["action"] == "alert":
                verdict = verdict or {"action": "pass", "stage": "stateful", "rule": f"{r['group']}#sid{r['sid']} (alert)"}
                continue
            return {"action": "drop" if r["action"] in ("drop", "reject") else "pass", "stage": "stateful", "rule": f"{r['group']}#sid{r['sid']}" if r["sid"] else r["group"], **({"reject": True} if r["action"] == "reject" else {})}
    if allow_domains and host and (pkt.get("tls_sni") or pkt.get("http_host")):
        return {"action": "drop", "stage": "stateful", "rule": allow_domains[0]["group"] + "#allowlist-implicit-deny"}
    if verdict:
        return verdict
    sda = fp.get("StatefulDefaultActions") or []
    if strict and any(a in ("aws:drop_strict", "aws:drop_established") for a in sda):
        return {"action": "drop", "stage": "default", "rule": "stateful default action"}
    return {"action": "pass", "stage": "default", "rule": "no rule matched"}
