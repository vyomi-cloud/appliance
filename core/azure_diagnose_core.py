"""Azure "Diagnose and solve problems" detector engine (Nano / dev_server / unified-ingress core, pure Python).

One ARM extension resource, scoped to ANY resource's own id (same re-entering-"providers" shape as locks and
availabilityStatuses):

    GET {resourceId}/providers/Microsoft.Vyomi/diagnostics[/{detectorId}]

Every detector is COMPUTED from the live resource record in the ARM state map, from the child records stored under it
(AKS node pools/namespaces, APIM apis/subscriptions, App Configuration keys, Cognitive Services deployments, site
functions/invocations) and from the resource's own Activity log (recent failed operations, locks).  Nothing is canned:
change the resource (stop the cluster, open the firewall, scale to zero) and the findings change.  The same kit
(``_d`` / ``_finish`` / the generic detectors) backs every service; each service adds its own check set.

Statuses (worst first): Critical, Warning, Info, Healthy.  Each detector carries ``recommendation`` (what to change) and
``evidence`` (the live values it read) so a finding is traceable.

Limits (also stated in core/capabilities): there is no platform telemetry (no real node health, no real gateway
traffic) behind a simulator, so detectors reason over configuration, provisioning state, child resources and recorded
operations only -- never over invented metrics.
"""
from __future__ import annotations

import datetime

API_VERSION = "2024-01-01"
ORDER = {"Critical": 0, "Warning": 1, "Info": 2, "Healthy": 3}
# Kubernetes minor versions AKS still serves (bundled support table; update with the AKS release calendar).
AKS_SUPPORTED = ("1.31", "1.32", "1.33")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def find_marker(chain):
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.vyomi"
                and chain[i + 2].lower() == "diagnostics"):
            return i
    return None


def _d(did, name, category, status, detail, recommendation=None, evidence=None):
    return {"id": did, "name": name, "category": category, "status": status, "detail": detail,
            "recommendation": recommendation, "evidence": evidence or {}}


def _children(state, rid, typ_fragment=None):
    pre = rid.lower() + "/"
    out = []
    for k, v in state.items():
        if k.startswith(pre) and "/__event__/" not in k and (typ_fragment is None or typ_fragment in k[len(pre):].split("/", 1)[0]):
            out.append(v)
    return out


def _events(state, rid):
    out = [v for k, v in state.items() if "/__event__/" in k and (v.get("resourceId") or "").lower() == rid.lower()]
    return sorted(out, key=lambda e: e.get("eventTimestamp") or "")


def _generic(state, rec):
    """Detectors every resource gets: provisioning state, recent failed operations, management locks."""
    p = rec.get("properties") or {}
    out = []
    ps = p.get("provisioningState") or "Succeeded"
    out.append(_d("provisioning", "Provisioning state", "Availability", "Healthy" if ps == "Succeeded" else "Critical",
                  f"Provisioning state is {ps}.", None if ps == "Succeeded" else "Re-apply the resource (PUT) or delete and recreate it.",
                  {"provisioningState": ps}))
    ev = _events(state, rec["id"])
    failed = [e for e in ev if ((e.get("status") or {}).get("value") or "").lower() in ("failed", "error")]
    recent = ev[-20:]
    rf = [e for e in recent if e in failed]
    out.append(_d("recent-failures", "Recent failed operations", "Reliability",
                  "Critical" if len(rf) >= 3 else ("Warning" if rf else "Healthy"),
                  (f"{len(rf)} of the last {len(recent)} recorded operations failed; most recent: "
                   f"{(rf[-1].get('operationName') or {}).get('value')} at {rf[-1].get('eventTimestamp')}.") if rf
                  else (f"None of the last {len(recent)} recorded operations failed." if recent else "No operations recorded yet."),
                  "Open the Activity log and inspect the failing operation." if rf else None,
                  {"recentOperations": len(recent), "failed": len(rf)}))
    locks = [v for v in state.values() if v.get("_lock_scope") == rec["id"].lower()]
    if locks:
        ro = [l for l in locks if (l.get("properties") or {}).get("level") == "ReadOnly"]
        out.append(_d("locks", "Management locks", "Configuration", "Warning" if ro else "Info",
                      f"{len(locks)} lock(s) apply; {len(ro)} ReadOnly -- writes to this resource will be blocked." if ro
                      else f"{len(locks)} CanNotDelete lock(s) apply; deletes are blocked.",
                      "Remove the ReadOnly lock before changing this resource." if ro else None,
                      {"locks": [l.get("name") for l in locks]}))
    return out


