"""Amazon EKS core (core/aws_eks_core.py + aws_eks_auth.py + aws_eks_nodes.py) against a FAKE docker (always runs; no Docker needed).
Everything goes through the real AwsWireRouter on the native EKS REST wire (SigV4 scope `eks`), the way boto3 / aws-cli reach it.
The live counterpart (real k3s, boto3) is tests/conformance/test_aws_eks_live.py.
Run: PYTHONPATH=. python3 tests/conformance/test_aws_eks_core.py"""
import base64
import json
import time
from urllib.parse import quote, parse_qsl

from core import aws_eks_auth as auth
from core import aws_eks_core as eks
from core import k3s_runtime as k3s
from core import kube_state_core as kube
from core.aws_wire_router import AwsWireRouter

KUBECONFIG = """apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: Q0FEQVRB
    server: https://127.0.0.1:6443
  name: default
users:
- name: default
  user: {client-certificate-data: Q0VSVA==, client-key-data: S0VZ}
"""


def _check(n, c, detail=None):
    if not c:
        raise AssertionError("%s %s" % (n, detail if detail is not None else ""))
    print("  ok ", n)


class FakeDocker:
    """Just enough docker for K3sRuntime + NodeProvisioner: containers keep their labels, kubectl answers nodes/coredns/readyz."""

    def __init__(self):
        self.containers, self.volumes, self.networks, self.kubectl_log, self.fail_run = {}, set(), set(), [], False

    def labels(self, name):
        a = self.containers[name]
        return [a[i + 1] for i, x in enumerate(a) if x == "--label"]

    def nodes(self, selector=None):
        out = []
        for n, a in self.containers.items():
            if "--node-label" in a or "agent" in a[-1:]:
                labels = {a[i + 1].split("=", 1)[0]: a[i + 1].split("=", 1)[1] for i, x in enumerate(a) if x == "--node-label"}
                out.append((n, labels))
        return out

    def __call__(self, args, stdin=None, timeout=120):
        a = list(args)
        if a[:2] == ["network", "inspect"]:
            return (0 if a[2] in self.networks else 1), "", ""
        if a[:2] == ["network", "create"]:
            self.networks.add(a[2]); return 0, "", ""
        if a[:2] == ["volume", "create"]:
            self.volumes.add(a[-1]); return 0, "", ""
        if a[:2] == ["volume", "ls"]:
            return 0, "\n".join(sorted(self.volumes)) + "\n", ""
        if a[:2] == ["volume", "rm"]:
            self.volumes.discard(a[-1]); return 0, "", ""
        if a[0] == "run":
            if self.fail_run and "agent" in a[-1:]:
                return 1, "", "no space left on device"
            self.containers[a[a.index("--name") + 1]] = a
            return 0, "cid\n", ""
        if a[:3] == ["inspect", "--type", "container"]:
            return (0 if a[3] in self.containers else 1), "", ""
        if a[0] == "ps":
            want = [a[i + 1].split("=", 1) for i, x in enumerate(a) if x == "--filter"]
            names = []
            for n in self.containers:
                ls = self.labels(n)
                if all(v in ls for k, v in want if k == "label"):
                    names.append(n)
            if "--format" in a and "vyomi.cloud" in a[a.index("--format") + 1]:
                return 0, "", ""
            return 0, "\n".join(names) + ("\n" if names else ""), ""
        if a[0] == "rm":
            self.containers.pop(a[-1], None); return 0, "", ""
        if a[0] == "port":
            return 0, "127.0.0.1:49152\n", ""
        if a[0] == "exec":
            if "cat" in a and k3s.KUBECONFIG_PATH in a:
                return 0, KUBECONFIG, ""
            if "cat" in a and "/var/lib/rancher/k3s/server/node-token" in a:
                return 0, "K10tokenhash::server:abc\n", ""
            if "kubectl" not in a:
                return 0, "", ""
            k = a[a.index("kubectl") + 1:]
            self.kubectl_log.append(k)
            if k[:2] == ["get", "--raw"]:
                return (0, "ok", "") if getattr(self, "ready", True) else (1, "", "not ready")
            if k[:2] == ["get", "nodes"]:
                rows = ["server Ready control-plane 1m v1"]
                sel = k[k.index("-l") + 1] if "-l" in k else None
                if sel:
                    key, _, val = sel.partition("=")
                    rows = ["%s Ready <none> 1m v1" % n for n, lab in self.nodes() if lab.get(key) == val]
                else:
                    rows += ["%s Ready <none> 1m v1" % n for n, _ in self.nodes()]
                return 0, "\n".join(rows) + "\n", ""
            if k[0] == "get":
                return 0, json.dumps({"items": []}), ""
            return 0, "ran %s\n" % " ".join(k), ""
        return 0, "", ""


def sig(svc="eks", region="us-east-1"):
    return {"authorization": "AWS4-HMAC-SHA256 Credential=AKIDTEST/20261109/%s/%s/aws4_request, SignedHeaders=host, Signature=0" % (region, svc)}


