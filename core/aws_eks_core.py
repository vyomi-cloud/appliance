"""Amazon EKS control plane (service ``eks``, SigV4 signing name ``eks``, rest-json) over a REAL Kubernetes (k3s) API server.

Speaks the native EKS REST/JSON wire, so an unmodified ``aws eks ...`` / boto3 ``eks`` client works:

  clusters         POST /clusters, GET /clusters, GET|DELETE /clusters/{name}, POST /clusters/{name}/updates (UpdateClusterVersion),
                   POST /clusters/{name}/update-config (UpdateClusterConfig), GET /cluster-versions
  updates          GET /clusters/{name}/updates, GET /clusters/{name}/updates/{id}   (DescribeUpdate / ListUpdates, also for node groups + add-ons)
  node groups      POST|GET /clusters/{n}/node-groups, GET|DELETE .../{ng}, POST .../{ng}/update-config, POST .../{ng}/update-version
  Fargate profiles POST|GET /clusters/{n}/fargate-profiles, GET|DELETE .../{fp}
  add-ons          POST|GET /clusters/{n}/addons, GET|DELETE .../{a}, PATCH .../{a}/update, GET /addons/supported-versions,
                   GET /addons/configuration-schemas
  access entries   POST|GET /clusters/{n}/access-entries, GET|POST|DELETE .../{principalArn}, POST|GET .../{principalArn}/access-policies,
                   DELETE .../{principalArn}/access-policies/{policyArn}, GET /access-policies
  OIDC providers   POST /clusters/{n}/identity-provider-configs/{associate|disassociate|describe}, GET .../identity-provider-configs
  tags             GET|POST|DELETE /tags/{resourceArn}
  Vyomi extension  POST /clusters/{n}/vyomi/kubectl   (the console's kubectl terminal / AWS Backup for EKS; EKS has no API to run kubectl)

What is REAL: ``CreateCluster`` starts a real k3s control plane through ``kube_state_core.CLUSTER_RUNTIME`` (core/k3s_runtime.py, offline appliance /
mesh with ``VYOMI_K8S_BACKEND=k3s``); the cluster is CREATING until the API server answers /readyz, then ACTIVE with the real ``endpoint`` and
``certificateAuthority.data`` of that server. Managed node groups launch real k3s agent nodes labelled ``eks.amazonaws.com/nodegroup`` (core/aws_eks_nodes.py).
Without that runtime (Nano, plain dev server) ``CreateCluster`` answers a native ``ServiceUnavailableException`` that says so -- nothing is faked.

Limits that stay honest (also in core/capabilities/aws/eks.json): the k3s image is the single pinned release regardless of the requested ``version``;
Fargate profiles, most managed add-ons (vpc-cni, EBS CSI ...), OIDC provider configs and ``logging`` are accepted and stored but run nothing;
access entries are enforced by core/aws_eks_auth.py only once the platform layer wires its TokenReview webhook into the k3s apiserver; the OIDC issuer is
a Vyomi URL whose discovery document is not served; the k3s server node also schedules workloads.

State: ``s3_store.account["eks"]`` (JSON-safe, persisted with the rest of the account bag). No fastapi/boto3/socket imports: loads under Pyodide.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

ACCT = "123456789012"
REGION = "us-east-1"
SUPPORTED_VERSIONS = ["1.30", "1.31", "1.32", "1.33", "1.34"]
DEFAULT_VERSION = "1.33"
DEFAULT_SERVICE_CIDR = "10.43.0.0/16"            # the k3s service CIDR (the runtime cannot change it); a requested serviceIpv4Cidr is stored, not applied
PLATFORM_VERSION = "eks.1"
TRANSITION_SECONDS = 2.0                          # how long update/profile/add-on transitions stay InProgress/CREATING (read lazily, no scheduler)
LOG_TYPES = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
NOW = time.time                                   # test seam
SYNC = False                                      # tests: run background provisioning inline
_LOCK = threading.RLock()

CLUSTER_NAME_RE = re.compile(r"^[0-9A-Za-z][A-Za-z0-9\-_]{0,99}$")
ROLE_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/.+$")
PRINCIPAL_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:(user|role)/.+$")
ACCESS_TYPES = ("STANDARD", "FARGATE_LINUX", "EC2_LINUX", "EC2_WINDOWS", "EC2", "HYBRID_LINUX")
AUTH_MODES = ("API", "API_AND_CONFIG_MAP", "CONFIG_MAP")
ACCESS_POLICIES = ["AmazonEKSAdminPolicy", "AmazonEKSAdminViewPolicy", "AmazonEKSClusterAdminPolicy", "AmazonEKSEditPolicy", "AmazonEKSViewPolicy",
                   "AmazonEKSAutoNodePolicy", "AmazonEKSBlockStoragePolicy", "AmazonEKSComputePolicy", "AmazonEKSLoadBalancingPolicy", "AmazonEKSNetworkingPolicy"]
AMI_TYPES = ("AL2_x86_64", "AL2_x86_64_GPU", "AL2_ARM_64", "CUSTOM", "BOTTLEROCKET_ARM_64", "BOTTLEROCKET_x86_64", "BOTTLEROCKET_ARM_64_NVIDIA",
             "BOTTLEROCKET_x86_64_NVIDIA", "WINDOWS_CORE_2019_x86_64", "WINDOWS_FULL_2019_x86_64", "WINDOWS_CORE_2022_x86_64", "WINDOWS_FULL_2022_x86_64",
             "AL2023_x86_64_STANDARD", "AL2023_ARM_64_STANDARD", "AL2023_x86_64_NEURON", "AL2023_x86_64_NVIDIA", "AL2023_ARM_64_NVIDIA")

# add-on catalogue: name -> (type, [versions newest-first]); kube-proxy versions are tied to their Kubernetes minor
ADDONS = {
    "coredns": ("networking", ["v1.11.4-eksbuild.2", "v1.11.3-eksbuild.2", "v1.10.1-eksbuild.13"]),
    "kube-proxy": ("networking", ["v1.34.0-eksbuild.1", "v1.33.0-eksbuild.2", "v1.32.3-eksbuild.2", "v1.31.2-eksbuild.3", "v1.30.6-eksbuild.3"]),
    "vpc-cni": ("networking", ["v1.20.0-eksbuild.1", "v1.19.5-eksbuild.1", "v1.18.6-eksbuild.3"]),
    "aws-ebs-csi-driver": ("storage", ["v1.44.0-eksbuild.1", "v1.38.1-eksbuild.1", "v1.35.0-eksbuild.1"]),
    "aws-efs-csi-driver": ("storage", ["v2.1.6-eksbuild.1", "v2.0.9-eksbuild.1"]),
    "snapshot-controller": ("storage", ["v8.2.0-eksbuild.1", "v8.1.0-eksbuild.2"]),
    "eks-pod-identity-agent": ("security", ["v1.3.5-eksbuild.2", "v1.3.4-eksbuild.1"]),
    "metrics-server": ("observability", ["v0.7.2-eksbuild.1"]),
    "amazon-cloudwatch-observability": ("observability", ["v3.3.0-eksbuild.1", "v2.6.0-eksbuild.1"]),
    "adot": ("observability", ["v0.109.0-eksbuild.1"]),
}
K3S_PROVIDED_ADDONS = ("coredns", "kube-proxy")   # reported installed on ACTIVE: k3s ships the equivalent (CoreDNS deployment; kube-proxy embedded in the server)

_STATUS_CODE = {"ResourceNotFoundException": 404, "ResourceInUseException": 409, "InvalidParameterException": 400, "InvalidRequestException": 400,
                "ResourceLimitExceededException": 400, "ClientException": 400, "ServerException": 500, "ServiceUnavailableException": 503,
                "UnsupportedAvailabilityZoneException": 400, "AccessDeniedException": 403, "BadRequestException": 400, "NotFoundException": 404}


@dataclass
class EksResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str = "application/json"


class EksError(Exception):
    def __init__(self, code, message, **extra):
        super().__init__("%s: %s" % (code, message))
        self.code, self.message, self.extra = code, message, extra
        self.status = _STATUS_CODE.get(code, 400)


def _ok(doc, status=200):
    return EksResponse(status, json.dumps(doc).encode())


def _err(e):
    body = {"message": e.message}
    body.update(e.extra)
    return EksResponse(e.status, json.dumps(body).encode(), {"x-amzn-ErrorType": e.code})


# ── state ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _st(acct):
    st = acct.setdefault("eks", {})
    st.setdefault("clusters", {})
    st.setdefault("kube", {})       # kube_state_core holders (only used when no real backend answers)
    return st


def _public(x):
    """Strip internal ``_`` fields (recursively) for the wire."""
    if isinstance(x, dict):
        return {k: _public(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [_public(v) for v in x]
    return x


def _arn(region, kind, *parts):
    return "arn:aws:eks:%s:%s:%s/%s" % (region, ACCT, kind, "/".join(parts))


def _cluster_arn(region, name):
    return _arn(region, "cluster", name)


def _region_of(headers):
    m = re.search(r"Credential=[^/]+/[^/]+/([^/]+)/", (headers or {}).get("authorization", "") or "")
    return m.group(1) if m else REGION


def _ck(region, name):
    return "%s/%s" % (region, name)


def _get_cluster(st, region, name):
    rec = st["clusters"].get(_ck(region, name))
    if rec is None:
        raise EksError("ResourceNotFoundException", "No cluster found for name: %s." % name, clusterName=name)
    return rec


def _runtime():
    try:
        from core import kube_state_core as kube
    except ImportError:
        import kube_state_core as kube  # type: ignore
    return kube.CLUSTER_RUNTIME


def _kube():
    try:
        from core import kube_state_core as kube
    except ImportError:
        import kube_state_core as kube  # type: ignore
    return kube


def backend(acct, region, name):
    """The kube backend (kubectl + export/apply) for a cluster: REAL when the runtime owns it. Used by the kubectl extension and AWS Backup for EKS."""
    st = _st(acct)
    rec = _get_cluster(st, region, name)
    return _kube().backend_for(st["kube"], "aws", rec["arn"], None, _kube().BACKEND_FACTORY)


def _bg(fn):
    if SYNC:
        fn()
    else:
        threading.Thread(target=fn, daemon=True, name="eks-bg").start()


def _now():
    return NOW()


def _require(p, *names):
    for n in names:
        if p.get(n) in (None, "", []):
            raise EksError("InvalidParameterException", "Missing required parameter: %s" % n)


def _page(items, query, key):
    try:
        mr = int(query.get("maxResults") or 100)
    except (TypeError, ValueError):
        raise EksError("InvalidParameterException", "maxResults must be an integer between 1 and 100.")
    if not 1 <= mr <= 100:
        raise EksError("InvalidParameterException", "maxResults must be between 1 and 100.")
    try:
        start = int(query.get("nextToken") or 0)
    except (TypeError, ValueError):
        raise EksError("InvalidParameterException", "Invalid nextToken.")
    out = {key: items[start:start + mr]}
    if start + mr < len(items):
        out["nextToken"] = str(start + mr)
    return out


def _tags(p):
    t = p.get("tags") or {}
    if not isinstance(t, dict) or len(t) > 50:
        raise EksError("InvalidParameterException", "tags must be a map of at most 50 keys.")
    return {str(k): str(v) for k, v in t.items()}


# ── cluster ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _oidc_id(arn):
    import hashlib
    return hashlib.sha1(arn.encode()).hexdigest()[:32].upper()


def _subnet_info(vpc_store, subnet_ids):
    """(vpc id, error) from the simulator's EC2/VPC model when it is linked, else (None, None)."""
    if vpc_store is None:
        return None, None
    try:
        try:
            from core import vpc_core as v
        except ImportError:
            import vpc_core as v  # type: ignore
        m = v._model(vpc_store)
    except Exception:
        return None, None
    vpcs, azs = set(), set()
    for s in subnet_ids:
        sn = m["subnets"].get(s)
        if sn is None:
            return None, EksError("InvalidParameterException", "The subnet ID '%s' does not exist" % s)
        vpcs.add(sn["vpc_id"])
        azs.add(sn.get("az"))
    if len(vpcs) > 1:
        return None, EksError("InvalidParameterException", "Subnets specified must belong to the same VPC")
    if len(azs) < 2:
        return None, EksError("InvalidParameterException", "Subnets specified must be in at least two different AZs")
    return next(iter(vpcs)), None


