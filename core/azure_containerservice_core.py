"""Azure Kubernetes Service core (``Microsoft.ContainerService``) — substrate-independent.

Speaks the ARM control-plane REST API of the ``containerservice`` resource provider
(azure-rest-api-specs ``specification/containerservice/resource-manager``, api-version 2024-09-01), so the
native ``azure-mgmt-containerservice`` / ``armcontainerservice`` /
``com.azure.resourcemanager.containerservice`` SDKs and ``az aks`` / ``az rest`` work unchanged.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME file runs offline and
in Nano. It does not own a store: it mutates the ARM resource map the dispatchers already keep
(``{lower-cased resource id: record}``), which is space-scoped and persisted by the existing seams.
Agent pools, maintenance configurations and trusted-access role bindings live INSIDE their parent cluster
(underscore keys, never serialised to clients), so the cost model counts one resource per cluster.

Resource types
    Microsoft.ContainerService/managedClusters   (+ agentPools, maintenanceConfigurations, trustedAccessRoleBindings,
        listClusterAdminCredential / listClusterUserCredential / listClusterMonitoringUserCredential,
        upgradeProfiles/default, accessProfiles/{role}/listCredential, stop, start, abortLatestOperation,
        rotateClusterCertificates, rotateServiceAccountSigningKeys, reimage, resolvePrivateLinkServiceId,
        privateEndpointConnections, privateLinkResources, commandResults)
    Microsoft.ContainerService/snapshots         (node-pool snapshots)
    Subscription / location scope: managedClusters, snapshots, locations/{loc}/{kubernetesVersions, osOptions,
        orchestrators}
Errors use the ARM shape ``{"error":{"code","message"}}``.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; the caller adds the
Azure-AsyncOperation headers when ``lro`` is true.  The service is control-plane only: the cluster has no
running Kubernetes API server (the Max-tier k3s backend is not started yet); kubeconfigs returned by the
credential actions point at the cluster FQDN and say so.
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.ContainerService"
API_VERSION = "2024-09-01"
DEFAULT_LOCATION = "eastus"

# supported Kubernetes versions, newest first: (version, is_default, is_preview)
K8S_VERSIONS = [("1.31.1", False, False), ("1.30.5", True, False), ("1.29.9", False, False), ("1.28.14", False, False)]
DEFAULT_K8S = "1.30.5"
VM_SIZES = {"Standard_B2s": (2, 4), "Standard_B2ms": (2, 8), "Standard_D2s_v3": (2, 8), "Standard_D4s_v3": (4, 16),
            "Standard_D2s_v5": (2, 8), "Standard_D4s_v5": (4, 16), "Standard_DS2_v2": (2, 7), "Standard_E4s_v3": (4, 32),
            "Standard_F4s_v2": (4, 8)}
DEFAULT_VM_SIZE = "Standard_DS2_v2"
TIERS = ("Free", "Standard", "Premium")
POWER_STATES = ("Running", "Stopped")
NETWORK_PLUGINS = ("azure", "kubenet", "none")
OS_TYPES = ("Linux", "Windows")
AGENT_MODES = ("System", "User")
TRUSTED_ROLES = [{"sourceResourceType": "Microsoft.MachineLearningServices/workspaces", "name": "backup-operator",
                  "rules": [{"verbs": ["get", "list"], "apiGroups": [""], "resources": ["namespaces"]}]}]
ACCESS_ROLES = ("clusterAdmin", "clusterUser")


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _to_bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")


def _to_int(v, default=None):
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _sysdata():
    return {"createdBy": "cloudlearn@vyomi.local", "createdByType": "User", "createdAt": _now(),
            "lastModifiedBy": "cloudlearn@vyomi.local", "lastModifiedByType": "User", "lastModifiedAt": _now()}


def _etag():
    return '"' + uuid.uuid4().hex + '"'


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _major_minor(v):
    p = str(v).split(".")
    return ".".join(p[:2])


def _resolve_version(v):
    """'1.30' → the newest patch; '1.30.5' → itself if supported."""
    if not v:
        return DEFAULT_K8S
    for ver, _, _ in K8S_VERSIONS:
        if v == ver:
            return ver
    for ver, _, _ in K8S_VERSIONS:
        if _major_minor(ver) == v:
            return ver
    raise _E(400, "K8sVersionNotSupported",
             f"Version {v} is not supported in this region. Please use `az aks get-versions` command to get the "
             f"supported version list in this region. For example, available versions: "
             f"{', '.join(x[0] for x in K8S_VERSIONS)}.")


# ── name validation ──────────────────────────────────────────────────────────
def _cluster_name_problem(name):
    if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9_-]{0,61}[A-Za-z0-9])?", name or ""):
        return ("InvalidParameter", f"The resource name '{name}' is invalid. It must be 1-63 characters of letters, "
                                    "digits, underscores and hyphens, and must start and end with a letter or digit.")
    return None


def _pool_name_problem(name, windows):
    mx = 6 if windows else 12
    if not re.fullmatch(r"[a-z][a-z0-9]*", name or "") or len(name) > mx:
        return ("InvalidParameter", f"Agent pool name '{name}' is invalid. It must be 1-{mx} lowercase alphanumeric "
                                    "characters and start with a lowercase letter.")
    return None


# ── managed clusters ─────────────────────────────────────────────────────────
def _clusters(state, sub=None):
    t = f"{NAMESPACE}/managedClusters".lower()
    return [r for r in state.values() if str(r.get("_type", "")).lower() == t and (sub is None or r.get("_sub") == sub)]


def _dns_prefix(name, sub):
    base = re.sub(r"[^A-Za-z0-9-]", "-", name).strip("-") or "aks"
    return f"{base}-dns"[:54]


def _fqdn(prefix, loc):
    return f"{prefix}-{hashlib.sha256((prefix + loc).encode()).hexdigest()[:8]}.hcp.{loc}.azmk8s.io"


def _node_rg(rg, name, loc):
    return f"MC_{rg}_{name}_{loc}"[:80]


def _new_pool(cluster_id, name, spec, version, mode_default="User", first=False):
    spec = spec or {}
    os_type = spec.get("osType") or "Linux"
    if os_type not in OS_TYPES:
        raise _E(400, "InvalidParameter", f"osType '{os_type}' is not supported. Valid values: {', '.join(OS_TYPES)}.")
    prob = _pool_name_problem(name, os_type == "Windows")
    if prob:
        raise _E(400, prob[0], prob[1])
    vm = spec.get("vmSize") or DEFAULT_VM_SIZE
    if vm not in VM_SIZES:
        raise _E(400, "InvalidParameter", f"The VM size '{vm}' is not allowed in this region. "
                                           f"Allowed sizes: {', '.join(sorted(VM_SIZES))}.")
    mode = spec.get("mode") or ("System" if first else mode_default)
    if mode not in AGENT_MODES:
        raise _E(400, "InvalidParameter", f"mode '{mode}' is invalid. Valid values: System, User.")
    count = _to_int(spec.get("count"), 3 if first else 1)
    autoscale = _to_bool(spec.get("enableAutoScaling", False))
    mn, mx = _to_int(spec.get("minCount")), _to_int(spec.get("maxCount"))
    if autoscale:
        if mn is None or mx is None:
            raise _E(400, "InvalidParameter", "minCount and maxCount are required when enableAutoScaling is true.")
        if mn > mx:
            raise _E(400, "InvalidParameter", "minCount must not be greater than maxCount.")
        if count < mn or count > mx:
            count = max(mn, min(mx, count))
    if count is None or count < 0 or count > 1000:
        raise _E(400, "InvalidParameter", "count must be between 0 and 1000.")
    if mode == "System" and count < 1 and not autoscale:
        raise _E(400, "InvalidParameter", "System node pools must have a count of at least 1.")
    ptype = spec.get("type") or "VirtualMachineScaleSets"
    if ptype not in ("VirtualMachineScaleSets", "AvailabilitySet", "VirtualMachines"):
        raise _E(400, "InvalidParameter", f"type '{ptype}' is invalid.")
    ver = _resolve_version(spec.get("orchestratorVersion") or version)
    props = {
        "count": count, "vmSize": vm, "osDiskSizeGB": _to_int(spec.get("osDiskSizeGB"), 128),
        "osDiskType": spec.get("osDiskType") or "Managed", "kubeletDiskType": "OS", "maxPods": _to_int(spec.get("maxPods"), 110),
        "type": ptype, "maxCount": mx, "minCount": mn, "enableAutoScaling": autoscale, "scaleDownMode": spec.get("scaleDownMode") or "Delete",
        "provisioningState": "Succeeded", "powerState": {"code": "Running"},
        "orchestratorVersion": ver, "currentOrchestratorVersion": ver, "nodeImageVersion": "AKSUbuntu-2204gen2containerd-202410.09.0",
        "mode": mode, "osType": os_type, "osSKU": spec.get("osSKU") or ("Windows2022" if os_type == "Windows" else "Ubuntu"),
        "enableFIPS": _to_bool(spec.get("enableFIPS", False)), "enableNodePublicIP": _to_bool(spec.get("enableNodePublicIP", False)),
        "enableEncryptionAtHost": _to_bool(spec.get("enableEncryptionAtHost", False)),
        "nodeLabels": spec.get("nodeLabels") or {}, "nodeTaints": spec.get("nodeTaints") or [],
        "tags": spec.get("tags") or {}, "scaleSetPriority": spec.get("scaleSetPriority") or "Regular",
        "upgradeSettings": spec.get("upgradeSettings") or {"maxSurge": "10%"},
        "availabilityZones": spec.get("availabilityZones") or [],
    }
    if spec.get("vnetSubnetID"):
        props["vnetSubnetID"] = spec["vnetSubnetID"]
    props = {k: v for k, v in props.items() if v is not None}      # the real API omits unset fields
    return {"id": f"{cluster_id}/agentPools/{name}", "name": name, "type": f"{NAMESPACE}/managedClusters/agentPools",
            "properties": props}


def _pool_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _new_cluster(rid, name, sub, rg, payload):
    prob = _cluster_name_problem(name)
    if prob:
        raise _E(400, prob[0], prob[1])
    loc = payload.get("location")
    if not loc:
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    pay = payload.get("properties") or {}
    ver = _resolve_version(pay.get("kubernetesVersion"))
    sku = payload.get("sku") or {}
    sku_name = sku.get("name") or "Base"
    if sku_name not in ("Base", "Automatic"):
        raise _E(400, "InvalidParameter", f"sku.name '{sku_name}' is invalid. Valid values: Base, Automatic.")
    tier = sku.get("tier") or "Free"
    if tier not in TIERS:
        raise _E(400, "InvalidParameter", f"sku.tier '{tier}' is invalid. Valid values: {', '.join(TIERS)}.")
    prefix = pay.get("dnsPrefix") or ""
    fqdn_sub = pay.get("fqdnSubdomain") or ""
    if not prefix and not fqdn_sub:
        raise _E(400, "InvalidParameter", "dnsPrefix or fqdnSubdomain is required.")
    if prefix and not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,52}[A-Za-z0-9])?", prefix):
        raise _E(400, "InvalidParameter", f"The dnsPrefix '{prefix}' is invalid. It must be 1-54 characters of letters, digits "
                                           "and hyphens, starting and ending with a letter or digit.")
    pools_in = pay.get("agentPoolProfiles")
    if not pools_in:
        raise _E(400, "InvalidParameter", "At least one agent pool profile is required (agentPoolProfiles).")
    pools = {}
    for i, spec in enumerate(pools_in):
        pname = (spec or {}).get("name")
        if not pname:
            raise _E(400, "InvalidParameter", "Agent pool profile 'name' is required.")
        if pname in pools:
            raise _E(400, "InvalidParameter", f"Duplicate agent pool name '{pname}'.")
        pools[pname] = _new_pool(rid, pname, spec, ver, first=(i == 0))
    if not any(p["properties"]["mode"] == "System" for p in pools.values()):
        raise _E(400, "InvalidParameter", "At least one agent pool with mode System is required.")
    net_in = pay.get("networkProfile") or {}
    plugin = net_in.get("networkPlugin") or "kubenet"
    if plugin not in NETWORK_PLUGINS:
        raise _E(400, "InvalidParameter", f"networkPlugin '{plugin}' is invalid. Valid values: {', '.join(NETWORK_PLUGINS)}.")
    net = {"networkPlugin": plugin, "loadBalancerSku": (net_in.get("loadBalancerSku") or "standard").lower(),
           "outboundType": net_in.get("outboundType") or "loadBalancer",
           "serviceCidr": net_in.get("serviceCidr") or "10.0.0.0/16", "dnsServiceIP": net_in.get("dnsServiceIP") or "10.0.0.10",
           "serviceCidrs": [net_in.get("serviceCidr") or "10.0.0.0/16"], "ipFamilies": ["IPv4"]}
    if plugin == "kubenet":
        net["podCidr"] = net_in.get("podCidr") or "10.244.0.0/16"
        net["podCidrs"] = [net["podCidr"]]
    for opt in ("networkPluginMode", "networkPolicy", "networkDataplane"):
        if net_in.get(opt):
            net[opt] = net_in[opt]
    fq = _fqdn(prefix or fqdn_sub, loc)
    props = {
        "provisioningState": "Succeeded", "powerState": {"code": "Running"}, "kubernetesVersion": ver,
        "currentKubernetesVersion": ver, "dnsPrefix": prefix, "fqdn": fq, "azurePortalFQDN": fq.replace(".hcp.", ".portal.hcp."),
        "agentPoolProfiles": [], "nodeResourceGroup": pay.get("nodeResourceGroup") or _node_rg(rg, name, loc),
        "enableRBAC": _to_bool(pay.get("enableRBAC", True)), "supportPlan": pay.get("supportPlan") or "KubernetesOfficial",
        "networkProfile": net, "maxAgentPools": 100,
        "disableLocalAccounts": _to_bool(pay.get("disableLocalAccounts", False)),
        "autoUpgradeProfile": pay.get("autoUpgradeProfile") or {"upgradeChannel": "none", "nodeOSUpgradeChannel": "NodeImage"},
        "securityProfile": pay.get("securityProfile") or {}, "storageProfile": pay.get("storageProfile") or {
            "diskCSIDriver": {"enabled": True, "version": "v1"}, "fileCSIDriver": {"enabled": True},
            "snapshotController": {"enabled": True}},
        "oidcIssuerProfile": {"enabled": _to_bool((pay.get("oidcIssuerProfile") or {}).get("enabled", False))},
    }
    if fqdn_sub:
        props["fqdnSubdomain"] = fqdn_sub
    if props["oidcIssuerProfile"]["enabled"]:
        props["oidcIssuerProfile"]["issuerURL"] = f"https://{loc}.oic.prod-aks.azure.com/00000000-0000-0000-0000-000000000000/{uuid.uuid5(uuid.NAMESPACE_URL, rid).hex}/"
    apiac = pay.get("apiServerAccessProfile")
    if apiac:
        props["apiServerAccessProfile"] = apiac
        if _to_bool(apiac.get("enablePrivateCluster", False)):
            pf = f"{prefix or fqdn_sub}-{uuid.uuid5(uuid.NAMESPACE_URL, rid).hex[:8]}.privatelink.{loc}.azmk8s.io"
            props["privateFQDN"] = pf
    for opt in ("addonProfiles", "aadProfile", "servicePrincipalProfile", "identityProfile", "autoScalerProfile",
                "windowsProfile", "linuxProfile", "workloadAutoScalerProfile", "ingressProfile", "metricsProfile"):
        if opt in pay:
            props[opt] = pay[opt]
    if "servicePrincipalProfile" not in props and not payload.get("identity"):
        props["servicePrincipalProfile"] = {"clientId": "msi"}
    rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/managedClusters", "location": loc, "etag": _etag(),
           "sku": {"name": sku_name, "tier": tier}, "tags": payload.get("tags") or {}, "properties": props,
           "systemData": _sysdata(), "_type": f"{NAMESPACE}/managedClusters", "_sub": sub, "_rg": rg, "_created": _now(),
           "_pools": pools, "_maint": {}, "_tabs": {}, "_pec": {}, "_ca": _ca_pem(rid), "_cmd": {}}
    if payload.get("kind"):
        rec["kind"] = payload["kind"]
    _apply_identity(rec, payload)
    _sync_pools(rec)
    return rec


def _ca_pem(rid):
    body = base64.b64encode(hashlib.sha256(rid.encode()).digest() * 8).decode()
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n-----END CERTIFICATE-----\n"


def _apply_identity(rec, payload):
    ident = payload.get("identity")
    if not ident:
        return
    t = ident.get("type") or "None"
    out = {"type": t}
    if "SystemAssigned" in t:
        out["principalId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, rec["id"] + "#p"))
        out["tenantId"] = "00000000-0000-0000-0000-000000000000"
    if "UserAssigned" in t:
        out["userAssignedIdentities"] = {k: {"principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#p")),
                                              "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#c"))}
                                          for k in (ident.get("userAssignedIdentities") or {})}
    if t == "None":
        rec.pop("identity", None)
    else:
        rec["identity"] = out


def _sync_pools(rec):
    """Mirror the live agent pools into ``properties.agentPoolProfiles`` (what the real GET returns)."""
    profs = []
    for p in rec["_pools"].values():
        d = dict(p["properties"])
        d["name"] = p["name"]
        d["powerState"] = {"code": rec["properties"]["powerState"]["code"]}
        profs.append(d)
    rec["properties"]["agentPoolProfiles"] = profs


def _cluster_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    out["properties"]["privateEndpointConnections"] = [dict(v) for v in rec["_pec"].values()] if rec["_pec"] else None
    if out["properties"]["privateEndpointConnections"] is None:
        out["properties"].pop("privateEndpointConnections")
    return out


def _put_cluster(state, sub, rg, rid, name, payload, method):
    rec = state.get(rid.lower())
    if method == "PATCH":                       # tags / identity only (TagsObject)
        if rec is None:
            raise _not_found("managedClusters", name, rg)
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = payload["tags"]
        _apply_identity(rec, payload)
        _touch(rec)
        return rec, False
    if rec is not None:
        _update_cluster(rec, payload)
        return rec, False
    rec = _new_cluster(rid, name, sub, rg, payload)
    state[rid.lower()] = rec
    return rec, True


def _touch(rec):
    rec["etag"] = _etag()
    rec["systemData"]["lastModifiedAt"] = _now()


def _update_cluster(rec, payload):
    pay = payload.get("properties") or {}
    p = rec["properties"]
    if payload.get("location") and payload["location"].lower() != rec["location"].lower():
        raise _E(400, "PropertyChangeNotAllowed", "Changing property 'location' is not allowed.")
    if pay.get("dnsPrefix") and pay["dnsPrefix"] != p.get("dnsPrefix"):
        raise _E(400, "PropertyChangeNotAllowed", "Changing property 'dnsPrefix' is not allowed.")
    if pay.get("kubernetesVersion"):
        new = _resolve_version(pay["kubernetesVersion"])
        cur = p["kubernetesVersion"]
        if new != cur:
            cm, nm = [int(x) for x in _major_minor(cur).split(".")], [int(x) for x in _major_minor(new).split(".")]
            if nm[1] < cm[1]:
                raise _E(400, "DowngradeNotAllowed", f"Cannot downgrade from {cur} to {new}.")
            if nm[1] - cm[1] > 1:
                raise _E(400, "UpgradeNotAllowed", f"Upgrading from {cur} to {new} would skip a minor version. "
                                                    "Upgrade one minor version at a time.")
            p["kubernetesVersion"] = p["currentKubernetesVersion"] = new
            for pl in rec["_pools"].values():
                pl["properties"]["orchestratorVersion"] = pl["properties"]["currentOrchestratorVersion"] = new
    if payload.get("sku"):
        s = payload["sku"]
        if s.get("tier"):
            if s["tier"] not in TIERS:
                raise _E(400, "InvalidParameter", f"sku.tier '{s['tier']}' is invalid.")
            rec["sku"]["tier"] = s["tier"]
        if s.get("name"):
            rec["sku"]["name"] = s["name"]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    for opt in ("enableRBAC", "disableLocalAccounts"):
        if opt in pay:
            p[opt] = _to_bool(pay[opt])
    for opt in ("autoUpgradeProfile", "securityProfile", "storageProfile", "addonProfiles", "aadProfile", "autoScalerProfile",
                "windowsProfile", "linuxProfile", "workloadAutoScalerProfile", "ingressProfile", "metricsProfile",
                "supportPlan", "apiServerAccessProfile"):
        if opt in pay:
            p[opt] = pay[opt]
    if "oidcIssuerProfile" in pay:
        en = _to_bool((pay["oidcIssuerProfile"] or {}).get("enabled", False))
        p["oidcIssuerProfile"] = {"enabled": en}
        if en:
            p["oidcIssuerProfile"]["issuerURL"] = f"https://{rec['location']}.oic.prod-aks.azure.com/00000000-0000-0000-0000-000000000000/{uuid.uuid5(uuid.NAMESPACE_URL, rec['id']).hex}/"
    if pay.get("networkProfile"):
        n = pay["networkProfile"]
        if n.get("networkPlugin") and n["networkPlugin"] != p["networkProfile"]["networkPlugin"]:
            raise _E(400, "PropertyChangeNotAllowed", "Changing property 'networkProfile.networkPlugin' is not allowed.")
        for k in ("loadBalancerSku", "outboundType", "networkPolicy"):
            if n.get(k):
                p["networkProfile"][k] = n[k].lower() if k == "loadBalancerSku" else n[k]
    if pay.get("agentPoolProfiles") is not None:
        incoming = {s.get("name"): s for s in pay["agentPoolProfiles"]}
        if None in incoming:
            raise _E(400, "InvalidParameter", "Agent pool profile 'name' is required.")
        for nm in list(rec["_pools"]):
            if nm not in incoming:
                del rec["_pools"][nm]
        for nm, spec in incoming.items():
            if nm in rec["_pools"]:
                _update_pool(rec, rec["_pools"][nm], spec)
            else:
                rec["_pools"][nm] = _new_pool(rec["id"], nm, spec, p["kubernetesVersion"])
        if not any(x["properties"]["mode"] == "System" for x in rec["_pools"].values()):
            raise _E(400, "InvalidParameter", "At least one agent pool with mode System is required.")
    _apply_identity(rec, payload)
    _sync_pools(rec)
    _touch(rec)


def _update_pool(rec, pool, spec):
    pr = pool["properties"]
    for immut in ("vmSize", "osType", "osDiskSizeGB", "osDiskType", "maxPods"):
        if spec.get(immut) is not None and spec[immut] != pr.get(immut):
            raise _E(400, "PropertyChangeNotAllowed", f"Changing property 'agentPoolProfile.{immut}' is not allowed.")
    if spec.get("mode"):
        if spec["mode"] not in AGENT_MODES:
            raise _E(400, "InvalidParameter", f"mode '{spec['mode']}' is invalid. Valid values: System, User.")
        pr["mode"] = spec["mode"]
    if "enableAutoScaling" in spec:
        pr["enableAutoScaling"] = _to_bool(spec["enableAutoScaling"])
    for k in ("minCount", "maxCount"):
        if k in spec:
            pr[k] = _to_int(spec[k])
    if pr["enableAutoScaling"] and (pr.get("minCount") is None or pr.get("maxCount") is None or pr["minCount"] > pr["maxCount"]):
        raise _E(400, "InvalidParameter", "minCount/maxCount are required and minCount must not exceed maxCount when "
                                          "enableAutoScaling is true.")
    if spec.get("count") is not None:
        c = _to_int(spec["count"])
        if c is None or c < 0 or c > 1000:
            raise _E(400, "InvalidParameter", "count must be between 0 and 1000.")
        if pr["enableAutoScaling"] and not (pr["minCount"] <= c <= pr["maxCount"]):
            raise _E(400, "InvalidParameter", "count must be within [minCount, maxCount] when autoscaling is enabled.")
        pr["count"] = c
    if spec.get("orchestratorVersion"):
        pr["orchestratorVersion"] = pr["currentOrchestratorVersion"] = _resolve_version(spec["orchestratorVersion"])
    for k in ("nodeLabels", "nodeTaints", "tags", "upgradeSettings", "scaleDownMode"):
        if k in spec:
            pr[k] = spec[k]


# ── agent pools ──────────────────────────────────────────────────────────────
def _pool_ops(rec, rest, method, payload, query):
    pools = rec["_pools"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_pool_view(p) for p in pools.values()]})
    name = rest[0]
    pool = pools.get(name)
    sub = rest[1:]
    if sub:
        s0 = sub[0].lower()
        if pool is None:
            raise _not_found("managedClusters/agentPools", name, rec["_rg"])
        if s0 == "upgradeprofiles" and method == "GET":
            return _ok(_pool_upgrade_profile(rec, pool))
        if s0 == "upgradenodeimageversion" and method == "POST":
            pool["properties"]["nodeImageVersion"] = "AKSUbuntu-2204gen2containerd-202411.04.0"
            return _ok(_pool_view(pool), 202, lro=True, rid=pool["id"], verb="post")
        if s0 == "abortlatestoperation" and method == "POST":
            return _ok(None, 204)
        raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/managedClusters/agentPools/{sub[0]}' is not supported.")
    if method == "GET":
        if pool is None:
            raise _not_found("managedClusters/agentPools", name, rec["_rg"])
        return _ok(_pool_view(pool))
    if method in ("PUT", "PATCH"):
        if method == "PATCH":
            raise _E(405, "MethodNotAllowed", "PATCH is not supported on agent pools; use PUT.")
        spec = payload.get("properties") or payload
        created = pool is None
        if created:
            if len(pools) >= rec["properties"]["maxAgentPools"]:
                raise _E(400, "InvalidParameter", "The maximum number of agent pools has been reached.")
            pools[name] = _new_pool(rec["id"], name, spec, rec["properties"]["kubernetesVersion"])
            pool = pools[name]
        else:
            _update_pool(rec, pool, spec)
        _sync_pools(rec)
        _touch(rec)
        return _ok(_pool_view(pool), 201 if created else 200, lro=True, rid=pool["id"], verb="put")
    if method == "DELETE":
        if pool is None:
            return _ok(None, 204)
        if pool["properties"]["mode"] == "System" and sum(1 for p in pools.values() if p["properties"]["mode"] == "System") == 1:
            raise _E(400, "OperationNotAllowed", "There has to be at least one system agent pool.")
        del pools[name]
        _sync_pools(rec)
        _touch(rec)
        return _ok(None, 202, lro=True, rid=pool["id"], verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _upgrades_from(cur):
    cm = int(_major_minor(cur).split(".")[1])
    out = []
    for ver, default, preview in K8S_VERSIONS:
        m = int(_major_minor(ver).split(".")[1])
        if m == cm and ver != cur and ver > cur:
            out.append((ver, default, preview))
        elif m == cm + 1:
            out.append((ver, default, preview))
    return out


def _pool_upgrade_profile(rec, pool):
    cur = pool["properties"]["orchestratorVersion"]
    return {"id": f"{pool['id']}/upgradeProfiles/default", "name": "default",
            "type": f"{NAMESPACE}/managedClusters/agentPools/upgradeProfiles",
            "properties": {"kubernetesVersion": cur, "osType": pool["properties"]["osType"],
                           "latestNodeImageVersion": "AKSUbuntu-2204gen2containerd-202411.04.0",
                           "upgrades": [{"kubernetesVersion": v, "isPreview": pv, "isOutOfSupport": False} for v, _, pv in _upgrades_from(cur)]}}


def _cluster_upgrade_profile(rec):
    cur = rec["properties"]["kubernetesVersion"]
    ups = [{"kubernetesVersion": v, "isPreview": pv, **({"isDefault": True} if d else {})} for v, d, pv in _upgrades_from(cur)]
    return {"id": f"{rec['id']}/upgradeProfiles/default", "name": "default", "type": f"{NAMESPACE}/managedClusters/upgradeprofiles",
            "properties": {"controlPlaneProfile": {"kubernetesVersion": cur, "osType": "Linux", "upgrades": ups},
                           "agentPoolProfiles": [{"kubernetesVersion": p["properties"]["orchestratorVersion"], "name": p["name"],
                                                  "osType": p["properties"]["osType"],
                                                  "upgrades": [{"kubernetesVersion": v, "isPreview": pv} for v, _, pv in _upgrades_from(p["properties"]["orchestratorVersion"])]}
                                                 for p in rec["_pools"].values()]}}


# ── maintenance configurations / trusted access ──────────────────────────────
def _maint_view(rec, m):
    return {"id": f"{rec['id']}/maintenanceConfigurations/{m['name']}", "name": m["name"],
            "type": f"{NAMESPACE}/managedClusters/maintenanceConfigurations", "properties": m["properties"],
            "systemData": m["systemData"]}


def _maint_ops(rec, rest, method, payload):
    items = rec["_maint"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_maint_view(rec, m) for m in items.values()]})
    name = rest[0]
    m = items.get(name)
    if method == "GET":
        if m is None:
            raise _not_found("managedClusters/maintenanceConfigurations", name, rec["_rg"])
        return _ok(_maint_view(rec, m))
    if method == "PUT":
        if name not in ("default", "aksManagedAutoUpgradeSchedule", "aksManagedNodeOSUpgradeSchedule"):
            raise _E(400, "InvalidParameter", f"Maintenance configuration name '{name}' is invalid. Valid names: default, "
                                              "aksManagedAutoUpgradeSchedule, aksManagedNodeOSUpgradeSchedule.")
        pr = payload.get("properties") or {}
        if not (pr.get("timeInWeek") or pr.get("notAllowedTime") or pr.get("maintenanceWindow")):
            raise _E(400, "InvalidParameter", "At least one of timeInWeek, notAllowedTime or maintenanceWindow is required.")
        sd = m["systemData"] if m else _sysdata()
        sd["lastModifiedAt"] = _now()
        items[name] = {"name": name, "properties": pr, "systemData": sd}
        return _ok(_maint_view(rec, items[name]))
    if method == "DELETE":
        if m is None:
            return _ok(None, 204)
        del items[name]
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _tab_view(rec, t):
    return {"id": f"{rec['id']}/trustedAccessRoleBindings/{t['name']}", "name": t["name"],
            "type": f"{NAMESPACE}/managedClusters/trustedAccessRoleBindings",
            "properties": {"provisioningState": "Succeeded", "sourceResourceId": t["sourceResourceId"], "roles": t["roles"]},
            "systemData": t["systemData"]}


def _tab_ops(rec, rest, method, payload):
    items = rec["_tabs"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_tab_view(rec, t) for t in items.values()]})
    name = rest[0]
    t = items.get(name)
    if method == "GET":
        if t is None:
            raise _not_found("managedClusters/trustedAccessRoleBindings", name, rec["_rg"])
        return _ok(_tab_view(rec, t))
    if method == "PUT":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,23}", name):
            raise _E(400, "InvalidParameter", f"Trusted access role binding name '{name}' is invalid.")
        pr = payload.get("properties") or {}
        if not pr.get("sourceResourceId") or not pr.get("roles"):
            raise _E(400, "InvalidParameter", "sourceResourceId and roles are required.")
        items[name] = {"name": name, "sourceResourceId": pr["sourceResourceId"], "roles": pr["roles"], "systemData": _sysdata()}
        return _ok(_tab_view(rec, items[name]), 201 if t is None else 200, lro=True, rid=_tab_view(rec, items[name])["id"], verb="put")
    if method == "DELETE":
        if t is None:
            return _ok(None, 204)
        del items[name]
        return _ok(None, 202, lro=True, rid=f"{rec['id']}/trustedAccessRoleBindings/{name}", verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _pec_ops(rec, rest, method, payload):
    items = rec["_pec"]
    if not rest:
        return _ok({"value": [dict(v) for v in items.values()]})
    name = rest[0]
    v = items.get(name)
    if method == "GET":
        if v is None:
            raise _not_found("managedClusters/privateEndpointConnections", name, rec["_rg"])
        return _ok(dict(v))
    if method == "PUT":
        pr = payload.get("properties") or {}
        state_in = (pr.get("privateLinkServiceConnectionState") or {})
        items[name] = {"id": f"{rec['id']}/privateEndpointConnections/{name}", "name": name,
                       "type": f"{NAMESPACE}/managedClusters/privateEndpointConnections",
                       "properties": {"provisioningState": "Succeeded", "privateEndpoint": pr.get("privateEndpoint") or {},
                                      "privateLinkServiceConnectionState": {"status": state_in.get("status") or "Approved",
                                                                            "description": state_in.get("description") or ""}}}
        return _ok(dict(items[name]))
    if method == "DELETE":
        if v is None:
            return _ok(None, 204)
        del items[name]
        return _ok(None, 202, lro=True, rid=f"{rec['id']}/privateEndpointConnections/{name}", verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── credentials ──────────────────────────────────────────────────────────────
def _kubeconfig(rec, user, token):
    p = rec["properties"]
    host = p.get("privateFQDN") or p["fqdn"]
    ca = base64.b64encode(rec["_ca"].encode()).decode()
    text = (
        "apiVersion: v1\n"
        "clusters:\n"
        f"- cluster:\n    certificate-authority-data: {ca}\n    server: https://{host}:443\n  name: {rec['name']}\n"
        "contexts:\n"
        f"- context:\n    cluster: {rec['name']}\n    user: {user}\n  name: {rec['name']}\n"
        f"current-context: {rec['name']}\n"
        "kind: Config\n"
        "preferences: {}\n"
        "users:\n"
        f"- name: {user}\n  user:\n    token: {token}\n")
    return base64.b64encode(text.encode()).decode()


def _credentials(rec, kind):
    if kind == "admin" and rec["properties"].get("disableLocalAccounts"):
        raise _E(400, "BadRequest", "Getting static credential is not allowed because this cluster is set to disable local accounts.")
    user = {"admin": f"clusterAdmin_{rec['_rg']}_{rec['name']}", "user": f"clusterUser_{rec['_rg']}_{rec['name']}",
            "monitoring": f"clusterMonitoringUser_{rec['_rg']}_{rec['name']}"}[kind]
    token = hashlib.sha256(f"{rec['id']}|{kind}".encode()).hexdigest()
    return {"kubeconfigs": [{"name": kind if kind != "monitoring" else "monitoring", "value": _kubeconfig(rec, user, token)}]}


# ── cluster actions ──────────────────────────────────────────────────────────
def _require_running(rec, what):
    if rec["properties"]["powerState"]["code"] != "Running":
        raise _E(400, "OperationNotAllowed", f"Operation '{what}' is not allowed because the cluster is stopped. Start the "
                                              "cluster and try again.")


def _cluster_ops(state, rec, rest, method, payload, query):
    r0 = rest[0].lower()
    if r0 == "agentpools":
        return _pool_ops(rec, rest[1:], method, payload, query)
    if r0 == "maintenanceconfigurations":
        return _maint_ops(rec, rest[1:], method, payload)
    if r0 == "trustedaccessrolebindings":
        return _tab_ops(rec, rest[1:], method, payload)
    if r0 == "privateendpointconnections":
        return _pec_ops(rec, rest[1:], method, payload)
    if r0 == "privatelinkresources" and method == "GET":
        return _ok({"value": [{"id": f"{rec['id']}/privateLinkResources/management", "name": "management",
                               "type": "Microsoft.ContainerService/managedClusters/privateLinkResources",
                               "groupId": "management", "requiredMembers": ["management"]}]})
    if r0 == "upgradeprofiles" and method == "GET":
        if len(rest) > 1 and rest[1].lower() != "default":
            raise _not_found("managedClusters/upgradeProfiles", rest[1], rec["_rg"])
        prof = _cluster_upgrade_profile(rec)
        return _ok(prof)
    if r0 == "accessprofiles" and len(rest) >= 3 and rest[2].lower() == "listcredential" and method == "POST":
        if rest[1] not in ACCESS_ROLES:
            raise _not_found("managedClusters/accessProfiles", rest[1], rec["_rg"])
        kind = "admin" if rest[1] == "clusterAdmin" else "user"
        cfg = _credentials(rec, kind)["kubeconfigs"][0]["value"]
        return _ok({"id": f"{rec['id']}/accessProfiles/{rest[1]}", "name": rest[1],
                    "type": f"{NAMESPACE}/managedClusters/accessProfiles", "location": rec["location"],
                    "properties": {"kubeConfig": cfg}})
    if method == "POST":
        if r0 == "listclusteradmincredential":
            return _ok(_credentials(rec, "admin"))
        if r0 == "listclusterusercredential":
            return _ok(_credentials(rec, "user"))
        if r0 == "listclustermonitoringusercredential":
            return _ok(_credentials(rec, "monitoring"))
        if r0 == "stop":
            if rec["properties"]["powerState"]["code"] == "Stopped":
                return _ok(None, 202, lro=True, rid=rec["id"], verb="post")
            if any(p["properties"]["scaleSetPriority"] == "Spot" for p in rec["_pools"].values()):
                raise _E(400, "InvalidParameter", "Stopping a cluster with Spot node pools is not supported.")
            rec["properties"]["powerState"] = {"code": "Stopped"}
            _sync_pools(rec)
            _touch(rec)
            return _ok(None, 202, lro=True, rid=rec["id"], verb="post")
        if r0 == "start":
            rec["properties"]["powerState"] = {"code": "Running"}
            _sync_pools(rec)
            _touch(rec)
            return _ok(None, 202, lro=True, rid=rec["id"], verb="post")
        if r0 == "abortlatestoperation":
            return _ok(None, 204)
        if r0 in ("rotateclustercertificates", "rotateserviceaccountsigningkeys"):
            _require_running(rec, rest[0])
            rec["_ca"] = _ca_pem(rec["id"] + uuid.uuid4().hex)
            _touch(rec)
            return _ok(None, 202, lro=True, rid=rec["id"], verb="post")
        if r0 == "reimagenodepoolnodes" or r0 == "reimage":
            _require_running(rec, rest[0])
            return _ok(None, 202, lro=True, rid=rec["id"], verb="post")
        if r0 == "resolveprivatelinkserviceid":
            if not payload.get("name") and not (payload.get("id")):
                raise _E(400, "InvalidParameter", "name is required.")
            return _ok({"id": f"{rec['id']}/privateLinkServices/{payload.get('name') or 'management'}"})
        if r0 == "runcommand":
            _require_running(rec, "runCommand")
            if not payload.get("command"):
                raise _E(400, "InvalidParameter", "command is required.")
            cid = uuid.uuid4().hex
            rec["_cmd"][cid] = {"id": cid, "properties": {"provisioningState": "Succeeded", "exitCode": 0,
                                                          "startedAt": _now(), "finishedAt": _now(),
                                                          "logs": "(control plane only: the cluster has no running API server)\n",
                                                          "reason": ""}}
            return _ok(rec["_cmd"][cid], 202, lro=True, rid=rec["id"], verb="post")
    if r0 == "commandresults" and len(rest) == 2 and method == "GET":
        c = rec["_cmd"].get(rest[1])
        if c is None:
            raise _not_found("managedClusters/commandResults", rest[1], rec["_rg"])
        return _ok(c)
    raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/managedClusters/{rest[0]}' is not supported.")


def _list_clusters(state, sub, rg):
    items = []
    for rec in _clusters(state, sub):
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_cluster_view(rec))
    return _ok({"value": items})


# ── snapshots ────────────────────────────────────────────────────────────────
def _snapshots(state, sub):
    t = f"{NAMESPACE}/snapshots".lower()
    return [r for r in state.values() if str(r.get("_type", "")).lower() == t and r.get("_sub") == sub]


def _snapshot_ops(state, sub, rg, chain, method, payload):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(s) for s in _snapshots(state, sub) if rg is None or (s.get("_rg") or "").lower() == rg.lower()]})
    name = chain[1]
    rid = _canon(sub, rg, ["snapshots"], [name])
    rec = state.get(rid.lower())
    if len(chain) > 2:
        raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/snapshots/{chain[2]}' is not supported.")
    if method == "GET":
        if rec is None:
            raise _not_found("snapshots", name, rg)
        return _ok(_view(rec))
    if method == "PUT":
        if rg is None:
            return _err(400, "InvalidResourceId", "Snapshots must be created in a resource group.")
        prob = _cluster_name_problem(name)
        if prob:
            raise _E(400, prob[0], prob[1])
        if rec is not None:
            raise _E(409, "PropertyChangeNotAllowed", "Snapshots are immutable; only tags can be updated with PATCH.")
        pr = payload.get("properties") or {}
        src = pr.get("creationData", {}).get("sourceResourceId")
        if not src:
            raise _E(400, "InvalidParameter", "properties.creationData.sourceResourceId is required.")
        pool = None
        for c in _clusters(state, sub):
            for p in c["_pools"].values():
                if p["id"].lower() == src.lower():
                    pool = p
        if pool is None:
            raise _E(400, "InvalidParameter", f"The source agent pool '{src}' was not found.")
        pp = pool["properties"]
        rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/snapshots", "location": payload.get("location") or DEFAULT_LOCATION,
               "tags": payload.get("tags") or {}, "systemData": _sysdata(),
               "properties": {"creationData": {"sourceResourceId": src}, "snapshotType": pr.get("snapshotType") or "NodePool",
                              "kubernetesVersion": pp["orchestratorVersion"], "nodeImageVersion": pp["nodeImageVersion"],
                              "osType": pp["osType"], "osSku": pp["osSKU"], "vmSize": pp["vmSize"], "enableFIPS": pp["enableFIPS"]},
               "_type": f"{NAMESPACE}/snapshots", "_sub": sub, "_rg": rg}
        state[rid.lower()] = rec
        return _ok(_view(rec), 201)
    if method == "PATCH":
        if rec is None:
            raise _not_found("snapshots", name, rg)
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = payload["tags"]
        return _ok(_view(rec))
    if method == "DELETE":
        if rec is not None:
            del state[rid.lower()]
        return _ok(None, 200 if rec is not None else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── location scope ───────────────────────────────────────────────────────────
def _location_ops(chain, method):
    if method != "GET":
        return _err(405, "MethodNotAllowed", "GET required.")
    loc, what = chain[1], chain[2].lower()
    if what == "kubernetesversions":
        vers = []
        for v, d, pv in K8S_VERSIONS:
            vers.append({"version": _major_minor(v), "isDefault": d, "isPreview": pv,
                         "patchVersions": {pv2: {"upgrades": [u for u, _, _ in _upgrades_from(pv2)]}
                                           for pv2, _, _ in K8S_VERSIONS if _major_minor(pv2) == _major_minor(v)},
                         "capabilities": {"supportPlan": ["KubernetesOfficial"]}})
        return _ok({"id": f"/subscriptions/00000000/providers/{NAMESPACE}/locations/{loc}/kubernetesVersions", "values": vers})
    if what == "osoptions":
        return _ok({"id": f"/subscriptions/00000000/providers/{NAMESPACE}/locations/{loc}/osOptions/default", "name": "default",
                    "type": f"{NAMESPACE}/locations/osOptions",
                    "properties": {"osOptionPropertyList": [{"os-type": "Linux", "enable-fips-image": True},
                                                            {"os-type": "Windows", "enable-fips-image": False}]}})
    if what == "orchestrators":
        return _ok({"id": f"/subscriptions/00000000/providers/{NAMESPACE}/locations/{loc}/orchestrators", "name": "default",
                    "type": f"{NAMESPACE}/locations/orchestrators",
                    "properties": {"orchestrators": [{"orchestratorType": "Kubernetes", "orchestratorVersion": v, "default": d,
                                                      "isPreview": pv, "upgrades": [{"orchestratorType": "Kubernetes", "orchestratorVersion": u}
                                                                                    for u, _, _ in _upgrades_from(v)]}
                                                     for v, d, pv in K8S_VERSIONS]}})
    return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/locations/{chain[2]}' is not supported.")


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.ContainerService`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {})
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload, query):
    low = chain[0].lower()
    if low == "locations":
        if len(chain) < 3:
            return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{'/'.join(chain)}' is not supported.")
        return _location_ops(chain, method)
    if low == "snapshots":
        return _snapshot_ops(state, sub, rg, chain, method, payload)
    if low != "managedclusters":
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0]}' is not supported.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_clusters(state, sub, rg)
    name = chain[1]
    rid = _canon(sub, rg, ["managedClusters"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("managedClusters", name, rg)
        r = _cluster_ops(state, rec, rest, method, payload, query)
        if r["lro"]:
            _sync_pools(rec)
        return r
    if method == "GET":
        if rec is None:
            raise _not_found("managedClusters", name, rg)
        return _ok(_cluster_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Managed clusters must be created in a resource group.")
        rec, created = _put_cluster(state, sub, rg, rid, name, payload, method)
        return _ok(_cluster_view(rec), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        del state[rid.lower()]
        return _ok(None, 202, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("managedClusters", API_VERSION), ("snapshots", API_VERSION)]
