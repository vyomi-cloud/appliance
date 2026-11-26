"""Organization Policy Service (orgpolicy.googleapis.com v2): constraint catalog, policy inheritance over the resource hierarchy,
effective policy, dry-run, and the request gate that enforces the constraints Vyomi has a hook for.

Pure stdlib; operates on the Resource Manager store (core/gcp_resourcemanager_core.ResourceManagerStore: projects, folders,
organizations, org_policies) so it loads under Pyodide (Nano) and on Mesh.

Policy document (v2): {"name": "<parent>/policies/<constraint>", "spec": {...}, "dryRunSpec": {...}, "etag"}
  spec = {"rules": [{"enforce": bool} | {"allowAll": true} | {"denyAll": true} | {"values": {"allowedValues": [...], "deniedValues": [...]}}],
          "inheritFromParent": bool, "reset": bool, "etag", "updateTime"}
Constraint ids are accepted as "iam.x" and "constraints/iam.x" (the store keeps whichever form the caller used; lookups try both).

Inheritance (documented behaviour, evaluated top-down org -> folders -> project):
  * no policy on a node            -> the node inherits its parent's effective policy;
  * `reset: true`                  -> parent policies are ignored, the constraint's default applies;
  * boolean constraints            -> the nearest policy decides (booleans never merge);
  * list constraints               -> `inheritFromParent: false` replaces the parent's policy; `true` merges: allowed and denied
                                      value sets are unioned, `allowAll`/`denyAll` from the child win over the parent's.
Conditional rules (`condition.expression`, tag based) are stored and returned but NOT evaluated: only unconditional rules apply.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ constraint catalog
# name, kind (boolean|list), constraintDefault, displayName, description, service, hook (engine enforcement in Vyomi)
_C = [
    ("iam.disableServiceAccountCreation", "boolean", "Disable service account creation", "When enforced, service accounts cannot be created in the affected projects.", "iam", "iam"),
    ("iam.disableServiceAccountKeyCreation", "boolean", "Disable service account key creation", "When enforced, user-managed service account keys cannot be created.", "iam", "iam"),
    ("iam.disableServiceAccountKeyUpload", "boolean", "Disable service account key upload", "When enforced, uploading external public keys to service accounts is blocked.", "iam", ""),
    ("iam.automaticIamGrantsForDefaultServiceAccounts", "boolean", "Disable automatic IAM grants for default service accounts", "When enforced, default service accounts are not granted the Editor role on creation.", "iam", ""),
    ("iam.disableCrossProjectServiceAccountUsage", "boolean", "Disable cross-project service account usage", "When enforced, service accounts cannot be attached to resources in other projects.", "iam", ""),
    ("iam.allowedPolicyMemberDomains", "list", "Domain restricted sharing", "Restricts which principals (by Cloud Identity / Workspace customer ID) can be granted IAM roles.", "iam", ""),
    ("iam.workloadIdentityPoolProviders", "list", "Allow external identity providers for workloads", "Restricts which external identity provider URLs can be used by workload identity pools.", "iam", ""),
    ("iam.workloadIdentityPoolAwsAccounts", "list", "Allow AWS accounts for workloads", "Restricts which AWS account IDs can be used by workload identity pools.", "iam", ""),
    ("storage.uniformBucketLevelAccess", "boolean", "Enforce uniform bucket-level access", "When enforced, new buckets must use uniform bucket-level access (no object ACLs).", "storage", "gcs"),
    ("storage.publicAccessPrevention", "boolean", "Enforce public access prevention", "When enforced, new buckets have public access prevention enforced.", "storage", "gcs"),
    ("storage.secureHttpTransport", "boolean", "Restrict unencrypted HTTP access", "When enforced, requests to Cloud Storage over plain HTTP are denied.", "storage", ""),
    ("storage.restrictAuthTypes", "list", "Restrict authentication types", "Restricts the authentication types (e.g. USER_ACCOUNT_HMAC_SIGNED_REQUESTS) accepted by Cloud Storage.", "storage", ""),
    ("gcp.resourceLocations", "list", "Google Cloud Platform - Resource Location Restriction", "Restricts the locations (regions, multi-regions, value groups such as in:us-locations) where location-based resources can be created.", "gcp", "gcs"),
    ("gcp.restrictServiceUsage", "list", "Restrict resource service usage", "Restricts which services can be used by resources in the affected projects.", "gcp", ""),
    ("gcp.restrictCmekCryptoKeyProjects", "list", "Restrict which projects may supply KMS CryptoKeys for CMEK", "Restricts the projects that can provide customer-managed encryption keys.", "gcp", ""),
    ("gcp.restrictNonCmekServices", "list", "Restrict which services may create resources without CMEK", "Services listed here must use customer-managed encryption keys.", "gcp", ""),
    ("gcp.detailedAuditLoggingMode", "boolean", "Detailed audit logging mode", "When enforced, audit logs include the request and response for supported services.", "gcp", ""),
    ("compute.disableSerialPortAccess", "boolean", "Disable VM serial port access", "When enforced, interactive serial port access to VMs is disabled.", "compute", ""),
    ("compute.disableSerialPortLogging", "boolean", "Disable VM serial port logging to Stackdriver", "When enforced, serial port output is not written to Cloud Logging.", "compute", ""),
    ("compute.requireOsLogin", "boolean", "Require OS Login", "When enforced, new projects have OS Login enabled by default.", "compute", ""),
    ("compute.requireShieldedVm", "boolean", "Shielded VMs", "When enforced, Compute Engine VMs must use Shielded VM images.", "compute", ""),
    ("compute.skipDefaultNetworkCreation", "boolean", "Skip default network creation", "When enforced, the default VPC network and its firewall rules are not created in new projects.", "compute", ""),
    ("compute.disableNestedVirtualization", "boolean", "Disable VM nested virtualization", "When enforced, nested virtualization is disabled for Compute Engine VMs.", "compute", ""),
    ("compute.disableGuestAttributesAccess", "boolean", "Disable guest attributes of Compute Engine metadata", "When enforced, applications cannot query guest attributes.", "compute", ""),
    ("compute.disableVpcExternalIpv6", "boolean", "Disable VPC external IPv6 usage", "When enforced, subnets cannot be configured with external IPv6.", "compute", ""),
    ("compute.vmExternalIpAccess", "list", "Define allowed external IPs for VM instances", "Defines the VM instances (by full resource name) allowed to use external IP addresses. Default: all denied when a policy exists.", "compute", ""),
    ("compute.vmCanIpForward", "list", "Define allowed VM instances for IP forwarding", "Defines the VM instances that can enable IP forwarding.", "compute", ""),
    ("compute.trustedImageProjects", "list", "Define trusted image projects", "Restricts the projects whose images can be used to create disks and instances.", "compute", ""),
    ("compute.restrictSharedVpcHostProjects", "list", "Restrict shared VPC host projects", "Restricts the host projects that service projects can attach to.", "compute", ""),
    ("compute.restrictSharedVpcSubnetworks", "list", "Restrict shared VPC subnetworks", "Restricts the subnetworks that resources in a service project can use.", "compute", ""),
    ("compute.restrictLoadBalancerCreationForTypes", "list", "Restrict load balancer creation for types", "Restricts the load balancer types that can be created.", "compute", ""),
    ("compute.restrictProtocolForwardingCreationForTypes", "list", "Restrict protocol forwarding based on type of IP address", "Restricts forwarding rules by IP type (INTERNAL, EXTERNAL).", "compute", ""),
    ("compute.restrictVpnPeerIPs", "list", "Restrict VPN peer IPs", "Restricts the VPN peer IP addresses that Cloud VPN tunnels can connect to.", "compute", ""),
    ("sql.restrictPublicIp", "boolean", "Restrict public IP access on Cloud SQL instances", "When enforced, Cloud SQL instances cannot have public IP addresses.", "sql", ""),
    ("sql.restrictAuthorizedNetworks", "boolean", "Restrict authorized networks on Cloud SQL instances", "When enforced, authorized networks cannot be added to Cloud SQL instances.", "sql", ""),
    ("run.allowedIngress", "list", "Allowed ingress settings (Cloud Run)", "Restricts the ingress settings Cloud Run services can use (all, internal, internal-and-cloud-load-balancing).", "run", ""),
    ("run.allowedVPCEgress", "list", "Allowed VPC egress settings (Cloud Run)", "Restricts the VPC egress settings Cloud Run services can use.", "run", ""),
    ("run.requireInvokerIam", "boolean", "Require IAM invoker check for Cloud Run services", "When enforced, Cloud Run services must require the IAM invoker permission.", "run", ""),
    ("cloudfunctions.allowedIngressSettings", "list", "Allowed ingress settings (Cloud Functions)", "Restricts the ingress settings Cloud Functions can use.", "cloudfunctions", ""),
    ("cloudfunctions.requireVPCConnector", "boolean", "Require VPC Connector (Cloud Functions)", "When enforced, Cloud Functions must use a Serverless VPC Access connector.", "cloudfunctions", ""),
    ("essentialcontacts.allowedContactDomains", "list", "Domain restricted contacts", "Restricts the email domains that can be set as Essential Contacts.", "essentialcontacts", ""),
    ("cloudbuild.allowedIntegrations", "list", "Allowed integrations (Cloud Build)", "Restricts the external integrations Cloud Build can use.", "cloudbuild", ""),
    ("ainotebooks.restrictPublicIp", "boolean", "Restrict public IP access on new Vertex AI Workbench notebooks and instances", "When enforced, new Workbench instances cannot have public IPs.", "ainotebooks", ""),
    ("ainotebooks.accessMode", "list", "Restrict Vertex AI Workbench access mode", "Restricts the access modes (single-user, service-account) for Workbench instances.", "ainotebooks", ""),
    ("container.restrictNoncompliantDiagnosticDataAccess", "boolean", "Restrict non-compliant diagnostic data access", "When enforced, GKE diagnostic data collection follows the restricted policy.", "container", ""),
    ("bigquery.disableBQOmniAWS", "boolean", "Disable BigQuery Omni AWS", "When enforced, BigQuery Omni on AWS cannot be used.", "bigquery", ""),
]
CATALOG = {n: {"name": "constraints/" + n, "displayName": d, "description": desc, "constraintDefault": "ALLOW",
               ("booleanConstraint" if k == "boolean" else "listConstraint"): ({} if k == "boolean" else {"supportsUnder": True, "supportsIn": True}),
               "supportsDryRun": True, "supportsSimulation": k == "boolean",
               "vyomi": {"service": svc, "enforcedBy": hook or None, "kind": k}}
           for n, k, d, desc, svc, hook in _C}
# list constraints whose default (no policy) is DENY ALL values in the real service
for _n in ("compute.vmExternalIpAccess", "compute.vmCanIpForward"):
    CATALOG[_n]["constraintDefault"] = "ALLOW"


def cid(c):
    return str(c or "").replace("constraints/", "", 1)


def list_constraints(parent=""):
    return [dict(v) for _, v in sorted(CATALOG.items())]


def get_constraint(c):
    return CATALOG.get(cid(c))


# ------------------------------------------------------------------ hierarchy
def _pstr(p):
    if isinstance(p, dict):
        t, i = p.get("type"), p.get("id")
        return ("organizations/" if t == "organization" else "folders/") + str(i)
    return str(p or "")


def _find_project(store, ref):
    ref = str(ref)
    if ref in store.projects:
        return store.projects[ref]
    for p in store.projects.values():
        if str(p.get("name", "")).endswith("/" + ref) or p.get("projectId") == ref:
            return p
    return None


def chain(store, node):
    """[node, parent, ..., organization] as 'projects/<id>' | 'folders/N' | 'organizations/N' (nearest first)."""
    node = str(node)
    out, seen = [], set()
    if node.startswith("projects/"):
        p = _find_project(store, node.split("/", 1)[1])
        out.append("projects/" + (p["projectId"] if p else node.split("/", 1)[1]))
        node = _pstr(p.get("parent")) if p else ""
    while node and node not in seen:
        seen.add(node)
        out.append(node)
        if node.startswith("folders/"):
            f = store.folders.get(node)
            node = _pstr(f.get("parent")) if f else ""
        else:
            break
    if out and not out[-1].startswith("organizations/") and store.organizations:
        out.append(sorted(store.organizations)[0])      # an orphan chain hangs off the (single) organization
    return out


def _policy(store, node, constraint):
    pols = store.org_policies
    for suffix in ("constraints/" + cid(constraint), cid(constraint)):
        p = pols.get(f"{node}/policies/{suffix}")
        if p is not None:
            return p
    if node.startswith("projects/"):                       # stored under the project number
        pr = _find_project(store, node.split("/", 1)[1])
        if pr:
            num = str(pr.get("name", "")).split("/")[-1]
            for suffix in ("constraints/" + cid(constraint), cid(constraint)):
                p = pols.get(f"projects/{num}/policies/{suffix}")
                if p is not None:
                    return p
    return None


def _rules(spec):
    return [r for r in ((spec or {}).get("rules") or []) if not r.get("condition")]       # conditional rules: stored, not evaluated


def _merge_list(parent, spec):
    """parent: effective {"allowAll","denyAll","allowed","denied"} ; spec: this node's spec -> new effective."""
    cur = {"allowAll": False, "denyAll": False, "allowed": [], "denied": []}
    for r in _rules(spec):
        if r.get("allowAll"):
            cur["allowAll"] = True
        if r.get("denyAll"):
            cur["denyAll"] = True
        v = r.get("values") or {}
        cur["allowed"] += list(v.get("allowedValues") or [])
        cur["denied"] += list(v.get("deniedValues") or [])
    if parent is not None and (spec or {}).get("inheritFromParent"):
        cur = {"allowAll": cur["allowAll"] or (parent["allowAll"] and not cur["denyAll"] and not cur["allowed"]),
               "denyAll": cur["denyAll"] or (parent["denyAll"] and not cur["allowAll"] and not cur["allowed"]),
               "allowed": sorted(set(parent["allowed"]) | set(cur["allowed"])),
               "denied": sorted(set(parent["denied"]) | set(cur["denied"]))}
    cur["allowed"], cur["denied"] = sorted(set(cur["allowed"])), sorted(set(cur["denied"]))
    return cur


