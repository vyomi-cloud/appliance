"""kube_state_core: the cloud-agnostic KubeBackend seam (InMemoryKubeBackend over the AKS object store).
   PYTHONPATH=. python3 tests/conformance/test_kube_state_core.py"""
from core import kube_state_core as k

MANIFEST = """kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata: {name: shop}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: shop}
spec: {replicas: 2, selector: {matchLabels: {app: web}}, template: {metadata: {labels: {app: web}}, spec: {containers: [{name: web, image: nginx}]}}}
---
apiVersion: v1
kind: ConfigMap
metadata: {name: cfg, namespace: shop}
data: {k: v}
EOF"""


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    store = {}
    b = k.backend_for(store, "gcp", "c1")
    check("kubectl apply", b.kubectl(MANIFEST)["exitCode"] == 0)
    snap = b.export_resources()
    check("snapshot has the user namespace + objects, no system namespaces", [n["name"] for n in snap["namespaces"]] == ["shop"] and snap["counts"].get("namespaces") == 1)
    b.delete_namespace("shop")
    check("namespace deleted (disaster)", b.export_resources()["counts"].get("namespaces", 0) == 0)
    b2 = k.backend_for(store, "gcp", "c1")
    check("same (cloud, cluster) shares the state tree", b2 is not None and b2.export_resources()["counts"].get("namespaces", 0) == 0)
    k.restore(k.holder(store, "gcp", "c1"), snap)
    check("restore brings the namespace and objects back", b.export_resources()["counts"] == snap["counts"])
    print("ALL OK")


if __name__ == "__main__":
    run()
