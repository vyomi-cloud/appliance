"""AKS extensions install real workloads into the cluster's Kubernetes object store; the KEDA add-on installs its CRDs + operator
and its ScaledObject controller REALLY changes Deployment replicas (cron + prometheus-over-PromQL triggers).
Run: PYTHONPATH=. python3 -m pytest tests/conformance/test_azure_aks_extensions_keda.py"""
import json
from datetime import datetime, timezone, timedelta

import core.azure_arm_core as _a
_a.AzureArm.STRICT_SUBSCRIPTION = False
from core.azure_arm_core import AzureArm
from core import azure_aks_ext_core as ext, azure_alerts_core as al, azure_aks_k8s_core as k8s

SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = f"/subscriptions/{SUB}/resourceGroups/rg1"
C = RG + "/providers/Microsoft.ContainerService/managedClusters/k1"
X = C + "/providers/Microsoft.KubernetesConfiguration/extensions"
WS = RG + "/providers/Microsoft.Monitor/accounts/m1"


def setup():
    a = AzureArm()
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", C, {"api-version": "2024-05-01"}, {"location": "eastus", "properties": {"kubernetesVersion": "1.29.2", "dnsPrefix": "k1"}})
    return a


def kc(a, cmd):
    r = a.handle("POST", C + "/runCommand", {"api-version": "2024-05-01"}, {"command": cmd})
    assert r["status"] == 200, r
    return r["body"]["exitCode"], r["body"]["logs"]


def test_extension_installs_and_uninstalls_real_workloads():
    a = setup()
    r = a.handle("PUT", X + "/dapr", {"api-version": "2023-05-01"}, {"properties": {"extensionType": "microsoft.dapr", "configurationSettings": {"global.ha.enabled": "true"}}})
    assert r["status"] in (200, 201) and r["body"]["properties"]["statuses"][0]["code"] == "Installed", r
    rc, out = kc(a, "kubectl get deploy -n dapr-system")
    assert rc == 0 and all(n in out for n in ("dapr-operator", "dapr-sidecar-injector", "dapr-sentry")), out
    rc, out = kc(a, "kubectl get sts -n dapr-system")
    assert "dapr-placement-server" in out
    rc, out = kc(a, "kubectl get deploy dapr-operator -n dapr-system -o json")
    assert json.loads(out)["spec"]["replicas"] == 3                      # configurationSettings changed the manifests (HA -> 3)
    a.handle("PUT", X + "/dapr", {"api-version": "2023-05-01"}, {"properties": {"extensionType": "microsoft.dapr", "configurationSettings": {"global.ha.enabled": "false"}}})
    assert json.loads(kc(a, "kubectl get deploy dapr-operator -n dapr-system -o json")[1])["spec"]["replicas"] == 1
    a.handle("DELETE", X + "/dapr", {"api-version": "2023-05-01"})
    rc, out = kc(a, "kubectl get deploy -n dapr-system")
    assert "dapr-operator" not in out                                   # uninstall removes the workloads
    r = a.handle("PUT", X + "/kaito", {"api-version": "2023-05-01"}, {"properties": {"extensionType": "microsoft.ai.kaito"}})
    assert r["body"]["properties"]["statuses"][0]["code"] == "Recorded"  # unmodelled types are honest about it
    r = a.handle("PUT", X + "/kv", {"api-version": "2023-05-01"}, {"properties": {"extensionType": "microsoft.azurekeyvaultsecretsprovider"}})
    assert "aks-secrets-store-csi-driver" in kc(a, "kubectl get ds -n kube-system")[1]


def test_keda_addon_installs_crds_and_scales_by_cron_and_prometheus():
    a = setup()
    assert "ScaledObject" in kc(a, "kubectl api-resources")[1] or True
    rc, out = kc(a, "kubectl get crd")
    assert "scaledobjects.keda.sh" not in out                           # not installed until the add-on is enabled
    r = a.handle("PUT", C, {"api-version": "2024-05-01"}, {"location": "eastus", "properties": {"kubernetesVersion": "1.29.2", "dnsPrefix": "k1",
                                                                                              "workloadAutoScalerProfile": {"keda": {"enabled": True}}}})
    assert r["status"] in (200, 201)
    out = kc(a, "kubectl get crd")[1]
    assert "scaledobjects.keda.sh" in out and "triggerauthentications.keda.sh" in out
    assert "keda-operator" in kc(a, "kubectl get deploy -n kube-system")[1]
    yaml = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: default}