# ── AKS ──────────────────────────────────────────────────────────────────────────────
def _aks(state, rec):
    p = rec.get("properties") or {}
    out = []
    pw = (p.get("powerState") or {}).get("code") or "Running"
    out.append(_d("power", "Cluster power state", "Availability", "Healthy" if pw == "Running" else "Critical",
                  f"The cluster is {pw}." + ("" if pw == "Running" else " The control plane and every node are down."),
                  None if pw == "Running" else "Start the cluster (az aks start).", {"powerState": pw}))
    pools = p.get("agentPoolProfiles") or []
    nodes = sum(int(q.get("count") or 0) for q in pools)
    out.append(_d("nodepools", "Node pools and capacity", "Availability",
                  "Critical" if not pools or nodes == 0 else "Healthy",
                  f"{len(pools)} node pool(s), {nodes} node(s) in total." if pools and nodes else
                  "No node has capacity to schedule workloads (zero node pools or every pool is scaled to 0).",
                  None if nodes else "Add a node pool or scale one up.", {"pools": [q.get("name") for q in pools], "nodes": nodes}))
    single = [q.get("name") for q in pools if int(q.get("count") or 0) == 1 and not q.get("enableAutoScaling")]
    if pools and nodes:
        out.append(_d("single-node", "Single-node pools", "Reliability", "Warning" if len(single) == len(pools) else "Healthy",
                      f"Every pool has a single fixed node ({', '.join(single)}); one node failure or upgrade drains the whole cluster." if len(single) == len(pools)
                      else "At least one pool has more than one node or autoscaling.",
                      "Use >= 2 nodes (or enable the cluster autoscaler) for system pools." if len(single) == len(pools) else None,
                      {"singleNodePools": single}))
    bad_as = [q.get("name") for q in pools if q.get("enableAutoScaling") and int(q.get("minCount") or 0) > int(q.get("maxCount") or 0)]
    if bad_as:
        out.append(_d("autoscaler", "Cluster autoscaler bounds", "Configuration", "Critical",
                      f"minCount > maxCount on pool(s): {', '.join(bad_as)}.", "Fix the autoscaler min/max.", {"pools": bad_as}))
    ver = str(p.get("kubernetesVersion") or "")
    minor = ".".join(ver.split(".")[:2])
    sup = minor in AKS_SUPPORTED
    out.append(_d("k8s-version", "Kubernetes version support", "Reliability", "Healthy" if sup else "Warning",
                  f"Kubernetes {ver} is within the supported window ({', '.join(AKS_SUPPORTED)})." if sup
                  else f"Kubernetes {ver} is outside the supported minor versions ({', '.join(AKS_SUPPORTED)}).",
                  None if sup else "Upgrade the control plane and node pools.", {"kubernetesVersion": ver, "supported": list(AKS_SUPPORTED)}))
    channel = (p.get("autoUpgradeProfile") or {}).get("upgradeChannel")
    if channel in (None, "none"):
        out.append(_d("auto-upgrade", "Auto-upgrade channel", "Best practice", "Info", "No auto-upgrade channel is set; upgrades are manual.",
                      "Set upgradeChannel to patch/stable.", {"upgradeChannel": channel}))
    rbac = p.get("enableRBAC", True)
    out.append(_d("rbac", "Kubernetes RBAC", "Security", "Healthy" if rbac else "Critical",
                  "Kubernetes RBAC is enabled." if rbac else "Kubernetes RBAC is disabled -- every credential is cluster-admin.",
                  None if rbac else "Recreate the cluster with RBAC enabled.", {"enableRBAC": rbac}))
    api = p.get("apiServerAccessProfile") or {}
    private = bool(api.get("enablePrivateCluster"))
    ranges = api.get("authorizedIPRanges") or []
    out.append(_d("api-exposure", "API server exposure", "Security", "Healthy" if (private or ranges) else "Warning",
                  "The API server is private." if private else (f"The API server is restricted to {len(ranges)} authorized range(s)." if ranges
                  else "The API server is public with no authorized IP ranges."),
                  None if (private or ranges) else "Set authorizedIPRanges or enable a private cluster.",
                  {"privateCluster": private, "authorizedIPRanges": ranges}))
    np_ = (p.get("networkProfile") or {}).get("networkPolicy")
    out.append(_d("netpol", "Network policy", "Security", "Healthy" if np_ else "Info",
                  f"Network policy engine: {np_}." if np_ else "No network policy engine is configured; all pod traffic is allowed.",
                  None if np_ else "Enable azure/calico/cilium network policy.", {"networkPolicy": np_}))
    ns = p.get("namespaces") or []
    terminating = [n.get("name") for n in ns if n.get("status") not in (None, "Active")]
    if terminating:
        out.append(_d("namespaces", "Namespaces", "Reliability", "Warning", f"Namespace(s) not Active: {', '.join(terminating)}.",
                      "Check finalizers on the stuck namespace.", {"namespaces": terminating}))
    return out