def run():
    eks.SYNC = True
    fd = FakeDocker()
    rt = k3s.K3sRuntime(docker=fd, sleep=lambda s: None)
    clock = [1_800_000_000.0]
    eks.NOW = lambda: clock[0]
    R = AwsWireRouter()

    def call(m, path, body=None, q=None, region="us-east-1"):
        out = R.handle(m, path, q or {}, {**sig(region=region), "content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
        raw = out["body"]
        doc = json.loads(raw) if raw else {}
        err = out["headers"].get("x-amzn-ErrorType") or out["headers"].get("x-amzn-errortype")
        return out["status"], doc, err

    def ec2(action, **p):
        form = "&".join("%s=%s" % (k, quote(str(v))) for k, v in {"Action": action, "Version": "2016-11-15", **p}.items())
        out = R.handle("POST", "/", {}, {**sig("ec2"), "content-type": "application/x-www-form-urlencoded"}, form.encode())
        return out["body"].decode()

    # ── routing + native degradation WITHOUT a runtime ──────────────────────────────────────────────────────────
    kube.CLUSTER_RUNTIME = None
    s, d, e = call("GET", "/clusters")
    _check("ListClusters routes by SigV4 scope `eks` and works without a runtime", s == 200 and d == {"clusters": []})
    s, d, e = call("POST", "/clusters", {"name": "x", "roleArn": "arn:aws:iam::123456789012:role/r", "resourcesVpcConfig": {"subnetIds": ["subnet-a", "subnet-b"]}})
    _check("CreateCluster without the k3s runtime -> native ServiceUnavailableException that names the backend",
           s == 503 and e == "ServiceUnavailableException" and "k3s" in d["message"] and "Nano" in d["message"])
    _check("nothing was stored", call("GET", "/clusters")[1] == {"clusters": []})

    # ── a VPC with subnets in two AZs, via the EC2 wire ────────────────────────────────────────────────────────
    import re
    vpc = re.search(r"<vpcId>(vpc-[^<]+)</vpcId>", ec2("CreateVpc", CidrBlock="10.0.0.0/16")).group(1)
    sn1 = re.search(r"<subnetId>([^<]+)</subnetId>", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.0.1.0/24", AvailabilityZone="us-east-1a")).group(1)
    sn2 = re.search(r"<subnetId>([^<]+)</subnetId>", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.0.2.0/24", AvailabilityZone="us-east-1b")).group(1)
    sn3 = re.search(r"<subnetId>([^<]+)</subnetId>", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.0.3.0/24", AvailabilityZone="us-east-1a")).group(1)
    ROLE = "arn:aws:iam::123456789012:role/eks-cluster-role"
    NROLE = "arn:aws:iam::123456789012:role/eks-node-role"
    body = {"name": "demo", "version": "1.31", "roleArn": ROLE, "resourcesVpcConfig": {"subnetIds": [sn1, sn2]}, "tags": {"env": "test"}}

    kube.CLUSTER_RUNTIME = rt
    kube.BACKEND_FACTORY = rt.backend_factory()
    for bad, msg in (({**body, "roleArn": "nope"}, "valid IAM role"), ({**body, "resourcesVpcConfig": {"subnetIds": [sn1]}}, "two different AZs"),
                     ({**body, "resourcesVpcConfig": {"subnetIds": [sn1, sn3]}}, "two different AZs"), ({**body, "resourcesVpcConfig": {"subnetIds": [sn1, "subnet-zzz"]}}, "does not exist"),
                     ({**body, "version": "0.9"}, "unsupported Kubernetes version"), ({**body, "name": "bad name"}, "Invalid cluster name"),
                     ({k: v for k, v in body.items() if k != "roleArn"}, "roleArn")):
        s, d, e = call("POST", "/clusters", bad)
        _check("CreateCluster rejects (%s)" % msg, s == 400 and e == "InvalidParameterException" and msg in d["message"])

    # ── cluster lifecycle: CREATING -> ACTIVE with the real fields ─────────────────────────────────────────────
    rt_ready = {"v": False}
    fd.ready = False
    orig_create = rt.create_cluster
    rt.create_cluster = lambda *a, on_ready=None, **k: orig_create(*a, **k)    # no background thread: readiness is resolved lazily on read
    s, d, e = call("POST", "/clusters", body)
    c = d["cluster"]
    _check("CreateCluster -> 200 CREATING with arn/version/roleArn/tags", s == 200 and c["status"] == "CREATING" and c["arn"] == "arn:aws:eks:us-east-1:123456789012:cluster/demo"
           and c["version"] == "1.31" and c["roleArn"] == ROLE and c["tags"] == {"env": "test"} and c["platformVersion"] == "eks.1")
    srv = k3s.server_name("aws", c["arn"])
    _check("a real k3s server container was started for cloud=aws", srv in fd.containers and k3s.NETWORK in fd.networks)
    _check("resourcesVpcConfig carries vpcId from the EC2 model + clusterSecurityGroupId", c["resourcesVpcConfig"]["vpcId"] == vpc and c["resourcesVpcConfig"]["clusterSecurityGroupId"].startswith("sg-")
           and c["resourcesVpcConfig"]["endpointPublicAccess"] is True and c["resourcesVpcConfig"]["publicAccessCidrs"] == ["0.0.0.0/0"])
    _check("identity.oidc.issuer is a simulator URL; kubernetesNetworkConfig present", c["identity"]["oidc"]["issuer"].startswith("https://oidc.eks.us-east-1.vyomi.local/id/")
           and c["kubernetesNetworkConfig"]["ipFamily"] == "ipv4" and "serviceIpv4Cidr" in c["kubernetesNetworkConfig"])
    _check("CREATING: no endpoint, empty certificateAuthority", "endpoint" not in c and c["certificateAuthority"] == {})
    _check("internal fields never leak", not any(k.startswith("_") for k in c))
    s, d, e = call("POST", "/clusters", body)
    _check("duplicate -> ResourceInUseException 409", s == 409 and e == "ResourceInUseException" and d["clusterName"] == "demo")
    _check("still CREATING until /readyz answers", call("GET", "/clusters/demo")[1]["cluster"]["status"] == "CREATING")
    fd.ready = True
    c = call("GET", "/clusters/demo")[1]["cluster"]
    _check("ACTIVE once the API server is ready", c["status"] == "ACTIVE")
    _check("endpoint + CA come from the REAL cluster (published port, kubeconfig CA)", c["endpoint"] == "https://127.0.0.1:49152" and c["certificateAuthority"]["data"] == "Q0FEQVRB")
    _check("ListClusters / paging", call("GET", "/clusters")[1] == {"clusters": ["demo"]} and call("GET", "/clusters", q={"maxResults": "1"})[1] == {"clusters": ["demo"]})
    _check("regional: another region sees nothing", call("GET", "/clusters", region="eu-west-1")[1] == {"clusters": []} and call("GET", "/clusters/demo", region="eu-west-1")[0] == 404)
    s, d, e = call("GET", "/clusters/nope")
    _check("DescribeCluster missing -> ResourceNotFoundException 404", s == 404 and e == "ResourceNotFoundException" and "No cluster found for name: nope." == d["message"])

    # ── add-ons k3s provides ───────────────────────────────────────────────────────────────────────────────────
    _check("coredns + kube-proxy reported installed (ACTIVE)", call("GET", "/clusters/demo/addons")[1] == {"addons": ["coredns", "kube-proxy"]}
           and call("GET", "/clusters/demo/addons/coredns")[1]["addon"]["status"] == "ACTIVE")
    s, d, e = call("GET", "/addons/supported-versions", q={"addonName": "vpc-cni", "kubernetesVersion": "1.31"})
    _check("DescribeAddonVersions lists vpc-cni versions with compatibilities", s == 200 and d["addons"][0]["addonName"] == "vpc-cni"
           and d["addons"][0]["addonVersions"][0]["compatibilities"][0]["clusterVersion"] == "1.31")
    s, d, e = call("POST", "/clusters/demo/addons", {"addonName": "aws-ebs-csi-driver", "addonVersion": "v1.38.1-eksbuild.1", "tags": {"a": "b"}})
    _check("CreateAddon -> CREATING, then ACTIVE", s == 200 and d["addon"]["status"] == "CREATING" and d["addon"]["addonVersion"] == "v1.38.1-eksbuild.1")
    clock[0] += 3
    _check("add-on ACTIVE after the transition", call("GET", "/clusters/demo/addons/aws-ebs-csi-driver")[1]["addon"]["status"] == "ACTIVE")
    s, d, e = call("POST", "/clusters/demo/addons", {"addonName": "aws-ebs-csi-driver"})
    _check("duplicate add-on -> ResourceInUseException", s == 409 and e == "ResourceInUseException")
    s, d, e = call("POST", "/clusters/demo/addons", {"addonName": "vpc-cni", "addonVersion": "v0.0.1"})
    _check("unsupported add-on version -> InvalidParameterException", s == 400 and "not supported" in d["message"])
    s, d, e = call("PATCH", "/clusters/demo/addons/aws-ebs-csi-driver/update", {"addonVersion": "v1.44.0-eksbuild.1"})
    uid = d["update"]["id"]
    _check("UpdateAddon -> update record (AddonUpdate, InProgress)", s == 200 and d["update"]["type"] == "AddonUpdate" and d["update"]["status"] == "InProgress")
    clock[0] += 3
    _check("DescribeUpdate scoped by addonName -> Successful + new version", call("GET", "/clusters/demo/updates/" + uid, q={"addonName": "aws-ebs-csi-driver"})[1]["update"]["status"] == "Successful"
           and call("GET", "/clusters/demo/addons/aws-ebs-csi-driver")[1]["addon"]["addonVersion"] == "v1.44.0-eksbuild.1")
    _check("ListUpdates scoped to the add-on", call("GET", "/clusters/demo/updates", q={"addonName": "aws-ebs-csi-driver"})[1] == {"updateIds": [uid]}
           and call("GET", "/clusters/demo/updates")[1] == {"updateIds": []})
    s, d, e = call("DELETE", "/clusters/demo/addons/aws-ebs-csi-driver")
    clock[0] += 3
    _check("DeleteAddon -> DELETING then gone", d["addon"]["status"] == "DELETING" and call("GET", "/clusters/demo/addons/aws-ebs-csi-driver")[0] == 404)

    # ── managed node groups -> real agents ─────────────────────────────────────────────────────────────────────
    ng = {"nodegroupName": "workers", "subnets": [sn1, sn2], "nodeRole": NROLE, "scalingConfig": {"minSize": 1, "maxSize": 3, "desiredSize": 2},
          "instanceTypes": ["t3.large"], "labels": {"tier": "app"}, "taints": [{"key": "dedicated", "value": "web", "effect": "NO_SCHEDULE"}], "tags": {"k": "v"}}
    for bad, msg in (({**ng, "scalingConfig": {"minSize": 3, "maxSize": 3, "desiredSize": 1}}, "Minimum capacity"), ({**ng, "nodeRole": "x"}, "valid IAM role"),
                     ({**ng, "subnets": ["subnet-zzz"]}, "does not exist"), ({**ng, "taints": [{"key": "a", "effect": "BAD"}]}, "Invalid taint")):
        s, d, e = call("POST", "/clusters/demo/node-groups", bad)
        _check("CreateNodegroup rejects (%s)" % msg, s == 400 and e == "InvalidParameterException" and msg in d["message"])
    s, d, e = call("POST", "/clusters/demo/node-groups", ng)
    n = d["nodegroup"]
    _check("CreateNodegroup -> nodegroupArn, scaling, labels, taints, version defaults to the cluster's", s == 200 and n["nodegroupArn"].startswith("arn:aws:eks:us-east-1:123456789012:nodegroup/demo/workers/")
           and n["scalingConfig"]["desiredSize"] == 2 and n["version"] == "1.31" and n["labels"] == {"tier": "app"} and n["amiType"] == "AL2023_x86_64_STANDARD")
    agents = [x for x in fd.containers if "-ng-workers-" in x]
    _check("2 real k3s agent containers launched with the EKS node labels + taint", len(agents) == 2 and all(
        "eks.amazonaws.com/nodegroup=workers" in fd.containers[x] and "node.kubernetes.io/instance-type=t3.large" in fd.containers[x] and "tier=app" in fd.containers[x]
        and "dedicated=web:NoSchedule" in fd.containers[x] and ("vyomi.k3s.name=" + srv) in fd.labels(x) for x in agents))
    _check("agents join the server with its node token", all("K3S_TOKEN=K10tokenhash::server:abc" in fd.containers[x] for x in agents))
    _check("nodegroup ACTIVE once its nodes are Ready", call("GET", "/clusters/demo/node-groups/workers")[1]["nodegroup"]["status"] == "ACTIVE")
    _check("ListNodegroups", call("GET", "/clusters/demo/node-groups")[1] == {"nodegroups": ["workers"]})
    s, d, e = call("POST", "/clusters/demo/node-groups", ng)
    _check("duplicate nodegroup -> ResourceInUseException", s == 409)
    s, d, e = call("POST", "/clusters/demo/node-groups", {**ng, "nodegroupName": "big", "scalingConfig": {"minSize": 1, "maxSize": 5, "desiredSize": 5}})
    _check("node cap -> ResourceLimitExceededException (native)", s == 400 and e == "ResourceLimitExceededException" and "VYOMI_EKS_MAX_NODES" in d["message"])
    s, d, e = call("POST", "/clusters/demo/node-groups/workers/update-config", {"scalingConfig": {"desiredSize": 1}, "labels": {"addOrUpdateLabels": {"x": "y"}}})
    _check("UpdateNodegroupConfig -> ConfigUpdate InProgress, group UPDATING", s == 200 and d["update"]["type"] == "ConfigUpdate" and call("GET", "/clusters/demo/node-groups/workers")[1]["nodegroup"]["status"] == "UPDATING")
    clock[0] += 3
    n = call("GET", "/clusters/demo/node-groups/workers")[1]["nodegroup"]
    _check("scale-down really removed an agent; group ACTIVE with new labels", n["status"] == "ACTIVE" and n["scalingConfig"]["desiredSize"] == 1 and n["labels"]["x"] == "y"
           and len([x for x in fd.containers if "-ng-workers-" in x]) == 1)
    s, d, e = call("DELETE", "/clusters/demo")
    _check("cluster with node groups cannot be deleted", s == 409 and "nodegroups attached" in d["message"])
    s, d, e = call("DELETE", "/clusters/demo/node-groups/workers")
    _check("DeleteNodegroup -> DELETING; agents + volumes removed; then gone", d["nodegroup"]["status"] == "DELETING" and not [x for x in fd.containers if "-ng-" in x]
           and not [v for v in fd.volumes if "-ng-" in v] and call("GET", "/clusters/demo/node-groups/workers")[0] == 404)

    # ── Fargate profiles (stored) ──────────────────────────────────────────────────────────────────────────────
    s, d, e = call("POST", "/clusters/demo/fargate-profiles", {"fargateProfileName": "fp1", "podExecutionRoleArn": NROLE, "selectors": [{"namespace": "default", "labels": {"a": "b"}}]})
    _check("CreateFargateProfile -> CREATING, subnets default to the cluster's", s == 200 and d["fargateProfile"]["status"] == "CREATING" and d["fargateProfile"]["subnets"] == [sn1, sn2]
           and d["fargateProfile"]["fargateProfileArn"].startswith("arn:aws:eks:us-east-1:123456789012:fargateprofile/demo/fp1/"))
    clock[0] += 3
    _check("Fargate profile ACTIVE + listed", call("GET", "/clusters/demo/fargate-profiles/fp1")[1]["fargateProfile"]["status"] == "ACTIVE" and call("GET", "/clusters/demo/fargate-profiles")[1] == {"fargateProfileNames": ["fp1"]})
    _check("Fargate reserved prefix rejected", call("POST", "/clusters/demo/fargate-profiles", {"fargateProfileName": "eks-x", "podExecutionRoleArn": NROLE, "selectors": [{"namespace": "a"}]})[0] == 400)
    call("DELETE", "/clusters/demo/fargate-profiles/fp1")
    clock[0] += 3
    _check("DeleteFargateProfile -> gone", call("GET", "/clusters/demo/fargate-profiles/fp1")[0] == 404)

    # ── cluster updates ────────────────────────────────────────────────────────────────────────────────────────
    s, d, e = call("POST", "/clusters/demo/updates", {"version": "1.33"})
    _check("UpdateClusterVersion skipping a minor -> InvalidParameterException", s == 400 and "Unsupported Kubernetes minor version update from 1.31 to 1.33" in d["message"])
    s, d, e = call("POST", "/clusters/demo/updates", {"version": "1.32"})
    u = d["update"]
    _check("UpdateClusterVersion -> VersionUpdate InProgress params; cluster UPDATING", s == 200 and u["type"] == "VersionUpdate" and {"type": "Version", "value": "1.32"} in u["params"]
           and call("GET", "/clusters/demo")[1]["cluster"]["status"] == "UPDATING")
    s, d, e = call("POST", "/clusters/demo/update-config", {"logging": {"clusterLogging": [{"types": ["api"], "enabled": True}]}})
    _check("a second update while one is running -> ResourceInUseException", s == 409)
    clock[0] += 3
    c = call("GET", "/clusters/demo")[1]["cluster"]
    _check("version applied + ACTIVE + kube-proxy add-on version follows", c["version"] == "1.32" and c["status"] == "ACTIVE"
           and call("GET", "/clusters/demo/addons/kube-proxy")[1]["addon"]["addonVersion"].startswith("v1.32"))
    _check("DescribeUpdate Successful", call("GET", "/clusters/demo/updates/" + u["id"])[1]["update"]["status"] == "Successful")
    s, d, e = call("POST", "/clusters/demo/update-config", {"logging": {"clusterLogging": [{"types": ["api", "audit"], "enabled": True}]}})
    _check("UpdateClusterConfig(logging) -> LoggingUpdate", s == 200 and d["update"]["type"] == "LoggingUpdate")
    clock[0] += 3
    lg = call("GET", "/clusters/demo")[1]["cluster"]["logging"]["clusterLogging"]
    _check("logging config applied (enabled types listed first)", {"types": ["api", "audit"], "enabled": True} in lg)
    s, d, e = call("POST", "/clusters/demo/update-config", {"logging": {"clusterLogging": [{"types": ["api"], "enabled": True}]}})
    _check("no-op logging change rejected like EKS", s == 400 and "No changes needed" in d["message"])
    s, d, e = call("POST", "/clusters/demo/update-config", {"resourcesVpcConfig": {"endpointPrivateAccess": True, "endpointPublicAccess": False}})
    clock[0] += 3
    v = call("GET", "/clusters/demo")[1]["cluster"]["resourcesVpcConfig"]
    _check("endpoint access update applied (EndpointAccessUpdate)", d["update"]["type"] == "EndpointAccessUpdate" and v["endpointPrivateAccess"] is True and v["endpointPublicAccess"] is False)
    s, d, e = call("POST", "/clusters/demo/update-config", {})
    _check("empty UpdateClusterConfig rejected", s == 400)

    # ── access entries ─────────────────────────────────────────────────────────────────────────────────────────
    PR = "arn:aws:iam::123456789012:role/dev-role"
    q = quote(PR, safe="")
    s, d, e = call("GET", "/clusters/demo/access-entries")
    _check("bootstrap creator-admin entry exists (root, ClusterAdmin)", s == 200 and d["accessEntries"] == ["arn:aws:iam::123456789012:root"])
    s, d, e = call("POST", "/clusters/demo/access-entries", {"principalArn": PR, "kubernetesGroups": ["devs"], "tags": {"t": "1"}})
    _check("CreateAccessEntry (STANDARD, default username {{SessionName}})", s == 200 and d["accessEntry"]["type"] == "STANDARD" and d["accessEntry"]["kubernetesGroups"] == ["devs"]
           and "{{SessionName}}" in d["accessEntry"]["username"] and d["accessEntry"]["accessEntryArn"].startswith("arn:aws:eks:us-east-1:123456789012:access-entry/demo/role/123456789012/dev-role/"))
    _check("duplicate -> ResourceInUseException", call("POST", "/clusters/demo/access-entries", {"principalArn": PR})[0] == 409)
    _check("system: groups are rejected", call("POST", "/clusters/demo/access-entries", {"principalArn": "arn:aws:iam::123456789012:user/x", "kubernetesGroups": ["system:masters"]})[0] == 400)
    _check("non-IAM principal rejected", call("POST", "/clusters/demo/access-entries", {"principalArn": "foo"})[0] == 400)
    _check("DescribeAccessEntry by URL-encoded principal ARN", call("GET", "/clusters/demo/access-entries/" + q)[1]["accessEntry"]["principalArn"] == PR)
    _check("... and by the decoded path (framework already decoded %2F)", call("GET", "/clusters/demo/access-entries/" + PR)[1]["accessEntry"]["principalArn"] == PR)
    s, d, e = call("POST", "/clusters/demo/access-entries/" + q, {"kubernetesGroups": ["devs", "ops"]})
    _check("UpdateAccessEntry", d["accessEntry"]["kubernetesGroups"] == ["devs", "ops"])
    POL = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
    s, d, e = call("POST", "/clusters/demo/access-entries/%s/access-policies" % q, {"policyArn": POL, "accessScope": {"type": "namespace", "namespaces": ["dev"]}})
    _check("AssociateAccessPolicy (namespace scope)", s == 200 and d["associatedAccessPolicy"]["accessScope"] == {"type": "namespace", "namespaces": ["dev"]})
    _check("namespace scope requires namespaces", call("POST", "/clusters/demo/access-entries/%s/access-policies" % q, {"policyArn": POL, "accessScope": {"type": "namespace"}})[0] == 400)
    _check("unknown policy rejected", call("POST", "/clusters/demo/access-entries/%s/access-policies" % q, {"policyArn": "arn:aws:eks::aws:cluster-access-policy/Nope", "accessScope": {"type": "cluster"}})[0] == 400)
    s, d, e = call("GET", "/clusters/demo/access-entries/%s/access-policies" % q)
    _check("ListAssociatedAccessPolicies", [p["policyArn"] for p in d["associatedAccessPolicies"]] == [POL] and d["principalArn"] == PR)
    _check("ListAccessPolicies catalogue", any(p["name"] == "AmazonEKSClusterAdminPolicy" for p in call("GET", "/access-policies")[1]["accessPolicies"]))
    _check("ListAccessEntries filtered by associatedPolicyArn", call("GET", "/clusters/demo/access-entries", q={"associatedPolicyArn": POL})[1]["accessEntries"] == [PR])
    _check("DisassociateAccessPolicy", call("DELETE", "/clusters/demo/access-entries/%s/access-policies/%s" % (q, quote(POL, safe="")))[0] == 200
           and call("GET", "/clusters/demo/access-entries/%s/access-policies" % q)[1]["associatedAccessPolicies"] == [])
    call("POST", "/clusters/demo/access-entries/%s/access-policies" % q, {"policyArn": POL, "accessScope": {"type": "namespace", "namespaces": ["dev"]}})
    _check("DeleteAccessEntry", call("DELETE", "/clusters/demo/access-entries/" + q)[0] == 200 and call("GET", "/clusters/demo/access-entries/" + q)[0] == 404)
    call("POST", "/clusters/demo/access-entries", {"principalArn": PR, "kubernetesGroups": ["devs"]})
    call("POST", "/clusters/demo/access-entries/%s/access-policies" % q, {"policyArn": POL, "accessScope": {"type": "namespace", "namespaces": ["dev"]}})

    # ── OIDC identity providers ────────────────────────────────────────────────────────────────────────────────
    s, d, e = call("POST", "/clusters/demo/identity-provider-configs/associate", {"oidc": {"identityProviderConfigName": "okta", "issuerUrl": "https://dev.okta.com", "clientId": "abc", "usernameClaim": "email"}, "tags": {"a": "b"}})
    _check("AssociateIdentityProviderConfig -> update", s == 200 and d["update"]["type"] == "AssociateIdentityProviderConfig" and d["tags"] == {"a": "b"})
    clock[0] += 3
    s, d, e = call("POST", "/clusters/demo/identity-provider-configs/describe", {"identityProviderConfig": {"type": "oidc", "name": "okta"}})
    _check("DescribeIdentityProviderConfig ACTIVE", d["identityProviderConfig"]["oidc"]["status"] == "ACTIVE" and d["identityProviderConfig"]["oidc"]["usernameClaim"] == "email")
    _check("ListIdentityProviderConfigs", call("GET", "/clusters/demo/identity-provider-configs")[1] == {"identityProviderConfigs": [{"type": "oidc", "name": "okta"}]})
    _check("second OIDC config refused", call("POST", "/clusters/demo/identity-provider-configs/associate", {"oidc": {"identityProviderConfigName": "o2", "issuerUrl": "https://x", "clientId": "c"}})[0] == 409)
    call("POST", "/clusters/demo/identity-provider-configs/disassociate", {"identityProviderConfig": {"type": "oidc", "name": "okta"}})
    clock[0] += 3
    _check("Disassociate -> gone", call("GET", "/clusters/demo/identity-provider-configs")[1] == {"identityProviderConfigs": []})

    # ── tags (cluster + nodegroup arn) ─────────────────────────────────────────────────────────────────────────
    carn = c["arn"]
    _check("TagResource / ListTagsForResource", call("POST", "/tags/" + quote(carn, safe=""), {"tags": {"x": "1"}})[0] == 200 and call("GET", "/tags/" + quote(carn, safe=""))[1]["tags"] == {"env": "test", "x": "1"})
    _check("UntagResource (tagKeys joined by the ingress)", call("DELETE", "/tags/" + quote(carn, safe=""), q={"tagKeys": "x,env"})[0] == 200 and call("GET", "/tags/" + carn)[1]["tags"] == {})
    _check("tags on an unknown resource -> NotFoundException 404", call("GET", "/tags/arn:aws:eks:us-east-1:123456789012:cluster/zzz")[0] == 404)
    _check("DescribeClusterVersions", any(v["clusterVersion"] == "1.33" and v["defaultVersion"] for v in call("GET", "/cluster-versions")[1]["clusterVersions"]))

    # ── kubectl extension + backend ────────────────────────────────────────────────────────────────────────────
    s, d, e = call("POST", "/clusters/demo/vyomi/kubectl", {"command": "kubectl get pods -A"})
    _check("Vyomi kubectl extension runs kubectl on the REAL server container", s == 200 and d["exitCode"] == 0 and ["get", "pods", "-A"] in fd.kubectl_log)
    _check("backend() is a RealK8sBackend (what AWS Backup for EKS uses)", isinstance(eks.backend(R.s3.account, "us-east-1", "demo"), kube.RealK8sBackend))

    # ── AWS Backup for EKS (real vault/job/recovery point/restore over the real backend) ───────────────────────
    BK = lambda m, p, b=None: (lambda o: (o["status"], json.loads(o["body"] or b"{}")))(R.handle(m, p, {}, {**sig("backup"), "content-type": "application/json"}, json.dumps(b).encode() if b is not None else b""))
    BK("PUT", "/backup-vaults/eksvault", {})
    s, d = BK("PUT", "/backup-jobs", {"BackupVaultName": "eksvault", "ResourceArn": carn, "IamRoleArn": ROLE.replace("eks-cluster-role", "backup")})
    jid = d["BackupJobId"]
    s, j = BK("GET", "/backup-jobs/" + jid)
    _check("StartBackupJob on an EKS cluster ARN -> COMPLETED, ResourceType EKS", j["State"] == "COMPLETED" and j["ResourceType"] == "EKS", j)
    rp = j["RecoveryPointArn"]
    s, rest = BK("PUT", "/restore-jobs", {"RecoveryPointArn": rp, "IamRoleArn": ROLE, "Metadata": {"ClusterName": "demo"}})
    s, rj = BK("GET", "/restore-jobs/" + rest["RestoreJobId"])
    _check("restore into the cluster -> COMPLETED, CreatedResourceArn is the cluster", rj["Status"] == "COMPLETED" and rj["CreatedResourceArn"] == carn, rj)

    # ── delete ─────────────────────────────────────────────────────────────────────────────────────────────────
    s, d, e = call("DELETE", "/clusters/demo")
    _check("DeleteCluster -> DELETING then DescribeCluster 404; container + volume gone", d["cluster"]["status"] == "DELETING" and call("GET", "/clusters/demo")[0] == 404
           and srv not in fd.containers and not fd.volumes)
    _check("k3s server container removed", srv not in fd.containers)

    # ── auth ───────────────────────────────────────────────────────────────────────────────────────────────────
    test_auth()


def test_auth():
    from datetime import datetime, timezone, timedelta
    class Iam:
        access_keys = {"AKIAUSER": {"user_name": "alice", "status": "Active", "secret_access_key": "s3cr3t"}}
    creds = auth.iam_store_credentials(Iam())
    cluster = {"name": "demo", "_access": {
        "arn:aws:iam::123456789012:user/alice": {"type": "STANDARD", "username": "", "kubernetesGroups": ["devs"], "_policies": {
            "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy": {"policyArn": "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy", "accessScope": {"type": "cluster"}}}},
        "arn:aws:iam::123456789012:role/dev": {"type": "STANDARD", "username": "dev:{{SessionName}}", "kubernetesGroups": [], "_policies": {
            "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy": {"policyArn": "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy", "accessScope": {"type": "namespace", "namespaces": ["dev", "qa"]}}}}}}
    now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
    tok = auth.generate_token("demo", "AKIAUSER", "s3cr3t", "us-east-1", now=now)
    _check("token has the k8s-aws-v1. prefix and base64url-encoded presigned STS URL", tok.startswith("k8s-aws-v1.") and auth.decode_token(tok).startswith("https://sts.us-east-1.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15"))
    ident = auth.verify_token(tok, "demo", creds, now=now + timedelta(seconds=5))
    _check("verify_token resolves the IAM user", ident["arn"] == "arn:aws:iam::123456789012:user/alice" and ident["principal"] == ident["arn"] and ident["accessKeyId"] == "AKIAUSER")

    def rej(code, token, cluster_name="demo", at=None, cr=creds, **kw):
        try:
            auth.verify_token(token, cluster_name, cr, now=at or now, **kw)
        except auth.TokenError as e:
            return e.code == code
        return False
    _check("token for ANOTHER cluster is rejected (x-k8s-aws-id is signed)", rej("SignatureDoesNotMatch", tok, "other"))
    _check("wrong secret -> SignatureDoesNotMatch", rej("SignatureDoesNotMatch", auth.generate_token("demo", "AKIAUSER", "WRONG", now=now)))
    _check("unknown access key -> InvalidClientTokenId", rej("InvalidClientTokenId", auth.generate_token("demo", "AKIANOPE", "s3cr3t", now=now)))
    _check("older than 15 minutes -> ExpiredToken", rej("ExpiredToken", tok, at=now + timedelta(minutes=16)))
    _check("dated in the future -> InvalidToken", rej("InvalidToken", tok, at=now - timedelta(minutes=30)))
    _check("missing prefix -> InvalidToken", rej("InvalidToken", tok[len("k8s-aws-v1."):]))
    evil = "k8s-aws-v1." + base64.urlsafe_b64encode(auth.decode_token(tok).replace("sts.us-east-1.amazonaws.com", "evil.example.com").encode()).decode().rstrip("=")
    _check("non-STS host -> InvalidToken", rej("InvalidToken", evil))
    _check("simulator STS host accepted when configured", auth.verify_token(auth.generate_token("demo", "AKIAUSER", "s3cr3t", now=now, host="127.0.0.1:8099"), "demo", creds, now=now,
                                                                         extra_hosts=("127.0.0.1",))["arn"].endswith("user/alice"))
    notag = auth.decode_token(tok).replace("host%3Bx-k8s-aws-id", "host")
    _check("token without x-k8s-aws-id signed -> InvalidToken", rej("InvalidToken", "k8s-aws-v1." + base64.urlsafe_b64encode(notag.encode()).decode().rstrip("=")))
    longexp = auth.decode_token(tok).replace("X-Amz-Expires=60", "X-Amz-Expires=3600")
    _check("X-Amz-Expires > 60 -> InvalidToken", rej("InvalidToken", "k8s-aws-v1." + base64.urlsafe_b64encode(longexp.encode()).decode().rstrip("=")))

    k = auth.authorize(cluster, ident)
    _check("cluster-admin access entry -> system:masters + its kubernetesGroups; username = user ARN",
           k["username"] == "arn:aws:iam::123456789012:user/alice" and "system:masters" in k["groups"] and "devs" in k["groups"] and k["bindings"][0]["clusterRole"] == "cluster-admin")
    role_ident = {"arn": "arn:aws:sts::123456789012:assumed-role/dev/bob", "principal": auth.canonical_principal("arn:aws:sts::123456789012:assumed-role/dev/bob"), "account": "123456789012", "user_id": "AROA", "sessionName": "bob"}
    kr = auth.authorize(cluster, role_ident)
    _check("assumed-role -> role entry; {{SessionName}} substituted; namespace-scoped groups", role_ident["principal"] == "arn:aws:iam::123456789012:role/dev" and kr["username"] == "dev:bob"
           and kr["groups"] == ["vyomi:eks:edit:dev", "vyomi:eks:edit:qa"])
    _check("principal without an access entry -> None", auth.authorize(cluster, {**role_ident, "principal": "arn:aws:iam::123456789012:role/stranger"}) is None)
    rv = auth.token_review({"apiVersion": "authentication.k8s.io/v1", "kind": "TokenReview", "spec": {"token": tok}}, cluster, creds, now=now)
    _check("TokenReview: authenticated user with groups + extra", rv["status"]["authenticated"] is True and rv["status"]["user"]["username"].endswith("user/alice") and "system:masters" in rv["status"]["user"]["groups"])
    rv = auth.token_review({"spec": {"token": "garbage"}}, cluster, creds, now=now)
    _check("TokenReview: bad token -> authenticated=false with error (never raises)", rv["status"]["authenticated"] is False and "InvalidToken" in rv["status"]["error"])
    rv = auth.token_review({"spec": {"token": auth.generate_token("demo", "AKIAUSER", "s3cr3t", now=now)}}, {"name": "demo", "_access": {}}, creds, now=now)
    _check("TokenReview: valid IAM identity without access entry -> denied", rv["status"]["authenticated"] is False and "no access entry" in rv["status"]["error"])

    try:
        import botocore.auth as ba, botocore.awsrequest as bar, botocore.credentials as bc
    except ImportError:
        print("  skip botocore-compat (botocore not installed)")
        return
    # byte-compat with botocore's own SigV4 presigner (what `aws eks get-token` uses)
    req = bar.AWSRequest(method="GET", url="https://sts.us-east-1.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15", headers={"x-k8s-aws-id": "demo"})
    ba.SigV4QueryAuth(bc.Credentials("AKIAUSER", "s3cr3t"), "sts", "us-east-1", expires=60).add_auth(req)   # botocore stamps the real clock
    boto_tok = "k8s-aws-v1." + base64.urlsafe_b64encode(req.url.encode()).decode().rstrip("=")
    issued = datetime.strptime(dict(parse_qsl(req.url.split("?", 1)[1]))["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    _check("a token minted by botocore's own presigner verifies, and equals generate_token for the same instant",
           auth.verify_token(boto_tok, "demo", creds, now=issued)["arn"].endswith("user/alice") and boto_tok == auth.generate_token("demo", "AKIAUSER", "s3cr3t", now=issued))


if __name__ == "__main__":
    run()
    print("OK aws_eks_core")