def _subnets_exist(vpc_store, ids):
    if vpc_store is None:
        return
    try:
        try:
            from core import vpc_core as v
        except ImportError:
            import vpc_core as v  # type: ignore
        m = v._model(vpc_store)
    except Exception:
        return
    for s in ids:
        if s not in m["subnets"]:
            raise EksError("InvalidParameterException", "The subnet ID '%s' does not exist" % s)


def _check_sgs(vpc_store, sgs):
    if vpc_store is None or not sgs:
        return
    try:
        try:
            from core import vpc_core as v
        except ImportError:
            import vpc_core as v  # type: ignore
        m = v._model(vpc_store)
    except Exception:
        return
    for g in sgs:
        if g not in m["sgs"]:
            raise EksError("InvalidParameterException", "The security group '%s' does not exist" % g)


def _create_cluster(st, region, p, ctx):
    rt = _runtime()
    if rt is None:
        raise EksError("ServiceUnavailableException",
                       "Amazon EKS on Vyomi needs the Kubernetes backend: a real k3s control plane, which runs only on the offline appliance / mesh "
                       "(start it with VYOMI_K8S_BACKEND=k3s and Docker). This runtime (Nano / browser) has none, so the cluster was not created.")
    name = p.get("name")
    _require(p, "name", "roleArn", "resourcesVpcConfig")
    if not CLUSTER_NAME_RE.match(str(name)):
        raise EksError("InvalidParameterException", "Invalid cluster name: names are 1-100 characters, start with a letter or digit, and contain only letters, digits, hyphens and underscores.")
    if not ROLE_RE.match(str(p["roleArn"])):
        raise EksError("InvalidParameterException", "Role ARN %s is not a valid IAM role ARN." % p["roleArn"])
    vpc = p["resourcesVpcConfig"]
    subnets = vpc.get("subnetIds") or []
    if len(subnets) < 2:
        raise EksError("InvalidParameterException", "Subnets specified must be in at least two different AZs")
    vpc_id, bad = _subnet_info(ctx.get("vpc_store"), subnets)
    if bad:
        raise bad
    _check_sgs(ctx.get("vpc_store"), vpc.get("securityGroupIds") or [])
    version = p.get("version") or DEFAULT_VERSION
    if version not in SUPPORTED_VERSIONS:
        raise EksError("InvalidParameterException", "unsupported Kubernetes version")
    if _ck(region, name) in st["clusters"]:
        raise EksError("ResourceInUseException", "Cluster already exists with name: %s" % name, clusterName=name)
    knc = p.get("kubernetesNetworkConfig") or {}
    fam = knc.get("ipFamily") or "ipv4"
    if fam not in ("ipv4", "ipv6"):
        raise EksError("InvalidParameterException", "ipFamily must be ipv4 or ipv6.")
    acc = dict(p.get("accessConfig") or {})
    mode = acc.get("authenticationMode") or "API_AND_CONFIG_MAP"
    if mode not in AUTH_MODES:
        raise EksError("InvalidParameterException", "authenticationMode must be one of %s." % ", ".join(AUTH_MODES))
    boot = acc.get("bootstrapClusterCreatorAdminPermissions", True)
    arn = _cluster_arn(region, name)
    rec = {"name": name, "arn": arn, "createdAt": _now(), "version": version, "roleArn": p["roleArn"], "status": "CREATING",
           "resourcesVpcConfig": {"subnetIds": list(subnets), "securityGroupIds": list(vpc.get("securityGroupIds") or []),
                                  "clusterSecurityGroupId": "sg-" + uuid.uuid4().hex[:17], "vpcId": vpc_id or ("vpc-" + uuid.uuid4().hex[:17]),
                                  "endpointPublicAccess": bool(vpc.get("endpointPublicAccess", True)),
                                  "endpointPrivateAccess": bool(vpc.get("endpointPrivateAccess", False)),
                                  "publicAccessCidrs": list(vpc.get("publicAccessCidrs") or ["0.0.0.0/0"])},
           "kubernetesNetworkConfig": {"serviceIpv4Cidr": knc.get("serviceIpv4Cidr") or DEFAULT_SERVICE_CIDR, "ipFamily": fam,
                                       "elasticLoadBalancing": {"enabled": bool((knc.get("elasticLoadBalancing") or {}).get("enabled", False))}},
           "logging": {"clusterLogging": [{"types": list(LOG_TYPES), "enabled": False}]},
           "identity": {"oidc": {"issuer": "https://oidc.eks.%s.vyomi.local/id/%s" % (region, _oidc_id(arn))}},
           "certificateAuthority": {}, "platformVersion": PLATFORM_VERSION, "tags": _tags(p),
           "encryptionConfig": p.get("encryptionConfig") or [], "health": {"issues": []},
           "accessConfig": {"authenticationMode": mode, "bootstrapClusterCreatorAdminPermissions": bool(boot)},
           "upgradePolicy": {"supportType": (p.get("upgradePolicy") or {}).get("supportType") or "EXTENDED"},
           "zonalShiftConfig": {"enabled": bool((p.get("zonalShiftConfig") or {}).get("enabled", False))},
           "deletionProtection": bool(p.get("deletionProtection", False)),
           "_ng": {}, "_fp": {}, "_addons": {}, "_access": {}, "_idp": {}, "_updates": []}
    if p.get("logging"):
        rec["logging"] = _norm_logging(p["logging"], rec["logging"])
    if mode != "CONFIG_MAP" and boot:
        who = ctx.get("caller_arn") or "arn:aws:iam::%s:root" % ACCT
        _put_access_entry(rec, region, who, {"type": "STANDARD"}, bootstrap=True)
    st["clusters"][_ck(region, name)] = rec

    def ready(ok, info, _rec=rec):
        with _LOCK:
            if _rec.get("status") != "CREATING":
                return
            if ok:
                _activate(_rec, rt)
            else:
                _rec["status"] = "FAILED"
                _rec["health"] = {"issues": [{"code": "Other", "message": "The k3s control plane failed to become ready.", "resourceIds": []}]}
    try:
        rt.create_cluster("aws", arn, version, 0, (), on_ready=ready, pools=[])
    except Exception as e:
        del st["clusters"][_ck(region, name)]
        raise EksError("ServerException", "Could not start the Kubernetes control plane: %s" % str(e)[:300])
    return {"cluster": _cluster_view(rec)}


