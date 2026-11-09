"""Azure Backup for AKS (Microsoft.DataProtection) + the shared kube state layer (core/kube_state_core.py).
Scenario: vault -> policy -> backup instance -> deploy app -> ad-hoc backup (async) -> delete namespace -> restore -> resources back.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_dataprotection_core.py"""
import time

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from core.azure_blob_core import AzureBlobStore
from core import azure_dataprotection_core as dp
from core import kube_state_core as kube


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


APP = """apiVersion: v1
kind: Namespace
metadata: {name: simulation-app}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: simulation-app}
spec:
  replicas: 2
  selector: {matchLabels: {app: web}}
  template:
    metadata: {labels: {app: web}}
    spec: {containers: [{name: web, image: nginx}]}
---
apiVersion: v1
kind: Service
metadata: {name: web, namespace: simulation-app}
spec: {selector: {app: web}, ports: [{port: 80}]}
"""


def run():
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    h = lambda m, p, b=None, av="2024-04-01": a.handle(m, p, {"api-version": av}, b)
    R = f"/subscriptions/{S}/resourceGroups"
    h("PUT", f"{R}/rg1", {"location": "eastus"}, "2021-04-01")
    CL = f"{R}/rg1/providers/Microsoft.ContainerService/managedClusters/aks1"
    _check("cluster", h("PUT", CL, {"location": "eastus", "properties": {"kubernetesVersion": "1.29.0", "dnsPrefix": "a", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_B2s", "mode": "System"}]}}, "2024-09-02-preview")["status"] in (200, 201))
    kc = lambda cmd: h("POST", CL + "/runCommand", {"command": cmd}, "2024-09-02-preview")["body"]["properties"]["logs"]
    P = f"{R}/rg1/providers/Microsoft.DataProtection/backupVaults/sim-vault"

    _check("bad vault name", h("PUT", P.replace("sim-vault", "1x"), {"location": "eastus"})["status"] == 400)
    _check("vault needs location", h("PUT", P, {})["status"] == 400)
    _check("vault created", h("PUT", P, {"location": "eastus", "properties": {"storageSettings": [{"datastoreType": "VaultStore", "type": "LocallyRedundant"}]}})["status"] == 201)
    _check("vault listed (rg + subscription)", len(h("GET", f"{R}/rg1/providers/Microsoft.DataProtection/backupVaults")["body"]["value"]) == 1
           and len(h("GET", f"/subscriptions/{S}/providers/Microsoft.DataProtection/backupVaults")["body"]["value"]) == 1)
    pol = {"properties": {"objectType": "BackupPolicy", "datasourceTypes": ["Microsoft.ContainerService/managedClusters"], "policyRules": [{"objectType": "AzureBackupRule", "name": "BackupDaily"}]}}
    _check("policy with wrong datasource rejected", h("PUT", P + "/backupPolicies/pol", {"properties": dict(pol["properties"], datasourceTypes=["x"])})["status"] == 400)
    _check("policy created", h("PUT", P + "/backupPolicies/pol", pol)["status"] == 201)
    inst = {"properties": {"objectType": "BackupInstance", "dataSourceInfo": {"resourceID": CL, "datasourceType": "Microsoft.ContainerService/managedClusters"}, "policyInfo": {"policyId": P + "/backupPolicies/pol"}}}
    _check("instance needs an existing cluster", h("PUT", P + "/backupInstances/i0", {"properties": dict(inst["properties"], dataSourceInfo={"resourceID": CL + "x"})})["status"] == 404)
    _check("instance created", h("PUT", P + "/backupInstances/aks-cluster-instance", inst)["status"] == 201)
    _check("second instance for same cluster rejected", h("PUT", P + "/backupInstances/other", inst)["status"] == 409)
    _check("policy in use cannot be deleted", h("DELETE", P + "/backupPolicies/pol")["status"] == 409)
    _check("vault with instances cannot be deleted", h("DELETE", P)["status"] == 409)
    I = P + "/backupInstances/aks-cluster-instance"

    _check("deploy app", "created" in kc("kubectl apply -f - <<EOF\n" + APP + "EOF"))
    _check("kubectl get pods lists the app", kc("kubectl get pods -n simulation-app").count("Pending") == 2)

    _check("scale deployment -> pods follow", "scaled" in kc("kubectl scale deployment web --replicas=3 -n simulation-app") and kc("kubectl get pods -n simulation-app").count("Pending") == 3)
    kc("kubectl scale deployment web --replicas=2 -n simulation-app")
    _check("scale down", kc("kubectl get pods -n simulation-app").count("Pending") == 2)
    dp.JOB_SECONDS = 0.6
    r = h("POST", I + "/backup", {"backupRuleOptions": {"ruleName": "BackupDaily", "triggerOption": {"retentionTagOverride": "Default"}}})
    _check("ad-hoc backup is async (202 + operation headers)", r["status"] == 202 and "operationStatus" in r["headers"]["Azure-AsyncOperation"])
    op = r["headers"]["Azure-AsyncOperation"].split("?")[0]
    jid = op.rsplit("/", 1)[-1]
    _check("operation InProgress, no recovery point yet", h("GET", op)["body"]["status"] == "InProgress" and not h("GET", I + "/recoveryPoints")["body"]["value"])
    _check("job listed InProgress", h("GET", P + f"/backupJobs/{jid}")["body"]["properties"]["status"] == "InProgress")
    _check("restore without a recovery point rejected", h("POST", I + "/restore", {"restoreRequestObject": {"objectType": "AzureBackupRecoveryPointBasedRestoreRequest", "recoveryPointId": "nope"}})["status"] == 404)
    time.sleep(0.8)
    _check("operation Succeeded", h("GET", op)["body"]["status"] == "Succeeded")
    rps = h("GET", I + "/recoveryPoints")["body"]["value"]
    _check("one recovery point", len(rps) == 1)
    rp = rps[0]
    _check("recovery point records the contents", rp["properties"]["vyomiContents"].get("pods") == 2 and rp["properties"]["vyomiContents"].get("deployments") == 1 and rp["properties"]["vyomiContents"].get("services") == 1)
    art = rp["properties"]["vyomiArtifact"]
    _check("artifact is a real blob in the simulator Blob store", store.container_exists(f"{art['account']}/{art['container']}") and art["container"] == "aksbackup-sim-vault")
    _check("job Completed", h("GET", P + f"/backupJobs/{jid}")["body"]["properties"]["status"] == "Completed")

    _check("disaster: delete namespace", "deleted" in kc("kubectl delete namespace simulation-app"))
    _check("get pods -> No resources found", kc("kubectl get pods -n simulation-app").strip() == "No resources found in simulation-app namespace.")

    body = {"restoreRequestObject": {"objectType": "AzureBackupRecoveryPointBasedRestoreRequest", "recoveryPointId": rp["name"], "sourceDataStoreType": "VaultStore"}}
    _check("validateRestore ok", h("POST", I + "/validateRestore", body)["body"]["status"] == "Succeeded")
    r = h("POST", I + "/restore", body)
    _check("restore is async", r["status"] == 202)
    rop = r["headers"]["Azure-AsyncOperation"].split("?")[0]
    _check("pods not back before the job completes", "No resources found" in kc("kubectl get pods -n simulation-app"))
    time.sleep(0.8)
    out = kc("kubectl get pods -n simulation-app")      # runCommand completes the due job first
    _check("restore re-injected the pods", out.count("Pending") == 2)
    _check("restore re-injected the deployment", "web" in kc("kubectl get deployments -n simulation-app"))
    _check("restore operation Succeeded", h("GET", rop)["body"]["status"] == "Succeeded")

    # restore into a different cluster
    CL2 = CL.replace("aks1", "aks2")
    h("PUT", CL2, {"location": "eastus", "properties": {"kubernetesVersion": "1.29.0", "dnsPrefix": "b", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_B2s", "mode": "System"}]}}, "2024-09-02-preview")
    b2 = {"restoreRequestObject": dict(body["restoreRequestObject"], restoreTargetInfo={"datasourceInfo": {"resourceID": CL2}})}
    _check("alternate-cluster restore accepted", h("POST", I + "/restore", b2)["status"] == 202)
    time.sleep(0.8)
    dp.tick(a.state, store)
    out2 = h("POST", CL2 + "/runCommand", {"command": "kubectl get pods -n simulation-app"}, "2024-09-02-preview")["body"]["properties"]["logs"]
    _check("pods exist in the second cluster", "Pending" in out2)

    # KubeBackend seam
    be = kube.backend_for({}, "aws", "eks-1")
    be.apply([{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "x"}}])
    _check("InMemoryKubeBackend export/delete/apply cycle", be.export_resources()["counts"]["namespaces"] == 1 and be.delete_namespace("x") and be.export_resources()["counts"]["namespaces"] == 0)
    _check("health", be.health()["status"] == "Healthy")
    try:
        kube.RealK8sBackend().export_resources(); ok = False
    except NotImplementedError:
        ok = True
    _check("RealK8sBackend is an unimplemented seam", ok)

    # cleanup rules
    _check("delete instance", h("DELETE", I)["status"] == 200)
    _check("delete policy", h("DELETE", P + "/backupPolicies/pol")["status"] == 200)
    _check("delete vault", h("DELETE", P)["status"] == 200)
    _check("vault gone", h("GET", P)["status"] == 404)
    print("azure dataprotection: ok")


if __name__ == "__main__":
    run()