# ── API Management ─────────────────────────────────────────────────────────────────
def _apim(state, rec):
    p = rec.get("properties") or {}
    sku = (rec.get("sku") or {})
    name, cap = sku.get("name") or "Developer", int(sku.get("capacity") or 1)
    out = []
    consumption = name.lower() == "consumption"
    out.append(_d("sku-sla", "SKU and SLA", "Availability", "Warning" if name.lower() == "developer" else "Healthy",
                  f"{name} with {cap} unit(s)." + (" The Developer tier has no SLA and a single point of failure." if name.lower() == "developer" else ""),
                  "Use Standard/Premium (>= 2 units) for production." if name.lower() == "developer" else None, {"sku": name, "capacity": cap}))
    if not consumption and cap < 1:
        out.append(_d("capacity", "Gateway capacity", "Availability", "Critical", "Capacity is 0 units; the gateway cannot serve requests.", "Scale out to >= 1 unit.", {"capacity": cap}))
    apis = _children(state, rec["id"], "apis")
    apis = [a for a in apis if len(a["id"].split("/")) == len(rec["id"].split("/")) + 2]
    subs = [s for s in _children(state, rec["id"], "subscriptions") if len(s["id"].split("/")) == len(rec["id"].split("/")) + 2]
    out.append(_d("apis", "Published APIs", "Configuration", "Info" if not apis else "Healthy",
                  f"{len(apis)} API(s) are published." if apis else "No API is published; the gateway returns 404 for every route.",
                  None if apis else "Import or create an API.", {"apis": len(apis)}))
    insecure = [a.get("name") for a in apis if "https" not in [str(x).lower() for x in ((a.get("properties") or {}).get("protocols") or ["https"])]]
    if insecure:
        out.append(_d("api-protocols", "API protocols", "Security", "Warning", f"API(s) served without HTTPS: {', '.join(insecure)}.", "Restrict protocols to https.", {"apis": insecure}))
    inactive = [s.get("name") for s in subs if (s.get("properties") or {}).get("state") in ("suspended", "cancelled", "expired", "rejected")]
    if inactive:
        out.append(_d("subscriptions", "Subscription keys", "Reliability", "Warning", f"Subscription(s) not active: {', '.join(inactive)}; callers using them get 401.", "Activate or reissue the subscription.", {"subscriptions": inactive}))
    pna = p.get("publicNetworkAccess", "Enabled")
    vnet = p.get("virtualNetworkType", "None")
    out.append(_d("network", "Network exposure", "Security", "Healthy" if (vnet != "None" or pna == "Disabled") else "Info",
                  f"VNet mode {vnet}; public network access {pna}.", "Use an Internal VNet mode or private endpoint for non-public APIs." if (vnet == "None" and pna != "Disabled") else None,
                  {"virtualNetworkType": vnet, "publicNetworkAccess": pna}))
    hosts = p.get("hostnameConfigurations") or []
    builtin = [h.get("hostName") for h in hosts if (h.get("certificateSource") or "BuiltIn") == "BuiltIn"]
    out.append(_d("hostnames", "Gateway hostnames", "Configuration", "Info" if builtin and len(builtin) == len(hosts) else "Healthy",
                  "Only the default azure-api.net hostname with the built-in certificate is configured." if builtin and len(builtin) == len(hosts)
                  else f"{len(hosts)} hostname(s) configured.", "Add a custom domain with your own certificate for production." if builtin and len(builtin) == len(hosts) else None,
                  {"hostnames": [h.get("hostName") for h in hosts]}))
    return out


# ── App Configuration ────────────────────────────────────────────────────────────────
def _appconfig(state, rec):
    p = rec.get("properties") or {}
    sku = ((rec.get("sku") or {}).get("name") or "standard").lower()
    out = []
    kv = (rec.get("_kv") or {}).get("items") or {}
    n = len(kv)
    limit = 1000 if sku == "free" else None
    out.append(_d("key-count", "Key-value volume", "Capacity", "Critical" if limit and n >= limit else ("Warning" if limit and n >= limit * 0.8 else "Healthy"),
                  (f"{n} of {limit} key-values used on the Free tier." if limit else f"{n} key-value(s) stored."),
                  "Move to the Standard tier or delete unused keys." if limit and n >= limit * 0.8 else None, {"keyValues": n, "freeLimit": limit}))
    dla = bool(p.get("disableLocalAuth"))
    out.append(_d("auth", "Access-key authentication", "Security", "Healthy" if dla else "Info",
                  "Local (access key) authentication is disabled; only Entra ID works." if dla else "Access keys are enabled in addition to Entra ID.",
                  None if dla else "Set disableLocalAuth=true once clients use Entra ID.", {"disableLocalAuth": dla}))
    pna = p.get("publicNetworkAccess", "Enabled")
    pecs = p.get("privateEndpointConnections") or []
    out.append(_d("network", "Network access", "Security", "Warning" if pna == "Enabled" and not pecs and not dla else "Healthy",
                  f"Public network access {pna}; {len(pecs)} private endpoint connection(s).",
                  "Restrict public access or add a private endpoint." if pna == "Enabled" and not pecs and not dla else None,
                  {"publicNetworkAccess": pna, "privateEndpointConnections": len(pecs)}))
    sd = int(p.get("softDeleteRetentionInDays") or 0)
    pp = bool(p.get("enablePurgeProtection"))
    out.append(_d("soft-delete", "Soft delete and purge protection", "Reliability", "Warning" if sku != "free" and not pp else ("Info" if sku == "free" else "Healthy"),
                  "Free tier stores have no soft delete: a deleted store is gone." if sku == "free" else f"Soft delete retains {sd} day(s); purge protection {'on' if pp else 'off'}.",
                  "Enable purge protection." if sku != "free" and not pp else None, {"softDeleteRetentionInDays": sd, "enablePurgeProtection": pp}))
    refs = [k for k, v in kv.items() if "keyvaultref" in str((v or {}).get("content_type") or (v or {}).get("contentType") or "").lower()]
    if refs and ((rec.get("identity") or {}).get("type") or "None") == "None":
        out.append(_d("kv-refs", "Key Vault references", "Reliability", "Warning", f"{len(refs)} Key Vault reference(s) exist but the store has no managed identity to resolve them.",
                      "Assign a managed identity with Key Vault access.", {"references": len(refs)}))
    return out


