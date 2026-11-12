# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Microsoft Defender for Cloud — the `Microsoft.Security` ARM namespace (substrate-free).

Served by the shared ARM engine (core/azure_arm_core.AzureArm) on both substrates, computed
LIVE from the ARM state every time it is read — nothing here is static data:

  * pricings                 Defender plans per subscription (Free / Standard), PUT to toggle.
                             The plans start off (Free), like a new subscription.
  * assessments              Recommendations x resources, from two sources:
      - a native rule engine over the ARM state (foundational CSPM — always on, like the free
        tier in Azure): storage public blob access / secure transfer, NSG management ports open
        to the internet, SQL public network access / TDE, Key Vault soft delete / purge
        protection, VM encryption at host, App Service / Function app HTTPS-only, Container
        registry unrestricted network access, API Management without a virtual network;
      - Kubernetes posture for every AKS cluster from its Kubescape scan
        (core/kubescape_core.py) — one recommendation per Kubescape control (Kubescape control id
        kept in properties.additionalData.kubescapeControlId), only while the **Containers**
        plan is Standard (off => no Kubernetes recommendations, as in Azure).
  * subAssessments           one per failed Kubernetes object of a Kubernetes recommendation.
  * assessmentMetadata       the recommendation definitions (severity, description, remediation).
  * secureScores / secureScoreControls / secureScoreControlDefinitions
                             the secure score, computed from the assessments with Azure's formula
                             (control score = max x healthy / (healthy + unhealthy) resources;
                             subscription % = sum(current) / sum(max) over controls in play).
  * alerts                   Microsoft.Security/locations/alerts from Vyomi's DETERMINISTIC detector
                             (core/secscan_core.py) over the ARM control-plane audit feed kept in this state
                             (storage opened to anonymous access, Owner role assigned, NSG management port
                             exposed to the internet, diagnostic settings deleted, Key Vault purged, ...).
                             Each alert is gated by its Defender plan (Storage / Resource Manager / Key
                             Vaults) exactly like Azure, carries vendorName "Vyomi", and dismiss / activate /
                             resolve are real. No real attacker or workload telemetry exists, so no ML alerts.
  * container images         Defender for Containers vulnerability assessment of the images in the registry
                             (core/vuln_scan_core.py; the real Trivy container where the appliance has it).