def _norm_logging(logging, current):
    """Merge a ``logging.clusterLogging`` request onto the current config (types listed enable/disable exactly those)."""
    state = {t: False for t in LOG_TYPES}
    for e in current.get("clusterLogging") or []:
        for t in e.get("types") or []:
            state[t] = bool(e.get("enabled"))
    for e in (logging or {}).get("clusterLogging") or []:
        for t in e.get("types") or []:
            if t not in LOG_TYPES:
                raise EksError("InvalidParameterException", "Invalid log type %r; valid types are %s." % (t, ", ".join(LOG_TYPES)))
            state[t] = bool(e.get("enabled"))
    on = [t for t in LOG_TYPES if state[t]]
    off = [t for t in LOG_TYPES if not state[t]]
    out = []
    if on:
        out.append({"types": on, "enabled": True})
    if off:
        out.append({"types": off, "enabled": False})
    return {"clusterLogging": out}


def _activate(rec, rt):
    """The API server answered /readyz: take the REAL endpoint + CA from the k3s cluster and report the add-ons k3s provides."""
    ep, ca = _real_endpoint(rec, rt)
    if ep:
        rec["endpoint"] = ep
    if ca:
        rec["certificateAuthority"] = {"data": ca}
    rec["status"] = "ACTIVE"
    for a in K3S_PROVIDED_ADDONS:
        if a in rec["_addons"]:
            continue
        v = _default_addon_version(a, rec["version"])
        rec["_addons"][a] = _new_addon(rec, a, v, status="ACTIVE", created=rec["createdAt"])


def _real_endpoint(rec, rt):
    ep = ca = None
    try:
        ep = "https://127.0.0.1:%s" % rt.host_port("aws", rec["arn"])
    except Exception:
        pass
    try:
        for line in rt.kubeconfig("aws", rec["arn"]).splitlines():
            if "certificate-authority-data:" in line:
                ca = line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ep, ca


def _cluster_view(rec):
    return _public(rec)


def _tick_cluster(rec, region):
    """Lazy state machine: completes due updates, resolves CREATING against the runtime, finishes deletes."""
    with _LOCK:
        now = _now()
        rt = _runtime()
        if rec["status"] == "CREATING" and rt is not None:
            try:
                if rt.is_ready("aws", rec["arn"]):
                    _activate(rec, rt)
            except Exception:
                pass
        for u in rec["_updates"]:
            if u["status"] == "InProgress" and now - u["createdAt"] >= TRANSITION_SECONDS:
                _complete_update(rec, u)
        if rec["status"] in ("ACTIVE", "UPDATING"):
            rec["status"] = "UPDATING" if any(u["status"] == "InProgress" and not u.get("_scope") for u in rec["_updates"]) else "ACTIVE"
        for fp in rec["_fp"].values():
            if fp["status"] == "CREATING" and now - fp["createdAt"] >= TRANSITION_SECONDS:
                fp["status"] = "ACTIVE"
        for k in [k for k, fp in rec["_fp"].items() if fp["status"] == "DELETING" and now - fp["_deleteAt"] >= TRANSITION_SECONDS]:
            del rec["_fp"][k]
        for a in rec["_addons"].values():
            if a["status"] in ("CREATING", "UPDATING") and now - a["modifiedAt"] >= TRANSITION_SECONDS:
                a["status"] = "ACTIVE"
        for k in [k for k, a in rec["_addons"].items() if a["status"] == "DELETING" and now - a["modifiedAt"] >= TRANSITION_SECONDS]:
            del rec["_addons"][k]
        for c in rec["_idp"].values():
            if c["status"] in ("CREATING",) and now - c["_t"] >= TRANSITION_SECONDS:
                c["status"] = "ACTIVE"
        for k in [k for k, c in rec["_idp"].items() if c["status"] == "DELETING" and now - c["_t"] >= TRANSITION_SECONDS]:
            del rec["_idp"][k]
        _tick_nodegroups(rec)


def _purge_deleted(st, region):
    for k in [k for k, r in st["clusters"].items() if r["status"] == "DELETING" and r.get("_gone")]:
        del st["clusters"][k]


def _list_clusters(st, region, q):
    names = sorted(r["name"] for k, r in st["clusters"].items() if k.startswith(region + "/"))
    return _page(names, q, "clusters")


def _delete_cluster(st, region, name):
    rec = _get_cluster(st, region, name)
    if rec["status"] == "DELETING":
        raise EksError("ResourceInUseException", "Cluster %s is already being deleted." % name)
    if rec["_ng"]:
        raise EksError("ResourceInUseException", "Cluster has nodegroups attached", clusterName=name)
    if rec["_fp"]:
        raise EksError("ResourceInUseException", "Cluster has Fargate profiles attached", clusterName=name)
    if rec.get("deletionProtection"):
        raise EksError("InvalidRequestException", "Cluster %s has deletion protection enabled." % name)
    rt = _runtime()
    rec["status"] = "DELETING"
    view = _cluster_view(rec)

    def work():
        try:
            if rt is not None:
                rt.delete_cluster("aws", rec["arn"])
        except Exception:
            pass
        with _LOCK:
            rec["_gone"] = True
            st["clusters"].pop(_ck(region, name), None)
    _bg(work)
    return {"cluster": view}


# ── updates ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _new_update(rec, utype, params, effect=None, scope=None):
    u = {"id": str(uuid.uuid4()), "status": "InProgress", "type": utype, "params": params, "createdAt": _now(), "errors": [],
         "_effect": effect or {}}
    if scope:
        u["_scope"] = scope
    rec["_updates"].append(u)
    return u


def _update_view(u):
    return _public(u)


def _complete_update(rec, u):
    e = u.get("_effect") or {}
    u["status"] = "Successful"
    k = e.get("kind")
    if k == "version":
        rec["version"] = e["value"]
        rec["platformVersion"] = PLATFORM_VERSION
        for a in K3S_PROVIDED_ADDONS:
            if a in rec["_addons"] and e["value"]:
                rec["_addons"][a]["addonVersion"] = _default_addon_version(a, e["value"])
    elif k == "config":
        for key, val in e["set"].items():
            if key == "logging":
                rec["logging"] = val
            elif key == "resourcesVpcConfig":
                rec["resourcesVpcConfig"].update(val)
            elif key == "accessConfig":
                rec["accessConfig"].update(val)
            else:
                rec[key] = val
    elif k == "ng_config":
        ng = rec["_ng"].get(e["nodegroup"])
        if ng is not None:
            ng.update(e["set"])
            ng["modifiedAt"] = _now()
            ng["status"] = "UPDATING" if ng.get("_prov") == "running" else "ACTIVE"
    elif k == "ng_version":
        ng = rec["_ng"].get(e["nodegroup"])
        if ng is not None:
            ng["version"] = e["value"]
            ng["releaseVersion"] = e["release"]
            ng["modifiedAt"] = _now()
            ng["status"] = "ACTIVE"
    elif k == "addon":
        a = rec["_addons"].get(e["addon"])
        if a is not None:
            a.update(e["set"])
            a["status"] = "ACTIVE"
    elif k == "idp_assoc":
        c = rec["_idp"].get(e["name"])
        if c is not None:
            c["status"] = "ACTIVE"