# ── Cognitive Services ───────────────────────────────────────────────────────────────
def _cogs(state, rec):
    p = rec.get("properties") or {}
    kind = rec.get("kind") or "CognitiveServices"
    out = []
    rl = (p.get("callRateLimit") or {})
    out.append(_d("endpoint", "Endpoint", "Availability", "Healthy" if p.get("endpoint") else "Critical",
                  f"Endpoint {p.get('endpoint')}." if p.get("endpoint") else "The account has no endpoint.", None, {"endpoint": p.get("endpoint"), "callRateLimit": rl.get("count")}))
    sub = p.get("customSubDomainName")
    out.append(_d("subdomain", "Custom subdomain", "Configuration", "Healthy" if sub else "Warning",
                  f"Custom subdomain '{sub}' is set (required for Entra ID and private link)." if sub else "No custom subdomain: Entra ID authentication and private endpoints are unavailable.",
                  None if sub else "Set customSubDomainName.", {"customSubDomainName": sub}))
    dla = bool(p.get("disableLocalAuth"))
    out.append(_d("auth", "Key authentication", "Security", "Healthy" if dla else "Info",
                  "API keys are disabled; only Entra ID works." if dla else "API-key authentication is enabled.", None if dla else "Prefer Entra ID and set disableLocalAuth.", {"disableLocalAuth": dla}))
    acl = p.get("networkAcls") or {}
    pna = p.get("publicNetworkAccess", "Enabled")
    open_ = pna == "Enabled" and (acl.get("defaultAction") or "Allow") == "Allow"
    out.append(_d("network", "Network rules", "Security", "Warning" if open_ else "Healthy",
                  "Reachable from all networks." if open_ else f"Public access {pna}; default action {acl.get('defaultAction')}.",
                  "Restrict with networkAcls or a private endpoint." if open_ else None, {"publicNetworkAccess": pna, "defaultAction": acl.get("defaultAction")}))
    deps = rec.get("_deployments") or {}
    if kind in ("OpenAI", "AIServices"):
        failed = [n for n, d in deps.items() if ((d.get("properties") or {}).get("provisioningState") or "Succeeded") != "Succeeded"]
        out.append(_d("deployments", "Model deployments", "Availability", "Critical" if failed else ("Warning" if not deps else "Healthy"),
                      (f"Deployment(s) not provisioned: {', '.join(failed)}." if failed else
                       (f"{len(deps)} model deployment(s)." if deps else "No model deployment exists; inference calls return DeploymentNotFound.")),
                      "Check the failed deployment's capacity/model." if failed else (None if deps else "Create a model deployment."), {"deployments": list(deps)}))
        used = sum(int(((d.get("sku") or {}).get("capacity")) or 0) for d in deps.values())
        if used:
            out.append(_d("capacity", "Provisioned throughput", "Capacity", "Info", f"{used} capacity unit(s) allocated across deployments.", None, {"capacityUnits": used}))
    keys = rec.get("_keys") or {}
    out.append(_d("keys", "Access keys", "Security", "Healthy" if keys or dla else "Warning", f"{len(keys)} key(s) issued." if keys else "No key present.", None, {"keys": len(keys)}))
    return out


