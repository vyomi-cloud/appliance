"""LIVE k3s test: a REAL Kubernetes (rancher/k3s in Docker) behind AKS, driven only through the native ARM wire.
Skipped unless Docker is available AND VYOMI_LIVE_K3S=1.  Pulls the single rancher/k3s image; removes everything it creates.
Flow: create AKS cluster -> k3s Ready -> apply a Deployment (hermetic pause image, no registry pull) -> pod Running ->
Azure Backup for AKS backup -> delete namespace -> restore -> pod Running again -> delete cluster (container + volume gone).
Run: VYOMI_LIVE_K3S=1 PYTHONPATH=. python3 tests/conformance/test_k3s_live.py"""
import base64
import os
import shutil
import subprocess
import sys
import time

from core import k3s_runtime as k3s
from core import kube_state_core as kube
from core import azure_dataprotection_core as dp
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from core.azure_blob_core import AzureBlobStore

# the pause image ships inside the k3s image, so the Deployment starts with no network pull
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
      containers:
      - {name: web, image: "rancher/mirrored-pause:3.6", imagePullPolicy: IfNotPresent}
---
apiVersion: v1
kind: ConfigMap
metadata: {name: cfg, namespace: live-app}
data: {hello: world}
"""


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n, flush=True)


def _until(fn, what, timeout=180, every=3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    raise AssertionError("timed out waiting for " + what)


def run():
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    rt = k3s.install(k3s.K3sRuntime())
    R = f"/subscriptions/{S}/resourceGroups"
    CL = f"{R}/rg1/providers/Microsoft.ContainerService/managedClusters/live1"
    h = lambda m, p, b=None, av="2024-04-01": a.handle(m, p, {"api-version": av}, b)
    kc = lambda cmd: h("POST", CL + "/runCommand", {"command": cmd}, "2024-09-02-preview")["body"]["properties"]
    try:
        h("PUT", f"{R}/rg1", {"location": "eastus"}, "2021-04-01")
        r = h("PUT", CL, {"location": "eastus", "properties": {"kubernetesVersion": "1.30.5", "dnsPrefix": "live", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_B2s", "mode": "System"}]}}, "2024-09-02-preview")
        _check("AKS PUT accepted, state Creating", r["status"] in (200, 201) and r["body"]["properties"]["provisioningState"] in ("Creating", "Succeeded"))
        _until(lambda: h("GET", CL, None, "2024-09-02-preview")["body"]["properties"]["provisioningState"] in ("Succeeded", "Failed"), "provisioning", 400)
        _check("provisioningState Succeeded (k3s API + node Ready)", h("GET", CL, None, "2024-09-02-preview")["body"]["properties"]["provisioningState"] == "Succeeded")
        cred = h("POST", CL + "/listClusterUserCredential", None, "2024-09-02-preview")["body"]["kubeconfigs"][0]["value"]
        kcfg = base64.b64decode(cred).decode()
        _check("get-credentials returns a real kubeconfig (client cert)", "client-certificate-data:" in kcfg and "server: https://127.0.0.1:" in kcfg)
        v = kc("kubectl version")
        _check("kubectl version talks to a real API server (k3s)", v["exitCode"] == 0 and "k3s" in v["logs"])
        _check("deploy app via runCommand", kc("kubectl apply -f - <<EOF\n" + APP + "EOF")["exitCode"] == 0)
        _until(lambda: "Running" in kc("kubectl get pods -n live-app")["logs"], "pod Running", 240)
        _check("pod reaches Running on the real kubelet", True)

        P = f"{R}/rg1/providers/Microsoft.DataProtection/backupVaults/live-vault"
        h("PUT", P, {"location": "eastus", "properties": {"storageSettings": [{"datastoreType": "VaultStore", "type": "LocallyRedundant"}]}})
        h("PUT", P + "/backupPolicies/pol", {"properties": {"objectType": "BackupPolicy", "datasourceTypes": ["Microsoft.ContainerService/managedClusters"], "policyRules": [{"objectType": "AzureBackupRule", "name": "BackupDaily"}]}})
        I = P + "/backupInstances/i1"
        _check("backup instance", h("PUT", I, {"properties": {"objectType": "BackupInstance", "dataSourceInfo": {"resourceID": CL, "datasourceType": "Microsoft.ContainerService/managedClusters"}, "policyInfo": {"policyId": P + "/backupPolicies/pol"}}})["status"] == 201)
        dp.JOB_SECONDS = 0.5
        _check("backup accepted", h("POST", I + "/backup", {"backupRuleOptions": {"ruleName": "BackupDaily", "triggerOption": {"retentionTagOverride": "Default"}}})["status"] == 202)
        time.sleep(1)
        rps = _until(lambda: (kc("kubectl get ns") or True) and h("GET", I + "/recoveryPoints")["body"]["value"], "recovery point", 60, 1)
        c = rps[0]["properties"]["vyomiContents"]
        _check("recovery point exported REAL objects (deployment + configmap)", c.get("deployments") == 1 and c.get("configmaps", 0) >= 1)
        _check("recovery point has no controller-owned pods/replicasets", "replicasets" not in c)

        _check("disaster: delete namespace", kc("kubectl delete namespace live-app")["exitCode"] == 0)
        _check("namespace really gone", "No resources found" in kc("kubectl get deployments -n live-app")["logs"] or "not found" in kc("kubectl get deployments -n live-app")["logs"].lower())
        body = {"restoreRequestObject": {"objectType": "AzureBackupRecoveryPointBasedRestoreRequest", "recoveryPointId": rps[0]["name"], "sourceDataStoreType": "VaultStore"}}
        _check("restore accepted", h("POST", I + "/restore", body)["status"] == 202)
        time.sleep(1)
        kc("kubectl get ns")                               # runCommand completes the due job first
        _until(lambda: "web" in kc("kubectl get deployments -n live-app")["logs"], "deployment restored", 60, 2)
        _check("restore re-created the deployment on the real cluster", True)
        _until(lambda: "Running" in kc("kubectl get pods -n live-app")["logs"], "restored pod Running", 240)
        _check("restored pod is Running again", True)
        _check("configmap restored", "world" in kc("kubectl get cm cfg -n live-app -o yaml")["logs"])
    finally:
        name = k3s.server_name("azure", CL if False else f"{R}/rg1/providers/Microsoft.ContainerService/managedClusters/live1")
        h("DELETE", CL, None, "2024-09-02-preview")
        left = subprocess.run(["docker", "ps", "-a", "--filter", "name=" + name, "-q"], capture_output=True, text=True).stdout.split()
        vols = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "label=vyomi.k3s.name=" + name], capture_output=True, text=True).stdout.split()
        _check("AKS DELETE removed the k3s container(s) and volume(s)", not left and not vols)
        kube.CLUSTER_RUNTIME = kube.BACKEND_FACTORY = None
    print("k3s live: ok")


if __name__ == "__main__":
    if os.environ.get("VYOMI_LIVE_K3S") != "1" or not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("SKIP: needs docker and VYOMI_LIVE_K3S=1")
        sys.exit(0)
    run()
