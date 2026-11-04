# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Security posture findings derived from the project's REAL Compute Engine / VPC firewall / Cloud Storage state.

Substrate-independent (stdlib only). This is a deterministic rule engine, not Security Command Center's
ML/threat analysis: every finding is a concrete misconfiguration read from a stored resource, with the
category names SCC's Security Health Analytics uses (PUBLIC_IP_ADDRESS, OPEN_SSH_PORT, PUBLIC_BUCKET_ACL ...).

  GET /v1/projects/{p}/securityPosture/compute   -> {findings, summary}
  GET /v1/projects/{p}/securityPosture/storage   -> {findings, summary}
"""
from __future__ import annotations

import hashlib
import json

SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
PUBLIC_MEMBERS = {"allUsers", "allAuthenticatedUsers"}
CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"
WORLD = {"0.0.0.0/0", "::/0"}


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers, self.body = status, {}, json.dumps(obj).encode()


def _f(project, category, severity, resource, description, recommendation, extra=None):
    out = {"name": "projects/%s/sources/vyomi-sha/findings/%s-%s" % (project, category.lower(), hashlib.sha1((category + resource).encode()).hexdigest()[:8]),
           "category": category, "severity": severity, "state": "ACTIVE", "resourceName": resource,
           "description": description, "recommendation": recommendation}
    if extra:
        out.update(extra)
    return out


def _meta(inst, key):
    for it in (inst.get("metadata") or {}).get("items") or []:
        if it.get("key") == key:
            return str(it.get("value", "")).upper()
    return None


def _port_covers(allowed, port):
    for a in allowed or []:
        proto = str(a.get("IPProtocol", "")).lower()
        if proto == "all":
            return True
        if proto not in ("tcp", "6"):
            continue
        ports = a.get("ports")
        if not ports:
            return True
        for p in ports:
            lo, _, hi = str(p).partition("-")
            if int(lo) <= port <= int(hi or lo):
                return True
    return False


def summarize(findings):
    by = {s: 0 for s in SEV_ORDER}
    for f in findings:
        by[f["severity"]] += 1
    return {"total": len(findings), "bySeverity": by}


def compute_findings(project, instances, firewalls):
    """instances: {full_name: instance}; firewalls: [firewall rec with networkName/allowed/sourceRanges/targetTags/..]."""
    out = []
    prefix = "projects/%s/zones/" % project
    insts = {n: i for n, i in instances.items() if n.startswith(prefix)}
    for full, i in sorted(insts.items()):
        res = "//compute.googleapis.com/" + full
        nm = i.get("name")
        if any(ac.get("natIP") for ni in i.get("networkInterfaces") or [] for ac in ni.get("accessConfigs") or []):
            out.append(_f(project, "PUBLIC_IP_ADDRESS", "HIGH", res, "Instance %s has an external IP address." % nm,
                          "Remove the external IP (access config) and use Cloud NAT / IAP for egress and administration."))
        for sa in i.get("serviceAccounts") or []:
            default = sa.get("email") == "default" or str(sa.get("email", "")).endswith("-compute@developer.gserviceaccount.com")
            if default and CLOUD_PLATFORM in (sa.get("scopes") or []):
                out.append(_f(project, "FULL_API_ACCESS", "HIGH", res, "Instance %s uses the default service account with the cloud-platform (full API access) scope." % nm,
                              "Run the instance as a dedicated least-privilege service account."))
            elif default:
                out.append(_f(project, "DEFAULT_SERVICE_ACCOUNT_USED", "MEDIUM", res, "Instance %s uses the default Compute Engine service account." % nm,
                              "Create and attach a dedicated service account with only the roles the workload needs."))
        if _meta(i, "enable-oslogin") != "TRUE":
            out.append(_f(project, "OS_LOGIN_DISABLED", "MEDIUM", res, "OS Login is not enabled on instance %s." % nm,
                          "Set metadata enable-oslogin=TRUE so SSH access is governed by IAM."))
        if _meta(i, "serial-port-enable") == "TRUE":
            out.append(_f(project, "SERIAL_PORTS_ENABLED", "MEDIUM", res, "Interactive serial port access is enabled on instance %s." % nm,
                          "Remove metadata serial-port-enable or set it to FALSE."))
        if _meta(i, "block-project-ssh-keys") != "TRUE":
            out.append(_f(project, "PROJECT_WIDE_SSH_KEYS_ALLOWED", "LOW", res, "Project-wide SSH keys can log in to instance %s." % nm,
                          "Set metadata block-project-ssh-keys=TRUE."))
        if not (i.get("shieldedInstanceConfig") or {}).get("enableSecureBoot"):
            out.append(_f(project, "SHIELDED_VM_DISABLED", "LOW", res, "Secure Boot is disabled on instance %s." % nm,
                          "Enable Secure Boot in the instance's Shielded VM settings."))
        if i.get("canIpForward"):
            out.append(_f(project, "IP_FORWARDING_ENABLED", "LOW", res, "IP forwarding is enabled on instance %s." % nm,
                          "Disable canIpForward unless the instance is a router/NVA."))
    for fw in sorted(firewalls, key=lambda r: r["name"]):
        if fw.get("project") != project or fw.get("disabled") or fw.get("direction", "INGRESS") != "INGRESS" or not fw.get("allowed"):
            continue
        if not (set(fw.get("sourceRanges") or []) & WORLD):
            continue
        res = "//compute.googleapis.com/projects/%s/global/firewalls/%s" % (project, fw["name"])
        tags = set(fw.get("targetTags") or [])
        hit = [i.get("name") for n, i in insts.items()
               if any(str(ni.get("network", "")).rstrip("/").endswith("/networks/" + fw["networkName"]) for ni in i.get("networkInterfaces") or [])
               and (not tags or tags & set((i.get("tags") or {}).get("items") or []))]
        allports = any(str(a.get("IPProtocol", "")).lower() == "all" or (not a.get("ports") and str(a.get("IPProtocol", "")).lower() in ("tcp", "udp")) for a in fw["allowed"])
        for cat, port, label in (("OPEN_SSH_PORT", 22, "SSH (22)"), ("OPEN_RDP_PORT", 3389, "RDP (3389)")):
            if _port_covers(fw["allowed"], port):
                out.append(_f(project, cat, "HIGH", res, "Firewall rule %s allows %s from the internet (0.0.0.0/0)." % (fw["name"], label),
                              "Restrict sourceRanges to known CIDRs or use IAP TCP forwarding (35.235.240.0/20).", {"affectedInstances": hit}))
        if allports:
            out.append(_f(project, "OPEN_FIREWALL", "HIGH", res, "Firewall rule %s allows all ports from the internet (0.0.0.0/0)." % fw["name"],
                          "Allow only the specific ports the workload serves.", {"affectedInstances": hit}))
    return sorted(out, key=lambda f: (SEV_ORDER.index(f["severity"]), f["category"], f["resourceName"]))


def storage_findings(project, buckets):
    """buckets: {name: bucket meta (iamConfiguration, iamPolicy, versioning, retentionPolicy, encryption, softDeletePolicy)}."""
    out = []
    for name, b in sorted(buckets.items()):
        res = "//storage.googleapis.com/" + name
        members = {m for bind in (b.get("iamPolicy") or {}).get("bindings", []) for m in bind.get("members", [])}
        iamc = b.get("iamConfiguration") or {}
        if members & PUBLIC_MEMBERS:
            out.append(_f(project, "PUBLIC_BUCKET_ACL", "CRITICAL", res, "Bucket %s grants access to %s." % (name, ", ".join(sorted(members & PUBLIC_MEMBERS))),
                          "Remove allUsers/allAuthenticatedUsers bindings and enforce public access prevention."))
        if not (iamc.get("uniformBucketLevelAccess") or {}).get("enabled"):
            out.append(_f(project, "BUCKET_POLICY_ONLY_DISABLED", "MEDIUM", res, "Uniform bucket-level access is disabled on bucket %s, so object ACLs can bypass IAM." % name,
                          "Enable uniform bucket-level access."))
        if iamc.get("publicAccessPrevention") != "enforced":
            out.append(_f(project, "PUBLIC_ACCESS_PREVENTION_NOT_ENFORCED", "LOW", res, "Public access prevention is not enforced on bucket %s." % name,
                          "Set publicAccessPrevention to enforced."))
        if not (b.get("versioning") or {}).get("enabled") and not b.get("retentionPolicy"):
            out.append(_f(project, "BUCKET_VERSIONING_DISABLED", "LOW", res, "Bucket %s has neither object versioning nor a retention policy." % name,
                          "Enable object versioning or set a retention policy."))
        if not (b.get("encryption") or {}).get("defaultKmsKeyName"):
            out.append(_f(project, "BUCKET_CMEK_DISABLED", "LOW", res, "Bucket %s is encrypted with Google-managed keys, not a customer-managed key." % name,
                          "Set a default Cloud KMS key on the bucket if CMEK is required."))
    return sorted(out, key=lambda f: (SEV_ORDER.index(f["severity"]), f["category"], f["resourceName"]))


def dispatch(vm_store, fw_store, obj_store, method, path):
    # /v1/projects/{p}/securityPosture/{kind}
    segs = path.split("?", 1)[0].strip("/").split("/")
    if len(segs) != 5 or segs[0] != "v1" or segs[1] != "projects" or segs[3] != "securityPosture" or segs[4] not in ("compute", "storage"):
        return Resp(404, {"error": {"code": 404, "message": "Unknown path: %s" % path, "status": "NOT_FOUND"}})
    if method.upper() != "GET":
        return Resp(405, {"error": {"code": 405, "message": "Method not allowed.", "status": "UNIMPLEMENTED"}})
    project = segs[2]
    if segs[4] == "compute":
        f = compute_findings(project, vm_store.instances, list(fw_store.firewalls.values()))
    else:
        f = storage_findings(project, obj_store.buckets)
    return Resp(200, {"findings": f, "summary": summarize(f)})