def effective(store, node, constraint, dry_run=False):
    """-> {"constraint", "kind", "source": node whose policy decides (or None = default), "enforce"|(allowAll,denyAll,allowed,denied),
    "path": [{"node","has_policy","reset","inheritFromParent"}...] (root first), "default": bool}"""
    c = get_constraint(constraint)
    kind = (c or {}).get("vyomi", {}).get("kind") or ("boolean" if _is_bool_name(constraint) else "list")
    nodes = list(reversed(chain(store, node)))                 # root first
    state, source, path = None, None, []
    for n in nodes:
        pol = _policy(store, n, constraint)
        spec = (pol or {}).get("dryRunSpec" if dry_run else "spec") if pol else None
        if dry_run and pol and not spec:
            spec = (pol or {}).get("spec")                       # a dry run changes only the nodes that carry a dryRunSpec
        path.append({"node": n, "hasPolicy": bool(spec), "reset": bool((spec or {}).get("reset")), "inheritFromParent": bool((spec or {}).get("inheritFromParent"))})
        if not spec:
            continue
        if spec.get("reset"):
            state, source = None, None
            continue
        if kind == "boolean":
            rs = _rules(spec)
            state = {"enforce": any(bool(r.get("enforce")) for r in rs) if rs else False}
        else:
            state = _merge_list(state, spec)
        source = n
    out = {"constraint": "constraints/" + cid(constraint), "kind": kind, "source": source, "path": path, "default": state is None}
    if kind == "boolean":
        out["enforce"] = bool((state or {}).get("enforce", False))
    else:
        s = state or {"allowAll": False, "denyAll": False, "allowed": [], "denied": []}
        out.update(allowAll=s["allowAll"], denyAll=s["denyAll"], allowedValues=s["allowed"], deniedValues=s["denied"])
    return out