def _update_cluster_version(rec, p):
    _require(p, "version")
    v = p["version"]
    if v not in SUPPORTED_VERSIONS:
        raise EksError("InvalidParameterException", "unsupported Kubernetes version")
    _check_idle(rec)
    cur = rec["version"]
    ci, vi = SUPPORTED_VERSIONS.index(cur), SUPPORTED_VERSIONS.index(v)
    if vi == ci:
        raise EksError("InvalidParameterException", "Cluster is already at version %s" % v)
    if vi < ci:
        raise EksError("InvalidParameterException", "Unsupported Kubernetes minor version update from %s to %s" % (cur, v))
    if vi - ci > 1:
        raise EksError("InvalidParameterException", "Unsupported Kubernetes minor version update from %s to %s" % (cur, v))
    u = _new_update(rec, "VersionUpdate", [{"type": "Version", "value": v}, {"type": "PlatformVersion", "value": PLATFORM_VERSION}],
                    {"kind": "version", "value": v})
    rec["status"] = "UPDATING"
    return {"update": _update_view(u)}


def _check_idle(rec):
    if rec["status"] not in ("ACTIVE", "UPDATING"):
        raise EksError("ResourceInUseException", "Cluster %s is in %s state; it must be ACTIVE." % (rec["name"], rec["status"]), clusterName=rec["name"])
    if any(u["status"] == "InProgress" and not u.get("_scope") for u in rec["_updates"]):
        raise EksError("ResourceInUseException", "Cluster has an update in progress; wait for it to complete.", clusterName=rec["name"])


def _update_cluster_config(rec, p):
    _check_idle(rec)
    types, sets, params = [], {}, []
    if p.get("logging"):
        new = _norm_logging(p["logging"], rec["logging"])
        if new == rec["logging"]:
            raise EksError("InvalidParameterException", "No changes needed for the logging config provided")
        sets["logging"] = new
        types.append("LoggingUpdate")
        params.append({"type": "ClusterLogging", "value": json.dumps(p["logging"])})
    if p.get("resourcesVpcConfig"):
        rv = p["resourcesVpcConfig"]
        cur = rec["resourcesVpcConfig"]
        change = {}
        for k in ("endpointPublicAccess", "endpointPrivateAccess", "publicAccessCidrs"):
            if k in rv and rv[k] != cur.get(k):
                change[k] = rv[k]
        if not change:
            raise EksError("InvalidParameterException", "No changes needed for the endpoint access config provided")
        if change.get("endpointPublicAccess") is False and not rv.get("endpointPrivateAccess", cur["endpointPrivateAccess"]):
            raise EksError("InvalidParameterException", "Cluster must have at least one of endpointPublicAccess or endpointPrivateAccess enabled")
        sets["resourcesVpcConfig"] = change
        types.append("EndpointAccessUpdate")
        params += [{"type": {"endpointPublicAccess": "EndpointPublicAccess", "endpointPrivateAccess": "EndpointPrivateAccess", "publicAccessCidrs": "PublicAccessCidrs"}[k],
                    "value": json.dumps(v)} for k, v in change.items()]
    if p.get("accessConfig"):
        mode = p["accessConfig"].get("authenticationMode")
        if mode:
            if mode not in AUTH_MODES:
                raise EksError("InvalidParameterException", "authenticationMode must be one of %s." % ", ".join(AUTH_MODES))
            cur = rec["accessConfig"]["authenticationMode"]
            if mode == cur:
                raise EksError("InvalidParameterException", "No changes needed for the access config provided")
            if (cur, mode) in (("API", "API_AND_CONFIG_MAP"), ("API", "CONFIG_MAP"), ("API_AND_CONFIG_MAP", "CONFIG_MAP")):
                raise EksError("InvalidParameterException", "Authentication mode cannot be changed from %s to %s; only CONFIG_MAP -> API_AND_CONFIG_MAP -> API is allowed." % (cur, mode))
            sets["accessConfig"] = {"authenticationMode": mode}
            types.append("AccessConfigUpdate")
            params.append({"type": "AuthenticationMode", "value": mode})
    if p.get("upgradePolicy"):
        sets["upgradePolicy"] = {"supportType": p["upgradePolicy"].get("supportType", rec["upgradePolicy"]["supportType"])}
        types.append("UpgradePolicyUpdate")
        params.append({"type": "UpgradePolicy", "value": json.dumps(p["upgradePolicy"])})
    if p.get("zonalShiftConfig"):
        sets["zonalShiftConfig"] = {"enabled": bool(p["zonalShiftConfig"].get("enabled"))}
        types.append("ZonalShiftConfigUpdate")
        params.append({"type": "ZonalShiftConfig", "value": json.dumps(p["zonalShiftConfig"])})
    if not types:
        raise EksError("InvalidParameterException", "At least one of resourcesVpcConfig, logging, accessConfig, upgradePolicy or zonalShiftConfig must be provided.")
    u = _new_update(rec, types[0] if len(types) == 1 else "ConfigUpdate", params, {"kind": "config", "set": sets})
    rec["status"] = "UPDATING"
    return {"update": _update_view(u)}


def _find_update(rec, uid, q):
    for u in rec["_updates"]:
        if u["id"] == uid:
            sc = u.get("_scope") or {}
            if (q.get("nodegroupName") or None) != sc.get("nodegroup") or (q.get("addonName") or None) != sc.get("addon"):
                continue
            return u
    raise EksError("ResourceNotFoundException", "No update found with ID: %s." % uid, clusterName=rec["name"])


def _list_updates(rec, q):
    ng, ad = q.get("nodegroupName") or None, q.get("addonName") or None
    if ng and ng not in rec["_ng"]:
        raise EksError("ResourceNotFoundException", "No node group found for name: %s." % ng, clusterName=rec["name"], nodegroupName=ng)
    if ad and ad not in rec["_addons"]:
        raise EksError("ResourceNotFoundException", "No addon: %s found in cluster: %s" % (ad, rec["name"]), clusterName=rec["name"], addonName=ad)
    ids = [u["id"] for u in reversed(rec["_updates"]) if (u.get("_scope") or {}).get("nodegroup") == ng and (u.get("_scope") or {}).get("addon") == ad]
    return _page(ids, q, "updateIds")


# ── managed node groups ──────────────────────────────────────────────────────────────────────────────────────────────────
def _scaling(sc, cur=None):
    base = dict(cur or {"minSize": 1, "maxSize": 2, "desiredSize": 2})
    sc = sc or {}
    for k in ("minSize", "maxSize", "desiredSize"):
        if k in sc and sc[k] is not None:
            base[k] = sc[k]
    if "desiredSize" not in sc and cur is None:
        base["desiredSize"] = max(base["minSize"], min(base["desiredSize"], base["maxSize"]))
    for k, v in base.items():
        if not isinstance(v, int) or v < 0:
            raise EksError("InvalidParameterException", "scalingConfig.%s must be a non-negative integer." % k)
    if base["maxSize"] < 1:
        raise EksError("InvalidParameterException", "Max size must be at least 1")
    if not base["minSize"] <= base["desiredSize"] <= base["maxSize"]:
        raise EksError("InvalidParameterException", "Minimum capacity %d can't be greater than desired size %d" % (base["minSize"], base["desiredSize"])
                       if base["minSize"] > base["desiredSize"] else
                       "Desired capacity %d can't be greater than max size %d" % (base["desiredSize"], base["maxSize"]))
    return base


def _get_ng(rec, name):
    ng = rec["_ng"].get(name)
    if ng is None:
        raise EksError("ResourceNotFoundException", "No node group found for name: %s." % name, clusterName=rec["name"], nodegroupName=name)
    return ng


def _need_active(rec):
    if rec["status"] not in ("ACTIVE", "UPDATING"):
        raise EksError("ResourceInUseException", "Cluster %s is not ACTIVE (status %s)." % (rec["name"], rec["status"]), clusterName=rec["name"])


def _ng_item(rec, region, ng):
    return _public(ng)