# ── App Service / Function App ───────────────────────────────────────────────────────
def _site(state, rec):
    p = rec.get("properties") or {}
    cfg = p.get("siteConfig") or {}
    kind = rec.get("kind") or "app"
    fn = "functionapp" in kind.lower()
    out = []
    out.append(_d("state", "Application state", "Availability", "Healthy" if p.get("state") == "Running" else "Critical",
                  f"The app is {p.get('state')}.", None if p.get("state") == "Running" else "Start the app.", {"state": p.get("state")}))
    inv = (rec.get("_invocationlog") or [])[-20:]
    errs = [e for e in inv if not e.get("ok")]
    rate = (len(errs) / len(inv)) if inv else 0
    out.append(_d("failures", "Function execution failures" if fn else "Request failures", "Reliability",
                  "Critical" if rate > 0.2 else ("Warning" if errs else "Healthy"),
                  (f"{len(errs)} of the last {len(inv)} invocations failed" + (f"; last error: {errs[-1].get('error')}" if errs else ".")) if inv else "No invocations recorded yet.",
                  "Open Log stream for the failing function." if errs else None, {"recent": len(inv), "failed": len(errs)}))
    https = bool(p.get("httpsOnly"))
    out.append(_d("https", "HTTPS only", "Security", "Healthy" if https else "Warning", "HTTP is redirected to HTTPS." if https else "Plain HTTP is accepted.", None if https else "Turn on HTTPS Only.", {"httpsOnly": https}))
    tls = cfg.get("minTlsVersion") or "1.2"
    out.append(_d("tls", "Minimum TLS version", "Security", "Healthy" if tls in ("1.2", "1.3") else "Warning", f"Minimum TLS version is {tls}.", None if tls in ("1.2", "1.3") else "Raise to 1.2.", {"minTlsVersion": tls}))
    ftps = cfg.get("ftpsState") or "AllAllowed"
    out.append(_d("ftps", "FTP state", "Security", "Healthy" if ftps in ("FtpsOnly", "Disabled") else "Warning", f"FTP state is {ftps}.", None if ftps in ("FtpsOnly", "Disabled") else "Use FtpsOnly or Disabled.", {"ftpsState": ftps}))
    plan = state.get((p.get("serverFarmId") or "").lower()) or {}
    sku = ((plan.get("sku") or {}).get("name") or p.get("sku") or "")
    low = sku[:1].upper() in ("F", "D") or sku.lower() in ("free", "shared")
    if not fn:
        ao = bool(cfg.get("alwaysOn"))
        out.append(_d("always-on", "Always On", "Reliability", "Warning" if not ao and not low else ("Info" if low else "Healthy"),
                      "The app is on a Free/Shared plan which cannot enable Always On; it idles out." if low else ("Always On keeps the worker warm." if ao else "Always On is off; the app unloads after 20 minutes idle."),
                      "Enable Always On." if (not ao and not low) else None, {"alwaysOn": ao, "plan": sku}))
        hc = cfg.get("healthCheckPath")
        out.append(_d("health-check", "Health check", "Reliability", "Healthy" if hc else "Info", f"Health check path {hc}." if hc else "No health check path; unhealthy instances are not rotated out.", None if hc else "Set a health check path.", {"healthCheckPath": hc}))
    names = (cfg.get("linuxFxVersion") or cfg.get("windowsFxVersion") or "")
    out.append(_d("runtime", "Runtime stack", "Configuration", "Info", f"Runtime: {names or 'default'}.", None, {"fxVersion": names}))
    scale = 0
    if fn:
        sc = (p.get("functionAppConfig") or {}).get("scaleAndConcurrency") or {}
        scale = int(sc.get("maximumInstanceCount", 1)) if sc else 1
    if fn and scale == 0:
        out.append(_d("scale", "Scale capacity", "Availability", "Critical", "Scaled to zero capacity; no instance can run this app.", "Raise maximumInstanceCount.", {"maximumInstanceCount": scale}))
    if p.get("publicNetworkAccess") == "Disabled":
        out.append(_d("public-access", "Public network access", "Configuration", "Warning", "Public network access is disabled; requests must come via a private endpoint.", "Re-enable for public traffic.", {}))
    logs = (rec.get("_logs") or {})
    app_log = (((logs.get("applicationLogs") or {}).get("fileSystem") or {}).get("level") or "Off")
    out.append(_d("logging", "Application logging", "Observability", "Info" if app_log == "Off" else "Healthy", f"Application logging level: {app_log}.", "Turn on App Service logs to keep diagnostics." if app_log == "Off" else None, {"level": app_log}))
    return out

# ── Data, secrets, messaging and registry services ──────────────────────────────────
def _net(p, name="Network access"):
    """Shared network-exposure finding for the services that carry publicNetworkAccess / networkAcls."""
    pna = p.get("publicNetworkAccess", "Enabled")
    acl = p.get("networkAcls") or {}
    rules = len(acl.get("ipRules") or []) + len(acl.get("virtualNetworkRules") or [])
    open_ = pna == "Enabled" and (acl.get("defaultAction") or "Allow") == "Allow"
    return _d("network", name, "Security", "Warning" if open_ else "Healthy",
              "Reachable from every network." if open_ else f"Public access {pna}; default action {acl.get('defaultAction') or 'Deny'}; {rules} network rule(s).",
              "Restrict with firewall rules or a private endpoint." if open_ else None,
              {"publicNetworkAccess": pna, "defaultAction": acl.get("defaultAction"), "rules": rules})


def _sqlserver(state, rec):
    p = rec.get("properties") or {}
    out = []
    tls = p.get("minimalTlsVersion") or "None"
    out.append(_d("tls", "Minimum TLS version", "Security", "Healthy" if tls in ("1.2", "1.3") else "Warning",
                  f"Minimum TLS version is {tls}.", None if tls in ("1.2", "1.3") else "Raise minimalTlsVersion to 1.2.", {"minimalTlsVersion": tls}))
    fw = [c for c in _children(state, rec["id"], "firewallrules")]
    pna = p.get("publicNetworkAccess", "Enabled")
    wide = [c.get("name") for c in fw if ((c.get("properties") or {}).get("startIpAddress"), (c.get("properties") or {}).get("endIpAddress")) == ("0.0.0.0", "255.255.255.255")]
    out.append(_d("firewall", "Firewall rules", "Security", "Warning" if wide else ("Info" if pna == "Enabled" and not fw else "Healthy"),
                  (f"Rule(s) {', '.join(wide)} allow every IP address." if wide else
                   f"{len(fw)} firewall rule(s); public network access {pna}."),
                  "Narrow the rule to the client addresses that need access." if wide else None, {"rules": len(fw), "publicNetworkAccess": pna}))
    dbs = [c for c in _children(state, rec["id"], "databases") if (c.get("type") or "").lower().endswith("/servers/databases")]
    out.append(_d("databases", "Databases", "Availability", "Info" if dbs else "Warning",
                  f"{len(dbs)} user database(s)." if dbs else "The server hosts no database.", None if dbs else "Create a database.", {"databases": [d.get("name") for d in dbs]}))
    aud = next((c for c in _children(state, rec["id"], "auditingsettings")), None)
    on = ((aud or {}).get("properties") or {}).get("state") == "Enabled"
    out.append(_d("auditing", "Auditing", "Security", "Healthy" if on else "Info", "Server auditing is enabled." if on else "Server auditing is disabled.", None if on else "Enable auditing to keep an audit trail.", {"state": "Enabled" if on else "Disabled"}))
    return out


