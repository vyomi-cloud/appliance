"""Azure "Dev Simplified" pages that have no real Microsoft backend to run against. Substrate-free (no fastapi / sockets /
subprocess), so the same file runs offline and in Nano.

    GET  /subscriptions/{sub}/providers/Microsoft.Vyomi/defenderInsights[/{kind}]   Dev Simplified Defender for Cloud pages
    *    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Vyomi/fabricMirrors[/{name}[/start|stop|sync]]
                                                                                    Dev Simplified Fabric mirroring configuration

Defender insights (``dataSecurity``, ``workloadProtections``, ``firewallManager``) are COMPUTED on every request from the live
ARM state (storage / SQL / Cosmos / Key Vault / NSG / firewall / VM / AKS / web app records): change a resource and the findings
change. They are configuration checks, not Defender's detection pipeline: no data classification, no sensitive-data scanning,
no traffic analysis.

Fabric mirroring is a configuration record (Dev Simplified). It validates that the SQL server and database exist and keeps the
mirroring settings, the run state and a *simulated* sync status (last sync time and counter); NO Microsoft Fabric workspace is
contacted and NO data is replicated or readable anywhere.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

LABEL = "Dev Simplified"
API_VERSION = "2024-01-01"
_KINDS = ("dataSecurity", "workloadProtections", "firewallManager")


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def handles(namespace, chain):
    return bool(chain) and namespace.lower() == "microsoft.vyomi" and chain[0].lower() in ("defenderinsights", "fabricmirrors")


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _recs(state, sub, *types):
    ts = {t.lower() for t in types}
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("type", "")).lower() in ts
            and (r.get("_sub") in (None, sub) or f"/subscriptions/{sub}/".lower() in str(r.get("id", "")).lower())]


def _f(r, severity, text, fix):
    return {"resourceId": r.get("id"), "resourceName": r.get("name"), "resourceType": r.get("type"), "severity": severity,
            "finding": text, "recommendation": fix}


# ═══════════════════════════ Defender for Cloud (computed) ═══════════════════════
def _data_security(state, sub):
    out = []
    for r in _recs(state, sub, "Microsoft.Storage/storageAccounts"):
        p = r.get("properties") or {}
        if p.get("allowBlobPublicAccess") is True:
            out.append(_f(r, "High", "Blob public access is allowed on the account.", "Set allowBlobPublicAccess to false."))
        if p.get("supportsHttpsTrafficOnly") is False:
            out.append(_f(r, "Medium", "Secure transfer (HTTPS only) is disabled.", "Enable secure transfer required."))
        if p.get("networkAcls", {}).get("defaultAction", "Allow") == "Allow" and p.get("publicNetworkAccess", "Enabled") != "Disabled":
            out.append(_f(r, "Medium", "The account firewall allows all networks.", "Restrict the firewall to selected networks."))
    for r in _recs(state, sub, "Microsoft.Sql/servers"):
        p = r.get("properties") or {}
        if p.get("publicNetworkAccess", "Enabled") == "Enabled":
            out.append(_f(r, "Medium", "The SQL server accepts connections over its public endpoint.", "Disable public network access or add firewall rules."))
        if str(p.get("minimalTlsVersion", "1.2")) < "1.2":
            out.append(_f(r, "Medium", "Minimum TLS version is below 1.2.", "Set minimalTlsVersion to 1.2."))
    for r in _recs(state, sub, "Microsoft.DocumentDB/databaseAccounts"):
        p = r.get("properties") or {}
        if p.get("publicNetworkAccess", "Enabled") == "Enabled" and not p.get("ipRules"):
            out.append(_f(r, "Medium", "The Cosmos DB account is reachable from all networks.", "Add IP rules or disable public network access."))
        if p.get("disableLocalAuth") is False:
            out.append(_f(r, "Low", "Key-based authentication is enabled.", "Disable local auth and use Microsoft Entra ID."))
    for r in _recs(state, sub, "Microsoft.KeyVault/vaults"):
        p = r.get("properties") or {}
        if not p.get("enablePurgeProtection"):
            out.append(_f(r, "Medium", "Purge protection is not enabled on the vault.", "Enable purge protection."))
        if p.get("enableSoftDelete") is False:
            out.append(_f(r, "High", "Soft delete is disabled on the vault.", "Enable soft delete."))
    return {"kind": "dataSecurity", "findings": out}


_PLANS = (("Servers", "Microsoft.Compute/virtualMachines"), ("Containers", "Microsoft.ContainerService/managedClusters"),
          ("App Service", "Microsoft.Web/sites"), ("Databases (SQL)", "Microsoft.Sql/servers"), ("Storage", "Microsoft.Storage/storageAccounts"),
          ("Databases (Cosmos DB)", "Microsoft.DocumentDB/databaseAccounts"), ("Key Vault", "Microsoft.KeyVault/vaults"))


def _workload_protections(state, sub):
    rows = []
    for plan, typ in _PLANS:
        rs = _recs(state, sub, typ)
        rows.append({"plan": plan, "resourceType": typ, "resources": len(rs), "names": sorted(r.get("name", "") for r in rs)[:20]})
    return {"kind": "workloadProtections", "plans": rows}


def _firewall_manager(state, sub):
    nsgs, fws = [], []
    for r in _recs(state, sub, "Microsoft.Network/networkSecurityGroups"):
        rules = (r.get("properties") or {}).get("securityRules") or []
        risky = [x.get("name") for x in rules if (x.get("properties") or {}).get("direction") == "Inbound"
                 and (x.get("properties") or {}).get("access") == "Allow"
                 and (x.get("properties") or {}).get("sourceAddressPrefix") in ("*", "0.0.0.0/0", "Internet")]
        nsgs.append({"id": r.get("id"), "name": r.get("name"), "location": r.get("location"), "rules": len(rules), "openInboundRules": risky})
    for r in _recs(state, sub, "Microsoft.Network/azureFirewalls"):
        p = r.get("properties") or {}
        fws.append({"id": r.get("id"), "name": r.get("name"), "location": r.get("location"), "tier": (p.get("sku") or {}).get("tier"),
                    "threatIntelMode": p.get("threatIntelMode"), "policy": (p.get("firewallPolicy") or {}).get("id")})
    return {"kind": "firewallManager", "networkSecurityGroups": nsgs, "firewalls": fws}


_INSIGHTS = {"datasecurity": _data_security, "workloadprotections": _workload_protections, "firewallmanager": _firewall_manager}


# ═══════════════════════════ Fabric mirroring (record) ═══════════════════════════
def _mirrors(state, sub, rg=None):
    return [r for r in state.values() if isinstance(r, dict) and r.get("_type") == "Microsoft.Vyomi/fabricMirrors" and r.get("_sub") == sub
            and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]


def _put_mirror(state, sub, rg, rid, name, payload, method):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", name or ""):
        raise _E(400, "InvalidResourceName", f"The name '{name}' is invalid.")
    old = state.get(rid.lower())
    if old is None and method == "PATCH":
        raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Vyomi/fabricMirrors/{name}' under resource group '{rg}' was not found.")
    pay = {**((old or {}).get("properties") or {}), **(payload.get("properties") or {})}
    server, db = pay.get("sqlServerName"), pay.get("databaseName")
    if not server or not db or not pay.get("fabricWorkspace"):
        raise _E(400, "InvalidParameter", "properties.sqlServerName, properties.databaseName and properties.fabricWorkspace are required.")
    sid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Sql/servers/{server}"
    if sid.lower() not in state:
        raise _E(404, "ResourceNotFound", f"The SQL server '{server}' was not found in resource group '{rg}'.")
    if f"{sid}/databases/{db}".lower() not in state:
        raise _E(404, "ResourceNotFound", f"The database '{db}' was not found on SQL server '{server}'.")
    tables = pay.get("tables") or []
    if not isinstance(tables, list):
        raise _E(400, "InvalidParameter", "properties.tables must be a list of table names (empty = all tables).")
    st = (old or {}).get("properties", {}).get("state", "Running")
    props = {"sqlServerName": server, "databaseName": db, "fabricWorkspace": pay["fabricWorkspace"], "tables": tables,
             "state": st, "dataSource": LABEL,
             "simulatedSync": (old or {}).get("properties", {}).get("simulatedSync") or {"syncCount": 0, "lastSyncTime": None,
                                                                                         "note": "Status is Dev Simplified: nothing is replicated to Fabric."},
             "provisioningState": "Succeeded"}
    rec = {"id": rid, "name": name, "type": "Microsoft.Vyomi/fabricMirrors", "location": payload.get("location") or (old or {}).get("location") or "eastus",
           "tags": payload.get("tags", (old or {}).get("tags", {})), "properties": props,
           "_type": "Microsoft.Vyomi/fabricMirrors", "_sub": sub, "_rg": rg}
    if old is None and props["state"] == "Running":
        props["simulatedSync"] = {"syncCount": 1, "lastSyncTime": _now(), "note": props["simulatedSync"]["note"]}
    state[rid.lower()] = rec
    return rec, old is None


def _mirror_action(rec, action):
    p = rec["properties"]
    if action == "stop":
        p["state"] = "Stopped"
    elif action == "start":
        p["state"] = "Running"
    elif action == "sync":
        if p["state"] != "Running":
            raise _E(409, "Conflict", "The mirror is stopped; start it before requesting a sync.")
        s = p["simulatedSync"]
        p["simulatedSync"] = {"syncCount": s["syncCount"] + 1, "lastSyncTime": _now(), "note": s["note"]}
    else:
        raise _E(404, "ActionNotSupported", f"Action '{action}' is not supported.")
    return rec


def dispatch(state, method, sub, rg, namespace, chain, payload=None, query=None):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, chain, payload)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload):
    kind = chain[0].lower()
    if kind == "defenderinsights":
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Defender insights are read-only.")
        if len(chain) == 1:
            return _ok({"value": [{"name": k, "dataSource": LABEL} for k in _KINDS]})
        fn = _INSIGHTS.get(chain[1].lower())
        if not fn:
            return _err(404, "ResourceNotFound", f"Unknown insight '{chain[1]}'. Known: {', '.join(_KINDS)}.")
        return _ok({**fn(state, sub), "dataSource": LABEL, "generatedAt": _now(),
                    "note": "Computed from the Dev Simplified view of your resources' configuration; not Microsoft Defender for Cloud detections."})
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _mirrors(state, sub, rg)]})
    if rg is None:
        return _err(400, "InvalidResourceId", "fabricMirrors must be addressed within a resource group.")
    name = chain[1]
    rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Vyomi/fabricMirrors/{name}"
    rec = state.get(rid.lower())
    nf = _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Vyomi/fabricMirrors/{name}' under resource group '{rg}' was not found.")
    if len(chain) == 3:
        if method != "POST":
            return _err(405, "MethodNotAllowed", "Actions use POST.")
        if rec is None:
            raise nf
        return _ok(_view(_mirror_action(rec, chain[2].lower())))
    if len(chain) > 3:
        return _err(404, "ResourceTypeNotSupported", "Unsupported path.")
    if method == "GET":
        if rec is None:
            raise nf
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _put_mirror(state, sub, rg, rid, name, payload, method)
        return _ok(_view(rec), 201 if created else 200)
    if method == "DELETE":
        state.pop(rid.lower(), None)
        return _ok(None, 200 if rec else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("Microsoft.Vyomi/fabricMirrors", API_VERSION)]