def _is_bool_name(c):
    return bool(get_constraint(c) and "booleanConstraint" in get_constraint(c))


def effective_policy_doc(store, node, constraint):
    """The GetEffectivePolicy answer: a Policy with the merged spec."""
    e = effective(store, node, constraint)
    spec = {"updateTime": None}
    if e["kind"] == "boolean":
        spec["rules"] = [{"enforce": e["enforce"]}] if not e["default"] else []
    else:
        rules = []
        if e["allowAll"]:
            rules.append({"allowAll": True})
        if e["denyAll"]:
            rules.append({"denyAll": True})
        if e["allowedValues"] or e["deniedValues"]:
            rules.append({"values": {k: v for k, v in (("allowedValues", e["allowedValues"]), ("deniedValues", e["deniedValues"])) if v}})
        spec["rules"] = rules
    spec.pop("updateTime")
    return {"name": f"{node}/policies/{cid(constraint)}", "spec": spec}


# ------------------------------------------------------------------ evaluation of a value
def value_matches(pattern, value, store=None, node=None):
    """Org Policy value syntax: exact, `is:x`, `under:folders/N` / `under:organizations/N` / `under:projects/p` (hierarchy), `in:group` value groups."""
    pattern, value = str(pattern), str(value)
    if pattern.startswith("is:"):
        pattern = pattern[3:]
    if pattern.startswith("under:"):
        target = pattern[6:]
        return value == target or (store is not None and target in chain(store, value))
    if pattern.startswith("in:"):
        group = _VALUE_GROUPS.get(pattern[3:])
        return bool(group) and any(value_matches(g, value) for g in group)
    return pattern == value or (pattern.endswith("*") and value.startswith(pattern[:-1]))


