# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Defender CSPM attack path analysis + Cloud Security Explorer over the LIVE ARM state (substrate-free, Nano + offline).

A security graph is built every time it is read -- nothing is stored or canned:

  nodes   every ARM resource that matters (VMs, storage accounts, Key Vaults, SQL servers, managed identities, App Services,
          NSGs/NICs/public IPs) plus a synthetic ``internet`` node;
  edges   internet -> VM            the VM's NIC has a public IP AND an NSG (NIC- or subnet-level) lets an internet source
                                    reach SSH/RDP (the same first-match priority logic as the NSG recommendation);
          VM/App -> identity        system-assigned / user-assigned managed identity;
          identity -> resource      ARM role assignments (scope inheritance honoured); each edge carries the role, and whether
                                    it is control-plane privileged (Owner / Contributor / User Access Administrator) or a
                                    data-plane role (Storage Blob Data *, Key Vault *, SQL *).
  insights  the native Defender rule engine's Unhealthy assessments on a node (public blob access, SQL public network, ...).

Attack path  internet -> exposed VM -> managed identity -> role -> target (a Key Vault / storage / SQL server / subscription-wide
role); risk Critical when the role is privileged or the target also carries an Unhealthy data-exposure insight, else High.
Cloud Security Explorer  {"nodeType": "microsoft.compute/virtualmachines", "filters": ["exposedToInternet", "hasIdentity",
"canAccess:microsoft.keyvault/vaults", "hasRecommendation", "privileged"]} -> matching nodes with the evidence per filter.

