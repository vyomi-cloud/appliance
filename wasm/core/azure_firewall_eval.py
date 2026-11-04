# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Firewall rule EVALUATION (substrate-independent, pure Python, Pyodide-loadable).

Answers what an Azure Firewall would do with one connection, from the ARM state of the firewall, its Firewall
Policy (+ base-policy chain) and rule collection groups (or the firewall's classic rule collections):

  processing order  DNAT  ->  Network  ->  Application   (each by rule-collection-group priority, then rule-
                    collection priority; first matching rule decides; no match = implicit Deny)
  network rule      ipProtocols (TCP/UDP/ICMP/Any), sourceAddresses (IP/CIDR/range/*), destinationAddresses (IP/CIDR/*),
                    destinationFqdns, destinationPorts (n, a-b, *)
  application rule  protocols (Http/Https/Mssql + port), targetFqdns (exact / leading wildcard / *), sourceAddresses;
                    FQDN tags / web categories / URL filtering are not evaluated (rule is skipped and reported)
  DNAT rule         matches destination (the firewall public IP) + port -> reports the translated address/port

Not modelled: threat-intelligence deny, IDPS signatures, TLS inspection, IP Groups (rules referencing them are
skipped and reported), forced-tunnelling, SNAT. The firewall is NOT inserted into UDR/netsim routing: this is an
evaluator over the rule base, exposed as the simulator action POST .../azureFirewalls/{fw}/evaluate.
"""
from __future__ import annotations

import ipaddress

POLICY = "microsoft.network/firewallpolicies"
RCG = "microsoft.network/firewallpolicies/rulecollectiongroups"


def _addr_match(rule_list, ip: str) -> bool:
    for r in rule_list or []:
        r = str(r).strip()
        if r == "*":
            return True
        try:
            a = ipaddress.ip_address(ip)
            if "/" in r:
                if a in ipaddress.ip_network(r, strict=False):
                    return True
            elif "-" in r:
                lo, hi = (ipaddress.ip_address(x.strip()) for x in r.split("-", 1))
                if lo <= a <= hi:
                    return True
            elif a == ipaddress.ip_address(r):
                return True
        except ValueError:
            continue
    return False


def _port_match(ports, port) -> bool:
    for p in ports or []:
        p = str(p).strip()
        if p == "*":
            return True
        if port is None:
            continue
        if "-" in p:
            lo, hi = p.split("-", 1)
            if lo.isdigit() and hi.isdigit() and int(lo) <= int(port) <= int(hi):
                return True
        elif p.isdigit() and int(p) == int(port):
            return True
    return False


def _fqdn_match(patterns, fqdn: str) -> bool:
    f = (fqdn or "").lower().rstrip(".")
    for p in patterns or []:
        p = str(p).lower()
        if p == "*" or (f and (p == f or (p.startswith("*.") and f.endswith(p[1:])) or (p.startswith("*") and f.endswith(p[1:])))):
            return True
    return False


def _collect(state: dict, fw: dict):
    """-> (list of (rcg_priority, rcg_name, collection dict), skipped notes). Classic rules become one pseudo group."""
    props = fw.get("properties") or {}
    out, notes = [], []
    pol_ref = (props.get("firewallPolicy") or {}).get("id") if isinstance(props.get("firewallPolicy"), dict) else props.get("firewallPolicy")
    seen = set()
    chain = []
    while pol_ref and pol_ref.lower() not in seen:
        seen.add(pol_ref.lower())
        pol = state.get(pol_ref.lower())
        if pol is None or (pol.get("_type") or "").lower() != POLICY:
            break
        chain.append(pol)
        bp = (pol.get("properties") or {}).get("basePolicy")
        pol_ref = (bp.get("id") if isinstance(bp, dict) else bp) or ""
    for depth, pol in enumerate(reversed(chain)):          # base policy first: its rules are evaluated before the child's
        for g in state.values():
            if (g.get("_type") or "").lower() == RCG and (g.get("id") or "").lower().startswith(pol["id"].lower() + "/"):
                gp = g.get("properties") or {}
                for c in gp.get("ruleCollections") or []:
                    out.append(((depth, gp.get("priority", 65000)), g.get("name", ""), c))
    for kind, key in (("FirewallPolicyNatRuleCollection", "natRuleCollections"), ("FirewallPolicyFilterRuleCollection:network", "networkRuleCollections"),
                      ("FirewallPolicyFilterRuleCollection:application", "applicationRuleCollections")):
        for c in props.get(key) or []:
            cp = c.get("properties") or c
            action = (cp.get("action") or {}).get("type", "Deny")
            if key == "natRuleCollections":
                out.append(((-1, 0), "classic", {"ruleCollectionType": "FirewallPolicyNatRuleCollection", "name": c.get("name"), "priority": cp.get("priority", 65000),
                                                  "action": {"type": "Dnat"}, "rules": [{"ruleType": "NatRule", "name": r.get("name"), "ipProtocols": r.get("protocols"),
                                                  "sourceAddresses": r.get("sourceAddresses"), "destinationAddresses": r.get("destinationAddresses"),
                                                  "destinationPorts": r.get("destinationPorts"), "translatedAddress": r.get("translatedAddress"),
                                                  "translatedPort": r.get("translatedPort")} for r in cp.get("rules") or []]}))
            elif key == "networkRuleCollections":
                out.append(((-1, 0), "classic", {"ruleCollectionType": "FirewallPolicyFilterRuleCollection", "name": c.get("name"), "priority": cp.get("priority", 65000),
                                                  "action": {"type": action}, "rules": [dict(r, ruleType="NetworkRule", ipProtocols=r.get("protocols")) for r in cp.get("rules") or []]}))
            else:
                out.append(((-1, 0), "classic", {"ruleCollectionType": "FirewallPolicyFilterRuleCollection", "name": c.get("name"), "priority": cp.get("priority", 65000),
                                                  "action": {"type": action}, "rules": [dict(r, ruleType="ApplicationRule", protocols=[{"protocolType": p.get("protocolType"), "port": p.get("port")} for p in r.get("protocols") or []])
                                                                                          for r in cp.get("rules") or []]}))
    return out, notes


def _proto_ok(rule_protos, proto: str) -> bool:
    ps = {str(p).lower() for p in rule_protos or []}
    return not ps or "any" in ps or proto.lower() in ps


def evaluate(state: dict, firewall_id: str, req: dict) -> dict:
    fw = state.get(firewall_id.lower())
    if fw is None:
        return {"error": "firewall not found"}
    proto = str(req.get("protocol") or "TCP")
    src = str(req.get("sourceAddress") or "")
    dst = str(req.get("destinationAddress") or "")
    fqdn = str(req.get("destinationFqdn") or "")
    port = req.get("destinationPort")
    port = int(port) if str(port).isdigit() else None
    colls, notes = _collect(state, fw)
    colls.sort(key=lambda x: (x[0][0], x[0][1], x[2].get("priority", 65000)))

    def done(action, group, coll, rule, typ, **kw):
        return {"action": action, "ruleType": typ, "ruleCollectionGroup": group, "ruleCollection": coll, "rule": rule, "notes": notes, **kw}

    # 1. DNAT
    for _prio, g, c in colls:
        if c.get("ruleCollectionType") != "FirewallPolicyNatRuleCollection":
            continue
        for r in c.get("rules") or []:
            if _proto_ok(r.get("ipProtocols"), proto) and _addr_match(r.get("sourceAddresses"), src) and _addr_match(r.get("destinationAddresses"), dst) and _port_match(r.get("destinationPorts"), port):
                return done("Dnat", g, c.get("name"), r.get("name"), "NatRule", translatedAddress=r.get("translatedAddress"), translatedPort=r.get("translatedPort"))
    # 2. network rules, 3. application rules
    for want in ("NetworkRule", "ApplicationRule"):
        for _prio, g, c in colls:
            if c.get("ruleCollectionType") != "FirewallPolicyFilterRuleCollection":
                continue
            act = (c.get("action") or {}).get("type", "Deny")
            for r in c.get("rules") or []:
                if r.get("ruleType") != want:
                    continue
                if r.get("sourceIpGroups") or r.get("destinationIpGroups"):
                    notes.append(f"rule {r.get('name')}: IP Groups are not evaluated; skipped")
                    continue
                if want == "NetworkRule":
                    if not (_proto_ok(r.get("ipProtocols"), proto) and _addr_match(r.get("sourceAddresses"), src) and _port_match(r.get("destinationPorts"), port)):
                        continue
                    if r.get("destinationFqdns"):
                        if not _fqdn_match(r["destinationFqdns"], fqdn):
                            continue
                    elif not _addr_match(r.get("destinationAddresses"), dst):
                        continue
                    return done(act, g, c.get("name"), r.get("name"), "NetworkRule")
                if r.get("fqdnTags") or r.get("webCategories"):
                    notes.append(f"rule {r.get('name')}: FQDN tags / web categories are not evaluated; skipped")
                    continue
                if proto.lower() not in ("http", "https", "mssql") or not _addr_match(r.get("sourceAddresses"), src):
                    continue
                if not any(str(p.get("protocolType", "")).lower() == proto.lower() and (p.get("port") in (None, port)) for p in r.get("protocols") or []):
                    continue
                if _fqdn_match(r.get("targetFqdns"), fqdn):
                    return done(act, g, c.get("name"), r.get("name"), "ApplicationRule")
    return done("Deny", None, None, None, "Default", reason="no rule matched: Azure Firewall denies by default")
