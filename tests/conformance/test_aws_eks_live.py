"""LIVE Amazon EKS test: a REAL Kubernetes (rancher/k3s in Docker) behind the EKS API, driven only through boto3's `eks`, `ec2`, `iam`, `backup`
clients and the real AWS CLI (`aws eks get-token`). Skipped unless Docker is available, boto3 is importable AND VYOMI_LIVE_K3S=1.

Starts consoles/dev_server.py (VYOMI_K8S_BACKEND=k3s) on a free port and points boto3 at it. Flow:
  create_cluster -> CREATING -> (waiter) ACTIVE with the REAL endpoint + CA -> kubectl sees the control plane and CoreDNS
  create_nodegroup (1 node) -> a real agent node labelled eks.amazonaws.com/nodegroup joins -> a Deployment with that nodeSelector runs ON it
  AWS Backup: backup the cluster -> delete the namespace -> restore -> pod Running again
  access entry + policy -> the token the real `aws eks get-token` prints is verified and mapped to Kubernetes groups
  update_cluster_version, tags, add-ons, delete nodegroup, delete cluster -> every container and volume gone
Run: VYOMI_LIVE_K3S=1 PYTHONPATH=. python3 tests/conformance/test_aws_eks_live.py     (boto3 must be importable)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

APP = """apiVersion: v1
kind: Namespace
metadata: {name: live-app}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: live-app}
spec:
  replicas: 1
  selector: {matchLabels: {app: web}}
  template:
    metadata: {labels: {app: web}}
    spec:
      nodeSelector: {eks.amazonaws.com/nodegroup: live-ng}
      containers:
      - {name: web, image: "rancher/mirrored-pause:3.6", imagePullPolicy: IfNotPresent}
