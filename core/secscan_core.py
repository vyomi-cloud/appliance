"""Security scanning + threat detection engine shared by AWS Security Hub / GuardDuty, Azure Defender for
Cloud alerts and GCP Security Command Center (substrate-free, stdlib only — loads under Pyodide).

Three honest layers, all derived from REAL simulated state, nothing is a canned feed:

  1. Posture findings   rule engines over stored resources (buckets, security groups, instances, databases,
                        IAM users, trails ...) — `aws_posture_findings` (Security Hub / FSBP controls and
                        Inspector-style network reachability), plus the Azure/GCP engines that already exist
                        (core/azure_security_core.py, core/gcp_posture_core.py) which this module only re-shapes.
  2. Vulnerability      images pushed to the simulator's registries are scanned by core/vuln_scan_core.py
                        (curated advisory snapshot, or the real Trivy container on the offline appliance).
  3. Runtime detection  Vyomi runs no attacker and no real workload telemetry, so "threat detection" is a
                        DETERMINISTIC rule engine over the simulator's own control-plane audit feed (every API
                        call the simulator serves, classified into semantic tags by `classify`). The same inputs
                        always give the same alerts; the rules are Vyomi's (not Microsoft's / Google's / AWS's
                        machine-learning models) and each finding says so (`detector: vyomi-rules`).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid

ACCOUNT = "123456789012"
REGION = "us-east-1"
AUDIT_CAP = 600
SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
SEV_NORM = {"CRITICAL": 90, "HIGH": 70, "MEDIUM": 40, "LOW": 1, "INFORMATIONAL": 0}
CONSOLE_ACTORS = ("console", "anonymous", "")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ts(s: str) -> float:
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _h(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


# ═════════════════════════════ 1. control-plane audit feed ═════════════════════════════
def new_event(cloud, actor, service, action, resource, status, tags, detail="", ts=None) -> dict:
    return {"id": uuid.uuid4().hex[:16], "ts": ts or _now(), "cloud": cloud, "actor": actor or "console", "service": service,
            "action": action, "resource": resource, "status": int(status), "tags": list(tags), "detail": detail}


def append(feed: list, ev: dict) -> None:
    feed.append(ev)
    if len(feed) > AUDIT_CAP:
        del feed[: len(feed) - AUDIT_CAP]


_PORTS_RISKY = {"22", "3389", "*", "0-65535", "-1"}


def _json(body):
    try:
        v = json.loads(body) if body else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _public_policy(doc: dict) -> bool:
    for st in doc.get("Statement") or []:
        if st.get("Effect") != "Allow":
            continue
        pr = st.get("Principal")
        if pr == "*" or (isinstance(pr, dict) and (pr.get("AWS") == "*" or "*" in (pr.get("AWS") if isinstance(pr.get("AWS"), list) else []))):
            return True
    return False


def classify(cloud: str, method: str, path: str, query: dict | None, headers: dict | None, body: bytes | str | None,
             status: int, svc: str = "", action: str = "", actor: str = "console") -> dict | None:
    """One served API call -> an audit event with semantic tags, or None when it is not security relevant.
    Pure function of its inputs (no clock except the event timestamp)."""
    method = (method or "GET").upper()
    q = {k: v for k, v in (query or {}).items()}
    if isinstance(body, str):
        body = body.encode()
    text = (body or b"").decode("utf-8", "replace")
    low = (path or "").lower()
    tags: list[str] = []
    resource, act, detail = path, action or method, ""
    ok = status < 400
    if cloud == "aws":
        hdr = {k.lower(): v for k, v in (headers or {}).items()}
        form = dict(re.findall(r"([A-Za-z0-9.]+)=([^&]*)", text)) if "=" in text and not text.lstrip().startswith("{") else {}
        act = action or form.get("Action") or (hdr.get("x-amz-target", "").rsplit(".", 1)[-1]) or method
        if svc == "s3" and method in ("PUT", "DELETE"):
            bucket = (path or "").strip("/").split("/")[0]
            resource = f"arn:aws:s3:::{bucket}"
            if "policy" in q and method == "PUT" and ok:
                act = "PutBucketPolicy"
                if _public_policy(_json(body)):
                    tags.append("storage-public"); detail = "Bucket policy grants access to Principal '*'"
            elif "acl" in q and method == "PUT" and ok:
                act = "PutBucketAcl"
                if "AllUsers" in text or hdr.get("x-amz-acl", "").startswith("public-read"):
                    tags.append("storage-public"); detail = "Bucket ACL grants access to AllUsers"
            elif "publicaccessblock" in {k.lower() for k in q}:
                act = "DeletePublicAccessBlock" if method == "DELETE" else "PutPublicAccessBlock"
                if ok and (method == "DELETE" or "<BlockPublicPolicy>false" in text.replace(" ", "")):
                    tags.append("block-public-access-disabled"); detail = "S3 Block Public Access was relaxed on the bucket"
        elif svc == "cloudtrail" and act in ("StopLogging", "DeleteTrail") and ok:
            tags.append("audit-log-disabled"); detail = f"CloudTrail {act}"
            resource = str(_json(body).get("Name") or _json(body).get("TrailName") or "trail")
        elif svc == "iam" and ok:
            if act in ("AttachUserPolicy", "AttachRolePolicy", "AttachGroupPolicy") and "AdministratorAccess" in text:
                tags.append("priv-escalation"); detail = "AdministratorAccess managed policy attached"
            elif act in ("PutUserPolicy", "PutRolePolicy", "PutGroupPolicy") and re.search(r'"Action"\s*:\s*"\*"|%22Action%22%3A%22\*%22', text):
                tags.append("priv-escalation"); detail = "Inline policy allows Action '*'"
            elif act in ("CreateAccessKey", "CreateLoginProfile", "CreateUser"):
                tags.append("credential-created"); detail = act
            resource = form.get("UserName") or form.get("RoleName") or "iam"
        elif svc in ("vpc", "ec2") and act == "AuthorizeSecurityGroupIngress" and ok:
            cidr = form.get("CidrIp") or form.get("IpPermissions.1.IpRanges.1.CidrIp") or ""
            port = form.get("FromPort") or form.get("IpPermissions.1.FromPort") or "*"
            if cidr in ("0.0.0.0/0", "::/0") and port in _PORTS_RISKY | {"-1"}:
                tags.append("network-exposed"); detail = f"Security group ingress {port} open to {cidr}"
            resource = form.get("GroupId") or "security-group"
        elif svc == "rds" and act in ("ModifyDBInstance", "CreateDBInstance") and ok and form.get("PubliclyAccessible", "").lower() == "true":
            tags.append("network-exposed"); detail = "DB instance made publicly accessible"; resource = form.get("DBInstanceIdentifier", "db")
        elif svc == "kms" and act in ("ScheduleKeyDeletion", "DisableKey") and ok:
            tags.append("key-destruction"); detail = act; resource = str(_json(body).get("KeyId", "key"))
        elif svc == "secretsmanager" and act == "DeleteSecret" and ok and _json(body).get("ForceDeleteWithoutRecovery"):
            tags.append("key-destruction"); detail = "Secret deleted without a recovery window"; resource = str(_json(body).get("SecretId", "secret"))
        if status in (401, 403) and actor not in CONSOLE_ACTORS:
            tags.append("auth-failure")
        if not tags and actor not in CONSOLE_ACTORS and method in ("GET", "POST") and re.match(r"(List|Describe|Get)", act or ""):
            tags.append("recon-read")
        if not tags:
            return None
        return new_event("aws", actor, svc, act, resource, status, tags, detail)
    if cloud == "azure":
        rid = (path or "").split("?", 1)[0]
        props = (_json(body).get("properties") or {}) if method in ("PUT", "PATCH", "POST") else {}
        resource, act = rid, f"{method} {rid.rsplit('/providers/', 1)[-1].split('/', 1)[0] if '/providers/' in rid else rid}"
        if method in ("PUT", "PATCH") and ok:
            if "/microsoft.storage/storageaccounts/" in low and "/containers/" not in low and props.get("allowBlobPublicAccess") is True:
                tags.append("storage-public"); detail = "allowBlobPublicAccess enabled on the storage account"
            elif "/containers/" in low and str(props.get("publicAccess", "None")) in ("Blob", "Container"):
                tags.append("storage-public"); detail = f"Container public access level set to {props['publicAccess']}"
            elif "/providers/microsoft.authorization/roleassignments/" in low and re.search(r"8e3af657-a8ff-443c-a75c-2fe8c4bcb635|18d7d88d-d35e-4fb5-a5c3-7773c20a72d9", str(props.get("roleDefinitionId", ""))):
                tags.append("priv-escalation"); detail = "Owner / User Access Administrator role assigned"
            elif "/securityrules/" in low or "/microsoft.network/networksecuritygroups/" in low:
                rules = [props] if "/securityrules/" in low else list(props.get("securityRules") or [])
                for r in rules:
                    rp = r.get("properties", r)
                    if str(rp.get("direction", "")) == "Inbound" and rp.get("access") == "Allow" and str(rp.get("sourceAddressPrefix", "")) in ("*", "Internet", "0.0.0.0/0") \
                            and str(rp.get("destinationPortRange", "")) in _PORTS_RISKY | {"22-22", "3389-3389"}:
                        tags.append("network-exposed"); detail = f"NSG rule allows {rp.get('destinationPortRange')} from the internet"; break
        elif method == "DELETE" and ok and "/providers/microsoft.insights/diagnosticsettings/" in low:
            tags.append("audit-log-disabled"); detail = "A diagnostic setting was deleted"
        elif method == "POST" and ok and low.endswith("/purge") and "/deletedvaults/" in low:
            tags.append("key-destruction"); detail = "A soft-deleted Key Vault was purged"
        elif method == "POST" and ok and ("/listkeys" in low or "/listaccountsas" in low) and "/microsoft.storage/" in low:
            tags.append("credential-read"); detail = "Storage account keys listed"
        if status in (401, 403) and actor not in CONSOLE_ACTORS:
            tags.append("auth-failure")
        return new_event("azure", actor, "arm", act, resource, status, tags, detail) if tags else None
    if cloud == "gcp":
        p = low.split("?", 1)[0]
        doc = _json(body)
        act = action or f"{method} {p}"
        if ok and (p.endswith(":setiampolicy") or (method in ("PUT", "POST") and p.endswith("/iam"))):
            members = {m for b in (doc.get("policy") or doc).get("bindings", []) for m in b.get("members", [])}
            roles = {b.get("role") for b in (doc.get("policy") or doc).get("bindings", [])}
            if members & {"allUsers", "allAuthenticatedUsers"}:
                tags.append("storage-public" if "/b/" in p or "storage" in p else "priv-escalation"); detail = "IAM policy grants access to allUsers/allAuthenticatedUsers"
            elif roles & {"roles/owner", "roles/editor"}:
                tags.append("priv-escalation"); detail = "Owner/Editor role granted"
        elif ok and method == "DELETE" and "/sinks/" in p:
            tags.append("audit-log-disabled"); detail = "A log sink was deleted"
        elif ok and method == "POST" and p.endswith("/global/firewalls"):
            if "0.0.0.0/0" in (doc.get("sourceRanges") or []) and doc.get("direction", "INGRESS") == "INGRESS" and any(
                    a.get("IPProtocol") == "all" or any(str(x) in ("22", "3389") for x in a.get("ports", [])) for a in doc.get("allowed", [])):
                tags.append("network-exposed"); detail = "Firewall rule opens SSH/RDP/all ports to 0.0.0.0/0"
        elif ok and method == "POST" and p.endswith(":destroy") and "cryptokeyversions" in p:
            tags.append("key-destruction"); detail = "A KMS key version was scheduled for destruction"
        elif ok and method == "POST" and p.endswith("/keys") and "/serviceaccounts/" in p:
            tags.append("credential-created"); detail = "A service account key was created"
        if status in (401, 403) and actor not in CONSOLE_ACTORS:
            tags.append("auth-failure")
        return new_event("gcp", actor, svc or "gcp", act, p, status, tags, detail) if tags else None
    return None


# ═════════════════════════════ 2. deterministic runtime detector ═════════════════════════════
# rule -> (severity, per-cloud type, per-cloud title, description)
RULES = {
    "audit-log-disabled": ("HIGH", {"aws": "Stealth:IAMUser/CloudTrailLoggingDisabled", "azure": "VYOMI_ARM_AUDIT_LOGGING_DISABLED", "gcp": "AUDIT_LOGGING_DISABLED"},
                           "Audit logging was disabled", "Control-plane audit logging was switched off, which hides later activity."),
    "storage-public": ("HIGH", {"aws": "Policy:S3/BucketAnonymousAccessGranted", "azure": "VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED", "gcp": "PUBLIC_BUCKET_ACL_GRANTED"},
                       "Storage was opened to anonymous access", "Data in a storage bucket/container became readable without authentication."),
    "block-public-access-disabled": ("MEDIUM", {"aws": "Policy:S3/BucketBlockPublicAccessDisabled", "azure": "VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED", "gcp": "PUBLIC_ACCESS_PREVENTION_REMOVED"},
                                     "Block Public Access was relaxed", "The guard rail that prevents public bucket policies was removed."),
    "priv-escalation": ("MEDIUM", {"aws": "PrivilegeEscalation:IAMUser/AdministrativePermissions", "azure": "VYOMI_ARM_PRIVILEGED_ROLE_ASSIGNED", "gcp": "PRIVILEGED_ROLE_GRANTED"},
                        "Administrative permissions were granted", "An identity received administrator-level permissions."),
    "network-exposed": ("HIGH", {"aws": "Policy:EC2/NetworkExposureChanged", "azure": "VYOMI_ARM_MANAGEMENT_PORT_EXPOSED", "gcp": "OPEN_FIREWALL_CREATED"},
                        "A network path was opened to the internet", "A security group / NSG / firewall now admits traffic from 0.0.0.0/0 to a sensitive port."),
    "key-destruction": ("HIGH", {"aws": "Impact:KMS/KeyDestructionRequested", "azure": "VYOMI_KEYVAULT_PURGED", "gcp": "KMS_KEY_DESTRUCTION_SCHEDULED"},
                        "A key or secret was destroyed", "Cryptographic material was scheduled for deletion or purged."),
    "credential-persistence": ("MEDIUM", {"aws": "Persistence:IAMUser/UserPermissions", "azure": "VYOMI_ARM_CREDENTIAL_PERSISTENCE", "gcp": "SERVICE_ACCOUNT_KEY_CREATED"},
                               "Credentials were created for persistence", "Several credentials were minted in a short window."),
    "auth-failure-burst": ("MEDIUM", {"aws": "Recon:IAMUser/ResourcePermissions", "azure": "VYOMI_SUSPICIOUS_AUTHENTICATION", "gcp": "REPEATED_PERMISSION_DENIED"},
                           "Repeated authorization failures", "One identity was denied repeatedly, consistent with permission probing."),
    "recon-burst": ("LOW", {"aws": "Discovery:IAMUser/AnomalousBehavior", "azure": "VYOMI_ARM_DISCOVERY_BURST", "gcp": "DISCOVERY_BURST"},
                    "Burst of enumeration calls", "One identity listed/described many resources across several services within two minutes."),
}
WINDOWS = {"auth-failure-burst": (5, 300), "recon-burst": (15, 120), "credential-persistence": (2, 600)}
PLAN_OF_RULE = {"storage-public": "StorageAccounts", "block-public-access-disabled": "StorageAccounts", "key-destruction": "KeyVaults"}   # Azure default: Arm


def detect(cloud: str, events: list) -> list:
    """Deterministic: events (oldest first) -> threat dicts. Same input, same output (ids are content hashes)."""
    out: dict[str, dict] = {}

    def add(rule, resource, actor, evs, extra=""):
        sev, types, title, desc = RULES[rule]
        key = _h(cloud, rule, resource, actor)
        t = out.get(key)
        if t is None:
            t = out[key] = {"id": key, "rule": rule, "cloud": cloud, "type": types[cloud], "severity": sev, "title": title,
                            "description": (extra or desc), "resource": resource, "actor": actor, "firstSeen": evs[0]["ts"],
                            "lastSeen": evs[-1]["ts"], "count": 0, "eventIds": [], "detector": "vyomi-rules"}
        t["count"] += len(evs)
        t["lastSeen"] = max(t["lastSeen"], evs[-1]["ts"])
        t["eventIds"] += [e["id"] for e in evs][:20]

    evs = [e for e in events if e.get("cloud") == cloud]
    for e in evs:
        for tag in e["tags"]:
            if tag in RULES and tag not in WINDOWS:
                add(tag, e["resource"], e["actor"], [e], e["detail"])
    for rule, tag, svcs in (("auth-failure-burst", "auth-failure", 1), ("recon-burst", "recon-read", 3)):
        need, win = WINDOWS[rule]
        by: dict[str, list] = {}
        for e in evs:
            if tag in e["tags"]:
                by.setdefault(e["actor"], []).append(e)
        for actor, lst in by.items():
            for i in range(len(lst)):
                w = [x for x in lst[i:] if _ts(x["ts"]) - _ts(lst[i]["ts"]) <= win]
                if len(w) >= need and len({x["service"] for x in w}) >= svcs:
                    add(rule, f"identity:{actor}", actor, w)
                    break
    need, win = WINDOWS["credential-persistence"]
    by = {}
    for e in evs:
        if "credential-created" in e["tags"] or "priv-escalation" in e["tags"]:
            by.setdefault(e["actor"], []).append(e)
    for actor, lst in by.items():
        for i in range(len(lst)):
            w = [x for x in lst[i:] if _ts(x["ts"]) - _ts(lst[i]["ts"]) <= win]
            if len(w) >= need and any("credential-created" in x["tags"] for x in w) and len({x["resource"] for x in w}) >= 1 \
                    and sum("credential-created" in x["tags"] for x in w) >= need:
                add("credential-persistence", f"identity:{actor}", actor, w)
                break
    return sorted(out.values(), key=lambda t: (SEV_ORDER.index(t["severity"]), t["firstSeen"], t["id"]))


# ═════════════════════════════ 3. AWS posture (Security Hub FSBP + Inspector-style) ═════════════════════════════
def aws_collect(s3=None, vpc_model=None, rds=None, iam=None, trails=0, lam=None) -> dict:
    """Plain inventory from the stores (every access defensive: a store a substrate lacks is simply absent)."""
    inv: dict = {"buckets": {}, "sgs": [], "instances": [], "dbs": [], "users": [], "trails": trails, "lambdas": []}
    for name, meta in sorted((getattr(s3, "buckets", None) or {}).items()):
        cfg = (meta or {}).get("cfg") or {}
        pol = {}
        try:
            pol = json.loads(cfg["policy"]) if cfg.get("policy") else {}
        except Exception:
            pass
        inv["buckets"][name] = {"policy_public": _public_policy(pol), "pab": cfg.get("publicAccessBlock"),
                                "encrypted": bool(cfg.get("encryption")), "versioning": (meta or {}).get("versioning", "Disabled")}
    if isinstance(vpc_model, dict):
        for sg in vpc_model.get("sgs", {}).values():
            inv["sgs"].append({"id": sg.get("id"), "name": sg.get("name"), "vpc": sg.get("vpc_id"), "ingress": list(sg.get("ingress") or [])})
        for i in vpc_model.get("instances", {}).values():
            if i.get("state") not in ("terminated", "shutting-down"):
                inv["instances"].append({"id": i.get("id"), "public_ip": i.get("public_ip") or "", "sg_ids": list(i.get("sg_ids") or []),
                                         "state": i.get("state")})
    try:
        for dbid in rds.instance_ids():
            d = rds.get_instance(dbid)
            inv["dbs"].append({"id": dbid, "public": bool(d.get("publicly_accessible")), "encrypted": bool(d.get("storage_encrypted") or d.get("encrypted"))})
    except Exception:
        pass
    for n, u in sorted((getattr(iam, "users", None) or {}).items()):
        has_pw = bool(u.get("login_profile") or u.get("password_enabled") or u.get("LoginProfile"))
        mfa = any(d.get("user_name") == n for d in (getattr(iam, "virtual_mfa_devices", None) or {}).values())
        inv["users"].append({"name": n, "console": has_pw, "mfa": mfa})
    for fn in (getattr(lam, "_lambda_functions", None) or {}).values() if lam is not None else []:
        if isinstance(fn, dict):
            inv["lambdas"].append({"name": fn.get("FunctionName") or fn.get("name"), "runtime": fn.get("Runtime") or fn.get("runtime") or ""})
    return inv


def _sg_world(sg, ports) -> str | None:
    for r in sg["ingress"]:
        cidrs = r.get("cidrs") or []
        if not ({"0.0.0.0/0", "::/0"} & set(cidrs)):
            continue
        proto, lo, hi = str(r.get("protocol", "")), int(r.get("from_port", 0) or 0), int(r.get("to_port", 0) or 0)
        if proto in ("-1", "all"):
            return "all traffic"
        for p in ports:
            if proto in ("tcp", "6") and lo <= p <= hi:
                return f"port {p}"
    return None


def aws_posture_findings(inv: dict, image_scans: list | None = None, today: datetime.date | None = None) -> list:
    """Normalised rows {product, control, title, severity, resource{type,id}, description, remediation, compliance}."""
    out = []

    def row(product, control, title, sev, rtype, rid, desc, rem, compliance="FAILED", types=None):
        out.append({"product": product, "control": control, "title": title, "severity": sev, "rtype": rtype, "rid": rid,
                    "description": desc, "remediation": rem, "compliance": compliance,
                    "types": types or ["Software and Configuration Checks/Industry and Regulatory Standards/AWS-Foundational-Security-Best-Practices"]})

    for n, b in inv["buckets"].items():
        arn = f"arn:aws:s3:::{n}"
        if b["policy_public"]:
            row("securityhub", "S3.2", "S3 buckets should prohibit public read access", "CRITICAL", "AwsS3Bucket", arn,
                f"Bucket {n} has a policy that allows access to Principal '*'.", "Remove the public statement and enable S3 Block Public Access.")
        pab = str(b["pab"] or "")
        if not pab or "false" in pab.lower():
            row("securityhub", "S3.8", "S3 general purpose buckets should block public access", "HIGH", "AwsS3Bucket", arn,
                f"Block Public Access is not fully enabled on bucket {n}.", "Enable all four Block Public Access settings.")
        if not b["encrypted"]:
            row("securityhub", "S3.4", "S3 buckets should have server-side encryption enabled", "MEDIUM", "AwsS3Bucket", arn,
                f"Bucket {n} has no explicit default-encryption configuration.", "Set a default SSE-S3 or SSE-KMS configuration.")
    by_id = {i["id"]: i for i in inv["instances"]}
    for sg in inv["sgs"]:
        arn = f"arn:aws:ec2:{REGION}:{ACCOUNT}:security-group/{sg['id']}"
        for ctl, port, label in (("EC2.13", 22, "SSH"), ("EC2.14", 3389, "RDP")):
            hit = _sg_world(sg, [port])
            if hit:
                row("securityhub", ctl, f"Security groups should not allow ingress from 0.0.0.0/0 to port {port}", "HIGH", "AwsEc2SecurityGroup", arn,
                    f"Security group {sg['name']} ({sg['id']}) allows {label} ({hit}) from the internet.", f"Restrict the source CIDR of the {label} rule.")
        for iid, i in by_id.items():
            if sg["id"] in i["sg_ids"] and i["public_ip"]:
                hit = _sg_world(sg, [22, 3389, 80, 443])
                if hit:
                    row("inspector", "NETWORK_REACHABILITY", f"Instance {iid} is reachable from the internet ({hit})", "HIGH" if hit != "port 80" else "MEDIUM",
                        "AwsEc2Instance", f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{iid}",
                        f"Instance {iid} has public IP {i['public_ip']} and security group {sg['id']} admits {hit} from 0.0.0.0/0.",
                        "Remove the public IP or narrow the security group.", types=["Software and Configuration Checks/AWS Inspector"])
    for i in inv["instances"]:
        if i["public_ip"]:
            row("securityhub", "EC2.9", "EC2 instances should not have a public IPv4 address", "HIGH", "AwsEc2Instance",
                f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{i['id']}", f"Instance {i['id']} has public IPv4 address {i['public_ip']}.", "Use a private subnet and a load balancer / NAT.")
    for d in inv["dbs"]:
        arn = f"arn:aws:rds:{REGION}:{ACCOUNT}:db:{d['id']}"
        if d["public"]:
            row("securityhub", "RDS.2", "RDS DB instances should prohibit public access", "CRITICAL", "AwsRdsDbInstance", arn,
                f"DB instance {d['id']} is publicly accessible.", "Modify the instance with PubliclyAccessible=false.")
        if not d["encrypted"]:
            row("securityhub", "RDS.3", "RDS DB instances should have encryption at rest enabled", "MEDIUM", "AwsRdsDbInstance", arn,
                f"DB instance {d['id']} storage is not encrypted.", "Create an encrypted copy from a snapshot.")
    for u in inv["users"]:
        if u["console"] and not u["mfa"]:
            row("securityhub", "IAM.5", "MFA should be enabled for all IAM users that have a console password", "MEDIUM", "AwsIamUser",
                f"arn:aws:iam::{ACCOUNT}:user/{u['name']}", f"IAM user {u['name']} can sign in to the console without MFA.", "Assign a virtual MFA device.")
    if not inv["trails"]:
        row("securityhub", "CloudTrail.1", "CloudTrail should be enabled and configured with at least one multi-Region trail", "HIGH", "AwsAccount",
            f"AWS::::Account:{ACCOUNT}", "No CloudTrail trail exists in the account.", "Create a multi-Region trail with CreateTrail + StartLogging.")
    try:
        from core import vuln_scan_core as vs
    except ImportError:
        import vuln_scan_core as vs                                    # type: ignore
    for fn in inv["lambdas"]:
        m = re.match(r"(python|nodejs)(\d+(?:\.\d+)?)", fn["runtime"] or "")
        if m:
            prod = "python" if m.group(1) == "python" else "node"
            ver = m.group(2)
            for cycle, date in vs.EOL.get(prod, []):
                if (ver == cycle or ver.startswith(cycle + ".") or (prod == "node" and ver.split(".")[0] == cycle)) and \
                        datetime.date.fromisoformat(date) < (today or datetime.date.today()):
                    row("inspector", "LAMBDA_RUNTIME_EOL", f"Lambda function {fn['name']} uses an end-of-life runtime ({fn['runtime']})", "MEDIUM", "AwsLambdaFunction",
                        f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{fn['name']}", f"{prod} {cycle} reached end of life on {date}.", "Upgrade the function runtime.",
                        types=["Software and Configuration Checks/Vulnerabilities/CVE"])
    for sc in image_scans or []:
        for f in sc["scan"]["findings"]:
            row("inspector", f["vulnerabilityId"], f"{f['vulnerabilityId']} - {f['package']} {f['installedVersion']}", f["severity"], "AwsEcrContainerImage", sc["resource"],
                f"{f['title']}. Fixed in {f['fixedVersion']}.", f"Upgrade {f['package']} to {f['fixedVersion']} or later.",
                types=["Software and Configuration Checks/Vulnerabilities/CVE"])
    return out


def asff(row: dict, state: dict | None = None, now: str | None = None) -> dict:
    """A posture row -> an AWS Security Finding Format document."""
    state = state or {}
    fid = _h("asff", row["product"], row["control"], row["rid"])
    arn_id = f"arn:aws:securityhub:{REGION}:{ACCOUNT}:" + ("subscription/aws-foundational-security-best-practices/v/1.0.0/" + row["control"] + "/finding/" + fid
                                                           if row["product"] == "securityhub" else f"{row['product']}/finding/{fid}")
    now = now or _now()
    return {"SchemaVersion": "2018-10-08", "Id": arn_id,
            "ProductArn": f"arn:aws:securityhub:{REGION}::product/aws/{row['product']}",
            "ProductName": {"securityhub": "Security Hub", "inspector": "Inspector", "guardduty": "GuardDuty"}[row["product"]],
            "CompanyName": "AWS", "Region": REGION,
            "GeneratorId": ("aws-foundational-security-best-practices/v/1.0.0/" + row["control"]) if row["product"] == "securityhub" else f"aws/{row['product']}/{row['control']}",
            "AwsAccountId": ACCOUNT, "Types": row["types"], "FirstObservedAt": state.get("first", now), "CreatedAt": state.get("first", now),
            "UpdatedAt": now, "Severity": {"Label": row["severity"], "Normalized": SEV_NORM[row["severity"]], "Original": row["severity"]},
            "Title": row["title"], "Description": row["description"],
            "Remediation": {"Recommendation": {"Text": row["remediation"], "Url": f"https://docs.aws.amazon.com/securityhub/latest/userguide/{row['control'].split('.')[0].lower()}-controls.html"}},
            "ProductFields": {"Vyomi/detector": "vyomi-rules" if row["product"] != "inspector" else "vuln_scan_core", "ControlId": row["control"]},
            "Resources": [{"Type": row["rtype"], "Id": row["rid"], "Partition": "aws", "Region": REGION}],
            "Compliance": {"Status": row["compliance"]},
            "WorkflowState": "NEW", "Workflow": {"Status": state.get("status", "NEW")}, "RecordState": "ACTIVE"}


def threat_asff(t: dict) -> dict:
    row = {"product": "guardduty", "control": t["type"], "title": t["title"], "severity": t["severity"], "rtype": "Other", "rid": t["resource"],
           "description": t["description"], "remediation": "Review the activity and revert the change if it was not intended.", "compliance": "FAILED",
           "types": ["TTPs/" + t["type"].split("/")[0]]}
    d = asff(row, {"first": t["firstSeen"]})
    d["Id"] = f"arn:aws:guardduty:{REGION}:{ACCOUNT}:detector/vyomi/finding/{t['id']}"
    return d


# ═════════════════════════════ 4. Security Hub + GuardDuty wire (rest-json) ═════════════════════════════
class _Err(Exception):
    def __init__(self, code, msg, status=400):
        self.code, self.msg, self.status = code, msg, status


class Resp:
    def __init__(self, status, doc, headers=None):
        self.status, self.headers = status, dict(headers or {})
        self.body = json.dumps(doc).encode() if doc is not None else b""
        self.media_type = "application/json"


def _state(bag: dict) -> dict:
    s = bag.setdefault("secscan", {})
    s.setdefault("audit", [])
    s.setdefault("hub", {"enabled": False, "enabledAt": None, "standards": [], "workflow": {}})
    s.setdefault("gd", {"detectors": {}, "archived": {}, "samples": {}})
    return s


def _cmp(val, c) -> bool:
    cv, op = str(c.get("Value", "")), c.get("Comparison", "EQUALS")
    v = str(val)
    return {"EQUALS": v == cv, "NOT_EQUALS": v != cv, "PREFIX": v.startswith(cv), "PREFIX_NOT_EQUALS": not v.startswith(cv),
            "CONTAINS": cv in v, "NOT_CONTAINS": cv not in v}.get(op, False)


_FILTER_FIELDS = {"SeverityLabel": lambda f: f["Severity"]["Label"], "ProductName": lambda f: f["ProductName"], "Title": lambda f: f["Title"],
                  "ResourceType": lambda f: f["Resources"][0]["Type"], "ResourceId": lambda f: f["Resources"][0]["Id"],
                  "ComplianceStatus": lambda f: f["Compliance"]["Status"], "WorkflowStatus": lambda f: f["Workflow"]["Status"],
                  "RecordState": lambda f: f["RecordState"], "GeneratorId": lambda f: f["GeneratorId"], "Id": lambda f: f["Id"],
                  "ProductArn": lambda f: f["ProductArn"]}


def hub_findings(bag: dict, posture_rows: list, threats: list) -> list:
    st = _state(bag)
    docs = [asff(r) for r in posture_rows]
    docs += [threat_asff(t) for t in threats if st["gd"]["detectors"]]          # GuardDuty findings flow in once a detector exists
    seen = st["hub"].setdefault("seen", {})
    for d in docs:
        first = seen.setdefault(d["Id"], d["CreatedAt"])
        d["FirstObservedAt"] = d["CreatedAt"] = first
        w = st["hub"]["workflow"].get(d["Id"])
        if w:
            d["Workflow"]["Status"] = w.get("status", "NEW")
            d["Note"] = w.get("note")
    return docs


def hub_dispatch(bag: dict, method: str, path: str, body: bytes, posture_rows: list, threats: list) -> Resp:
    st = _state(bag)
    hub = st["hub"]
    path = path.split("?", 1)[0].rstrip("/") or "/"
    p = _json(body)
    try:
        if path == "/accounts" and method == "POST":
            if hub["enabled"]:
                raise _Err("ResourceConflictException", "Account is already subscribed to Security Hub", 409)
            hub.update(enabled=True, enabledAt=_now(),
                       standards=[{"StandardsArn": f"arn:aws:securityhub:{REGION}::standards/aws-foundational-security-best-practices/v/1.0.0", "StandardsStatus": "READY"}] if p.get("EnableDefaultStandards", True) else [])
            return Resp(200, {})
        if path == "/accounts" and method == "GET":
            if not hub["enabled"]:
                raise _Err("InvalidAccessException", f"Account {ACCOUNT} is not subscribed to AWS Security Hub", 401)
            return Resp(200, {"HubArn": f"arn:aws:securityhub:{REGION}:{ACCOUNT}:hub/default", "SubscribedAt": hub["enabledAt"], "AutoEnableControls": True,
                              "ControlFindingGenerator": "SECURITY_CONTROL"})
        if path == "/accounts" and method == "DELETE":
            if not hub["enabled"]:
                raise _Err("InvalidAccessException", f"Account {ACCOUNT} is not subscribed to AWS Security Hub", 401)
            hub.update(enabled=False, enabledAt=None, standards=[])
            return Resp(200, {})
        if not hub["enabled"]:
            raise _Err("InvalidAccessException", f"Account {ACCOUNT} is not subscribed to AWS Security Hub", 401)
        if path == "/standards/get" and method == "POST":
            return Resp(200, {"StandardsSubscriptions": [dict(s, StandardsSubscriptionArn=s["StandardsArn"].replace(":standards/", f":subscription/").replace(f"::subscription", f":{ACCOUNT}:subscription")) for s in hub["standards"]]})
        if path == "/findings" and method == "POST":
            docs = hub_findings(bag, posture_rows, threats)
            for f, conds in (p.get("Filters") or {}).items():
                fn = _FILTER_FIELDS.get(f)
                if fn is None:
                    raise _Err("InvalidInputException", f"Unsupported filter field {f}")
                docs = [d for d in docs if any(_cmp(fn(d), c) for c in conds)] if not any(c.get("Comparison", "").startswith("NOT") for c in conds) \
                    else [d for d in docs if all(_cmp(fn(d), c) for c in conds)]
            for sc in reversed(p.get("SortCriteria") or [{"Field": "SeverityLabel", "SortOrder": "desc"}]):
                if sc.get("Field") == "SeverityLabel":
                    docs.sort(key=lambda d: SEV_ORDER.index(d["Severity"]["Label"]), reverse=sc.get("SortOrder") == "asc")
            mr = int(p.get("MaxResults") or 100)
            if not 1 <= mr <= 100:
                raise _Err("InvalidInputException", "MaxResults must be between 1 and 100")
            start = int(p.get("NextToken") or 0)
            out = {"Findings": docs[start:start + mr]}
            if start + mr < len(docs):
                out["NextToken"] = str(start + mr)
            return Resp(200, out)
        if path == "/findings/batchupdate" and method == "PATCH" or path == "/findings/batchupdate" and method == "POST":
            ids = p.get("FindingIdentifiers") or []
            if not ids:
                raise _Err("InvalidInputException", "FindingIdentifiers is required")
            known = {d["Id"] for d in hub_findings(bag, posture_rows, threats)}
            ok, bad = [], []
            for fi in ids:
                if fi.get("Id") in known:
                    hub["workflow"][fi["Id"]] = {"status": (p.get("Workflow") or {}).get("Status", "NEW"), "note": (p.get("Note") or {}).get("Text")}
                    ok.append(fi)
                else:
                    bad.append({"Id": fi.get("Id"), "ProductArn": fi.get("ProductArn"), "ErrorCode": "FindingNotFound", "ErrorMessage": "Finding not found"})
            return Resp(200, {"ProcessedFindings": ok, "UnprocessedFindings": bad})
        if path == "/findings/stats" and method == "POST":
            docs = hub_findings(bag, posture_rows, threats)
            return Resp(200, {"BySeverity": {l: sum(d["Severity"]["Label"] == l for d in docs) for l in SEV_ORDER}, "Total": len(docs)})
    except _Err as e:
        return Resp(e.status, {"Code": e.code, "Message": e.msg}, {"x-amzn-errortype": e.code})
    return Resp(404, {"Code": "ResourceNotFoundException", "Message": f"Unknown Security Hub operation: {method} {path}"})


GD_SAMPLE_TYPES = {"UnauthorizedAccess:EC2/SSHBruteForce": ("MEDIUM", "EC2"), "Policy:S3/BucketAnonymousAccessGranted": ("HIGH", "S3"),
                   "Recon:IAMUser/ResourcePermissions": ("MEDIUM", "IAM"), "Stealth:IAMUser/CloudTrailLoggingDisabled": ("HIGH", "IAM")}
GD_SEV = {"CRITICAL": 9.0, "HIGH": 8.0, "MEDIUM": 5.0, "LOW": 2.0, "INFORMATIONAL": 1.0}


def gd_finding(t: dict, det_id: str, archived=False, sample=False) -> dict:
    return {"AccountId": ACCOUNT, "Arn": f"arn:aws:guardduty:{REGION}:{ACCOUNT}:detector/{det_id}/finding/{t['id']}", "CreatedAt": t["firstSeen"],
            "Description": t["description"], "Id": t["id"], "Partition": "aws", "Region": REGION, "SchemaVersion": "2.0",
            "Resource": {"ResourceType": "AccessKey" if t["actor"] not in CONSOLE_ACTORS else "Other", "AccessKeyDetails": {"UserName": t["actor"]}},
            "Service": {"Action": {"ActionType": "AWS_API_CALL", "AwsApiCallAction": {"Api": t["rule"], "ServiceName": "vyomi", "CallerType": "Remote IP"}},
                        "Archived": archived, "Count": t["count"], "DetectorId": det_id, "EventFirstSeen": t["firstSeen"], "EventLastSeen": t["lastSeen"],
                        "ResourceRole": "TARGET", "ServiceName": "guardduty",
                        "AdditionalInfo": {"Type": "default", "Value": json.dumps({"detector": "vyomi-rules", "affectedResource": t["resource"], "sample": sample})}},
            "Severity": GD_SEV[t["severity"]], "Title": t["title"], "Type": t["type"], "UpdatedAt": t["lastSeen"]}


def gd_dispatch(bag: dict, method: str, path: str, body: bytes, threats: list) -> Resp:
    st = _state(bag)["gd"]
    segs = [s for s in path.split("?", 1)[0].split("/") if s]
    p = _json(body)
    try:
        if segs == ["detector"] and method == "POST":
            if st["detectors"]:
                raise _Err("BadRequestException", "The request is rejected because a detector already exists for the current account.")
            did = uuid.uuid5(uuid.NAMESPACE_DNS, f"vyomi-gd-{ACCOUNT}").hex
            st["detectors"][did] = {"createdAt": _now(), "status": "ENABLED" if p.get("Enable", True) else "DISABLED",
                                    "findingPublishingFrequency": p.get("FindingPublishingFrequency", "SIX_HOURS")}
            return Resp(200, {"DetectorId": did})
        if segs == ["detector"] and method == "GET":
            return Resp(200, {"DetectorIds": list(st["detectors"])})
        if len(segs) >= 2 and segs[0] == "detector":
            did = segs[1]
            det = st["detectors"].get(did)
            if det is None:
                raise _Err("BadRequestException", "The request is rejected because the input detectorId is not owned by the current account.")
            if len(segs) == 2 and method == "GET":
                return Resp(200, {"CreatedAt": det["createdAt"], "FindingPublishingFrequency": det["findingPublishingFrequency"], "ServiceRole": f"arn:aws:iam::{ACCOUNT}:role/aws-service-role/guardduty.amazonaws.com/AWSServiceRoleForAmazonGuardDuty",
                                  "Status": det["status"], "UpdatedAt": det["createdAt"], "Tags": {}})
            if len(segs) == 2 and method == "POST":
                det["status"] = "ENABLED" if p.get("Enable", det["status"] == "ENABLED") else "DISABLED"
                return Resp(200, {})
            if len(segs) == 2 and method == "DELETE":
                st["detectors"].pop(did)
                return Resp(200, {})
            live = threats if det["status"] == "ENABLED" else []
            allf = [gd_finding(t, did, st["archived"].get(t["id"], False)) for t in live] + [gd_finding(t, did, st["archived"].get(t["id"], False), True) for t in st["samples"].values()]
            if segs[2:] == ["findings"] and method == "POST":
                crit = (p.get("FindingCriteria") or {}).get("Criterion") or {}
                for f, c in crit.items():
                    if f == "severity":
                        lo = c.get("Gte", c.get("GreaterThanOrEqual", 0))
                        allf = [x for x in allf if x["Severity"] >= lo]
                    elif f == "type":
                        allf = [x for x in allf if x["Type"] in (c.get("Eq") or [x["Type"]])]
                    elif f == "service.archived":
                        want = "true" in [str(v).lower() for v in c.get("Eq", [])]
                        allf = [x for x in allf if x["Service"]["Archived"] == want]
                return Resp(200, {"FindingIds": [x["Id"] for x in allf]})
            if segs[2:] == ["findings", "get"] and method == "POST":
                ids = set(p.get("FindingIds") or [])
                return Resp(200, {"Findings": [x for x in allf if x["Id"] in ids]})
            if segs[2:] == ["findings", "archive"] and method == "POST":
                for i in p.get("FindingIds") or []:
                    st["archived"][i] = True
                return Resp(200, {})
            if segs[2:] == ["findings", "unarchive"] and method == "POST":
                for i in p.get("FindingIds") or []:
                    st["archived"].pop(i, None)
                return Resp(200, {})
            if segs[2:] == ["findings", "create"] and method == "POST":
                for ft in p.get("FindingTypes") or list(GD_SAMPLE_TYPES):
                    if ft not in GD_SAMPLE_TYPES:
                        raise _Err("BadRequestException", f"The request is rejected because the finding type {ft} is not supported for sample findings.")
                    sev = GD_SAMPLE_TYPES[ft][0]
                    t = {"id": _h("sample", ft), "rule": "sample", "cloud": "aws", "type": ft, "severity": sev, "title": f"[SAMPLE] {ft}",
                         "description": "This is a sample finding generated by CreateSampleFindings.", "resource": "sample", "actor": "sample",
                         "firstSeen": _now(), "lastSeen": _now(), "count": 1, "eventIds": []}
                    st["samples"][t["id"]] = t
                return Resp(200, {})
            if segs[2:] == ["findings", "statistics"] and method == "POST":
                return Resp(200, {"FindingStatistics": {"CountBySeverity": {str(int(x["Severity"])): 1 for x in allf}}})
    except _Err as e:
        return Resp(e.status, {"__type": e.code, "Message": e.msg}, {"x-amzn-errortype": e.code})
    return Resp(404, {"__type": "NotFoundException", "Message": f"Unknown GuardDuty operation: {method} {path}"})


# ═════════════════════════════ 5. Azure / GCP shapes ═════════════════════════════
AZ_SEV = {"CRITICAL": "High", "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low", "INFORMATIONAL": "Informational"}


def azure_alert_view(t: dict, sub: str, status: str = "Active", location: str = "centralus") -> dict:
    rid = t["resource"] if str(t["resource"]).startswith("/subscriptions/") else f"/subscriptions/{sub}"
    rg = re.split(r"/resourcegroups/", rid, flags=re.I)[1].split("/", 1)[0] if "/resourcegroups/" in rid.lower() else "vyomi-rg"
    name = str(uuid.uuid5(uuid.NAMESPACE_URL, t["id"]))
    return {"id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Security/locations/{location}/alerts/{name}", "name": name,
            "type": "Microsoft.Security/Locations/alerts",
            "properties": {"version": "2022-01-01", "vendorName": "Vyomi", "productName": "Microsoft Defender for Cloud (Vyomi rule engine)",
                           "alertType": t["type"], "systemAlertId": name, "alertDisplayName": t["title"], "description": t["description"],
                           "severity": AZ_SEV[t["severity"]], "intent": "Unknown", "status": status, "isIncident": False,
                           "startTimeUtc": t["firstSeen"], "endTimeUtc": t["lastSeen"], "timeGeneratedUtc": t["lastSeen"],
                           "compromisedEntity": t["resource"], "remediationSteps": ["Review the change in the Activity log and revert it if it was not intended."],
                           "resourceIdentifiers": [{"type": "AzureResource", "azureResourceId": rid}],
                           "entities": [{"type": "account", "name": t["actor"]}], "extendedProperties": {"detector": "vyomi-rules", "eventCount": str(t["count"])}}}


def scc_finding_view(project: str, category: str, severity: str, resource: str, desc: str, source: str, state="ACTIVE", extra=None) -> dict:
    fid = _h("scc", category, resource)
    d = {"name": f"projects/{project}/sources/{source}/findings/{fid}", "parent": f"projects/{project}/sources/{source}", "resourceName": resource,
         "state": state, "category": category, "severity": severity if severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "LOW",
         "description": desc, "mute": "UNDEFINED", "findingClass": {"vulnerability": "VULNERABILITY", "threat": "THREAT"}.get(source, "MISCONFIGURATION")}
    if extra:
        d.update(extra)
    return d
