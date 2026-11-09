# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure "Dev Simplified" pages that have no real Microsoft backend to run against. Substrate-free (no fastapi / sockets /
subprocess), so the same file runs offline and in Nano.

    GET  /subscriptions/{sub}/providers/Microsoft.Vyomi/defenderInsights[/{kind}]   Dev Simplified Defender for Cloud pages
    *    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Vyomi/fabricMirrors[/{name}[/start|stop|sync]]
                                                                                    Fabric mirroring configuration (the worker is azure_sql_mirror_core)

Defender insights (``dataSecurity``, ``workloadProtections``, ``firewallManager``) are COMPUTED on every request from the live
ARM state (storage / SQL / Cosmos / Key Vault / NSG / firewall / VM / AKS / web app records): change a resource and the findings
change. They are configuration checks, not Defender's detection pipeline: no data classification, no sensitive-data scanning,
no traffic analysis.

A Fabric mirror is the configuration record of a REAL replication: it validates that the SQL server and database exist and keeps
the settings (tables, destination container). The sync itself is the data-plane worker core/azure_sql_mirror_core.py, which
copies the tables into Parquet files in the simulator's blob store. Microsoft Fabric itself is not in scope.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

LABEL = "Dev Simplified"
API_VERSION = "2024-01-01"
_KINDS = ("dataSecurity", "workloadProtections", "firewallManager")
TRIVY_IMAGE = "aquasec/trivy:0.57.1"


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


# ═══════════════════════════ DevOps security: REAL Trivy IaC scan ════════════════
_TPL = ("{{ range . }}{{ range .Misconfigurations }}{{ .ID }}\t{{ .Severity }}\t{{ .Title }}\t{{ .Message }}\t{{ .Resolution }}\t{{ .PrimaryURL }}\n{{ end }}{{ end }}")
_CMD = ("mkdir -p /tmp/s && cat > /tmp/s/main.json && HOME=/tmp trivy config --cache-dir /tmp/c --skip-check-update --quiet "
        "--format template --template '" + _TPL + "' /tmp/s")
_SKIP_TYPES = ("microsoft.resources/resourcegroups", "microsoft.logic/workflows", "microsoft.logic/workflows/runs", "microsoft.vyomi/fabricmirrors", "microsoft.vyomi/iacscanresults")


def iac_scan(state, sub, exporter, runner):
    """Export each resource group as an ARM template and run the REAL Trivy misconfiguration engine on it (offline container, no network)."""
    if runner is None or exporter is None:
        raise _E(501, "NotImplemented", "IaC scanning runs Trivy in a container and needs Docker on the offline appliance; this context has no container engine.")
    rgs = sorted({r["_rg"] for r in state.values() if isinstance(r, dict) and r.get("_sub") == sub and r.get("_rg")
                  and str(r.get("_type", "")).lower() not in _SKIP_TYPES and "/" in str(r.get("_type", ""))})
    findings, scanned, started = [], [], _now()
    for rg in rgs:
        tpl = exporter(rg)
        if not tpl or not tpl.get("resources"):
            continue
        res = runner(TRIVY_IMAGE, _CMD, {}, 180, stdin=json.dumps(tpl).encode(), tmpfs_mb=256, memory_mb=768)
        if res.get("error"):
            raise _E(400 if res["error"] == "ImageNotFound" else 500, res["error"], res["message"])
        if res["exitCode"] != 0:
            raise _E(500, "ScannerFailed", f"Trivy exited with code {res['exitCode']}: {res['logs'][-300:]}")
        for line in res["logs"].splitlines():
            parts = line.split("\t")
            if len(parts) >= 6:
                findings.append({"resourceGroup": rg, "ruleId": parts[0], "severity": parts[1].title(), "title": parts[2], "message": parts[3],
                                 "recommendation": parts[4], "reference": parts[5], "scanner": "Trivy " + TRIVY_IMAGE.split(":")[1]})
        scanned.append({"resourceGroup": rg, "resources": len(tpl["resources"]), "durationMs": res.get("durationMs")})
    out = {"scanner": TRIVY_IMAGE, "startedAt": started, "completedAt": _now(), "scanned": scanned, "findings": findings,
           "summary": {sev: sum(1 for f in findings if f["severity"] == sev) for sev in ("Critical", "High", "Medium", "Low")}}
    state[f"/subscriptions/{sub}/providers/microsoft.vyomi/iacscanresults/latest"] = {"_type": "Microsoft.Vyomi/iacScanResults", "_sub": sub, "result": out}
    return out


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
             "state": st, "destinationContainer": pay.get("destinationContainer") or f"fabric-mirror-{name.lower()}"[:63],
             "destinationPrefix": pay.get("destinationPrefix") or "mirror", "provisioningState": "Succeeded"}
    rec = {"id": rid, "name": name, "type": "Microsoft.Vyomi/fabricMirrors", "location": payload.get("location") or (old or {}).get("location") or "eastus",
           "tags": payload.get("tags", (old or {}).get("tags", {})), "properties": props,
           "_type": "Microsoft.Vyomi/fabricMirrors", "_sub": sub, "_rg": rg}
    state[rid.lower()] = rec
    return rec, old is None


def _mirror_action(rec, action):
    """start / stop only change whether the console may run syncs; the replication itself is the data-plane worker
    (core/azure_sql_mirror_core.py, POST /azure-sql/servers/{s}/databases/{db}/mirror/sync)."""
    if action == "stop":
        rec["properties"]["state"] = "Stopped"
    elif action == "start":
        rec["properties"]["state"] = "Running"
    else:
        raise _E(404, "ActionNotSupported", f"Action '{action}' is not supported.")
    return rec


def dispatch(state, method, sub, rg, namespace, chain, payload=None, query=None, exporter=None, runner=None):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, chain, payload, exporter, runner)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload, exporter=None, runner=None):
    kind = chain[0].lower()
    if kind == "defenderinsights" and len(chain) == 2 and chain[1].lower() == "iacscan":
        if method == "POST":
            return _ok({**iac_scan(state, sub, exporter, runner), "dataSource": "Trivy"})
        if method == "GET":
            last = state.get(f"/subscriptions/{sub}/providers/microsoft.vyomi/iacscanresults/latest")
            return _ok({**(last["result"] if last else {"findings": [], "scanned": [], "summary": {}, "completedAt": None}), "dataSource": "Trivy"})
        return _err(405, "MethodNotAllowed", "GET the last result or POST to run a scan.")
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