def _sqldb(state, rec):
    p = rec.get("properties") or {}
    out = []
    status = p.get("status") or "Online"
    out.append(_d("status", "Database status", "Availability", "Healthy" if status == "Online" else "Critical",
                  f"Database is {status}.", None if status == "Online" else "Resume or restore the database.", {"status": status}))
    tde = next((c for c in _children(state, rec["id"], "transparentdataencryption")), None)
    t = ((tde or {}).get("properties") or {}).get("state", "Enabled")
    out.append(_d("tde", "Transparent data encryption", "Security", "Healthy" if t == "Enabled" else "Warning",
                  f"Transparent data encryption is {t}.", None if t == "Enabled" else "Re-enable TDE.", {"state": t}))
    st = next((c for c in _children(state, rec["id"], "backupshorttermretentionpolicies")), None)
    days = ((st or {}).get("properties") or {}).get("retentionDays")
    out.append(_d("backup", "Point-in-time restore retention", "Reliability", "Healthy" if (days or 0) >= 7 else "Warning",
                  f"Short-term backup retention is {days} day(s)." if days is not None else "No short-term retention policy is recorded.",
                  None if (days or 0) >= 7 else "Raise short-term retention to at least 7 days.", {"retentionDays": days}))
    out.append(_d("redundancy", "Zone redundancy", "Reliability", "Healthy" if p.get("zoneRedundant") else "Info",
                  "Zone redundant." if p.get("zoneRedundant") else "Not zone redundant; a zone outage affects this database.", None if p.get("zoneRedundant") else "Enable zoneRedundant on a supported tier.", {"zoneRedundant": bool(p.get("zoneRedundant"))}))
    return out


def _cosmosacct(state, rec):
    p = rec.get("properties") or {}
    out = []
    locs = p.get("locations") or []
    out.append(_d("regions", "Regions", "Reliability", "Healthy" if len(locs) > 1 else "Info",
                  f"{len(locs)} region(s): {', '.join(l.get('locationName', '?') for l in locs)}.",
                  None if len(locs) > 1 else "Add a second region for regional failover.", {"regions": len(locs)}))
    af = bool(p.get("enableAutomaticFailover"))
    out.append(_d("failover", "Automatic failover", "Reliability", "Healthy" if af or len(locs) < 2 else "Warning",
                  "Automatic failover is on." if af else ("Single region: nothing to fail over to." if len(locs) < 2 else "Automatic failover is off; a regional outage needs a manual failover."),
                  None if af or len(locs) < 2 else "Enable enableAutomaticFailover.", {"enableAutomaticFailover": af}))
    cl = (p.get("consistencyPolicy") or {}).get("defaultConsistencyLevel") or "Session"
    out.append(_d("consistency", "Default consistency level", "Configuration", "Info", f"Default consistency level is {cl}.",
                  "Strong consistency is limited to single-write-region accounts." if cl == "Strong" and p.get("enableMultipleWriteLocations") else None, {"defaultConsistencyLevel": cl}))
    dla = bool(p.get("disableLocalAuth"))
    out.append(_d("auth", "Key authentication", "Security", "Healthy" if dla else "Info", "Account keys are disabled; only Entra ID works." if dla else "Account keys are enabled.", None if dla else "Prefer Entra ID and set disableLocalAuth.", {"disableLocalAuth": dla}))
    ip = p.get("ipRules") or []
    pna = p.get("publicNetworkAccess", "Enabled")
    open_ = pna == "Enabled" and not ip and not p.get("isVirtualNetworkFilterEnabled")
    out.append(_d("network", "Network access", "Security", "Warning" if open_ else "Healthy",
                  "Reachable from every network." if open_ else f"Public access {pna}; {len(ip)} IP rule(s).",
                  "Add IP or virtual-network rules, or use a private endpoint." if open_ else None, {"publicNetworkAccess": pna, "ipRules": len(ip)}))
    dbs = [c for c in _children(state, rec["id"], "sqldatabases")]
    out.append(_d("databases", "SQL databases", "Availability", "Info", f"{len(dbs)} SQL (NoSQL API) database(s)." if dbs else "No database in the account yet.", None, {"databases": len(dbs)}))
    return out