"""


def _check(n, c, detail=""):
    if not c:
        raise AssertionError("%s %s" % (n, detail))
    print("  ok ", n, flush=True)


def _until(fn, what, timeout=240, every=3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    raise AssertionError("timed out waiting for " + what)


MINE = {"prefix": None}      # server container name of THIS test's cluster: never touch anybody else's k3s clusters


def _docker_names():
    if not MINE["prefix"]:
        return []
    out = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return [n for n in out.split() if n.startswith(MINE["prefix"])]


def _docker_volumes():
    if not MINE["prefix"]:
        return []
    out = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True).stdout
    return [v for v in out.split() if v.startswith(MINE["prefix"])]


def run():
    import boto3
    from botocore.config import Config
    from core import aws_eks_auth as auth
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    p = port.getsockname()[1]
    port.close()
    env = dict(os.environ, VYOMI_K8S_BACKEND="k3s", PYTHONPATH=str(ROOT))
    srv = subprocess.Popen([sys.executable, str(ROOT / "consoles" / "dev_server.py"), "--port", str(p), "-q"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ep = "http://127.0.0.1:%d/_wire" % p
        _until(lambda: socket.socket().connect_ex(("127.0.0.1", p)) == 0, "dev server", 30, 0.5)
        kw = dict(endpoint_url=ep, region_name="us-east-1", aws_access_key_id="AKIAEKSLIVE", aws_secret_access_key="secret", config=Config(retries={"max_attempts": 1}))
        eks, ec2, iam, backup = (boto3.client(s, **kw) for s in ("eks", "ec2", "iam", "backup"))
        _check("list_clusters starts empty", eks.list_clusters()["clusters"] == [])

        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subs = [ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.%d.0/24" % i, AvailabilityZone="us-east-1" + az)["Subnet"]["SubnetId"] for i, az in ((1, "a"), (2, "b"))]
        role = iam.create_role(RoleName="eks-cluster", AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": []}))["Role"]["Arn"]
        nrole = iam.create_role(RoleName="eks-node", AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": []}))["Role"]["Arn"]

        try:
            eks.create_cluster(name="bad", roleArn=role, resourcesVpcConfig={"subnetIds": subs[:1]})
            _check("create_cluster with one subnet fails", False)
        except eks.exceptions.InvalidParameterException as e:
            _check("create_cluster with one subnet -> InvalidParameterException (typed boto3 exception)", "two different AZs" in str(e))

        t0 = time.time()
        c = eks.create_cluster(name="live", version="1.31", roleArn=role, resourcesVpcConfig={"subnetIds": subs}, tags={"env": "live"})["cluster"]
        from core import k3s_runtime
        MINE["prefix"] = k3s_runtime.server_name("aws", c["arn"])
        _check("create_cluster -> CREATING", c["status"] == "CREATING" and c["arn"].endswith(":cluster/live"))
        eks.get_waiter("cluster_active").wait(name="live", WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        c = eks.describe_cluster(name="live")["cluster"]
        print("   ACTIVE after %.0fs" % (time.time() - t0))
        _check("waiter cluster_active -> ACTIVE", c["status"] == "ACTIVE")
        _check("REAL endpoint + CA + OIDC issuer + network config + VPC config", c["endpoint"].startswith("https://127.0.0.1:") and len(c["certificateAuthority"]["data"]) > 100
               and "/id/" in c["identity"]["oidc"]["issuer"] and c["kubernetesNetworkConfig"]["ipFamily"] == "ipv4"
               and c["resourcesVpcConfig"]["subnetIds"] == subs and c["resourcesVpcConfig"]["vpcId"] == vpc and c["version"] == "1.31" and c["platformVersion"] == "eks.1")
        import base64
        _check("certificateAuthority.data is a real PEM", base64.b64decode(c["certificateAuthority"]["data"]).startswith(b"-----BEGIN CERTIFICATE-----"))
        _check("coredns + kube-proxy add-ons ACTIVE", sorted(eks.list_addons(clusterName="live")["addons"]) == ["coredns", "kube-proxy"])

        def kubectl(cmd):
            import urllib.request
            req = urllib.request.Request(ep + "/clusters/live/vyomi/kubectl", data=json.dumps({"command": cmd}).encode(), method="POST",
                                         headers={"authorization": "AWS4-HMAC-SHA256 Credential=X/20261109/us-east-1/eks/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=120).read())
        r = kubectl("kubectl get nodes -o wide")
        _check("kubectl through the EKS cluster sees the real k3s control-plane node", r["exitCode"] == 0 and "control-plane" in r["logs"], r)
        r = kubectl("kubectl get deploy -n kube-system")
        _check("CoreDNS is really deployed", "coredns" in r["logs"], r)

        ng = eks.create_nodegroup(clusterName="live", nodegroupName="live-ng", subnets=subs, nodeRole=nrole, scalingConfig={"minSize": 1, "maxSize": 2, "desiredSize": 1},
                                  instanceTypes=["t3.large"], labels={"tier": "web"})["nodegroup"]
        _check("create_nodegroup -> CREATING", ng["status"] == "CREATING")
        eks.get_waiter("nodegroup_active").wait(clusterName="live", nodegroupName="live-ng", WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        r = kubectl("kubectl get nodes -l eks.amazonaws.com/nodegroup=live-ng --show-labels --no-headers")
        _check("a real agent node with the EKS nodegroup + instance-type + custom labels joined", r["exitCode"] == 0 and "Ready" in r["logs"] and "tier=web" in r["logs"]
               and "node.kubernetes.io/instance-type=t3.large" in r["logs"], r)
        r = kubectl("kubectl apply -f - <<EOF\n%sEOF" % APP)
        _check("apply Deployment (nodeSelector = the nodegroup)", r["exitCode"] == 0, r)
        _until(lambda: "Running" in kubectl("kubectl get pods -n live-app -o wide --no-headers")["logs"], "pod Running", 180)
        pods = kubectl("kubectl get pods -n live-app -o wide --no-headers")["logs"]
        node = kubectl("kubectl get nodes -l eks.amazonaws.com/nodegroup=live-ng --no-headers")["logs"].split()[0]
        _check("the pod runs ON the nodegroup's node", node in pods, pods)

        # ── AWS Backup for EKS ──
        backup.create_backup_vault(BackupVaultName="eks-vault")
        job = backup.start_backup_job(BackupVaultName="eks-vault", ResourceArn=c["arn"], IamRoleArn="arn:aws:iam::123456789012:role/backup")["BackupJobId"]
        j = backup.describe_backup_job(BackupJobId=job)
        _check("AWS Backup job for the EKS cluster COMPLETED", j["State"] == "COMPLETED" and j["ResourceType"] == "EKS", j.get("StatusMessage"))
        rp = j["RecoveryPointArn"]
        kubectl("kubectl delete namespace live-app")
        _check("namespace deleted (disaster)", "live-app" not in kubectl("kubectl get ns --no-headers")["logs"])
        rj = backup.start_restore_job(RecoveryPointArn=rp, IamRoleArn="arn:aws:iam::123456789012:role/backup", Metadata={"ClusterName": "live"})["RestoreJobId"]
        d = backup.describe_restore_job(RestoreJobId=rj)
        _check("restore job COMPLETED into the cluster", d["Status"] == "COMPLETED" and d["CreatedResourceArn"] == c["arn"], d.get("StatusMessage"))
        _until(lambda: "Running" in kubectl("kubectl get pods -n live-app --no-headers")["logs"], "restored pod Running", 180)
        _check("restored Deployment's pod is Running again", True)

        # ── nodegroup scale + update records ──
        u = eks.update_nodegroup_config(clusterName="live", nodegroupName="live-ng", labels={"addOrUpdateLabels": {"x": "y"}})["update"]
        _until(lambda: eks.describe_update(name="live", updateId=u["id"], nodegroupName="live-ng")["update"]["status"] == "Successful", "nodegroup update", 30, 1)
        _check("update_nodegroup_config -> Successful; label stored", eks.describe_nodegroup(clusterName="live", nodegroupName="live-ng")["nodegroup"]["labels"]["x"] == "y")

        # ── cluster update ──
        u = eks.update_cluster_version(name="live", version="1.32")["update"]
        _check("update_cluster_version -> InProgress", u["status"] == "InProgress" and u["type"] == "VersionUpdate")
        eks.get_waiter("cluster_active").wait(name="live", WaiterConfig={"Delay": 2, "MaxAttempts": 30})
        _check("version now 1.32; update Successful; list_updates has it", eks.describe_cluster(name="live")["cluster"]["version"] == "1.32"
               and eks.describe_update(name="live", updateId=u["id"])["update"]["status"] == "Successful" and u["id"] in eks.list_updates(name="live")["updateIds"])
        eks.tag_resource(resourceArn=c["arn"], tags={"a": "b"})
        _check("tags round-trip", eks.list_tags_for_resource(resourceArn=c["arn"])["tags"] == {"env": "live", "a": "b"})
        eks.create_addon(clusterName="live", addonName="vpc-cni")
        _check("create_addon vpc-cni + describe_addon_versions", eks.describe_addon(clusterName="live", addonName="vpc-cni")["addon"]["status"] in ("CREATING", "ACTIVE")
               and eks.describe_addon_versions(addonName="vpc-cni")["addons"][0]["addonVersions"])

        # ── access entries + the REAL `aws eks get-token` ──
        iam.create_user(UserName="alice")
        k = iam.create_access_key(UserName="alice")["AccessKey"]
        arn = "arn:aws:iam::123456789012:user/alice"
        eks.create_access_entry(clusterName="live", principalArn=arn, kubernetesGroups=["devs"])
        eks.associate_access_policy(clusterName="live", principalArn=arn, policyArn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy", accessScope={"type": "namespace", "namespaces": ["live-app"]})
        entry = eks.describe_access_entry(clusterName="live", principalArn=arn)["accessEntry"]
        pols = eks.list_associated_access_policies(clusterName="live", principalArn=arn)["associatedAccessPolicies"]
        _check("access entry + namespace-scoped policy stored", entry["kubernetesGroups"] == ["devs"] and pols[0]["accessScope"]["namespaces"] == ["live-app"])
        if shutil.which("aws"):
            out = subprocess.run(["aws", "eks", "get-token", "--cluster-name", "live", "--region", "us-east-1"], capture_output=True, text=True,
                                 env=dict(os.environ, AWS_ACCESS_KEY_ID=k["AccessKeyId"], AWS_SECRET_ACCESS_KEY=k["SecretAccessKey"]))
            tok = json.loads(out.stdout)["status"]["token"]
            cluster = {"name": "live", "_access": {arn: {"type": "STANDARD", "username": entry["username"], "kubernetesGroups": entry["kubernetesGroups"],
                                                          "_policies": {x["policyArn"]: x for x in pols}}}}
            creds = lambda akid, tk=None: {"secret": k["SecretAccessKey"], "arn": arn, "account": "123456789012", "user_id": "AIDA"} if akid == k["AccessKeyId"] else None
            rv = auth.token_review({"spec": {"token": tok}}, cluster, creds)
            _check("token printed by the real `aws eks get-token` -> TokenReview authenticated, groups from the access entry/policy",
                   rv["status"]["authenticated"] and rv["status"]["user"]["groups"] == ["devs", "vyomi:eks:edit:live-app"], rv)
            bad = auth.token_review({"spec": {"token": tok}}, dict(cluster, name="another"), creds)
            _check("the same token is refused for another cluster", not bad["status"]["authenticated"])
        else:
            print("   skip: aws CLI not installed")

        # ── teardown ──
        eks.delete_nodegroup(clusterName="live", nodegroupName="live-ng")
        eks.get_waiter("nodegroup_deleted").wait(clusterName="live", nodegroupName="live-ng", WaiterConfig={"Delay": 3, "MaxAttempts": 60})
        _check("nodegroup deleted (waiter) and its agent container is gone", not [n for n in _docker_names() if "-ng-" in n])
        eks.delete_cluster(name="live")
        eks.get_waiter("cluster_deleted").wait(name="live", WaiterConfig={"Delay": 3, "MaxAttempts": 60})
        _until(lambda: not _docker_names(), "k3s containers removed", 60, 2)
        vols = _docker_volumes()
        _check("cluster deleted (waiter): server container + volumes gone, list_clusters empty", not vols and eks.list_clusters()["clusters"] == [])
    finally:
        srv.terminate()
        # belt and braces: anything this run left behind
        for n in _docker_names():
            subprocess.run(["docker", "rm", "-f", "-v", n], capture_output=True)
        for v in _docker_volumes():
            subprocess.run(["docker", "volume", "rm", "-f", v], capture_output=True)


if __name__ == "__main__":
    if os.environ.get("VYOMI_LIVE_K3S") != "1" or not shutil.which("docker"):
        print("SKIP: set VYOMI_LIVE_K3S=1 with Docker running")
        sys.exit(0)
    try:
        import boto3  # noqa: F401
    except ImportError:
        print("SKIP: boto3 not importable")
        sys.exit(0)
    run()
    print("OK aws_eks_live")