_VALUE_GROUPS = {   # a subset of Google's value groups (resource locations)
    "us-locations": ["us", "us-central1", "us-east1", "us-east4", "us-east5", "us-south1", "us-west1", "us-west2", "us-west3", "us-west4"],
    "eu-locations": ["eu", "europe-central2", "europe-north1", "europe-southwest1", "europe-west1", "europe-west2", "europe-west3", "europe-west4", "europe-west6", "europe-west8", "europe-west9", "europe-west10", "europe-west12"],
    "asia-locations": ["asia", "asia-east1", "asia-east2", "asia-northeast1", "asia-northeast2", "asia-northeast3", "asia-south1", "asia-south2", "asia-southeast1", "asia-southeast2"],
}


def allows(store, node, constraint, value, dry_run=False):
    """List constraint: is `value` permitted at `node`? -> (bool, reason)."""
    e = effective(store, node, constraint, dry_run)
    if e["kind"] != "list":
        return True, "boolean constraint"
    if e["default"]:
        return True, "no policy: constraint default (ALLOW)"
    if any(value_matches(p, value, store, node) for p in e["deniedValues"]):
        return False, "value is in deniedValues"
    if e["denyAll"]:
        return False, "denyAll"
    if e["allowAll"]:
        return True, "allowAll"
    if e["allowedValues"]:
        ok = any(value_matches(p, value, store, node) for p in e["allowedValues"])
        return ok, "value is in allowedValues" if ok else "value is not in allowedValues"
    return True, "no allowed values listed"