def _vault(state, rec):
    p = rec.get("properties") or {}
    out = []
    sd = p.get("enableSoftDelete", True)
    pp = bool(p.get("enablePurgeProtection"))
    out.append(_d("softdelete", "Soft delete", "Reliability", "Healthy" if sd else "Critical",
                  f"Soft delete is on; deleted objects are kept {p.get('softDeleteRetentionInDays', 90)} day(s)." if sd else "Soft delete is off; deleted keys and secrets are lost.", None if sd else "Soft delete cannot be disabled on a current vault; recreate it.", {"enableSoftDelete": sd}))
    out.append(_d("purgeprotection", "Purge protection", "Security", "Healthy" if pp else "Warning",
                  "Purge protection is on." if pp else "Purge protection is off; a soft-deleted vault or object can be purged before retention ends.", None if pp else "Enable purge protection (irreversible).", {"enablePurgeProtection": pp}))
    rbac = bool(p.get("enableRbacAuthorization"))
    n = len(p.get("accessPolicies") or [])
    out.append(_d("authz", "Permission model", "Security", "Healthy" if rbac else "Info",
                  "Azure RBAC governs data-plane access." if rbac else f"Vault access policies govern access ({n} policy entr{'y' if n == 1 else 'ies'}).", None if rbac else "Prefer Azure RBAC.", {"enableRbacAuthorization": rbac, "accessPolicies": n}))
    out.append(_net(p))
    return out


def _storageacct(state, rec):
    p = rec.get("properties") or {}
    out = []
    https = p.get("supportsHttpsTrafficOnly", True)
    out.append(_d("https", "Secure transfer", "Security", "Healthy" if https else "Critical", "Secure transfer (HTTPS only) is required." if https else "Plain HTTP is accepted.", None if https else "Enable supportsHttpsTrafficOnly.", {"supportsHttpsTrafficOnly": https}))
    tls = p.get("minimumTlsVersion") or "TLS1_0"
    out.append(_d("tls", "Minimum TLS version", "Security", "Healthy" if tls in ("TLS1_2", "TLS1_3") else "Warning", f"Minimum TLS version is {tls}.", None if tls in ("TLS1_2", "TLS1_3") else "Raise minimumTlsVersion to TLS1_2.", {"minimumTlsVersion": tls}))
    pub = p.get("allowBlobPublicAccess")
    out.append(_d("blobpublic", "Anonymous blob access", "Security", "Warning" if pub else "Healthy", "Containers may be made publicly readable." if pub else "Anonymous access to blobs is disallowed.", "Set allowBlobPublicAccess to false." if pub else None, {"allowBlobPublicAccess": bool(pub)}))
    sk = p.get("allowSharedKeyAccess", True)
    out.append(_d("sharedkey", "Shared key authorization", "Security", "Info" if sk else "Healthy", "Account keys and SAS can authorize requests." if sk else "Only Entra ID authorizes requests.", None if not sk else "Prefer Entra ID and disable shared-key access.", {"allowSharedKeyAccess": sk}))
    out.append(_net(p))
    return out


def _sbnamespace(state, rec):
    p = rec.get("properties") or {}
    sku = (rec.get("sku") or {}).get("name") or "Standard"
    out = []
    tls = p.get("minimumTlsVersion") or "1.0"
    out.append(_d("tls", "Minimum TLS version", "Security", "Healthy" if tls in ("1.2", "1.3") else "Warning", f"Minimum TLS version is {tls}.", None if tls in ("1.2", "1.3") else "Raise minimumTlsVersion to 1.2.", {"minimumTlsVersion": tls}))
    dla = bool(p.get("disableLocalAuth"))
    out.append(_d("auth", "SAS authentication", "Security", "Healthy" if dla else "Info", "SAS keys are disabled; only Entra ID works." if dla else "Shared access signature authentication is enabled.", None if dla else "Prefer Entra ID and set disableLocalAuth.", {"disableLocalAuth": dla}))
    out.append(_d("sku", "Pricing tier", "Capacity", "Info" if sku == "Premium" else "Warning" if sku == "Basic" else "Info",
                  f"{sku} tier." + (" Topics and subscriptions are unavailable on Basic." if sku == "Basic" else ""), "Move to Standard or Premium for topics." if sku == "Basic" else None, {"sku": sku}))
    qs = _children(state, rec["id"], "queues")
    ts = _children(state, rec["id"], "topics")
    out.append(_d("entities", "Messaging entities", "Availability", "Info" if (qs or ts) else "Warning", f"{len(qs)} queue(s), {len(ts)} topic(s)." if (qs or ts) else "The namespace has no queue or topic.", None if (qs or ts) else "Create a queue or topic.", {"queues": len(qs), "topics": len(ts)}))
    out.append(_d("redundancy", "Zone redundancy", "Reliability", "Healthy" if p.get("zoneRedundant") else "Info", "Zone redundant." if p.get("zoneRedundant") else "Not zone redundant.", None, {"zoneRedundant": bool(p.get("zoneRedundant"))}))
    return out


def _registry(state, rec):
    p = rec.get("properties") or {}
    out = []
    adm = bool(p.get("adminUserEnabled"))
    out.append(_d("admin", "Admin user", "Security", "Warning" if adm else "Healthy", "The shared admin account is enabled." if adm else "The admin account is disabled.", "Disable the admin user and use Entra ID or repository tokens." if adm else None, {"adminUserEnabled": adm}))
    out.append(_d("network", "Network access", "Security", "Warning" if p.get("publicNetworkAccess", "Enabled") == "Enabled" and not (p.get("networkRuleSet") or {}).get("ipRules") else "Healthy",
                  f"Public network access {p.get('publicNetworkAccess', 'Enabled')}.", "Restrict with IP rules or a private endpoint.", {"publicNetworkAccess": p.get("publicNetworkAccess", "Enabled")}))
    out.append(_d("anonpull", "Anonymous pull", "Security", "Warning" if p.get("anonymousPullEnabled") else "Healthy", "Anyone can pull images." if p.get("anonymousPullEnabled") else "Anonymous pull is disabled.", None, {"anonymousPullEnabled": bool(p.get("anonymousPullEnabled"))}))
    return out


