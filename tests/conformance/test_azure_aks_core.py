"""Azure AKS (Microsoft.ContainerService/managedClusters) conformance.

AKS rides the SAME generic ARM catalog CRUD every other control-plane-only Azure resource
does (core/azure_arm_core.py + the 'aks' entry in core/azure_arm_data.py) — this test proves
the two behaviours that are AKS-specific:

  - the nested node-pool resource (managedClusters/{cluster}/agentPools/{pool}) is scoped to
    its PARENT cluster on LIST, not every pool in the resource group, and cascades away when
    the cluster is deleted (both are the generic-engine fixes this console added);
  - the managedClusters action verbs (start/stop/runCommand/listClusterUserCredential) that
    azure_arm_core._aks_action implements.

Locks, tags, activity log and LRO headers are the SAME generic-engine behaviour
test_azure_arm_core.py already proves for every catalog resource type, so they are only
smoke-checked here, not re-proven in full.

Run:  PYTHONPATH=. python3 tests/conformance/test_azure_aks_core.py
"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


SUB = DEFAULT_SUBSCRIPTION
RG = "cloudlearn-rg"
AV = "2024-09-02-preview"


def _p(rg, *tail):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.ContainerService/managedClusters/" + "/".join(tail)


def run() -> int:
    arm = AzureArm()

    # 1. Create cluster → LRO + realistic defaults
    c1 = _p(RG, "aks1")
    r = arm.handle("PUT", c1, {"api-version": AV}, {"location": "eastus"})
    _check("cluster put 200 (LRO)", r["status"] == 200)
    _check("cluster id canonical", r["body"]["id"].lower() == c1.lower())
    _check("cluster LRO async header", "/api/azure/operations/" in (r["headers"].get("Azure-AsyncOperation") or ""))
    p = r["body"]["properties"]
    _check("cluster default kubernetesVersion", p.get("kubernetesVersion"))
    _check("cluster default fqdn contains name", "aks1" in p.get("fqdn", ""))
    _check("cluster default namespaces seeded", {n["name"] for n in p.get("namespaces", [])} >= {"default", "kube-system"})
    _check("cluster default node resource group", p.get("nodeResourceGroup") == "MC_rg_aks1")

    # 2. Node pools: nested resource, scoped per-cluster on LIST
    c2 = _p(RG, "aks2")
    arm.handle("PUT", c2, {"api-version": AV}, {"location": "eastus"})
    pool1 = _p(RG, "aks1", "agentPools", "nodepool1")
    r = arm.handle("PUT", pool1, {"api-version": AV}, {"properties": {"count": 3, "vmSize": "Standard_DS2_v2", "mode": "System"}})
    _check("pool put 201", r["status"] == 201 and r["body"]["name"] == "nodepool1")
    _check("pool count stored", r["body"]["properties"]["count"] == 3)
    poolX = _p(RG, "aks2", "agentPools", "poolx")
    arm.handle("PUT", poolX, {"api-version": AV}, {"properties": {"count": 1}})

    r = arm.handle("GET", _p(RG, "aks1", "agentPools"), {"api-version": AV})
    names = {x["name"] for x in r["body"]["value"]}
    _check("agentPools list scoped to parent cluster (not cross-cluster)", names == {"nodepool1"})
    r = arm.handle("GET", _p(RG, "aks2", "agentPools"), {"api-version": AV})
    _check("other cluster's pools unaffected", {x["name"] for x in r["body"]["value"]} == {"poolx"})

    # 3. Scale a node pool (PATCH merges properties, generic engine)
    r = arm.handle("PATCH", pool1, {"api-version": AV}, {"properties": {"count": 5}})
    _check("pool scale via PATCH", r["body"]["properties"]["count"] == 5)

    # 4. Tags (generic top-level merge)
    r = arm.handle("PATCH", c1, {"api-version": AV}, {"tags": {"env": "dev"}})
    _check("cluster tags patch", r["body"]["tags"]["env"] == "dev")

    # 5. Locks + activity log (generic engine, proven in full by test_azure_arm_core.py)
    lock = c1 + "/providers/Microsoft.Authorization/locks/dont-delete"
    r = arm.handle("PUT", lock, {"api-version": "2020-05-01"}, {"properties": {"level": "CanNotDelete"}})
    _check("lock on cluster", r["status"] == 201)
    events = f"/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values"
    ev = arm.handle("GET", events, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{c1}'"})
    _check("activity log sees the cluster's lock create", any(e["operationName"]["value"] == "Create lock" for e in ev["body"]["value"]))

    # 6. Action verbs: start/stop (metadata-only power state)
    r = arm.handle("POST", c1 + "/stop", {"api-version": AV})
    _check("cluster stop succeeded", r["status"] == 200 and r["body"]["powerState"]["code"] == "Stopped")
    r = arm.handle("GET", c1, {"api-version": AV})
    _check("stopped power state persisted", r["body"]["properties"]["powerState"]["code"] == "Stopped")

    # 6b. A stopped cluster rejects node-pool writes/deletes AND runCommand (ENFORCED, not just
    # stored) until it is started again.
    r = arm.handle("PATCH", pool1, {"api-version": AV}, {"properties": {"count": 7}})
    _check("node pool scale rejected while cluster stopped", r["status"] == 409 and r["body"]["error"]["code"] == "ClusterNotRunning")
    r = arm.handle("GET", pool1, {"api-version": AV})
    _check("node pool count unchanged while cluster stopped", r["body"]["properties"]["count"] == 5)
    r = arm.handle("DELETE", pool1, {"api-version": AV})
    _check("node pool delete rejected while cluster stopped", r["status"] == 409)
    r = arm.handle("POST", c1 + "/runCommand", {"api-version": AV}, {"command": "kubectl get pods -A"})
    _check("runCommand rejected while cluster stopped", r["status"] == 409 and r["body"]["error"]["code"] == "ClusterNotRunning")
    # the OTHER (running) cluster's pool is unaffected by cluster1's stopped state
    r = arm.handle("PATCH", poolX, {"api-version": AV}, {"properties": {"count": 2}})
    _check("unrelated running cluster's node pool still scales", r["status"] == 200 and r["body"]["properties"]["count"] == 2)

    r = arm.handle("POST", c1 + "/start", {"api-version": AV})
    _check("cluster start succeeded", r["status"] == 200 and r["body"]["powerState"]["code"] == "Running")
    r = arm.handle("PATCH", pool1, {"api-version": AV}, {"properties": {"count": 5}})
    _check("node pool scale works again once cluster is running", r["status"] == 200)

    # 7. runCommand — kubectl against the cluster's Kubernetes object store (no kubelet: objects
    #    are stored, not scheduled; the full kubectl surface is test_azure_aks_k8s_core.py)
    r = arm.handle("POST", c1 + "/runCommand", {"api-version": AV}, {"command": "kubectl get pods -A"})
    _check("runCommand accepted", r["status"] == 200 and r["body"]["exitCode"] == 0)
    _check("runCommand returns the RunCommandResult shape", r["body"]["properties"]["provisioningState"] == "Succeeded"
           and r["body"]["properties"]["exitCode"] == 0)
    _check("runCommand reads the (empty) object store", "No resources found" in r["body"]["logs"])
    r = arm.handle("POST", c1 + "/runCommand", {"api-version": AV}, {"command": "kubectl logs web"})
    _check("runCommand fails honestly for what needs running containers", r["body"]["exitCode"] == 1
           and "doesn't run containers" in r["body"]["logs"])

    # 8. listClusterUserCredential / listClusterAdminCredential — kubeconfig shape
    r = arm.handle("POST", c1 + "/listClusterUserCredential", {"api-version": AV})
    _check("listClusterUserCredential returns a kubeconfig", r["status"] == 200 and r["body"]["kubeconfigs"][0]["name"] == "clusterUser")
    r = arm.handle("POST", c1 + "/listClusterAdminCredential", {"api-version": AV})
    _check("listClusterAdminCredential returns a kubeconfig", r["body"]["kubeconfigs"][0]["name"] == "clusterAdmin")

    # 8b. Namespaces: system namespaces are protected from deletion, and a namespace
    # create/delete needs the same running API server a node-pool write does (ENFORCED,
    # not just stored — azure.aks.namespaces).
    r = arm.handle("GET", c1, {"api-version": AV})
    ns = r["body"]["properties"]["namespaces"]
    _check("cluster still has its seeded system namespaces", {n["name"] for n in ns} >= {"default", "kube-system", "kube-public", "kube-node-lease"})
    without_kube_system = [n for n in ns if n["name"] != "kube-system"]
    r = arm.handle("PATCH", c1, {"api-version": AV}, {"properties": {"namespaces": without_kube_system}})
    _check("deleting a system namespace rejected", r["status"] == 409 and r["body"]["error"]["code"] == "ProtectedNamespace")
    r = arm.handle("GET", c1, {"api-version": AV})
    _check("system namespace survives the rejected delete", any(n["name"] == "kube-system" for n in r["body"]["properties"]["namespaces"]))
    with_app_ns = ns + [{"name": "app-team", "status": "Active"}]
    r = arm.handle("PATCH", c1, {"api-version": AV}, {"properties": {"namespaces": with_app_ns}})
    _check("ordinary namespace create succeeds while running", r["status"] == 200 and any(n["name"] == "app-team" for n in r["body"]["properties"]["namespaces"]))

    arm.handle("POST", c1 + "/stop", {"api-version": AV})
    r = arm.handle("PATCH", c1, {"api-version": AV}, {"properties": {"namespaces": with_app_ns + [{"name": "another", "status": "Active"}]}})
    _check("namespace create rejected while cluster stopped", r["status"] == 409 and r["body"]["error"]["code"] == "ClusterNotRunning")
    without_app_ns = [n for n in with_app_ns if n["name"] != "app-team"]
    r = arm.handle("PATCH", c1, {"api-version": AV}, {"properties": {"namespaces": without_app_ns}})
    _check("namespace delete rejected while cluster stopped", r["status"] == 409 and r["body"]["error"]["code"] == "ClusterNotRunning")
    arm.handle("POST", c1 + "/start", {"api-version": AV})
    r = arm.handle("PATCH", c1, {"api-version": AV}, {"properties": {"namespaces": without_app_ns}})
    _check("ordinary namespace delete succeeds once running again", r["status"] == 200 and not any(n["name"] == "app-team" for n in r["body"]["properties"]["namespaces"]))

    # 9. Action verbs are rejected on non-AKS types (same guard VM start/stop uses)
    storage = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/notacluster"
    arm.handle("PUT", storage, {"api-version": "2023-01-01"}, {"location": "eastus"})
    r = arm.handle("POST", storage + "/runCommand", {"api-version": AV})
    # runCommand is also real now for Microsoft.Compute/virtualMachines (azure.vms.run_command,
    # core/azure_arm_core.py's _vm_run_command) and rejects any other type with the same 400
    # ActionNotSupported guard VM start/stop already used — no more silent 200 {} no-op.
    _check("runCommand only valid on managedClusters (or virtualMachines)", r["status"] == 400)

    # 10. Delete cascades: node pool AND lock both disappear with the cluster
    r = arm.handle("DELETE", c1, {"api-version": AV})
    _check("cluster delete 200", r["status"] == 200)
    r = arm.handle("GET", pool1, {"api-version": AV})
    _check("node pool cascade-deleted with cluster", r["status"] == 404)
    r = arm.handle("GET", lock, {"api-version": "2020-05-01"})
    _check("lock cascade-deleted with cluster", r["status"] == 404)
    # the other cluster's pool is untouched
    r = arm.handle("GET", poolX, {"api-version": AV})
    _check("unrelated cluster's pool survives", r["status"] == 200)

    print("\nRESULT: PASS — Azure AKS (managedClusters + agentPools) conforms on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