def enforced(store, node, constraint, dry_run=False):
    return bool(effective(store, node, constraint, dry_run).get("enforce"))


# ------------------------------------------------------------------ the dry-run report
def check(store, node, constraint, value=None):
    """What the policy does to one operation at `node`: real (spec) vs dry run (dryRunSpec). Used by the console 'dry run' panel."""
    kind = effective(store, node, constraint)["kind"]
    real, dry = effective(store, node, constraint), effective(store, node, constraint, dry_run=True)
    if kind == "boolean":
        return {"constraint": real["constraint"], "kind": kind, "wouldBlock": real["enforce"], "dryRunWouldBlock": dry["enforce"],
                "real": real, "dryRun": dry}
    ok, why = allows(store, node, constraint, value)
    dok, dwhy = allows(store, node, constraint, value, True)
    return {"constraint": real["constraint"], "kind": kind, "value": value, "wouldBlock": not ok, "reason": why,
            "dryRunWouldBlock": not dok, "dryRunReason": dwhy, "real": real, "dryRun": dry}


# ------------------------------------------------------------------ request gate (engine enforcement)
class Violation(Exception):
    def __init__(self, constraint, node, what):
        super().__init__(what)
        self.constraint, self.node, self.what = "constraints/" + cid(constraint), node, what

    def message(self):
        return f"Constraint {self.constraint} violated for [orgpolicy:{self.node}]: {self.what}"


_BUCKET_CREATE = re.compile(r"^/storage/v1/b/?$")


def request_gate(store, method, path, query=None, body=None):
    """Called by the Mesh router / Nano router before a GCP request is dispatched. -> None, or a Violation. Hooks (the `enforcedBy`
    entries of the catalog): GCS bucket creation (gcp.resourceLocations, storage.uniformBucketLevelAccess, storage.publicAccessPrevention)."""
    if store is None or str(method).upper() != "POST":
        return None
    p = str(path).split("?", 1)[0]
    if not _BUCKET_CREATE.match(p):
        return None
    q = query or {}
    project = str(q.get("project") or (body or {}).get("project") or "")
    if not project:
        return None
    node = "projects/" + project
    loc = str((body or {}).get("location") or "US")
    ok, why = allows(store, node, "gcp.resourceLocations", loc.lower())
    if not ok:
        raise Violation("gcp.resourceLocations", node, f"attempting to create a bucket in location '{loc}' ({why}).")
    iam = (body or {}).get("iamConfiguration") or {}
    ubla = bool((iam.get("uniformBucketLevelAccess") or iam.get("bucketPolicyOnly") or {}).get("enabled"))
    if enforced(store, node, "storage.uniformBucketLevelAccess") and not ubla:
        raise Violation("storage.uniformBucketLevelAccess", node, "bucket creation requires uniform bucket-level access to be enabled.")
    if enforced(store, node, "storage.publicAccessPrevention") and iam.get("publicAccessPrevention") not in ("enforced",):
        raise Violation("storage.publicAccessPrevention", node, "bucket creation requires publicAccessPrevention to be 'enforced'.")
    return None


def violation_response(v):
    import json
    msg = v.message()
    return {"status": 412, "headers": {"content-type": "application/json; charset=UTF-8"},
            "body": json.dumps({"error": {"code": 412, "message": msg, "status": "FAILED_PRECONDITION",
                                          "errors": [{"message": msg, "domain": "global", "reason": "conditionNotMet"}]}}).encode()}