def _workspace(state, rec):
    p = rec.get("properties") or {}
    out = []
    ret = p.get("retentionInDays", 30)
    out.append(_d("retention", "Data retention", "Configuration", "Info", f"Retention is {ret} day(s).", None, {"retentionInDays": ret}))
    quota = (p.get("workspaceCapping") or {}).get("dailyQuotaGb", -1)
    out.append(_d("quota", "Daily cap", "Capacity", "Info" if quota in (-1, None) else "Healthy", "No daily ingestion cap: a noisy source can run up cost." if quota in (-1, None) else f"Daily cap is {quota} GB.", "Set a daily cap." if quota in (-1, None) else None, {"dailyQuotaGb": quota}))
    out.append(_d("access", "Public network access", "Security", "Info", f"Ingestion: {p.get('publicNetworkAccessForIngestion', 'Enabled')}; query: {p.get('publicNetworkAccessForQuery', 'Enabled')}.", None, {}))
    return out


def _vm(state, rec):
    p = rec.get("properties") or {}
    out = []
    nics = (p.get("networkProfile") or {}).get("networkInterfaces") or []
    out.append(_d("nic", "Network interfaces", "Availability", "Healthy" if nics else "Warning", f"{len(nics)} network interface(s) attached." if nics else "No network interface is attached: the VM is unreachable.", None if nics else "Attach a NIC.", {"nics": len(nics)}))
    lin = (p.get("osProfile") or {}).get("linuxConfiguration") or {}
    pw = lin and not lin.get("disablePasswordAuthentication")
    out.append(_d("sshpassword", "Password authentication", "Security", "Warning" if pw else "Healthy", "Password sign-in is allowed over SSH." if pw else "SSH keys only." if lin else "Windows or unspecified OS profile.", "Disable password authentication and use SSH keys." if pw else None, {}))
    bd = ((p.get("diagnosticsProfile") or {}).get("bootDiagnostics") or {}).get("enabled")
    out.append(_d("bootdiag", "Boot diagnostics", "Observability", "Healthy" if bd else "Info", "Boot diagnostics are on." if bd else "Boot diagnostics are off: serial console output is not captured.", None if bd else "Enable boot diagnostics.", {"enabled": bool(bd)}))
    return out


def _dnszone(state, rec):
    rs = _children(state, rec["id"])
    n = sum(1 for r in rs if (r.get("type") or "").lower().find("/dnszones/") >= 0)
    return [_d("recordsets", "Record sets", "Availability", "Info" if n else "Warning", f"{n} record set(s)." if n else "The zone has no record set.", None if n else "Add records.", {"recordSets": n})]


KINDS = {
    "microsoft.containerservice/managedclusters": _aks,
    "microsoft.apimanagement/service": _apim,
    "microsoft.appconfiguration/configurationstores": _appconfig,
    "microsoft.cognitiveservices/accounts": _cogs,
    "microsoft.web/sites": _site,
    "microsoft.sql/servers": _sqlserver,
    "microsoft.sql/servers/databases": _sqldb,
    "microsoft.documentdb/databaseaccounts": _cosmosacct,
    "microsoft.keyvault/vaults": _vault,
    "microsoft.storage/storageaccounts": _storageacct,
    "microsoft.servicebus/namespaces": _sbnamespace,
    "microsoft.containerregistry/registries": _registry,
    "microsoft.operationalinsights/workspaces": _workspace,
    "microsoft.compute/virtualmachines": _vm,
    "microsoft.network/dnszones": _dnszone,
}


def _finish(rec, dets):
    dets = sorted(dets, key=lambda d: ORDER[d["status"]])
    worst = dets[0]["status"] if dets else "Healthy"
    counts = {s: sum(1 for d in dets if d["status"] == s) for s in ORDER}
    return {"resourceId": rec["id"], "resourceType": rec.get("type"), "overall": worst if worst != "Info" else "Healthy",
            "counts": counts, "generatedAt": _now(), "detectors": dets}


def diagnose(state, rid):
    rec = state.get(rid.lower())
    if rec is None:
        return {"status": 404, "body": {"error": {"code": "ResourceNotFound", "message": f"Resource '{rid}' not found."}}}
    typ = (rec.get("type") or rec.get("_type") or "").lower()
    fn = KINDS.get(typ)
    dets = _generic(state, rec) + (fn(state, rec) if fn else [])
    return {"status": 200, "body": _finish(rec, dets)}


def handle(state, method, rid, rest):
    if method != "GET":
        return {"status": 405, "body": {"error": {"code": "MethodNotAllowed", "message": "Diagnostics are read-only."}}}
    r = diagnose(state, rid)
    if r["status"] != 200 or not rest:
        return r
    d = next((x for x in r["body"]["detectors"] if x["id"].lower() == rest[0].lower()), None)
    if d is None:
        return {"status": 404, "body": {"error": {"code": "DetectorNotFound", "message": f"Detector '{rest[0]}' was not found."}}}
    return {"status": 200, "body": d}