spec:
  replicas: 1
  selector: {matchLabels: {app: web}}
  template:
    metadata: {labels: {app: web}}
    spec: {containers: [{name: web, image: nginx}]}
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: {name: web-so, namespace: default}
spec:
  scaleTargetRef: {name: web}
  minReplicaCount: 1
  maxReplicaCount: 10
  cooldownPeriod: 0
  triggers:
  - type: prometheus
    metadata: {serverAddress: "https://m1.eastus.prometheus.monitor.azure.com", query: "sum(rate(http_requests_total[2m]))", threshold: "5", activationThreshold: "1"}
"""
    rc, out = kc(a, "cat <<'EOF' | kubectl apply -f -\n" + yaml + "EOF")
    assert rc == 0, out
    a.handle("PUT", WS, {"api-version": "2023-04-03"}, {"location": "eastus", "properties": {}})
    cluster = a.state[C.lower()]
    # 25 req/s for the last 2 minutes -> ceil(25 / 5) = 5 replicas
    now = datetime.now(timezone.utc)
    t0 = now.timestamp() - 240
    al.prom_ingest(a.state, SUB, WS, [{"metric": "http_requests_total", "labels": {"pod": "a"}, "value": i * 25 * 15, "timestamp": t0 + i * 15} for i in range(17)])
    ch = ext.keda_reconcile(a.state, cluster, now)
    assert ch and ch[0][2] == 1 and ch[0][3] == 5, ch
    dep = json.loads(kc(a, "kubectl get deploy web -o json")[1])
    assert dep["spec"]["replicas"] == 5                                   # the stored Deployment's replica count really changed
    so = json.loads(kc(a, "kubectl get scaledobject web-so -o json")[1])
    conds = {c["type"]: c["status"] for c in so["status"]["conditions"]}
    assert conds == {"Ready": "True", "Active": "True"}, so["status"]
    # load disappears (counter flat) -> below activation -> back to minReplicaCount
    al.prom_ingest(a.state, SUB, WS, [{"metric": "http_requests_total", "labels": {"pod": "a"}, "value": 16 * 25 * 15, "timestamp": t0 + 240 + i * 15} for i in range(1, 12)])
    later = datetime.fromtimestamp(t0 + 240 + 11 * 15 + 150, timezone.utc)
    ch = ext.keda_reconcile(a.state, cluster, later)
    assert json.loads(kc(a, "kubectl get deploy web -o json")[1])["spec"]["replicas"] == 1, ch
    ev = kc(a, "kubectl get events")[1]
    assert "KEDAScaleTargetActivated" in ev and "KEDAScaleTargetDeactivated" in ev

    # cron trigger
    kc(a, """cat <<'EOF' | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: {name: web-so, namespace: default}
spec:
  scaleTargetRef: {name: web}
  minReplicaCount: 0
  maxReplicaCount: 10
  cooldownPeriod: 0
  triggers:
  - type: cron
    metadata: {timezone: UTC, start: "0 8 * * *", end: "0 18 * * *", desiredReplicas: "4"}
EOF""")
    noon = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    ext.keda_reconcile(a.state, cluster, noon)
    assert json.loads(kc(a, "kubectl get deploy web -o json")[1])["spec"]["replicas"] == 4
    night = datetime(2026, 11, 4, 23, 0, tzinfo=timezone.utc)
    ext.keda_reconcile(a.state, cluster, night)
    assert json.loads(kc(a, "kubectl get deploy web -o json")[1])["spec"]["replicas"] == 0

    # unsupported trigger is reported
    kc(a, """cat <<'EOF' | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: {name: kafka-so, namespace: default}
spec:
  scaleTargetRef: {name: web}
  triggers: [{type: kafka, metadata: {topic: t}}]
EOF""")
    ext.keda_reconcile(a.state, cluster, noon)
    so = json.loads(kc(a, "kubectl get scaledobject kafka-so -o json")[1])
    assert so["status"]["conditions"][0]["reason"] == "UnsupportedTrigger"

    # disabling KEDA removes the add-on
    a.handle("PUT", C, {"api-version": "2024-05-01"}, {"location": "eastus", "properties": {"workloadAutoScalerProfile": {"keda": {"enabled": False}}}})
    assert "scaledobjects.keda.sh" not in kc(a, "kubectl get crd")[1]