def _create_nodegroup(rec, region, p, ctx):
    _require(p, "nodegroupName", "subnets", "nodeRole")
    name = p["nodegroupName"]
    if not CLUSTER_NAME_RE.match(name):
        raise EksError("InvalidParameterException", "Invalid nodegroup name %r." % name)
    if not ROLE_RE.match(str(p["nodeRole"])):
        raise EksError("InvalidParameterException", "Role ARN %s is not a valid IAM role ARN." % p["nodeRole"])
    if name in rec["_ng"]:
        raise EksError("ResourceInUseException", "NodeGroup already exists with name %s and cluster name %s" % (name, rec["name"]), clusterName=rec["name"], nodegroupName=name)
    _need_active(rec)
    _subnets_exist(ctx.get("vpc_store"), p["subnets"])
    ami = p.get("amiType") or "AL2023_x86_64_STANDARD"
    if ami not in AMI_TYPES:
        raise EksError("InvalidParameterException", "Invalid amiType %r." % ami)
    cap = p.get("capacityType") or "ON_DEMAND"
    if cap not in ("ON_DEMAND", "SPOT", "CAPACITY_BLOCK"):
        raise EksError("InvalidParameterException", "capacityType must be ON_DEMAND or SPOT.")
    sc = _scaling(p.get("scalingConfig"))
    for t in p.get("taints") or []:
        if t.get("effect") not in ("NO_SCHEDULE", "NO_EXECUTE", "PREFER_NO_SCHEDULE") or not t.get("key"):
            raise EksError("InvalidParameterException", "Invalid taint: effect must be NO_SCHEDULE, NO_EXECUTE or PREFER_NO_SCHEDULE.")
    ver = p.get("version") or rec["version"]
    if ver not in SUPPORTED_VERSIONS:
        raise EksError("InvalidParameterException", "unsupported Kubernetes version")
    now = _now()
    ng = {"nodegroupName": name, "nodegroupArn": _arn(region, "nodegroup", rec["name"], name, str(uuid.uuid4())), "clusterName": rec["name"],
          "version": ver, "releaseVersion": p.get("releaseVersion") or "%s.0-vyomi1" % ver, "createdAt": now, "modifiedAt": now, "status": "CREATING",
          "capacityType": cap, "scalingConfig": sc, "instanceTypes": list(p.get("instanceTypes") or ["t3.medium"]), "subnets": list(p["subnets"]),
          "amiType": ami, "nodeRole": p["nodeRole"], "labels": dict(p.get("labels") or {}), "taints": list(p.get("taints") or []),
          "resources": {"autoScalingGroups": [{"name": "eks-%s-%s" % (name, uuid.uuid4().hex[:8])}]}, "diskSize": int(p.get("diskSize") or 20),
          "health": {"issues": []}, "updateConfig": p.get("updateConfig") or {"maxUnavailable": 1}, "tags": _tags(p),
          "_ami_id": "ami-" + uuid.uuid4().hex[:17], "_prov": "pending"}
    if p.get("remoteAccess"):
        ng["remoteAccess"] = p["remoteAccess"]
    if p.get("nodeRepairConfig"):
        ng["nodeRepairConfig"] = p["nodeRepairConfig"]
    # fail synchronously (native error) when the appliance cannot host that many nodes
    rt = _runtime()
    if rt is not None:
        from core import aws_eks_nodes as nodes
        others = nodes.NodeProvisioner(rt).other_count(rec["arn"], name)
        if others + sc["desiredSize"] > nodes.max_agents():
            raise EksError("ResourceLimitExceededException", "This appliance runs at most %d EKS worker nodes per cluster (VYOMI_EKS_MAX_NODES); %d already exist." % (nodes.max_agents(), others),
                           clusterName=rec["name"], nodegroupName=name)
    rec["_ng"][name] = ng
    _provision(rec, ng, sc["desiredSize"])
    return {"nodegroup": _public(ng)}


def _provision(rec, ng, desired):
    """Start / resize the node group's k3s agents in the background; the group is ACTIVE once the nodes are Ready."""
    rt = _runtime()
    ng["_prov"] = "running"
    arn = rec["arn"]

    def work():
        try:
            from core import aws_eks_nodes as nodes
            nodes.NodeProvisioner(rt).scale(arn, ng, desired)
            with _LOCK:
                ng["_prov"] = "done"
        except Exception as e:
            with _LOCK:
                ng["_prov"] = "failed"
                ng["status"] = "CREATE_FAILED" if ng["status"] == "CREATING" else "DEGRADED"
                ng["health"] = {"issues": [{"code": "Ec2LaunchTemplateNotFound" if False else "AsgInstanceLaunchFailures", "message": str(e)[:300], "resourceIds": []}]}
    if rt is None:
        ng["_prov"] = "done"
        return
    _bg(work)


def _tick_nodegroups(rec):
    rt = _runtime()
    for name in list(rec["_ng"]):
        ng = rec["_ng"][name]
        if ng["status"] == "DELETING" and ng.get("_gone"):
            del rec["_ng"][name]
            continue
        if ng["status"] == "UPDATING" and ng.get("_prov") == "done" and not any(u["status"] == "InProgress" and (u.get("_scope") or {}).get("nodegroup") == name for u in rec["_updates"]):
            ng["status"] = "ACTIVE"
        if ng["status"] == "CREATING" and ng.get("_prov") == "done":
            want = ng["scalingConfig"]["desiredSize"]
            try:
                from core import aws_eks_nodes as nodes
                ready = nodes.NodeProvisioner(rt).ready_count(rec["arn"], name) if rt is not None else want
            except Exception:
                ready = 0
            if ready >= want:
                ng["status"] = "ACTIVE"
                ng["modifiedAt"] = _now()


def _update_nodegroup_config(rec, region, ngname, p):
    ng = _get_ng(rec, ngname)
    if ng["status"] not in ("ACTIVE", "DEGRADED"):
        raise EksError("ResourceInUseException", "Nodegroup %s is %s." % (ngname, ng["status"]), clusterName=rec["name"], nodegroupName=ngname)
    sets, params = {}, []
    if p.get("scalingConfig"):
        sets["scalingConfig"] = _scaling(p["scalingConfig"], ng["scalingConfig"])
        params.append({"type": "MinSize", "value": str(sets["scalingConfig"]["minSize"])})
        params.append({"type": "MaxSize", "value": str(sets["scalingConfig"]["maxSize"])})
        params.append({"type": "DesiredSize", "value": str(sets["scalingConfig"]["desiredSize"])})
    if p.get("labels"):
        lab = dict(ng["labels"])
        lab.update(p["labels"].get("addOrUpdateLabels") or {})
        for k in p["labels"].get("removeLabels") or []:
            lab.pop(k, None)
        sets["labels"] = lab
        params.append({"type": "LabelsToAdd", "value": json.dumps(p["labels"].get("addOrUpdateLabels") or {})})
        params.append({"type": "LabelsToRemove", "value": json.dumps(p["labels"].get("removeLabels") or [])})
    if p.get("taints"):
        tl = {t["key"]: t for t in ng["taints"]}
        for t in p["taints"].get("addOrUpdateTaints") or []:
            tl[t["key"]] = t
        for t in p["taints"].get("removeTaints") or []:
            tl.pop(t["key"], None)
        sets["taints"] = list(tl.values())
        params.append({"type": "TaintsToAdd", "value": json.dumps(p["taints"].get("addOrUpdateTaints") or [])})
        params.append({"type": "TaintsToRemove", "value": json.dumps(p["taints"].get("removeTaints") or [])})
    if p.get("updateConfig"):
        sets["updateConfig"] = p["updateConfig"]
        params.append({"type": "MaxUnavailable", "value": str(p["updateConfig"].get("maxUnavailable", ""))})
    if not sets:
        raise EksError("InvalidParameterException", "No changes provided for the nodegroup config.")
    u = _new_update(rec, "ConfigUpdate", params, {"kind": "ng_config", "nodegroup": ngname, "set": sets}, scope={"nodegroup": ngname})
    ng["status"] = "UPDATING"
    if "scalingConfig" in sets and _runtime() is not None:
        merged = dict(ng)
        merged.update(sets)
        ng["_prov"] = "running"
        rt, arn = _runtime(), rec["arn"]

        def work():
            try:
                from core import aws_eks_nodes as nodes
                nodes.NodeProvisioner(rt).scale(arn, merged, sets["scalingConfig"]["desiredSize"])
            except Exception as e:
                with _LOCK:
                    ng["health"] = {"issues": [{"code": "AsgInstanceLaunchFailures", "message": str(e)[:300], "resourceIds": []}]}
            with _LOCK:
                ng["_prov"] = "done"
        _bg(work)
    return {"update": _update_view(u)}


def _update_nodegroup_version(rec, region, ngname, p):
    ng = _get_ng(rec, ngname)
    if ng["status"] not in ("ACTIVE", "DEGRADED"):
        raise EksError("ResourceInUseException", "Nodegroup %s is %s." % (ngname, ng["status"]), clusterName=rec["name"], nodegroupName=ngname)
    v = p.get("version") or rec["version"]
    if v not in SUPPORTED_VERSIONS:
        raise EksError("InvalidParameterException", "unsupported Kubernetes version")
    if SUPPORTED_VERSIONS.index(v) > SUPPORTED_VERSIONS.index(rec["version"]):
        raise EksError("InvalidParameterException", "Nodegroup version %s cannot be newer than the cluster version %s." % (v, rec["version"]))
    rel = p.get("releaseVersion") or "%s.0-vyomi1" % v
    if v == ng["version"] and rel == ng["releaseVersion"]:
        raise EksError("InvalidParameterException", "Nodegroup is already at the requested version and release version.")
    u = _new_update(rec, "VersionUpdate", [{"type": "Version", "value": v}, {"type": "ReleaseVersion", "value": rel}],
                    {"kind": "ng_version", "nodegroup": ngname, "value": v, "release": rel}, scope={"nodegroup": ngname})
    ng["status"] = "UPDATING"
    return {"update": _update_view(u)}