Gated by the Defender CSPM plan like Azure.  No traffic or process telemetry exists, so reachability is configuration-derived
(the path says "can", never "did").
"""
from __future__ import annotations

import uuid

try:
    from core import azure_security_core as sec
    from core import azure_iam_core as iam
except ImportError:                                    # Pyodide flat layout
    import azure_security_core as sec                  # type: ignore
    import azure_iam_core as iam                       # type: ignore

PRIVILEGED = {"owner", "contributor", "user access administrator"}
DATA_ROLE_HINTS = ("storage blob data", "storage queue data", "storage table data", "key vault", "sql", "cosmos db", "azure service bus data", "azure event hubs data")
TARGET_TYPES = {"microsoft.keyvault/vaults": "Key Vault", "microsoft.storage/storageaccounts": "Storage account", "microsoft.sql/servers": "SQL server",
                "microsoft.documentdb/databaseaccounts": "Cosmos DB account"}


def _rid(r):
    return str(r.get("id") or "")


def _low(s):
    return str(s or "").lower()


def _uid(*parts):
    return str(uuid.uuid5(sec._UUID_NS, "|".join(map(str, parts))))


def _role_name(ref):
    tail = str(ref or "").rsplit("/", 1)[-1]
    return iam._BUILTIN_IDS.get(tail.lower()) or tail


def _resources(state, sub):
    return [r for r in state.values() if isinstance(r, dict) and r.get("_sub") == sub and r.get("id") and sec._rec_type(r)]


def _vm_exposure(state, vm, by_id):
    """-> (exposed_ports[(port, rule)], public_ips[str]) for a VM via its NICs."""
    ports, ips = [], []
    for nref in ((sec._props(vm).get("networkProfile") or {}).get("networkInterfaces") or []):
        nic = by_id.get(_low(nref.get("id")))
        if not nic:
            continue
        has_pip = False
        subnet_ids = []
        for ic in sec._props(nic).get("ipConfigurations") or []:
            ip = ic.get("properties") or {}
            pip = by_id.get(_low((ip.get("publicIPAddress") or {}).get("id")))
            if pip:
                has_pip = True
                ips.append(sec._props(pip).get("ipAddress") or pip.get("name"))
            if (ip.get("subnet") or {}).get("id"):
                subnet_ids.append(_low(ip["subnet"]["id"]))
        if not has_pip:
            continue
        nsg_ids = []
        if (sec._props(nic).get("networkSecurityGroup") or {}).get("id"):
            nsg_ids.append(_low(sec._props(nic)["networkSecurityGroup"]["id"]))
        for sid in subnet_ids:
            vnet_id, _, sname = sid.partition("/subnets/")
            vnet = by_id.get(vnet_id)
            for sn in (sec._props(vnet or {}).get("subnets") or []):
                if _low(sn.get("name")) == sname and ((sn.get("properties") or {}).get("networkSecurityGroup") or {}).get("id"):
                    nsg_ids.append(_low(sn["properties"]["networkSecurityGroup"]["id"]))
            sub_rec = by_id.get(sid)
            if sub_rec and (sec._props(sub_rec).get("networkSecurityGroup") or {}).get("id"):
                nsg_ids.append(_low(sec._props(sub_rec)["networkSecurityGroup"]["id"]))
        for nid in nsg_ids:
            nsg = by_id.get(nid)
            if nsg:
                for port, rule, _ in sec._exposed_ports(state, nid, nsg):
                    ports.append((port, rule))
    return ports, ips


def _identities(res):
    ident = res.get("identity") or {}
    out = []
    if ident.get("principalId"):
        out.append(("system-assigned", ident["principalId"], None))
    for uid, v in (ident.get("userAssignedIdentities") or {}).items():
        if (v or {}).get("principalId"):
            out.append(("user-assigned", v["principalId"], uid))
    return out


def build(state, sub):
    res = _resources(state, sub)
    by_id = {_low(_rid(r)): r for r in res}
    # unhealthy insights per resource id from the live rule engine
    ev = sec.evaluate(state, sub, refresh=False)
    insights = {}
    for a in ev["assessments"]:
        if a["status"] == "Unhealthy":
            insights.setdefault(_low(a["rid"]), []).append({"name": a["meta"]["displayName"], "severity": a["meta"]["severity"], "cause": a["cause"]})
    assigns = []
    for r in state.values():
        if isinstance(r, dict) and _low(r.get("_type", r.get("type"))) == "microsoft.authorization/roleassignments":
            p = r.get("properties") or {}
            scope = p.get("scope") or _rid(r).rsplit("/providers/Microsoft.Authorization/roleAssignments/", 1)[0]
            assigns.append({"principalId": p.get("principalId"), "scope": scope, "role": _role_name(p.get("roleDefinitionId") or p.get("roleDefinition"))})
    nodes, edges = {}, []
    nodes["internet"] = {"id": "internet", "type": "internet", "name": "Internet", "insights": []}
    for r in res:
        t = sec._rec_type(r)
        n = {"id": _rid(r), "type": t, "name": r.get("name"), "insights": insights.get(_low(_rid(r)), []), "exposedToInternet": False,
             "identities": [], "access": []}
        nodes[_low(_rid(r))] = n
    for r in res:
        t = sec._rec_type(r)
        n = nodes[_low(_rid(r))]
        if t == "microsoft.compute/virtualmachines":
            ports, ips = _vm_exposure(state, r, by_id)
            if ports:
                n["exposedToInternet"] = True
                n["exposure"] = {"ports": [{"port": p, "rule": ru} for p, ru in ports], "publicIps": ips}
                edges.append({"from": "internet", "to": n["id"], "kind": "exposes", "detail": ", ".join(f"port {p} via rule '{ru}'" for p, ru in ports)})
        if t in ("microsoft.compute/virtualmachines", "microsoft.web/sites", "microsoft.containerservice/managedclusters"):
            for kind, pid, uid in _identities(r):
                n["identities"].append({"kind": kind, "principalId": pid, "resource": uid})
                edges.append({"from": n["id"], "to": f"identity:{pid}", "kind": "hasIdentity", "detail": kind})
                for a in assigns:
                    if a["principalId"] != pid:
                        continue
                    for tr in res:
                        tt = sec._rec_type(tr)
                        if tt in TARGET_TYPES and iam._scope_covers(a["scope"], _rid(tr)):
                            priv = _low(a["role"]) in PRIVILEGED
                            data = any(h in _low(a["role"]) for h in DATA_ROLE_HINTS)
                            if not (priv or data):
                                continue
                            n["access"].append({"target": _rid(tr), "targetType": tt, "role": a["role"], "privileged": priv, "scope": a["scope"]})
                            edges.append({"from": f"identity:{pid}", "to": _rid(tr), "kind": "canAccess", "detail": f"{a['role']} at {a['scope']}"})
    return {"nodes": nodes, "edges": edges, "assignments": assigns}


def attack_paths(state, sub):
    g = build(state, sub)
    out = []
    for n in g["nodes"].values():
        if n.get("type") != "microsoft.compute/virtualmachines" or not n["exposedToInternet"]:
            continue
        for acc in n["access"]:
            tgt = g["nodes"].get(_low(acc["target"])) or {}
            risky = acc["privileged"] or any(i["severity"] in ("High", "Medium") for i in tgt.get("insights", []))
            risk = "Critical" if acc["privileged"] and tgt.get("insights") else ("High" if risky or acc["privileged"] else "Medium")
            steps = [
                {"node": "Internet", "type": "internet"},
                {"node": n["name"], "type": n["type"], "via": n["exposure"]["ports"]},
                {"node": f"managed identity ({n['identities'][0]['kind']})" if n["identities"] else "identity", "type": "identity", "principalId": n["identities"][0]["principalId"] if n["identities"] else None},
                {"node": tgt.get("name"), "type": acc["targetType"], "role": acc["role"], "roleScope": acc["scope"], "insights": tgt.get("insights", [])},
            ]
            out.append({"id": _uid("path", n["id"], acc["target"], acc["role"]), "displayName": f"Internet exposed VM '{n['name']}' can reach {TARGET_TYPES.get(acc['targetType'], acc['targetType'])} '{tgt.get('name')}'",
                        "riskLevel": risk, "entryPoint": n["id"], "target": acc["target"], "steps": steps,
                        "remediation": [f"Remove or restrict the NSG rule(s) {', '.join(str(p['rule']) for p in n['exposure']['ports'])} so SSH/RDP is not reachable from the internet.",
                                        f"Reduce the '{acc['role']}' role of the VM's managed identity to the narrowest scope/role it needs."] +
                                       [f"Fix: {i['name']}" for i in tgt.get("insights", [])]})
    order = {"Critical": 0, "High": 1, "Medium": 2}
    return sorted(out, key=lambda p: (order[p["riskLevel"]], p["displayName"]))


def explore(state, sub, q):
    g = build(state, sub)
    t = _low(q.get("nodeType"))
    filters = [str(f) for f in q.get("filters") or []]
    res = []
    for n in g["nodes"].values():
        if n["type"] in ("internet",) or (t and n["type"] != t):
            continue
        ev = {}
        ok = True
        for f in filters:
            fl = f.lower()
            if fl == "exposedtointernet":
                hit = n.get("exposedToInternet")
                ev[f] = n.get("exposure")
            elif fl == "hasidentity":
                hit = bool(n.get("identities"))
                ev[f] = n.get("identities")
            elif fl == "hasrecommendation":
                hit = bool(n.get("insights"))
                ev[f] = n.get("insights")
            elif fl == "privileged":
                ev[f] = [a for a in n.get("access", []) if a["privileged"]]
                hit = bool(ev[f])
            elif fl.startswith("canaccess:"):
                want = fl.split(":", 1)[1]
                ev[f] = [a for a in n.get("access", []) if a["targetType"] == want]
                hit = bool(ev[f])
            else:
                return {"error": f"Unknown filter '{f}'. Use exposedToInternet, hasIdentity, hasRecommendation, privileged, canAccess:<resource type>."}
            ok = ok and bool(hit)
        if ok:
            res.append({"id": n["id"], "name": n["name"], "type": n["type"], "evidence": ev})
    return {"query": q, "count": len(res), "results": sorted(res, key=lambda x: x["name"] or "")}
