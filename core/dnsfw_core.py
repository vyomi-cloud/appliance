"""Route 53 Resolver DNS Firewall (JSON 1.1, X-Amz-Target Route53Resolver.*) over the shared VPC model
(m["dnsfw"]): domain lists (validated domain syntax, ADD/REMOVE/REPLACE), rule groups with prioritised
ALLOW/ALERT/BLOCK rules (BlockResponse NODATA/NXDOMAIN/OVERRIDE validated), VPC associations (priority
100-9900 unique per VPC, VPC must exist), in-use ConflictException checks, tags.

`resolve_decision(store, vpc_id, qname, qtype)` evaluates a DNS query for a VPC exactly like the
Resolver does (associations by priority, rules by priority, first matching domain list wins; no match =
allowed) and is unit-tested. The simulator has no Route 53 Resolver data plane, so nothing calls it for
live DNS answers (see core/capabilities/aws/vpc.json `aws.vpc.dns-firewall`)."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

ACCOUNT = "123456789012"
REGION = "us-east-1"


@dataclass
class DnsfwResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class DnsfwError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _V():
    from core import vpc_core
    return vpc_core


def _st(store):
    m = _V()._model(store)
    n = m.setdefault("dnsfw", {})
    for k in ("lists", "groups", "assocs"):
        n.setdefault(k, {})
    return n


def _need(p, k):
    v = p.get(k)
    if v in (None, "", []):
        raise DnsfwError("ValidationException", f"{k} is required")
    return v


_DOM = re.compile(r"^(\*\.)?([a-zA-Z0-9_]([a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?\.)+[a-zA-Z]{2,63}\.?$|^(\*\.)?[a-zA-Z0-9_-]{1,63}\.?$")


def _check_domains(ds):
    for d in ds:
        if len(d) > 255 or not _DOM.match(d):
            raise DnsfwError("ValidationException", f"{d!r} is not a valid domain name (wildcards only as a leading '*.')")


def _tags(p):
    return {t["Key"]: t.get("Value", "") for t in (p.get("Tags") or [])}


def _tag_list(d):
    return [{"Key": k, "Value": v} for k, v in d.items()]


def _norm(d):
    return d.lower().rstrip(".")


def _list_view(l):
    return {"Id": l["id"], "Arn": l["arn"], "Name": l["name"], "DomainCount": len(l["domains"]), "Status": "COMPLETE", "StatusMessage": "Created Firewall Domain List", "ManagedOwnerName": None,
            "CreatorRequestId": l["creator"], "CreationTime": l["created"], "ModificationTime": l["modified"]}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())


def _find_list(n, p):
    l = n["lists"].get(p.get("FirewallDomainListId"))
    if not l:
        raise DnsfwError("ResourceNotFoundException", f"Firewall domain list {p.get('FirewallDomainListId')} not found")
    return l


def _create_list(store, p):
    n = _st(store); name = _need(p, "Name")
    lid = "rslvr-fdl-" + uuid.uuid4().hex[:17]
    l = {"id": lid, "arn": f"arn:aws:route53resolver:{REGION}:{ACCOUNT}:firewall-domain-list/{lid}", "name": name, "domains": [], "creator": p.get("CreatorRequestId", ""), "created": _now(), "modified": _now(), "tags": _tags(p)}
    n["lists"][lid] = l
    return {"FirewallDomainList": _list_view(l)}


def _get_list(store, p):
    return {"FirewallDomainList": _list_view(_find_list(_st(store), p))}


def _list_lists(store, p):
    return {"FirewallDomainLists": [{k: v[k] for k in ("Id", "Arn", "Name")} | {"CreatorRequestId": v["CreatorRequestId"]} for v in map(_list_view, _st(store)["lists"].values())]}


def _update_domains(store, p):
    n = _st(store); l = _find_list(n, p)
    op = _need(p, "Operation")
    ds = [_norm(d) for d in _need(p, "Domains")]
    if op not in ("ADD", "REMOVE", "REPLACE"):
        raise DnsfwError("ValidationException", "Operation must be ADD, REMOVE or REPLACE")
    _check_domains(ds)
    if op == "ADD":
        l["domains"] = sorted(set(l["domains"]) | set(ds))
    elif op == "REMOVE":
        missing = [d for d in ds if d not in l["domains"]]
        if missing:
            raise DnsfwError("ValidationException", f"Domains not in the list: {', '.join(missing)}")
        l["domains"] = [d for d in l["domains"] if d not in ds]
    else:
        l["domains"] = sorted(set(ds))
    l["modified"] = _now()
    return {"Id": l["id"], "Name": l["name"], "Status": "UPDATING"}


def _list_domains(store, p):
    return {"Domains": _find_list(_st(store), p)["domains"]}


def _delete_list(store, p):
    n = _st(store); l = _find_list(n, p)
    if any(r["list"] == l["id"] for g in n["groups"].values() for r in g["rules"]):
        raise DnsfwError("ConflictException", "The domain list is used by a firewall rule and cannot be deleted.")
    n["lists"].pop(l["id"])
    return {"FirewallDomainList": _list_view(l)}


def _group_view(g, n):
    return {"Id": g["id"], "Arn": g["arn"], "Name": g["name"], "RuleCount": len(g["rules"]), "Status": "COMPLETE", "StatusMessage": "Created Firewall Rule Group", "OwnerId": ACCOUNT, "CreatorRequestId": g["creator"],
            "ShareStatus": "NOT_SHARED", "CreationTime": g["created"], "ModificationTime": g["modified"]}


def _find_group(n, p, key="FirewallRuleGroupId"):
    g = n["groups"].get(p.get(key))
    if not g:
        raise DnsfwError("ResourceNotFoundException", f"Firewall rule group {p.get(key)} not found")
    return g


def _create_group(store, p):
    n = _st(store); name = _need(p, "Name")
    gid = "rslvr-frg-" + uuid.uuid4().hex[:17]
    g = {"id": gid, "arn": f"arn:aws:route53resolver:{REGION}:{ACCOUNT}:firewall-rule-group/{gid}", "name": name, "rules": [], "creator": p.get("CreatorRequestId", ""), "created": _now(), "modified": _now(), "tags": _tags(p)}
    n["groups"][gid] = g
    return {"FirewallRuleGroup": _group_view(g, n)}


def _get_group(store, p):
    n = _st(store)
    return {"FirewallRuleGroup": _group_view(_find_group(n, p), n)}


def _list_groups(store, p):
    n = _st(store)
    return {"FirewallRuleGroups": [{"Id": g["id"], "Arn": g["arn"], "Name": g["name"], "OwnerId": ACCOUNT, "CreatorRequestId": g["creator"], "ShareStatus": "NOT_SHARED"} for g in n["groups"].values()]}


def _delete_group(store, p):
    n = _st(store); g = _find_group(n, p)
    if any(a["group"] == g["id"] for a in n["assocs"].values()):
        raise DnsfwError("ConflictException", "The rule group is associated with a VPC; disassociate it first.")
    n["groups"].pop(g["id"])
    return {"FirewallRuleGroup": _group_view(g, n)}


def _rule_view(g, r):
    out = {"FirewallRuleGroupId": g["id"], "FirewallDomainListId": r["list"], "Name": r["name"], "Priority": r["priority"], "Action": r["action"], "CreatorRequestId": r.get("creator", ""),
           "CreationTime": r["created"], "ModificationTime": r["modified"], "FirewallDomainRedirectionAction": "INSPECT_REDIRECTION_DOMAIN", "Qtype": r.get("qtype")}
    if r["action"] == "BLOCK":
        out["BlockResponse"] = r["block"]
        if r["block"] == "OVERRIDE":
            out.update({"BlockOverrideDomain": r["override_domain"], "BlockOverrideDnsType": "CNAME", "BlockOverrideTtl": r["override_ttl"]})
    return out


def _rule_fill(n, g, p, r=None, creating=True):
    r = dict(r or {})
    if creating or "FirewallDomainListId" in p:
        lid = _need(p, "FirewallDomainListId")
        if lid not in n["lists"]:
            raise DnsfwError("ResourceNotFoundException", f"Firewall domain list {lid} not found")
        r["list"] = lid
    if creating or "Priority" in p:
        pr = p.get("Priority")
        if not isinstance(pr, int) or pr < 1 or pr > 10000:
            raise DnsfwError("ValidationException", "Priority must be an integer 1-10000")
        if any(x is not r and x["priority"] == pr for x in g["rules"]):
            raise DnsfwError("ValidationException", f"A rule with priority {pr} already exists in the group")
        r["priority"] = pr
    if creating or "Action" in p:
        a = _need(p, "Action")
        if a not in ("ALLOW", "ALERT", "BLOCK"):
            raise DnsfwError("ValidationException", "Action must be ALLOW, ALERT or BLOCK")
        r["action"] = a
    if "Name" in p or creating:
        r["name"] = _need(p, "Name")
    if "Qtype" in p:
        r["qtype"] = p["Qtype"]
    if r["action"] == "BLOCK":
        br = p.get("BlockResponse", r.get("block"))
        if br not in ("NODATA", "NXDOMAIN", "OVERRIDE"):
            raise DnsfwError("ValidationException", "BLOCK rules need BlockResponse NODATA, NXDOMAIN or OVERRIDE")
        r["block"] = br
        if br == "OVERRIDE":
            if not (p.get("BlockOverrideDomain") or r.get("override_domain")) or (p.get("BlockOverrideDnsType") or "CNAME") != "CNAME":
                raise DnsfwError("ValidationException", "OVERRIDE needs BlockOverrideDomain and BlockOverrideDnsType CNAME")
            r["override_domain"] = p.get("BlockOverrideDomain", r.get("override_domain"))
            ttl = p.get("BlockOverrideTtl", r.get("override_ttl", 300))
            if not isinstance(ttl, int) or not 0 <= ttl <= 604800:
                raise DnsfwError("ValidationException", "BlockOverrideTtl must be 0-604800")
            r["override_ttl"] = ttl
    elif "BlockResponse" in p:
        raise DnsfwError("ValidationException", "BlockResponse is only valid for BLOCK rules")
    return r


def _create_rule(store, p):
    n = _st(store); g = _find_group(n, p)
    r = _rule_fill(n, g, p)
    r.update({"created": _now(), "modified": _now(), "creator": p.get("CreatorRequestId", "")})
    g["rules"].append(r); g["rules"].sort(key=lambda x: x["priority"]); g["modified"] = _now()
    return {"FirewallRule": _rule_view(g, r)}


def _find_rule(g, p):
    r = next((x for x in g["rules"] if x["list"] == p.get("FirewallDomainListId")), None)
    if not r:
        raise DnsfwError("ResourceNotFoundException", "Firewall rule not found")
    return r


def _list_rules(store, p):
    n = _st(store); g = _find_group(n, p)
    return {"FirewallRules": [_rule_view(g, r) for r in g["rules"] if not p.get("Priority") or r["priority"] == p["Priority"] if not p.get("Action") or r["action"] == p["Action"]]}


def _update_rule(store, p):
    n = _st(store); g = _find_group(n, p); r = _find_rule(g, p)
    nr = _rule_fill(n, g, {k: v for k, v in p.items() if k != "FirewallDomainListId"}, r, creating=False)
    r.update(nr); r["modified"] = _now(); g["rules"].sort(key=lambda x: x["priority"])
    return {"FirewallRule": _rule_view(g, r)}


def _delete_rule(store, p):
    n = _st(store); g = _find_group(n, p); r = _find_rule(g, p)
    g["rules"].remove(r)
    return {"FirewallRule": _rule_view(g, r)}


def _assoc_view(a):
    return {"Id": a["id"], "Arn": a["arn"], "FirewallRuleGroupId": a["group"], "VpcId": a["vpc"], "Name": a["name"], "Priority": a["priority"], "MutationProtection": a["protection"], "Status": "COMPLETE",
            "StatusMessage": "Finished rule association", "CreatorRequestId": a["creator"], "CreationTime": a["created"], "ModificationTime": a["modified"]}


def _associate(store, p):
    n = _st(store); m = _V()._model(store); g = _find_group(n, p)
    vpc = _need(p, "VpcId")
    if vpc not in m["vpcs"]:
        raise DnsfwError("ValidationException", f"VPC {vpc} does not exist")
    pr = p.get("Priority")
    if not isinstance(pr, int) or not 100 <= pr <= 9900:
        raise DnsfwError("ValidationException", "Association Priority must be an integer 100-9900")
    if any(a["vpc"] == vpc and a["group"] == g["id"] for a in n["assocs"].values()):
        raise DnsfwError("ConflictException", "The rule group is already associated with this VPC")
    if any(a["vpc"] == vpc and a["priority"] == pr for a in n["assocs"].values()):
        raise DnsfwError("ValidationException", f"VPC {vpc} already has an association with priority {pr}")
    aid = "rslvr-frgassoc-" + uuid.uuid4().hex[:17]
    a = {"id": aid, "arn": f"arn:aws:route53resolver:{REGION}:{ACCOUNT}:firewall-rule-group-association/{aid}", "group": g["id"], "vpc": vpc, "name": _need(p, "Name"), "priority": pr,
         "protection": p.get("MutationProtection", "DISABLED"), "creator": p.get("CreatorRequestId", ""), "created": _now(), "modified": _now(), "tags": _tags(p)}
    n["assocs"][aid] = a
    return {"FirewallRuleGroupAssociation": _assoc_view(a)}


def _find_assoc(n, p):
    a = n["assocs"].get(p.get("FirewallRuleGroupAssociationId"))
    if not a:
        raise DnsfwError("ResourceNotFoundException", "Firewall rule group association not found")
    return a


def _get_assoc(store, p):
    return {"FirewallRuleGroupAssociation": _assoc_view(_find_assoc(_st(store), p))}


def _list_assocs(store, p):
    n = _st(store)
    rows = [a for a in n["assocs"].values() if (not p.get("VpcId") or a["vpc"] == p["VpcId"]) and (not p.get("FirewallRuleGroupId") or a["group"] == p["FirewallRuleGroupId"])]
    return {"FirewallRuleGroupAssociations": [_assoc_view(a) for a in sorted(rows, key=lambda a: a["priority"])]}


def _update_assoc(store, p):
    n = _st(store); a = _find_assoc(n, p)
    if a["protection"] == "ENABLED" and ("Priority" in p or p.get("MutationProtection") == "DISABLED" and False):
        raise DnsfwError("ValidationException", "The association has mutation protection enabled")
    if "Priority" in p:
        if not isinstance(p["Priority"], int) or not 100 <= p["Priority"] <= 9900:
            raise DnsfwError("ValidationException", "Association Priority must be an integer 100-9900")
        a["priority"] = p["Priority"]
    for k, f in (("MutationProtection", "protection"), ("Name", "name")):
        if k in p: a[f] = p[k]
    a["modified"] = _now()
    return {"FirewallRuleGroupAssociation": _assoc_view(a)}


def _disassociate(store, p):
    n = _st(store); a = _find_assoc(n, p)
    if a["protection"] == "ENABLED":
        raise DnsfwError("ValidationException", "The association has mutation protection enabled")
    n["assocs"].pop(a["id"])
    return {"FirewallRuleGroupAssociation": _assoc_view(a)}


def _resource(n, arn):
    for coll in (n["lists"], n["groups"], n["assocs"]):
        for x in coll.values():
            if x["arn"] == arn:
                return x
    raise DnsfwError("ResourceNotFoundException", f"{arn} not found")


def _tag(store, p):
    _resource(_st(store), _need(p, "ResourceArn"))["tags"].update(_tags(p)); return {}


def _untag(store, p):
    r = _resource(_st(store), _need(p, "ResourceArn"))
    for k in p.get("TagKeys", []): r["tags"].pop(k, None)
    return {}


def _list_tags(store, p):
    return {"Tags": _tag_list(_resource(_st(store), _need(p, "ResourceArn"))["tags"])}


def resolve_decision(store, vpc_id, qname, qtype="A"):
    """-> {'action': 'ALLOW'|'BLOCK'|'ALERT'|None, 'block': response, 'rule': name, 'group': name}; None action = no rule matched (resolved normally)."""
    n = _st(store)
    q = _norm(qname)
    alerts = []
    for a in sorted((a for a in n["assocs"].values() if a["vpc"] == vpc_id), key=lambda a: a["priority"]):
        g = n["groups"][a["group"]]
        for r in g["rules"]:
            if r.get("qtype") and r["qtype"] != qtype:
                continue
            doms = n["lists"][r["list"]]["domains"]
            if any(d == q or (d.startswith("*.") and q.endswith(d[1:])) for d in doms):
                if r["action"] == "ALERT":
                    alerts.append((g["name"], r["name"])); continue
                return {"action": r["action"], "block": r.get("block"), "rule": r["name"], "group": g["name"], "alerts": alerts}
    return {"action": "ALERT" if alerts else None, "block": None, "rule": alerts[0][1] if alerts else "", "group": alerts[0][0] if alerts else "", "alerts": alerts}


OPS = {
    "CreateFirewallDomainList": _create_list, "GetFirewallDomainList": _get_list, "ListFirewallDomainLists": _list_lists, "UpdateFirewallDomains": _update_domains,
    "ListFirewallDomains": _list_domains, "DeleteFirewallDomainList": _delete_list,
    "CreateFirewallRuleGroup": _create_group, "GetFirewallRuleGroup": _get_group, "ListFirewallRuleGroups": _list_groups, "DeleteFirewallRuleGroup": _delete_group,
    "CreateFirewallRule": _create_rule, "ListFirewallRules": _list_rules, "UpdateFirewallRule": _update_rule, "DeleteFirewallRule": _delete_rule,
    "AssociateFirewallRuleGroup": _associate, "GetFirewallRuleGroupAssociation": _get_assoc, "ListFirewallRuleGroupAssociations": _list_assocs,
    "UpdateFirewallRuleGroupAssociation": _update_assoc, "DisassociateFirewallRuleGroup": _disassociate,
    "TagResource": _tag, "UntagResource": _untag, "ListTagsForResource": _list_tags,
}


def dispatch(store, target: str, payload: dict | None = None) -> DnsfwResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = OPS.get(action)
    hdr = {"x-amzn-requestid": str(uuid.uuid4())}
    if op is None:
        return DnsfwResponse(400, {"__type": "UnknownOperationException", "message": f"The action {action} is not implemented."}, hdr)
    try:
        return DnsfwResponse(200, op(store, body), hdr)
    except DnsfwError as e:
        return DnsfwResponse(e.status, {"__type": e.code, "message": e.message}, hdr)