def _delete_nodegroup(rec, region, ngname):
    ng = _get_ng(rec, ngname)
    if ng["status"] == "DELETING":
        raise EksError("ResourceInUseException", "Nodegroup %s is already being deleted." % ngname, clusterName=rec["name"], nodegroupName=ngname)
    ng["status"] = "DELETING"
    ng["modifiedAt"] = _now()
    rt, arn = _runtime(), rec["arn"]

    def work():
        try:
            if rt is not None:
                from core import aws_eks_nodes as nodes
                nodes.NodeProvisioner(rt).remove(arn, ngname)
        except Exception:
            pass
        with _LOCK:
            ng["_gone"] = True
    _bg(work)
    return {"nodegroup": _public(ng)}


# ── Fargate profiles (accepted and stored: Vyomi has no Fargate data plane) ─────────────────────────────────────────────
def _create_fargate(rec, region, p):
    _require(p, "fargateProfileName", "podExecutionRoleArn", "selectors")
    name = p["fargateProfileName"]
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,99}$", name) or name.startswith("eks-"):
        raise EksError("InvalidParameterException", "Invalid Fargate profile name (must not start with 'eks-').")
    if not ROLE_RE.match(str(p["podExecutionRoleArn"])):
        raise EksError("InvalidParameterException", "Role ARN %s is not a valid IAM role ARN." % p["podExecutionRoleArn"])
    if name in rec["_fp"]:
        raise EksError("ResourceInUseException", "A Fargate profile already exists with name %s in cluster %s" % (name, rec["name"]), clusterName=rec["name"], fargateProfileName=name)
    sel = p["selectors"]
    if len(sel) > 5 or any(not s.get("namespace") for s in sel):
        raise EksError("InvalidParameterException", "selectors: 1-5 entries, each with a namespace.")
    _need_active(rec)
    fp = {"fargateProfileName": name, "fargateProfileArn": _arn(region, "fargateprofile", rec["name"], name, str(uuid.uuid4())), "clusterName": rec["name"],
          "createdAt": _now(), "podExecutionRoleArn": p["podExecutionRoleArn"], "subnets": list(p.get("subnets") or rec["resourcesVpcConfig"]["subnetIds"]),
          "selectors": [{"namespace": s["namespace"], **({"labels": s["labels"]} if s.get("labels") else {})} for s in sel],
          "status": "CREATING", "tags": _tags(p)}
    rec["_fp"][name] = fp
    return {"fargateProfile": _public(fp)}


def _get_fp(rec, name):
    fp = rec["_fp"].get(name)
    if fp is None:
        raise EksError("ResourceNotFoundException", "No Fargate Profile found with name: %s." % name, clusterName=rec["name"], fargateProfileName=name)
    return fp


# ── add-ons ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _minor(v):
    m = re.match(r"^v?(\d+\.\d+)", v or "")
    return m.group(1) if m else ""


def _compatible_versions(addon, cluster_version):
    vs = ADDONS[addon][1]
    if addon == "kube-proxy":
        return [v for v in vs if _minor(v) == cluster_version]
    return list(vs)


def _default_addon_version(addon, cluster_version):
    c = _compatible_versions(addon, cluster_version)
    return c[0] if c else ADDONS[addon][1][0]


def _new_addon(rec, name, version, status="CREATING", created=None, **kw):
    now = created or _now()
    a = {"addonName": name, "clusterName": rec["name"], "status": status, "addonVersion": version,
         "health": {"issues": []}, "addonArn": _arn(rec["arn"].split(":")[3], "addon", rec["name"], name, str(uuid.uuid4())),
         "createdAt": now, "modifiedAt": _now() if status != "ACTIVE" else now, "tags": kw.get("tags") or {}, "publisher": "eks", "owner": "aws"}
    if kw.get("serviceAccountRoleArn"):
        a["serviceAccountRoleArn"] = kw["serviceAccountRoleArn"]
    if kw.get("configurationValues"):
        a["configurationValues"] = kw["configurationValues"]
    if kw.get("podIdentityAssociations"):
        a["podIdentityAssociations"] = kw["podIdentityAssociations"]
    return a


def _get_addon(rec, name):
    a = rec["_addons"].get(name)
    if a is None:
        raise EksError("ResourceNotFoundException", "No addon: %s found in cluster: %s" % (name, rec["name"]), clusterName=rec["name"], addonName=name)
    return a


def _check_addon_version(rec, name, version):
    if version not in ADDONS[name][1] or version not in _compatible_versions(name, rec["version"]):
        raise EksError("InvalidParameterException", "Addon version specified is not supported", clusterName=rec["name"], addonName=name)


def _create_addon(rec, region, p):
    _require(p, "addonName")
    name = p["addonName"]
    if name not in ADDONS:
        raise EksError("InvalidParameterException", "Addon %s is not supported." % name, clusterName=rec["name"], addonName=name)
    if name in rec["_addons"]:
        raise EksError("ResourceInUseException", "Addon already exists", clusterName=rec["name"], addonName=name)
    _need_active(rec)
    ver = p.get("addonVersion") or _default_addon_version(name, rec["version"])
    _check_addon_version(rec, name, ver)
    if p.get("resolveConflicts") not in (None, "NONE", "OVERWRITE", "PRESERVE"):
        raise EksError("InvalidParameterException", "resolveConflicts must be NONE, OVERWRITE or PRESERVE.")
    if p.get("configurationValues"):
        try:
            json.loads(p["configurationValues"])
        except ValueError:
            raise EksError("InvalidParameterException", "configurationValues must be valid JSON or YAML.")
    a = _new_addon(rec, name, ver, tags=_tags(p), serviceAccountRoleArn=p.get("serviceAccountRoleArn"),
                   configurationValues=p.get("configurationValues"), podIdentityAssociations=[x.get("roleArn") for x in p.get("podIdentityAssociations") or []] or None)
    rec["_addons"][name] = a
    return {"addon": _public(a)}


def _update_addon(rec, name, p):
    a = _get_addon(rec, name)
    if a["status"] not in ("ACTIVE", "DEGRADED"):
        raise EksError("ResourceInUseException", "Addon %s is %s." % (name, a["status"]), clusterName=rec["name"], addonName=name)
    sets, params = {}, []
    if p.get("addonVersion"):
        _check_addon_version(rec, name, p["addonVersion"])
        sets["addonVersion"] = p["addonVersion"]
        params.append({"type": "AddonVersion", "value": p["addonVersion"]})
    if p.get("serviceAccountRoleArn"):
        sets["serviceAccountRoleArn"] = p["serviceAccountRoleArn"]
        params.append({"type": "ServiceAccountRoleArn", "value": p["serviceAccountRoleArn"]})
    if p.get("configurationValues") is not None:
        sets["configurationValues"] = p["configurationValues"]
        params.append({"type": "ConfigurationValues", "value": p["configurationValues"]})
    if not sets:
        raise EksError("InvalidParameterException", "No changes requested for addon %s." % name)
    u = _new_update(rec, "AddonUpdate", params, {"kind": "addon", "addon": name, "set": sets}, scope={"addon": name})
    a["status"] = "UPDATING"
    a["modifiedAt"] = _now()
    return {"update": _update_view(u)}


def _delete_addon(rec, name, q):
    a = _get_addon(rec, name)
    if str(q.get("preserve", "")).lower() == "true":
        view = _public(a)
        del rec["_addons"][name]
        return {"addon": view}
    a["status"] = "DELETING"
    a["modifiedAt"] = _now()
    return {"addon": _public(a)}


def _addon_versions(q):
    name, kv = q.get("addonName"), q.get("kubernetesVersion")
    out = []
    for n, (typ, vs) in sorted(ADDONS.items()):
        if name and n != name:
            continue
        if q.get("types") and typ not in q["types"].split(","):
            continue
        items = []
        for i, v in enumerate(vs):
            comp = []
            for cv in SUPPORTED_VERSIONS:
                if kv and cv != kv:
                    continue
                if n == "kube-proxy" and _minor(v) != cv:
                    continue
                comp.append({"clusterVersion": cv, "platformVersions": ["*"], "defaultVersion": (_default_addon_version(n, cv) == v)})
            if comp:
                items.append({"addonVersion": v, "architecture": ["amd64", "arm64"], "compatibilities": comp, "requiresConfiguration": False,
                              "requiresIamPermissions": n in ("aws-ebs-csi-driver", "aws-efs-csi-driver", "vpc-cni") and False})
        if items:
            out.append({"addonName": n, "type": typ, "addonVersions": items, "publisher": "eks", "owner": "aws"})
    return _page(out, q, "addons")