State it keeps (JSON-only, persisted with the ARM state, excluded from resource listings):
``/subscriptions/{sub}/providers/microsoft.security/pricings`` (plan tiers) and
``…/microsoft.security/__assessmentstate__`` (first-evaluation / status-change dates).
"""
from __future__ import annotations

import datetime
import json
import time
import uuid

try:
    from core import kubescape_core as ks
    from core import secscan_core as sc
except ImportError:                                    # Pyodide flat layout
    import kubescape_core as ks                        # type: ignore
    import secscan_core as sc                          # type: ignore

API_PRICINGS = "2024-01-01"
NS = "Microsoft.Security"
TYPE_PREFIX = "microsoft.security/"
_UUID_NS = uuid.UUID("6f1d5a52-4f0e-4c61-9f6f-76796f6d6964")   # Vyomi Defender namespace (stable ids)

PLANS = [
    ("VirtualMachines", "Servers"), ("SqlServers", "Azure SQL Databases"), ("AppServices", "App Service"),
    ("StorageAccounts", "Storage"), ("SqlServerVirtualMachines", "SQL servers on machines"),
    ("KeyVaults", "Key Vault"), ("Arm", "Resource Manager"),
    ("OpenSourceRelationalDatabases", "Open-source relational databases"), ("CosmosDbs", "Azure Cosmos DB"),
    ("Containers", "Containers"), ("CloudPosture", "Defender CSPM"), ("Api", "APIs"), ("AI", "AI services"),
]
PLAN_NAMES = {p.lower(): p for p, _ in PLANS}

# Secure score controls (Azure's names and max scores).
CONTROLS = {
    "Secure management ports": 8,
    "Enable encryption at rest": 4,
    "Encrypt data in transit": 4,
    "Restrict unauthorized network access": 4,
    "Manage access and permissions": 4,
    "Remediate security configurations": 4,
    "Implement security best practices": 0,
}


def _id(*parts) -> str:
    return str(uuid.uuid5(_UUID_NS, "/".join(parts)))


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ok(body, status=200):
    return {"status": status, "headers": {}, "body": body}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


# ── native rule engine (non-Kubernetes recommendations) ─────────────────────────────────
INTERNET = {"*", "0.0.0.0/0", "0.0.0.0", "internet", "any", "::/0"}
MGMT_PORTS = (22, 3389)


def _port_in(spec, port: int) -> bool:
    s = str(spec).strip()
    if s in ("*", ""):
        return s == "*"
    if "-" in s:
        a, _, b = s.partition("-")
        try:
            return int(a) <= port <= int(b)
        except ValueError:
            return False
    try:
        return int(s) == port
    except ValueError:
        return False


def _nsg_rules(state: dict, nsg_key: str, nsg: dict) -> list:
    rules = {}
    for r in ((nsg.get("properties") or {}).get("securityRules") or []):
        if isinstance(r, dict):
            rules[str(r.get("name")).lower()] = r
    prefix = nsg_key + "/securityrules/"
    for k, r in state.items():
        if k.startswith(prefix) and k.count("/") == prefix.count("/"):
            rules[k[len(prefix):]] = r
    return list(rules.values())


def _exposed_ports(state, key, nsg) -> list:
    """Management ports an internet source can reach through this NSG (priority order, first
    matching rule wins — the platform's default rules deny the internet otherwise)."""
    rules = []
    for r in _nsg_rules(state, key, nsg):
        p = r.get("properties") if isinstance(r.get("properties"), dict) else r
        if str(p.get("direction") or "").lower() != "inbound":
            continue
        try:
            prio = int(p.get("priority") or 0)
        except (TypeError, ValueError):
            prio = 0
        srcs = [p.get("sourceAddressPrefix")] + list(p.get("sourceAddressPrefixes") or [])
        if not any(str(s or "").strip().lower() in INTERNET for s in srcs if s is not None):
            continue
        if str(p.get("protocol") or "*").lower() not in ("*", "tcp"):
            continue
        ports = [p.get("destinationPortRange")] + list(p.get("destinationPortRanges") or [])
        rules.append((prio, str(p.get("access") or "").lower(), [x for x in ports if x is not None], r.get("name") or p.get("name")))
    rules.sort(key=lambda x: x[0])
    exposed = []
    for port in MGMT_PORTS:
        for prio, access, ports, name in rules:
            if any(_port_in(x, port) for x in ports):
                if access == "allow":
                    exposed.append((port, name, prio))
                break
    return exposed


def _rec_type(r) -> str:
    return str(r.get("_type") or r.get("type") or "").lower()


def _props(r) -> dict:
    return r.get("properties") or {}


RULES = []


def rule(key, *, display, severity, control, description, remediation, categories, rtype, effort="Low", impact="Low", threats=()):
    def deco(fn):
        RULES.append({"key": key, "name": _id("rule", key), "displayName": display, "severity": severity,
                      "control": control, "description": description, "remediation": remediation,
                      "categories": list(categories), "rtype": rtype, "fn": fn, "effort": effort,
                      "impact": impact, "threats": list(threats)})
        return fn
    return deco


@rule("storage-public-blob", display="Storage account public access should be disallowed", severity="Medium",
      control="Restrict unauthorized network access", rtype="microsoft.storage/storageaccounts", categories=["Data"],
      description="Anonymous public read access to containers and blobs in Azure Storage is a convenient way to share data but might present security risks. Disallow public blob access on the storage account unless your scenario requires it.",
      remediation="On the storage account's Configuration page set 'Allow Blob anonymous access' to Disabled (properties.allowBlobPublicAccess = false).",
      threats=["dataExfiltration", "dataSpillage"])
def _r_storage_public(state, key, r):
    if _props(r).get("allowBlobPublicAccess") is True:
        return "Unhealthy", "allowBlobPublicAccess is true"
    return "Healthy", ""


@rule("storage-secure-transfer", display="Secure transfer to storage accounts should be enabled", severity="High",
      control="Encrypt data in transit", rtype="microsoft.storage/storageaccounts", categories=["Data"],
      description="Secure transfer forces the storage account to accept requests only over HTTPS, protecting data in transit from network layer attacks such as man-in-the-middle, eavesdropping and session hijacking.",
      remediation="On the storage account's Configuration page set 'Secure transfer required' to Enabled (properties.supportsHttpsTrafficOnly = true).",
      threats=["dataExfiltration", "accountBreach"])
def _r_storage_https(state, key, r):
    if _props(r).get("supportsHttpsTrafficOnly") is False:
        return "Unhealthy", "supportsHttpsTrafficOnly is false"
    return "Healthy", ""


@rule("nsg-management-ports", display="Management ports should not be open to the internet on network security groups",
      severity="High", control="Secure management ports", rtype="microsoft.network/networksecuritygroups", categories=["Networking"],
      description="An inbound rule allowing SSH (22) or RDP (3389) from any internet source exposes the virtual machines behind this network security group to brute-force attacks.",
      remediation="Remove or restrict the inbound rule: limit the source to known IP ranges, or deny ports 22 and 3389 from 'Internet' / '*' at a higher priority.",
      threats=["accountBreach", "maliciousInsider", "threatResistance"], effort="Moderate", impact="Moderate")
def _r_nsg(state, key, r):
    exposed = _exposed_ports(state, key, r)
    if exposed:
        return "Unhealthy", "; ".join(f"port {p} allowed from the internet by rule '{n}' (priority {pr})" for p, n, pr in exposed)
    return "Healthy", ""


@rule("sql-public-network", display="Public network access on Azure SQL Database should be disabled", severity="Medium",
      control="Restrict unauthorized network access", rtype="microsoft.sql/servers", categories=["Data"],
      description="Disabling public network access ensures the Azure SQL Database can only be reached from a private endpoint, denying logins that match IP or virtual network based firewall rules.",
      remediation="On the logical server's Networking page set 'Public network access' to Disable (properties.publicNetworkAccess = 'Disabled').",
      threats=["dataExfiltration"])
def _r_sql_public(state, key, r):
    v = _props(r).get("publicNetworkAccess")
    if v != "Disabled":
        return "Unhealthy", f"publicNetworkAccess is {v or 'Enabled (default)'}"
    return "Healthy", ""


@rule("sql-tde", display="Transparent Data Encryption on SQL databases should be enabled", severity="Low",
      control="Enable encryption at rest", rtype="microsoft.sql/servers/databases", categories=["Data"],
      description="Transparent data encryption protects data at rest by encrypting the database, backups and transaction logs.",
      remediation="On the database's Data encryption page set transparent data encryption to ON.",
      threats=["dataExfiltration"])
def _r_sql_tde(state, key, r):
    if str(r.get("name") or "").lower() == "master":
        return None
    if ((_props(r).get("transparentDataEncryption") or {}).get("state")) == "Disabled":
        return "Unhealthy", "transparent data encryption is OFF"
    return "Healthy", ""


@rule("kv-soft-delete", display="Key vaults should have soft delete enabled", severity="High",
      control="Implement security best practices", rtype="microsoft.keyvault/vaults", categories=["Data"],
      description="Deleting a key vault without soft delete permanently deletes all secrets, keys and certificates stored in it. Soft delete keeps deleted vaults recoverable for a retention period.",
      remediation="Enable soft delete on the vault (properties.enableSoftDelete = true).",
      threats=["dataSpillage"])
def _r_kv_soft(state, key, r):
    if _props(r).get("enableSoftDelete") is False:
        return "Unhealthy", "enableSoftDelete is false"
    return "Healthy", ""


@rule("kv-purge-protection", display="Key vaults should have deletion protection enabled", severity="Medium",
      control="Implement security best practices", rtype="microsoft.keyvault/vaults", categories=["Data"],
      description="Purge protection enforces a mandatory retention period for soft-deleted vaults and objects, so a malicious insider cannot permanently delete them before the period ends.",
      remediation="Enable purge protection on the vault's Properties page (properties.enablePurgeProtection = true). It cannot be turned off afterwards.",
      threats=["maliciousInsider", "dataSpillage"])
def _r_kv_purge(state, key, r):
    if _props(r).get("enablePurgeProtection") is not True:
        return "Unhealthy", "enablePurgeProtection is not enabled"
    return "Healthy", ""


@rule("vm-encryption", display="Virtual machines should encrypt temp disks, caches, and data flows between Compute and Storage resources",
      severity="High", control="Enable encryption at rest", rtype="microsoft.compute/virtualmachines", categories=["Compute"],
      description="Without encryption at host or disk encryption, a VM's temp disk, disk caches and the data flowing between compute and storage are not encrypted with platform- or customer-managed keys.",
      remediation="Enable 'Encryption at host' on the VM's Disks page (properties.securityProfile.encryptionAtHost = true), or attach the OS disk with a disk encryption set.",
      threats=["dataExfiltration"], effort="Moderate")
def _r_vm_enc(state, key, r):
    p = _props(r)
    sp = (p.get("securityProfile") or {})
    os_disk = ((p.get("storageProfile") or {}).get("osDisk") or {})
    if sp.get("encryptionAtHost") is True or (os_disk.get("encryptionSettings") or {}).get("enabled") is True \
            or ((os_disk.get("managedDisk") or {}).get("diskEncryptionSet") or {}).get("id"):
        return "Healthy", ""
    return "Unhealthy", "no encryption at host and no disk encryption set on the OS disk"


@rule("web-https-only", display="App Service apps should only be accessible over HTTPS", severity="Medium",
      control="Encrypt data in transit", rtype="microsoft.web/sites", categories=["AppServices"],
      description="Use of HTTPS ensures server/service authentication and protects data in transit from network layer eavesdropping attacks.",
      remediation="On the app's Configuration > General settings set 'HTTPS Only' to On (properties.httpsOnly = true).",
      threats=["dataExfiltration", "accountBreach"])
def _r_web_https(state, key, r):
    if "functionapp" in str(r.get("kind") or "").lower():
        return None
    return ("Healthy", "") if _props(r).get("httpsOnly") is True else ("Unhealthy", "httpsOnly is not enabled")


@rule("func-https-only", display="Function apps should only be accessible over HTTPS", severity="Medium",
      control="Encrypt data in transit", rtype="microsoft.web/sites", categories=["AppServices"],
      description="Use of HTTPS ensures server/service authentication and protects data in transit from network layer eavesdropping attacks.",
      remediation="On the function app's Configuration > General settings set 'HTTPS Only' to On (properties.httpsOnly = true).",
      threats=["dataExfiltration", "accountBreach"])
def _r_func_https(state, key, r):
    if "functionapp" not in str(r.get("kind") or "").lower():
        return None
    return ("Healthy", "") if _props(r).get("httpsOnly") is True else ("Unhealthy", "httpsOnly is not enabled")


@rule("acr-network", display="Container registries should not allow unrestricted network access", severity="Medium",
      control="Restrict unauthorized network access", rtype="microsoft.containerregistry/registries", categories=["Containers"],
      description="Azure container registries by default accept connections over the internet from hosts on any network. Restrict access to specific public IP ranges, virtual networks or private endpoints.",
      remediation="On the registry's Networking page disable public network access, or set the default action of the network rule set to Deny with explicit allow rules (Premium SKU).",
      threats=["dataExfiltration"], effort="Moderate")
def _r_acr(state, key, r):
    p = _props(r)
    if p.get("publicNetworkAccess") == "Disabled" or ((p.get("networkRuleSet") or {}).get("defaultAction") == "Deny"):
        return "Healthy", ""
    return "Unhealthy", "public network access is enabled with no network rule set"


@rule("apim-vnet", display="API Management services should use a virtual network", severity="Medium",
      control="Restrict unauthorized network access", rtype="microsoft.apimanagement/service", categories=["Networking"],
      description="Deploying API Management into a virtual network places the gateway on a network you control, so you can restrict access to backends and the developer portal.",
      remediation="On the service's Network page set the virtual network type to External or Internal (Developer or Premium tier).",
      threats=["dataExfiltration"], effort="High", impact="High")
def _r_apim(state, key, r):
    vt = str(_props(r).get("virtualNetworkType") or "None")
    return ("Healthy", "") if vt in ("External", "Internal") else ("Unhealthy", f"virtualNetworkType is {vt}")


# ── Kubernetes (Kubescape) recommendation mapping ───────────────────────────────────────
# Kubescape controls with an established Defender for Cloud equivalent get its title; every other
# control keeps Kubescape's own name. The Kubescape id always rides along in additionalData.
DEFENDER_TITLES = {
    "C-0057": "Privileged containers should be avoided",
    "C-0013": "Running containers as root user should be avoided",
    "C-0016": "Container with privilege escalation should be avoided",
    "C-0017": "Immutable (read-only) root filesystem should be enforced for containers",
    "C-0038": "Containers sharing sensitive host namespaces should be avoided",
    "C-0041": "Usage of host networking and ports should be restricted",
    "C-0044": "Usage of host networking and ports should be restricted",
    "C-0045": "Usage of pod HostPath volume mounts should be restricted to a known list to restrict node access from compromised containers",
    "C-0048": "Usage of pod HostPath volume mounts should be restricted to a known list to restrict node access from compromised containers",
    "C-0046": "Least privileged Linux capabilities should be enforced for containers",
    "C-0034": "Kubernetes clusters should disable automounting API credentials",
    "C-0270": "Container CPU and memory limits should be enforced",
    "C-0271": "Container CPU and memory limits should be enforced",
    "C-0055": "Overriding or disabling of containers AppArmor profile should be restricted",
    "C-0030": "Kubernetes workloads should have network policies restricting ingress and egress",
}
_K8S_CONTROL = {"Access control": "Manage access and permissions", "Network": "Restrict unauthorized network access"}


def k8s_title(cid: str, name: str) -> str:
    base = DEFENDER_TITLES.get(cid)
    return f"{base} ({cid})" if base else f"Kubernetes: {name} ({cid})"


def k8s_meta(f: dict) -> dict:
    sev = {"Critical": "High", "Unknown": "Low"}.get(f.get("severity"), f.get("severity") or "Low")
    return {"name": _id("kubescape", f["controlId"]), "displayName": k8s_title(f["controlId"], f["name"]),
            "severity": sev, "control": _K8S_CONTROL.get(f.get("category"), "Remediate security configurations"),
            "description": f.get("description") or f["name"], "remediation": f.get("remediation") or "",
            "categories": ["Containers"], "effort": "Low", "impact": "Low", "threats": [],
            "kubescapeControlId": f["controlId"], "kubescapeSeverity": f.get("severity"), "frameworks": f.get("frameworks") or []}


# ── state helpers ───────────────────────────────────────────────────────────────────────
def _pricing_key(sub):
    return f"/subscriptions/{sub}/providers/microsoft.security/pricings".lower()


def _astate_key(sub):
    return f"/subscriptions/{sub}/providers/microsoft.security/__assessmentstate__".lower()


def plans(state: dict, sub: str) -> dict:
    rec = state.get(_pricing_key(sub)) or {}
    return dict(rec.get("plans") or {})


def plan_on(state: dict, sub: str, plan: str) -> bool:
    return (plans(state, sub).get(plan) or {}).get("pricingTier") == "Standard"


def _pricing_view(sub, name, entry):
    tier = (entry or {}).get("pricingTier") or "Free"
    props = {"pricingTier": tier, "freeTrialRemainingTime": "PT0S", "deprecated": False}
    if tier == "Standard":
        props["enablementTime"] = (entry or {}).get("enablementTime")
        if (entry or {}).get("subPlan"):
            props["subPlan"] = entry["subPlan"]
    if (entry or {}).get("extensions") is not None:   # Defender for Storage: OnUploadMalwareScanning / SensitiveDataDiscovery (core/malware_scan_core)
        props["extensions"] = [{"name": n, "isEnabled": "True" if e.get("isEnabled") else "False", "additionalExtensionProperties": e.get("additionalExtensionProperties") or {},
                                "operationStatus": {"code": "OK", "message": "The operation completed successfully."}} for n, e in sorted(entry["extensions"].items())]
    return {"id": f"/subscriptions/{sub}/providers/{NS}/pricings/{name}", "name": name,
            "type": f"{NS}/pricings", "properties": props}


# ── evaluation ──────────────────────────────────────────────────────────────────────────
def _resources(state, sub, rtype):
    for k, r in list(state.items()):
        if isinstance(r, dict) and r.get("_sub") == sub and _rec_type(r) == rtype:
            yield k, r


IMG_META = {"name": _id("vyomi", "acr-image-vulnerabilities"), "displayName": "Container registry images should have vulnerability findings resolved",
            "severity": "High", "control": "Remediate vulnerabilities", "categories": ["Containers"], "effort": "Moderate", "impact": "Low", "threats": ["dataExfiltration"],
            "description": "Vulnerabilities were found in the packages and runtime of images pushed to the registry (Defender for Containers vulnerability assessment).",
            "remediation": "Rebuild the image with the fixed package versions listed in the sub-assessments, push the new tag and delete the vulnerable one."}


def evaluate(state: dict, sub: str, *, refresh: bool = True, ctx: dict | None = None) -> dict:
    """All assessments for a subscription -> {assessments: [...], scanners: [...]}.
    ctx (optional, supplied by the ARM engine): {"images": [{"repo","tag","digest","scan"}]} — scanned registry images."""
    out, scanners = [], []
    for rl in RULES:
        for key, r in _resources(state, sub, rl["rtype"]):
            res = rl["fn"](state, key, r)
            if res is None:
                continue
            status, cause = res
            out.append({"meta": rl, "rid": r.get("id") or key, "status": status, "cause": cause, "sub": None})
    containers_on = plan_on(state, sub, "Containers")
    images = (ctx or {}).get("images") or []
    regs = sorted(_resources(state, sub, "microsoft.containerregistry/registries"), key=lambda kr: kr[0])
    if containers_on and images and regs:
        # Vyomi's registry data plane is one flat store (not tied to a login server): its images are assessed on the
        # subscription's first registry.
        rid = regs[0][1].get("id") or regs[0][0]
        bad = [i for i in images if i["scan"]["findings"]]
        n = sum(len(i["scan"]["findings"]) for i in images)
        res = ("Unhealthy", f"{n} vulnerabilities in {len(bad)} of {len(images)} image(s)") if bad else ("Healthy", "")
        out.append({"meta": IMG_META, "rid": rid, "status": res[0], "cause": res[1], "sub": None, "images": images,
                    "engine": images[0]["scan"]["engine"]})
    for key, r in _resources(state, sub, "microsoft.containerservice/managedclusters"):
        rid = r.get("id") or key
        if not containers_on:
            scanners.append({"clusterId": rid, "status": "plan-off",
                             "reason": "The Defender for Containers plan is off — Kubernetes recommendations are not generated"})
            continue
        if refresh:
            ks.ensure_fresh(r, rid)
        res = ks.result(r) or {}
        scanners.append({"clusterId": rid, "status": res.get("status") or "never", "engine": res.get("engine"),
                         "reason": res.get("reason") or "", "scannedAt": res.get("scannedAt"),
                         "kubescapeVersion": res.get("kubescapeVersion"), "frameworks": res.get("frameworks"),
                         "controlsEvaluated": len(res.get("controlsEvaluated") or []),
                         "frameworkScores": res.get("frameworkScores") or {},
                         "stale": res.get("lastObjectsVersion") != ks.k8s.version(r) if res.get("controls") is not None else None,
                         "objectsVersion": ks.k8s.version(r)})
        for f in res.get("controls") or []:
            meta = k8s_meta(f)
            if f.get("status") == "failed" and (f.get("failed") or f.get("failedCount")):
                status, cause = "Unhealthy", f"{f.get('failedCount') or len(f.get('failed') or [])} Kubernetes object(s) failed {f['controlId']}"
            elif f.get("status") == "skipped":
                status, cause = "NotApplicable", f"Kubescape skipped {f['controlId']}: {f.get('subStatus') or 'not evaluated'}"
            elif f.get("subStatus") == "irrelevant" or (not f.get("passedCount") and not f.get("failedCount")):
                status, cause = "NotApplicable", "No Kubernetes objects in the cluster match this control"
            else:
                status, cause = "Healthy", ""
            out.append({"meta": meta, "rid": rid, "status": status, "cause": cause, "sub": f,
                        "scannedAt": res.get("scannedAt"), "engine": res.get("engine")})
    return {"assessments": out, "scanners": scanners}


def _track(state, sub, aid, status):
    k = _astate_key(sub)
    rec = state.get(k)
    if rec is None:
        rec = state[k] = {"_type": "microsoft.security/assessmentstate", "_sub": sub, "items": {}}
    items = rec.setdefault("items", {})
    now = _now()
    e = items.get(aid)
    if e is None:
        e = items[aid] = {"first": now, "code": status, "changed": now}
    elif e.get("code") != status:
        e["code"], e["changed"] = status, now
    return e


def _assessment_view(state, sub, a) -> dict:
    m = a["meta"]
    aid = f"{a['rid']}/providers/{NS}/assessments/{m['name']}"
    t = _track(state, sub, aid.lower(), a["status"])
    status = {"code": a["status"], "firstEvaluationDate": t["first"], "statusChangeDate": t["changed"]}
    if a["status"] != "Healthy" and a.get("cause"):
        status["cause"] = "VyomiEvaluation" if a["status"] == "Unhealthy" else "NotApplicable"
        status["description"] = a["cause"]
    add = {"evaluatedBy": "Vyomi native rule engine"}
    if a.get("sub") is not None:
        f = a["sub"]
        add = {"kubescapeControlId": f["controlId"], "kubescapeControlName": f["name"],
               "kubescapeSeverity": f.get("severity"), "frameworks": ", ".join(f.get("frameworks") or []),
               "failedResources": str(f.get("failedCount") or 0), "passedResources": str(f.get("passedCount") or 0),
               "evaluatedBy": f"Kubescape ({a.get('engine') or ''})", "scannedAt": a.get("scannedAt") or ""}
    if a.get("images"):
        add = {"evaluatedBy": f"Vyomi image scanner ({a.get('engine')})", "imagesScanned": str(len(a["images"])),
               "vulnerabilities": str(sum(len(i["scan"]["findings"]) for i in a["images"])),
               "scanEngines": ", ".join(sorted({i["scan"]["engine"] for i in a["images"]}))}
    return {
        "id": aid, "name": m["name"], "type": f"{NS}/assessments",
        "properties": {
            "resourceDetails": {"Source": "Azure", "Id": a["rid"]},
            "displayName": m["displayName"],
            "status": status,
            "additionalData": add,
            "metadata": _metadata_props(m),
            "links": {"azurePortalUri": f"#/defender/recommendations/{m['name']}"},
        },
    }


def _metadata_props(m) -> dict:
    p = {"displayName": m["displayName"], "severity": m["severity"], "description": m["description"],
         "remediationDescription": m["remediation"], "assessmentType": "BuiltIn", "categories": m["categories"],
         "implementationEffort": m["effort"], "userImpact": m["impact"], "threats": m["threats"],
         "securityControl": m["control"]}
    if m.get("kubescapeControlId"):
        p["kubescapeControlId"] = m["kubescapeControlId"]
        p["frameworks"] = m.get("frameworks") or []
    return p


def _image_sub_views(a, aid) -> list:
    out = []
    for im in a.get("images") or []:
        for v in im["scan"]["findings"]:
            oid = f"{im['repo']}:{im['tag']}/{v['vulnerabilityId']}/{v['package']}"
            name = _id("subimg", aid.lower(), oid, im["digest"])
            out.append({"id": f"{aid}/subAssessments/{name}", "name": name, "type": f"{NS}/assessments/subAssessments",
                        "properties": {"id": v["vulnerabilityId"], "displayName": f"{v['vulnerabilityId']} in {v['package']} {v['installedVersion']}",
                                       "status": {"code": "Unhealthy", "severity": {"CRITICAL": "High", "HIGH": "High", "MEDIUM": "Medium"}.get(v["severity"], "Low"),
                                                  "cause": "", "description": v["title"]},
                                       "remediation": f"Upgrade {v['package']} to {v['fixedVersion']} or later." if v["fixedVersion"] else "No fixed version is available yet.",
                                       "impact": v["title"], "category": "Vulnerability", "description": v["title"],
                                       "timeGenerated": _now(), "resourceDetails": {"source": "Azure", "id": a["rid"]},
                                       "additionalData": {"assessedResourceType": "AzureContainerRegistryVulnerability", "type": "Vulnerability",
                                                          "cvss": {"base": v["cvss"]}, "repositoryName": im["repo"], "imageTag": im["tag"], "imageDigest": im["digest"],
                                                          "patchable": bool(v["fixedVersion"]), "cve": [{"title": v["vulnerabilityId"]}],
                                                          "publishedTime": "", "vulnerabilityScanner": im["scan"]["engine"], "package": v["package"],
                                                          "installedVersion": v["installedVersion"], "fixedVersion": v["fixedVersion"]}}})
    return out


def _sub_views(a, aid) -> list:
    if a.get("images"):
        return _image_sub_views(a, aid) if a["status"] == "Unhealthy" else []
    f = a.get("sub")
    if not f or a["status"] != "Unhealthy":
        return []
    out = []
    for o in f.get("failed") or []:
        oid = f"{o['kind']}/{o['namespace'] or ''}/{o['name']}"
        name = _id("sub", aid.lower(), oid)
        out.append({
            "id": f"{aid}/subAssessments/{name}", "name": name, "type": f"{NS}/assessments/subAssessments",
            "properties": {
                "id": oid, "displayName": f"{o['kind']} {(o['namespace'] + '/') if o['namespace'] else ''}{o['name']}",
                "status": {"code": "Unhealthy", "severity": a["meta"]["severity"], "cause": "", "description": f["name"]},
                "remediation": f.get("remediation") or "", "impact": f.get("description") or "",
                "category": f.get("category") or "", "description": f["name"],
                "timeGenerated": a.get("scannedAt"),
                "resourceDetails": {"source": "Azure", "id": a["rid"]},
                "additionalData": {"assessedResourceType": "KubernetesObject", "kind": o["kind"], "namespace": o["namespace"],
                                   "name": o["name"], "apiVersion": o.get("apiVersion"), "kubescapeControlId": f["controlId"],
                                   "fixPaths": o.get("fixPaths") or [], "failedPaths": o.get("failedPaths") or [],
                                   "reviewPaths": o.get("reviewPaths") or [],
                                   "relatedObjects": [f"{r['kind']}/{(r['namespace'] + '/') if r['namespace'] else ''}{r['name']}" for r in o.get("related") or []]},
            },
        })
    return out


def _all_meta(state, sub) -> list:
    seen, out = set(), []
    for rl in RULES:
        if rl["name"] not in seen:
            seen.add(rl["name"]); out.append(rl)
    out.append(IMG_META)
    for key, r in _resources(state, sub, "microsoft.containerservice/managedclusters"):
        for f in (ks.result(r) or {}).get("controls") or []:
            m = k8s_meta(f)
            if m["name"] not in seen:
                seen.add(m["name"]); out.append(m)
    return out


def _meta_view(sub, m) -> dict:
    return {"id": f"/subscriptions/{sub}/providers/{NS}/assessmentMetadata/{m['name']}", "name": m["name"],
            "type": f"{NS}/assessmentMetadata", "properties": _metadata_props(m)}


def _scores(evaluated) -> tuple:
    per = {c: {"healthy": set(), "unhealthy": set(), "na": set()} for c in CONTROLS}
    for a in evaluated:
        c = per.setdefault(a["meta"]["control"], {"healthy": set(), "unhealthy": set(), "na": set()})
        rid = a["rid"].lower()
        if a["status"] == "Unhealthy":
            c["unhealthy"].add(rid)
        elif a["status"] == "Healthy":
            c["healthy"].add(rid)
        else:
            c["na"].add(rid)
    rows = []
    for name, c in per.items():
        unhealthy = c["unhealthy"]
        healthy = c["healthy"] - unhealthy
        na = c["na"] - unhealthy - healthy
        mx = CONTROLS.get(name, 0)
        total = len(healthy) + len(unhealthy)
        cur = round(mx * len(healthy) / total, 2) if total else 0.0
        rows.append({"name": name, "max": mx, "current": cur, "healthy": len(healthy), "unhealthy": len(unhealthy),
                     "na": len(na), "inPlay": total > 0})
    smax = sum(r["max"] for r in rows if r["inPlay"])
    scur = round(sum(r["current"] for r in rows if r["inPlay"]), 2)
    return rows, smax, scur


def _control_view(sub, r, expand) -> dict:
    cid = _id("control", r["name"])
    v = {"id": f"/subscriptions/{sub}/providers/{NS}/secureScores/ascScore/secureScoreControls/{cid}", "name": cid,
         "type": f"{NS}/secureScores/secureScoreControls",
         "properties": {"displayName": r["name"], "healthyResourceCount": r["healthy"],
                        "unhealthyResourceCount": r["unhealthy"], "notApplicableResourceCount": r["na"],
                        "weight": max(r["healthy"] + r["unhealthy"], 0),
                        "score": {"max": r["max"], "current": r["current"],
                                  "percentage": round(r["current"] / r["max"], 4) if r["max"] else 0.0}}}
    if expand:
        v["properties"]["definition"] = _definition_view(r["name"])
    return v


def _definition_view(name) -> dict:
    cid = _id("control", name)
    return {"id": f"/providers/{NS}/secureScoreControlDefinitions/{cid}", "name": cid,
            "type": f"{NS}/secureScoreControlDefinitions",
            "properties": {"displayName": name, "maxScore": CONTROLS.get(name, 0), "source": {"sourceType": "BuiltIn"},
                           "assessmentDefinitions": [{"id": f"/providers/{NS}/assessmentMetadata/{rl['name']}"}
                                                     for rl in RULES if rl["control"] == name]}}


# ── ARM dispatch ────────────────────────────────────────────────────────────────────────
def find_marker(chain: list):
    """Index of a re-entrant `providers/Microsoft.Security` inside a resource chain, else None."""
    low = [c.lower() for c in chain]
    for i in range(1, len(low) - 1):
        if low[i] == "providers" and low[i + 1] == "microsoft.security" and i % 2 == 0:
            return i
    return None


def dispatch(state: dict, method: str, sub: str, rg, chain: list, payload: dict, query: dict, scope_rid: str | None = None, ctx: dict | None = None):
    """`chain` = segments after providers/Microsoft.Security; scope_rid = the resource the call is
    scoped to (resource-scoped assessments), else subscription / resource-group scope."""
    low = [c.lower() for c in chain]
    if not low:
        return _err(400, "BadRequest", "Missing Microsoft.Security resource type.")
    head = low[0]
    if head == "pricings":
        return _pricings(state, method, sub, chain[1:], payload)
    if head == "defenderforstoragesettings":
        return _dfs_settings(state, method, sub, chain[1:], payload, scope_rid)
    if head == "automations":
        try:
            from core import azure_security_automations_core as auto
        except ImportError:                                    # Pyodide flat layout
            import azure_security_automations_core as auto     # type: ignore
        return auto.dispatch(state, method, sub, rg, chain[1:], payload, lambda: alert_views(state, sub))
    if head == "advancedthreatprotectionsettings" and scope_rid:
        # per-resource Defender (Cosmos DB / SQL / storage) toggle: stored on the account, single "current" setting
        rid = f"{scope_rid}/providers/{NS}/advancedThreatProtectionSettings/current"
        cur = state.get(rid.lower()) or {"id": rid, "name": "current", "type": f"{NS}/advancedThreatProtectionSettings",
                                         "properties": {"isEnabled": False}}
        if method in ("PUT", "PATCH"):
            en = ((payload or {}).get("properties") or {}).get("isEnabled")
            if not isinstance(en, bool):
                return _err(400, "BadRequest", "properties.isEnabled must be true or false.")
            cur = dict(cur, properties={"isEnabled": en})
            state[rid.lower()] = cur
            return _ok(cur)
        if method == "GET":
            return _ok(cur if len(chain) > 1 else {"value": [cur]})
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if head in ("alerts", "locations"):
        _fire_automations(state, sub)
        return _alerts(state, method, sub, rg, chain, ctx)
    if head in ("attackpaths", "cloudsecurityexplorer"):
        if not plan_on(state, sub, "CloudPosture"):
            return _err(403, "PlanNotEnabled", "Attack path analysis and the Cloud Security Explorer need the Defender CSPM plan (Microsoft.Security/pricings/CloudPosture = Standard).")
        try:
            from core import azure_attackpath_core as ap
        except ImportError:                                    # Pyodide flat layout
            import azure_attackpath_core as ap                 # type: ignore
        if head == "attackpaths" and method == "GET":
            paths = ap.attack_paths(state, sub)
            if len(chain) > 1:
                hit = next((p for p in paths if p["id"] == low[1]), None)
                return _ok(hit) if hit else _err(404, "NotFound", f"Attack path '{chain[1]}' not found.")
            return _ok({"value": paths})
        if head == "cloudsecurityexplorer" and method == "POST":
            r = ap.explore(state, sub, payload or {})
            return _err(400, "BadRequest", r["error"]) if "error" in r else _ok(r)
        return _err(405, "MethodNotAllowed", f"{NS}/{chain[0]} does not support {method}.")
    if method != "GET":
        return _err(405, "MethodNotAllowed", f"{NS}/{chain[0]} supports GET only in Vyomi.")
    if head == "assessmentmetadata":
        metas = _all_meta(state, sub)
        if len(chain) == 1:
            return _ok({"value": [_meta_view(sub, m) for m in metas]})
        m = next((m for m in metas if m["name"] == low[1]), None)
        return _ok(_meta_view(sub, m)) if m else _err(404, "NotFound", f"Assessment metadata '{chain[1]}' not found.")
    if head == "securescorecontroldefinitions":
        return _ok({"value": [_definition_view(n) for n in CONTROLS]})
    ev = evaluate(state, sub, ctx=ctx)
    assessments = ev["assessments"]
    if rg is not None:
        assessments = [a for a in assessments if f"/resourcegroups/{rg.lower()}/" in a["rid"].lower()]
    if scope_rid:
        assessments = [a for a in assessments if a["rid"].lower() == scope_rid.lower()]
    if head == "assessments":
        views = [(a, _assessment_view(state, sub, a)) for a in assessments]
        if len(chain) == 1:
            body = {"value": [v for _, v in views],
                    "vyomiKubernetesScanners": [s for s in ev["scanners"] if not scope_rid or s["clusterId"].lower() == scope_rid.lower()]}
            return _ok(body)
        hit = next(((a, v) for a, v in views if v["name"] == low[1]), None)
        if hit is None:
            return _err(404, "NotFound", f"Assessment '{chain[1]}' not found at this scope.")
        a, v = hit
        if len(chain) == 2:
            return _ok(v)
        if low[2] == "subassessments":
            subs = _sub_views(a, v["id"])
            if len(chain) == 3:
                return _ok({"value": subs})
            s = next((s for s in subs if s["name"] == low[3]), None)
            return _ok(s) if s else _err(404, "NotFound", f"Sub-assessment '{chain[3]}' not found.")
        return _err(404, "NotFound", "Unknown assessment child resource.")
    if head == "subassessments":
        out = []
        for a in assessments:
            out += _sub_views(a, _assessment_view(state, sub, a)["id"])
        return _ok({"value": out})
    if head in ("securescores", "securescorecontrols"):
        rows, smax, scur = _scores(assessments)
        expand = "definition" in str(query.get("$expand") or "").lower()
        if head == "securescorecontrols" or (len(chain) >= 3 and low[2] == "securescorecontrols"):
            return _ok({"value": [_control_view(sub, r, expand) for r in rows if r["inPlay"] or r["na"]]})
        score = {"id": f"/subscriptions/{sub}/providers/{NS}/secureScores/ascScore", "name": "ascScore",
                 "type": f"{NS}/secureScores",
                 "properties": {"displayName": "ASC score", "weight": sum(r["healthy"] + r["unhealthy"] for r in rows),
                                "score": {"max": smax, "current": scur,
                                          "percentage": round(scur / smax, 4) if smax else 0.0}}}
        if len(chain) == 1:
            return _ok({"value": [score]})
        if low[1] != "ascscore":
            return _err(404, "NotFound", f"Secure score '{chain[1]}' not found (Vyomi computes the 'ascScore' initiative).")
        return _ok(score)
    return _err(404, "ResourceTypeNotSupported", f"Type '{NS}/{chain[0]}' is not simulated.")


# ── alerts (Vyomi deterministic detector over the ARM audit feed) ─────────────────────────
AUDIT_LIMIT = sc.AUDIT_CAP


def _feed_key(sub):
    return f"/subscriptions/{sub}/providers/microsoft.security/__auditfeed__"


def audit_feed(state: dict, sub: str) -> list:
    rec = state.get(_feed_key(sub))
    if rec is None:
        rec = state[_feed_key(sub)] = {"_type": "microsoft.security/auditfeed", "_sub": sub, "events": [], "alerts": {}}
    return rec["events"]


def record_call(state: dict, sub: str, method: str, path: str, body, status: int, actor: str = "console") -> None:
    """Classify one served ARM call into the audit feed (best effort; ignores non security-relevant calls)."""
    try:
        ev = sc.classify("azure", method, path, {}, {}, json.dumps(body) if isinstance(body, dict) else body, int(status), actor=actor)
        if ev:
            sc.append(audit_feed(state, sub), ev)
    except Exception:
        pass


_ALERT_PLAN = {"malware-upload": "StorageAccounts", "storage-public": "StorageAccounts", "block-public-access-disabled": "StorageAccounts", "key-destruction": "KeyVaults"}


def threats(state: dict, sub: str) -> list:
    """Detector output, gated by Defender plans (an alert needs its workload protection plan to be Standard)."""
    out = []
    for t in sc.detect("azure", audit_feed(state, sub)):
        if plan_on(state, sub, _ALERT_PLAN.get(t["rule"], "Arm")):
            out.append(t)
    return out


def alert_views(state: dict, sub: str) -> list:
    """The Microsoft.Security/locations/alerts documents Vyomi's detector currently raises (workflow automations match on these)."""
    rec = state.get(_feed_key(sub)) or {}
    states = rec.get("alerts") or {}
    return [sc.azure_alert_view(t, sub, states.get(t["id"], "Active")) for t in threats(state, sub)]


def _fire_automations(state, sub):
    try:
        try:
            from core import azure_security_automations_core as auto
        except ImportError:                                    # Pyodide flat layout
            import azure_security_automations_core as auto     # type: ignore
        if any(isinstance(r, dict) and r.get("_type") == auto.TYPE for r in state.values()):
            auto.evaluate(state, sub, alert_views(state, sub))
    except Exception:       # an automation target never breaks reading the alerts
        pass


def _alerts(state, method, sub, rg, chain, ctx):
    low = [c.lower() for c in chain]
    rec = state.get(_feed_key(sub)) or {}
    states = (rec.get("alerts") if rec else None) or {}
    views = {}
    for t in threats(state, sub):
        v = sc.azure_alert_view(t, sub, states.get(t["id"], "Active"))
        hist = (rec.get("history") or {}).get(t["id"]) if rec else None
        if hist:
            v["properties"]["extendedProperties"]["statusHistory"] = json.dumps(hist)
        if t["id"] in ((rec.get("remediated") or {}) if rec else {}):
            v["properties"]["extendedProperties"]["remediation"] = json.dumps(rec["remediated"][t["id"]])
        views[v["name"]] = (t, v)
    # .../alerts            (subscription / resource group)         .../locations/{loc}/alerts[/{name}[/{action}]]
    if low[0] == "locations":
        if len(low) < 3 or low[2] != "alerts":
            return _err(404, "ResourceTypeNotSupported", f"Type '{NS}/{chain[0]}' is not simulated.")
        rest = chain[3:]
    else:
        rest = chain[1:]
    if rg is not None:
        views = {k: tv for k, tv in views.items() if f"/resourcegroups/{rg.lower()}/" in tv[1]["id"].lower()}
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Use GET to list alerts.")
        return _ok({"value": [v for _, v in views.values()]})
    hit = views.get(rest[0].lower())
    if hit is None:
        return _err(404, "ResourceNotFound", f"Alert '{rest[0]}' was not found.")
    t, v = hit
    if len(rest) == 1:
        return _ok(v) if method == "GET" else _err(405, "MethodNotAllowed", "Use GET, or POST dismiss / activate / resolve.")
    action = rest[1].lower()
    new = {"dismiss": "Dismissed", "activate": "Active", "resolve": "Resolved", "inprogress": "InProgress", "remediate": "Resolved"}.get(action)
    if new is None or method != "POST":
        return _err(404, "NotFound", f"Alert action '{rest[1]}' is not supported (dismiss, activate, resolve, inprogress, remediate).")
    fr = state.get(_feed_key(sub))
    if fr is None:
        audit_feed(state, sub)
        fr = state[_feed_key(sub)]
    if action == "remediate":
        done = _remediate(state, t)
        if isinstance(done, dict) and "status" in done:
            return done
        fr.setdefault("remediated", {})[t["id"]] = done
    fr.setdefault("alerts", {})[t["id"]] = new
    fr.setdefault("history", {}).setdefault(t["id"], []).append(
        {"status": new, "action": action, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return {"status": 204, "headers": {}, "body": None}


def _remediate(state, t):
    """Vyomi remediation: revert the offending change on the affected resource's state. Returns a summary dict, or an error response."""
    rule, key = t["rule"], str(t["resource"]).lower()
    rec = state.get(key)
    if rule in ("storage-public", "block-public-access-disabled"):
        if rec is None:
            return _err(409, "ResourceGone", "The affected resource no longer exists; resolve the alert instead.")
        props = rec.get("properties") if isinstance(rec.get("properties"), dict) else rec
        if "/containers/" in key:
            props["publicAccess"] = "None"
            return {"action": "set publicAccess=None", "resource": t["resource"]}
        props["allowBlobPublicAccess"] = False
        return {"action": "set allowBlobPublicAccess=false", "resource": t["resource"]}
    if rule == "network-exposed":
        if rec is None:
            return _err(409, "ResourceGone", "The affected resource no longer exists; resolve the alert instead.")
        props = rec.get("properties") if isinstance(rec.get("properties"), dict) else rec
        n = 0
        rules = props.get("securityRules")

        def bad(r):
            rp = r.get("properties", r)
            return rp.get("direction") == "Inbound" and rp.get("access") == "Allow" and str(rp.get("sourceAddressPrefix", "")) in ("*", "Internet", "0.0.0.0/0")
        if isinstance(rules, list):
            keep = [r for r in rules if not bad(r)]
            n = len(rules) - len(keep)
            props["securityRules"] = keep
        elif bad(rec):
            props["access"] = "Deny"
            n = 1
        return {"action": f"closed {n} internet-open inbound rule(s)", "resource": t["resource"]}
    if rule == "priv-escalation" and "/roleassignments/" in key:
        if state.pop(key, None) is None:
            return _err(409, "ResourceGone", "The role assignment no longer exists; resolve the alert instead.")
        return {"action": "deleted the privileged role assignment", "resource": t["resource"]}
    return _err(400, "RemediationNotAvailable", f"No automated remediation exists for '{rule}' alerts; follow the remediation steps and resolve manually.")


def _dfs_key(rid):
    return rid.lower() + "/providers/microsoft.security/defenderforstoragesettings/current"


def dfs_settings(state, rid):
    return state.get(_dfs_key(rid))


def _dfs_view(rid, rec):
    r = rec or {}
    return {"id": f"{rid}/providers/{NS}/DefenderForStorageSettings/current", "name": "current", "type": f"{NS}/DefenderForStorageSettings",
            "properties": {"isEnabled": bool(r.get("isEnabled", False)),
                           "malwareScanning": {"onUpload": {"isEnabled": bool(r.get("onUpload", False)), "capGBPerMonth": r.get("capGBPerMonth", 5000)},
                                               "scanResultsEventGridTopicResourceId": r.get("topic", ""), "operationStatus": {"code": "OK"}},
                           "sensitiveDataDiscovery": {"isEnabled": bool(r.get("sdd", False)), "operationStatus": {"code": "OK"}},
                           "overrideSubscriptionLevelSettings": bool(r.get("override", False))}}


def _dfs_settings(state, method, sub, rest, payload, scope_rid):
    if not scope_rid or "microsoft.storage/storageaccounts" not in scope_rid.lower():
        return _err(400, "InvalidResourceType", "DefenderForStorageSettings is a child of a storage account.")
    if rest and rest[0].lower() != "current":
        return _err(404, "NotFound", "The only DefenderForStorageSettings name is 'current'.")
    k = _dfs_key(scope_rid)
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Use GET/PUT .../DefenderForStorageSettings/current.")
        return _ok({"value": [_dfs_view(scope_rid, state.get(k))]})
    if method == "GET":
        return _ok(_dfs_view(scope_rid, state.get(k)))
    if method == "DELETE":
        state.pop(k, None)
        return {"status": 204, "headers": {}, "body": None}
    if method in ("PUT", "PATCH"):
        p = (payload or {}).get("properties") or {}
        cur = dict(state.get(k) or {})
        ou = ((p.get("malwareScanning") or {}).get("onUpload") or {})
        cap = ou.get("capGBPerMonth")
        if cap is not None and (not isinstance(cap, int) or cap < -1):
            return _err(400, "InvalidInputJson", "malwareScanning.onUpload.capGBPerMonth must be an integer >= -1.")
        if "isEnabled" in p:
            cur["isEnabled"] = bool(p["isEnabled"])
        if "isEnabled" in ou:
            cur["onUpload"] = bool(ou["isEnabled"])
        if cap is not None:
            cur["capGBPerMonth"] = cap
        topic = (p.get("malwareScanning") or {}).get("scanResultsEventGridTopicResourceId")
        if topic is not None:
            cur["topic"] = topic
        if "isEnabled" in (p.get("sensitiveDataDiscovery") or {}):
            cur["sdd"] = bool(p["sensitiveDataDiscovery"]["isEnabled"])
        if "overrideSubscriptionLevelSettings" in p:
            cur["override"] = bool(p["overrideSubscriptionLevelSettings"])
        if cur.get("onUpload") and not cur.get("isEnabled"):
            return _err(400, "InvalidInputJson", "malwareScanning.onUpload can only be enabled while isEnabled is true.")
        cur["_type"] = "microsoft.security/defenderforstoragesettings"
        state[k] = cur
        return _ok(_dfs_view(scope_rid, cur))
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _pricings(state, method, sub, rest, payload):
    cur = plans(state, sub)
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Use PUT .../pricings/{name}.")
        return _ok({"value": [_pricing_view(sub, n, cur.get(n)) for n, _ in PLANS]})
    name = PLAN_NAMES.get(rest[0].lower())
    if name is None:
        return _err(404, "NotFound", f"Pricing '{rest[0]}' does not exist. Plans: {', '.join(p for p, _ in PLANS)}.")
    if method == "GET":
        return _ok(_pricing_view(sub, name, cur.get(name)))
    if method in ("PUT", "PATCH"):
        props = (payload or {}).get("properties") or {}
        tier = props.get("pricingTier")
        if tier not in ("Free", "Standard"):
            return _err(400, "InvalidInputJson", "properties.pricingTier must be 'Free' or 'Standard'.")
        k = _pricing_key(sub)
        rec = state.get(k)
        if rec is None:
            rec = state[k] = {"_type": "microsoft.security/pricings", "_sub": sub, "plans": {}}
        entry = dict(rec.setdefault("plans", {}).get(name) or {})
        if tier == "Standard" and entry.get("pricingTier") != "Standard":
            entry["enablementTime"] = _now()
        entry["pricingTier"] = tier
        if props.get("subPlan"):
            if name == "StorageAccounts" and props["subPlan"] not in ("DefenderForStorageV2", "PerTransaction"):
                return _err(400, "InvalidInputJson", "properties.subPlan for StorageAccounts must be DefenderForStorageV2 or PerTransaction.")
            entry["subPlan"] = props["subPlan"]
        if name == "StorageAccounts" and props.get("extensions") is not None:
            exts = dict(entry.get("extensions") or {})
            for e in props["extensions"] or []:
                if e.get("name") not in ("OnUploadMalwareScanning", "SensitiveDataDiscovery"):
                    return _err(400, "InvalidInputJson", f"Extension '{e.get('name')}' is not supported on StorageAccounts (OnUploadMalwareScanning, SensitiveDataDiscovery).")
                en = str(e.get("isEnabled")).lower() in ("true", "1")
                extra = dict(e.get("additionalExtensionProperties") or {})
                cap = extra.get("CapGBPerMonthPerStorageAccount")
                if cap is not None and (not str(cap).lstrip("-").isdigit() or int(cap) < -1):
                    return _err(400, "InvalidInputJson", "CapGBPerMonthPerStorageAccount must be an integer >= -1 (-1 = uncapped).")
                exts[e["name"]] = {"isEnabled": en, "additionalExtensionProperties": extra}
            if tier != "Standard" and any(v["isEnabled"] for v in exts.values()):
                return _err(400, "InvalidInputJson", "Extensions can only be enabled while pricingTier is Standard.")
            entry["extensions"] = exts
        rec["plans"][name] = json.loads(json.dumps(entry))
        return _ok(_pricing_view(sub, name, entry))
    return _err(405, "MethodNotAllowed", f"{method} not allowed on pricings.")