def _addon_schema(q):
    name = q.get("addonName")
    if name not in ADDONS:
        raise EksError("ResourceNotFoundException", "No addon named %s." % (name,))
    ver = q.get("addonVersion") or ADDONS[name][1][0]
    if ver not in ADDONS[name][1]:
        raise EksError("InvalidParameterException", "Addon version specified is not supported")
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
              "properties": {"replicaCount": {"type": "integer", "minimum": 1}, "resources": {"type": "object"}}}
    return {"addonName": name, "addonVersion": ver, "configurationSchema": json.dumps(schema)}


# ── access entries ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _need_api_mode(rec):
    if rec["accessConfig"]["authenticationMode"] == "CONFIG_MAP":
        raise EksError("InvalidRequestException", "The cluster's authentication mode must be set to one of [API, API_AND_CONFIG_MAP] to perform this operation.")


def _put_access_entry(rec, region, principal, p, bootstrap=False):
    etype = p.get("type") or "STANDARD"
    uname = p.get("username")
    if not uname and etype == "STANDARD":
        uname = principal if (":user/" in principal or principal.endswith(":root")) else "arn:aws:sts::%s:assumed-role/%s/{{SessionName}}" % (principal.split(":")[4], principal.rsplit("/", 1)[-1])
    e = {"clusterName": rec["name"], "principalArn": principal, "kubernetesGroups": list(p.get("kubernetesGroups") or []),
         "accessEntryArn": _arn(region, "access-entry", rec["name"], (principal.split(":")[5].split("/", 1) + [""])[0], principal.split(":")[4], principal.split(":")[5].split("/", 1)[-1], str(uuid.uuid4())),
         "createdAt": _now(), "modifiedAt": _now(), "tags": _tags(p), "username": uname or "", "type": etype, "_policies": {}}
    if bootstrap:
        pol = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
        e["_policies"][pol] = {"policyArn": pol, "accessScope": {"type": "cluster", "namespaces": []}, "associatedAt": _now(), "modifiedAt": _now()}
    rec["_access"][principal] = e
    return e


def _entry_view(e):
    return _public(e)


def _get_entry(rec, principal):
    e = rec["_access"].get(principal)
    if e is None:
        raise EksError("ResourceNotFoundException", "The specified principal ARN is not associated with an access entry.", clusterName=rec["name"], principalArn=principal)
    return e


def _create_access_entry(rec, region, p):
    _need_api_mode(rec)
    _require(p, "principalArn")
    pr = p["principalArn"]
    if not PRINCIPAL_RE.match(pr):
        raise EksError("InvalidParameterException", "The principalArn must be an IAM user or role ARN.")
    et = p.get("type") or "STANDARD"
    if et not in ACCESS_TYPES:
        raise EksError("InvalidParameterException", "Invalid access entry type %r." % et)
    if et != "STANDARD" and (p.get("kubernetesGroups") or p.get("username")):
        raise EksError("InvalidParameterException", "kubernetesGroups and username are only valid for STANDARD access entries.")
    if pr in rec["_access"]:
        raise EksError("ResourceInUseException", "The specified access entry resource is already in use on this cluster.", clusterName=rec["name"], principalArn=pr)
    for g in p.get("kubernetesGroups") or []:
        if g.startswith("system:"):
            raise EksError("InvalidParameterException", "Kubernetes group %r is reserved and cannot be used." % g)
    return {"accessEntry": _entry_view(_put_access_entry(rec, region, pr, p))}


def _update_access_entry(rec, principal, p):
    _need_api_mode(rec)
    e = _get_entry(rec, principal)
    if "kubernetesGroups" in p:
        e["kubernetesGroups"] = list(p["kubernetesGroups"] or [])
    if "username" in p:
        e["username"] = p["username"]
    e["modifiedAt"] = _now()
    return {"accessEntry": _entry_view(e)}


def _associate_policy(rec, principal, p):
    _need_api_mode(rec)
    e = _get_entry(rec, principal)
    _require(p, "policyArn", "accessScope")
    m = re.match(r"^arn:aws[a-z-]*:eks::aws:cluster-access-policy/(.+)$", p["policyArn"])
    if not m or m.group(1) not in ACCESS_POLICIES:
        raise EksError("InvalidParameterException", "The specified access policy %s does not exist." % p["policyArn"])
    sc = p["accessScope"]
    if sc.get("type") not in ("cluster", "namespace"):
        raise EksError("InvalidParameterException", "accessScope.type must be cluster or namespace.")
    if sc["type"] == "namespace" and not sc.get("namespaces"):
        raise EksError("InvalidParameterException", "accessScope.namespaces is required for namespace-scoped access.")
    if e["type"] != "STANDARD":
        raise EksError("InvalidRequestException", "Access policies can only be associated with STANDARD access entries.")
    prev = e["_policies"].get(p["policyArn"])
    ap = {"policyArn": p["policyArn"], "accessScope": {"type": sc["type"], "namespaces": list(sc.get("namespaces") or [])},
          "associatedAt": prev["associatedAt"] if prev else _now(), "modifiedAt": _now()}
    e["_policies"][p["policyArn"]] = ap
    return {"clusterName": rec["name"], "principalArn": principal, "associatedAccessPolicy": ap}


# ── OIDC identity provider configs ───────────────────────────────────────────────────────────────────────────────────────
def _associate_idp(rec, region, p):
    o = p.get("oidc")
    if not o:
        raise EksError("InvalidParameterException", "oidc is required.")
    _require(o, "identityProviderConfigName", "issuerUrl", "clientId")
    n = o["identityProviderConfigName"]
    if not str(o["issuerUrl"]).startswith("https://"):
        raise EksError("InvalidParameterException", "issuerUrl must be an https URL.")
    if rec["_idp"]:
        raise EksError("ResourceInUseException", "Only one OIDC identity provider configuration can be associated with a cluster.", clusterName=rec["name"])
    if n in rec["_idp"]:
        raise EksError("ResourceInUseException", "Identity provider config %s already exists." % n)
    _need_active(rec)
    cfg = {"identityProviderConfigName": n, "identityProviderConfigArn": _arn(region, "identityproviderconfig", rec["name"], "oidc", n, str(uuid.uuid4())),
           "clusterName": rec["name"], "issuerUrl": o["issuerUrl"], "clientId": o["clientId"], "usernameClaim": o.get("usernameClaim", ""),
           "usernamePrefix": o.get("usernamePrefix", ""), "groupsClaim": o.get("groupsClaim", ""), "groupsPrefix": o.get("groupsPrefix", ""),
           "requiredClaims": o.get("requiredClaims") or {}, "tags": _tags(p), "status": "CREATING", "_t": _now()}
    rec["_idp"][n] = cfg
    u = _new_update(rec, "AssociateIdentityProviderConfig", [{"type": "IdentityProviderConfig", "value": json.dumps({"type": "oidc", "name": n})}],
                    {"kind": "idp_assoc", "name": n})
    return {"update": _update_view(u), "tags": cfg["tags"]}


def _disassociate_idp(rec, p):
    ref = p.get("identityProviderConfig") or {}
    n = ref.get("name")
    cfg = rec["_idp"].get(n)
    if ref.get("type") != "oidc" or cfg is None:
        raise EksError("ResourceNotFoundException", "No identity provider config found for name: %s." % n, clusterName=rec["name"])
    cfg["status"] = "DELETING"
    cfg["_t"] = _now()
    u = _new_update(rec, "DisassociateIdentityProviderConfig", [{"type": "IdentityProviderConfig", "value": json.dumps({"type": "oidc", "name": n})}])
    return {"update": _update_view(u)}


# ── tags ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _tag_target(st, arn):
    m = re.match(r"^arn:aws:eks:([a-z0-9-]+):\d{12}:(cluster|nodegroup|fargateprofile|addon|access-entry|identityproviderconfig)/([^/]+)(?:/(.*))?$", arn or "")
    if not m:
        raise EksError("NotFoundException", "The specified resource was not found: %s" % arn)
    region, kind, cname, rest = m.groups()
    rec = st["clusters"].get(_ck(region, cname))
    if rec is None:
        raise EksError("NotFoundException", "The specified resource was not found: %s" % arn)
    if kind == "cluster":
        return rec
    coll = {"nodegroup": rec["_ng"], "fargateprofile": rec["_fp"], "addon": rec["_addons"], "access-entry": None, "identityproviderconfig": rec["_idp"]}[kind]
    if coll is not None:
        for item in coll.values():
            if item.get("nodegroupArn") == arn or item.get("fargateProfileArn") == arn or item.get("addonArn") == arn or item.get("identityProviderConfigArn") == arn:
                return item
    else:
        for item in rec["_access"].values():
            if item["accessEntryArn"] == arn:
                return item
    raise EksError("NotFoundException", "The specified resource was not found: %s" % arn)


# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _body(raw):
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except ValueError:
        raise EksError("InvalidParameterException", "The request body is not valid JSON.")
    return d if isinstance(d, dict) else {}


def dispatch(acct, method, path, query, headers, body, vpc_store=None, caller_arn=None, iam_store=None):
    """Serve one EKS REST request. ``acct`` is the account bag (``s3_store.account``)."""
    try:
        with _LOCK:
            return _ok_or_raise(_route(acct, method.upper(), unquote(path.split("?", 1)[0]), query or {}, headers or {}, body,
                                       {"vpc_store": vpc_store, "caller_arn": caller_arn, "iam_store": iam_store}))
    except EksError as e:
        return _err(e)


def _ok_or_raise(res):
    return res if isinstance(res, EksResponse) else _ok(res)


_ACCESS_RE = re.compile(r"^/clusters/([^/]+)/access-entries/(.+?)(?:/access-policies(?:/(.+))?)?$")


def _route(acct, m, path, q, headers, raw, ctx):
    st = _st(acct)
    region = _region_of({k.lower(): v for k, v in headers.items()})
    segs = [s for s in path.split("/") if s]
    if not segs:
        raise EksError("InvalidRequestException", "Unknown operation %s %s." % (m, path))
    head = segs[0]
    if head == "cluster-versions" and m == "GET":
        return {"clusterVersions": [{"clusterType": "eks", "clusterVersion": v, "defaultPlatformVersion": PLATFORM_VERSION, "defaultVersion": v == DEFAULT_VERSION,
                                     "versionStatus": "STANDARD_SUPPORT", "status": "STANDARD_SUPPORT"} for v in reversed(SUPPORTED_VERSIONS)]}
    if head == "access-policies" and m == "GET" and len(segs) == 1:
        return _page([{"name": n, "arn": "arn:aws:eks::aws:cluster-access-policy/" + n} for n in ACCESS_POLICIES], q, "accessPolicies")
    if head == "addons" and m == "GET" and len(segs) == 2:
        if segs[1] == "supported-versions":
            return _addon_versions(q)
        if segs[1] == "configuration-schemas":
            return _addon_schema(q)
    if head == "tags" and len(segs) >= 2:
        arn = path[len("/tags/"):]
        target = _tag_target(st, arn)
        if m == "GET":
            return {"tags": dict(target.get("tags") or {})}
        if m == "POST":
            t = _body(raw).get("tags") or {}
            target.setdefault("tags", {}).update({str(k): str(v) for k, v in t.items()})
            return {}
        if m == "DELETE":
            keys = q.get("tagKeys") or []
            for k in (keys.split(",") if isinstance(keys, str) else keys):
                (target.get("tags") or {}).pop(k, None)
            return {}
    if head != "clusters":
        raise EksError("InvalidRequestException", "Unknown operation %s %s." % (m, path))
    if len(segs) == 1:
        if m == "POST":
            return _create_cluster(st, region, _body(raw), ctx)
        if m == "GET":
            for r in st["clusters"].values():
                _tick_cluster(r, region)
            return _list_clusters(st, region, q)
    name = segs[1]
    rec = _get_cluster(st, region, name)
    _tick_cluster(rec, region)
    rest = segs[2:]
    p = _body(raw) if m in ("POST", "PATCH", "PUT") else {}
    if not rest:
        if m == "GET":
            if rec["status"] in ("ACTIVE", "UPDATING") and _runtime() is not None:
                try:
                    rec["endpoint"] = "https://127.0.0.1:%s" % _runtime().host_port("aws", rec["arn"])   # the published port can change if Docker restarted
                except Exception:
                    pass
            return {"cluster": _cluster_view(rec)}
        if m == "DELETE":
            return _delete_cluster(st, region, name)
    elif rest == ["updates"]:
        if m == "POST":
            return _update_cluster_version(rec, p)
        if m == "GET":
            return _list_updates(rec, q)
    elif rest == ["update-config"] and m == "POST":
        return _update_cluster_config(rec, p)
    elif len(rest) == 2 and rest[0] == "updates" and m == "GET":
        return {"update": _update_view(_find_update(rec, rest[1], q))}
    elif rest[0] == "node-groups":
        if len(rest) == 1:
            if m == "POST":
                return _create_nodegroup(rec, region, p, ctx)
            if m == "GET":
                return _page(sorted(rec["_ng"]), q, "nodegroups")
        elif len(rest) == 2:
            if m == "GET":
                return {"nodegroup": _public(_get_ng(rec, rest[1]))}
            if m == "DELETE":
                return _delete_nodegroup(rec, region, rest[1])
        elif len(rest) == 3 and m == "POST":
            if rest[2] == "update-config":
                return _update_nodegroup_config(rec, region, rest[1], p)
            if rest[2] == "update-version":
                return _update_nodegroup_version(rec, region, rest[1], p)
    elif rest[0] == "fargate-profiles":
        if len(rest) == 1:
            if m == "POST":
                return _create_fargate(rec, region, p)
            if m == "GET":
                return _page(sorted(rec["_fp"]), q, "fargateProfileNames")
        elif len(rest) == 2:
            if m == "GET":
                return {"fargateProfile": _public(_get_fp(rec, rest[1]))}
            if m == "DELETE":
                fp = _get_fp(rec, rest[1])
                fp["status"] = "DELETING"
                fp["_deleteAt"] = _now()
                return {"fargateProfile": _public(fp)}
    elif rest[0] == "addons":
        if len(rest) == 1:
            if m == "POST":
                return _create_addon(rec, region, p)
            if m == "GET":
                return _page(sorted(rec["_addons"]), q, "addons")
        elif len(rest) == 2:
            if m == "GET":
                return {"addon": _public(_get_addon(rec, rest[1]))}
            if m == "DELETE":
                return _delete_addon(rec, rest[1], q)
        elif len(rest) == 3 and rest[2] == "update" and m in ("PATCH", "POST"):
            return _update_addon(rec, rest[1], p)
    elif rest[0] == "access-entries":
        if len(rest) == 1:
            if m == "POST":
                return _create_access_entry(rec, region, p)
            if m == "GET":
                _need_api_mode(rec)
                pol = q.get("associatedPolicyArn")
                prs = sorted(pr for pr, e in rec["_access"].items() if not pol or pol in e["_policies"])
                return _page(prs, q, "accessEntries")
        else:
            mm = _ACCESS_RE.match(path)
            principal, pol_arn = mm.group(2), mm.group(3)
            has_pol = "/access-policies" in path[path.index("/access-entries/"):]
            if not has_pol:
                if m == "GET":
                    _need_api_mode(rec)
                    return {"accessEntry": _entry_view(_get_entry(rec, principal))}
                if m == "POST":
                    return _update_access_entry(rec, principal, p)
                if m == "DELETE":
                    _need_api_mode(rec)
                    _get_entry(rec, principal)
                    del rec["_access"][principal]
                    return {}
            elif pol_arn is None:
                if m == "POST":
                    return _associate_policy(rec, principal, p)
                if m == "GET":
                    _need_api_mode(rec)
                    e = _get_entry(rec, principal)
                    out = _page(sorted(e["_policies"].values(), key=lambda x: x["policyArn"]), q, "associatedAccessPolicies")
                    out.update({"clusterName": rec["name"], "principalArn": principal})
                    return out
            elif m == "DELETE":
                _need_api_mode(rec)
                e = _get_entry(rec, principal)
                if pol_arn not in e["_policies"]:
                    raise EksError("ResourceNotFoundException", "The specified access policy is not associated with this access entry.", clusterName=rec["name"], principalArn=principal)
                del e["_policies"][pol_arn]
                return {}
    elif rest[0] == "identity-provider-configs":
        if rest == ["identity-provider-configs"] and m == "GET":
            return _page([{"type": "oidc", "name": n} for n in sorted(rec["_idp"])], q, "identityProviderConfigs")
        if rest == ["identity-provider-configs", "associate"] and m == "POST":
            return _associate_idp(rec, region, p)
        if rest == ["identity-provider-configs", "disassociate"] and m == "POST":
            return _disassociate_idp(rec, p)
        if rest == ["identity-provider-configs", "describe"] and m == "POST":
            ref = p.get("identityProviderConfig") or {}
            cfg = rec["_idp"].get(ref.get("name"))
            if ref.get("type") != "oidc" or cfg is None:
                raise EksError("ResourceNotFoundException", "No identity provider config found for name: %s." % ref.get("name"), clusterName=rec["name"])
            return {"identityProviderConfig": {"oidc": _public(cfg)}}
    elif rest[0] == "vyomi" and rest == ["vyomi", "kubectl"] and m == "POST":
        _need_active(rec)
        rt = _runtime()
        if rt is None or not rt.exists("aws", rec["arn"]):
            raise EksError("ServiceUnavailableException", "This cluster has no Kubernetes API server on this runtime (needs the k3s backend).")
        _require(p, "command")
        return backend(acct, region, name).kubectl(p["command"], p.get("contextB64"))
    raise EksError("InvalidRequestException", "Unknown operation %s %s." % (m, path))
