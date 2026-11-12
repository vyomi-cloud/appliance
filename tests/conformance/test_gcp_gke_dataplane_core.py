"""Unit tests for the GKE Kubernetes data plane (core/gcp_gke_dataplane_core.py), reached
through core/gcp_container_core.py's `clusters/{c}/k8s/{real Kubernetes REST path}` bridge.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_gke_dataplane_core.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_container_core as gk  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, path, body=None, query=None):
    r = gk.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return r.status, json.loads(r.body or b"{}")
    except Exception:
        return r.status, r.body


L = "/v1/projects/p1/locations/us-central1"
st = gk.ContainerStore()
call(st, "POST", L + "/clusters", {"cluster": {"name": "c1", "initialNodeCount": 2}})
K = L + "/clusters/c1/k8s"

s, ns = call(st, "GET", K + "/api/v1/namespaces")
check("default namespaces exist on a fresh cluster", s == 200 and {n["metadata"]["name"] for n in ns["items"]} == {"default", "kube-system", "kube-public", "kube-node-lease"}, ns)

s, c = call(st, "POST", K + "/api/v1/namespaces", {"metadata": {"name": "staging"}})
check("create namespace", s == 200 and c["metadata"]["name"] == "staging")
check("duplicate namespace -> 409", call(st, "POST", K + "/api/v1/namespaces", {"metadata": {"name": "staging"}})[0] == 409)
check("delete system namespace -> 403", call(st, "DELETE", K + "/api/v1/namespaces/default")[0] == 403)

DEPL = {"metadata": {"name": "web", "labels": {"app": "web"}},
        "spec": {"replicas": 3, "template": {"metadata": {"labels": {"app": "web"}},
                 "spec": {"containers": [{"name": "nginx", "image": "nginx:1.27", "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}}}]}}}}
s, d = call(st, "POST", K + "/apis/apps/v1/namespaces/default/deployments", DEPL)
check("create deployment", s == 200 and d["spec"]["replicas"] == 3 and d["status"]["readyReplicas"] == 3, d)
s, pods = call(st, "GET", K + "/api/v1/namespaces/default/pods")
check("deployment materializes 3 real Pod objects", s == 200 and len(pods["items"]) == 3 and all(p["status"]["phase"] == "Running" for p in pods["items"]))
check("missing container -> 422", call(st, "POST", K + "/apis/apps/v1/namespaces/default/deployments", {"metadata": {"name": "bad"}, "spec": {"template": {"spec": {"containers": []}}}})[0] == 422)

s, d2 = call(st, "PUT", K + "/apis/apps/v1/namespaces/default/deployments/web", {"spec": {"replicas": 1}})
check("scale down to 1", s == 200 and d2["spec"]["replicas"] == 1)
s, pods = call(st, "GET", K + "/api/v1/namespaces/default/pods")
check("pod count reconciles down to 1", len(pods["items"]) == 1)
victim = pods["items"][0]["metadata"]["name"]
call(st, "DELETE", K + "/api/v1/namespaces/default/pods/%s" % victim)
s, pods2 = call(st, "GET", K + "/api/v1/namespaces/default/pods")
check("deleting a controller-owned pod respawns a replacement", len(pods2["items"]) == 1 and pods2["items"][0]["metadata"]["name"] != victim)

s, svc = call(st, "POST", K + "/api/v1/namespaces/default/services",
              {"metadata": {"name": "web-svc"}, "spec": {"selector": {"app": "web"}, "ports": [{"port": 80, "targetPort": 80}], "type": "LoadBalancer"}})
check("create LoadBalancer service gets a clusterIP + external IP", s == 200 and svc["spec"]["clusterIP"] and svc["status"]["loadBalancer"]["ingress"][0]["ip"])
s, svcs = call(st, "GET", K + "/api/v1/namespaces/default/services")
check("service endpoint count reflects real matching pods", svcs["items"][0]["_endpoints"] == 1)

s, sec = call(st, "POST", K + "/api/v1/namespaces/default/secrets", {"metadata": {"name": "my-sec"}, "stringData": {"password": "hunter2"}})
check("secret stringData is base64-encoded like real k8s wire", s == 200 and sec["data"]["password"] == "aHVudGVyMg==")
s, cm = call(st, "POST", K + "/api/v1/namespaces/default/configmaps", {"metadata": {"name": "my-cm"}, "data": {"k": "v"}})
check("create configmap", s == 200 and cm["data"]["k"] == "v")
check("delete secret", call(st, "DELETE", K + "/api/v1/namespaces/default/secrets/my-sec")[0] == 200)
check("get deleted secret -> 404 Status", call(st, "GET", K + "/api/v1/namespaces/default/secrets/my-sec")[1].get("kind") == "Status")

s, scs = call(st, "GET", K + "/apis/storage.k8s.io/v1/storageclasses")
check("cluster ships default StorageClasses", s == 200 and {x["metadata"]["name"] for x in scs["items"]} == {"standard-rwo", "premium-rwo", "standard"})
s, pvc = call(st, "POST", K + "/api/v1/namespaces/default/persistentvolumeclaims", {"metadata": {"name": "data"}, "spec": {"resources": {"requests": {"storage": "10Gi"}}}})
check("PVC binds instantly to an auto-provisioned PV", s == 200 and pvc["status"]["phase"] == "Bound" and pvc["spec"]["volumeName"])
s, pvs = call(st, "GET", K + "/api/v1/persistentvolumes")
check("PV created to match the PVC", s == 200 and len(pvs["items"]) == 1 and pvs["items"][0]["spec"]["capacity"]["storage"] == "10Gi")
call(st, "DELETE", K + "/api/v1/namespaces/default/persistentvolumeclaims/data")
s, pvs2 = call(st, "GET", K + "/api/v1/persistentvolumes")
check("deleting the PVC reclaims its PV", len(pvs2["items"]) == 0)
check("bad storage class -> 422", call(st, "POST", K + "/api/v1/namespaces/default/persistentvolumeclaims", {"metadata": {"name": "d2"}, "spec": {"storageClassName": "nope", "resources": {"requests": {"storage": "1Gi"}}}})[0] == 422)

s, ing = call(st, "POST", K + "/apis/networking.k8s.io/v1/namespaces/default/ingresses",
              {"metadata": {"name": "web-ing"},
               "spec": {"rules": [{"host": "example.com", "http": {"paths": [{"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "web-svc", "port": {"number": 80}}}}]}}]}})
check("create ingress referencing a real service", s == 200 and ing["status"]["loadBalancer"]["ingress"][0]["ip"])
check("ingress referencing a missing service -> 422", call(st, "POST", K + "/apis/networking.k8s.io/v1/namespaces/default/ingresses",
      {"metadata": {"name": "bad-ing"}, "spec": {"rules": [{"http": {"paths": [{"backend": {"service": {"name": "nope"}}}]}}]}})[0] == 422)

s, gw = call(st, "POST", K + "/apis/gateway.networking.k8s.io/v1/namespaces/default/gateways",
             {"metadata": {"name": "gw1"}, "spec": {"gatewayClassName": "gke-l7-global-external-managed", "listeners": [{"name": "http", "protocol": "HTTP", "port": 80}]}})
check("create Gateway", s == 200 and gw["status"]["addresses"][0]["value"])
check("gateway missing gatewayClassName -> 422", call(st, "POST", K + "/apis/gateway.networking.k8s.io/v1/namespaces/default/gateways", {"metadata": {"name": "bad"}, "spec": {}})[0] == 422)

s, nodes = call(st, "GET", K + "/api/v1/nodes")
check("Nodes are derived from the real 2-node default-pool (e2-medium)", s == 200 and len(nodes["items"]) == 2
      and nodes["items"][0]["status"]["allocatable"]["cpu"] == "2" and nodes["items"][0]["status"]["nodeInfo"]["kubeletVersion"] == gk.DEFAULT_VERSION, nodes)

s, job = call(st, "POST", K + "/apis/batch/v1/namespaces/default/jobs", {"metadata": {"name": "migrate"}, "spec": {"template": {"spec": {"containers": [{"name": "m", "image": "migrate:1"}]}}}})
check("Job runs to completion synchronously", s == 200 and job["status"]["succeeded"] == 1 and job["status"]["conditions"][0]["type"] == "Complete")
s, jpods = call(st, "GET", K + "/api/v1/namespaces/default/pods")
check("Job's pod is Succeeded, not Running", any(p["metadata"]["ownerReferences"][0]["kind"] == "Job" and p["status"]["phase"] == "Succeeded" for p in jpods["items"]))

s, cm0 = call(st, "GET", K + "/apis/configmanagement.gke.io/v1/configmanagements/config-management")
check("ConfigManagement singleton starts disabled", s == 200 and cm0["spec"]["policyController"]["enabled"] is False)
s, cm1 = call(st, "PUT", K + "/apis/configmanagement.gke.io/v1/configmanagements/config-management", {"spec": {"policyController": {"enabled": True}}})
check("enable Policy Controller", s == 200 and cm1["spec"]["policyController"]["enabled"] is True)

s, constraint = call(st, "POST", K + "/apis/constraints.gatekeeper.sh/v1beta1/k8srequiredlabels",
                      {"metadata": {"name": "require-team"}, "spec": {"match": {"kinds": [{"kinds": ["Deployment"]}]}, "parameters": {"labels": ["team"]}}})
check("create K8sRequiredLabels constraint", s == 200)
s, denied = call(st, "POST", K + "/apis/apps/v1/namespaces/default/deployments",
                  {"metadata": {"name": "nolabel"}, "spec": {"replicas": 1, "template": {"metadata": {"labels": {"app": "nolabel"}}, "spec": {"containers": [{"name": "c", "image": "x:1"}]}}}})
check("Policy Controller DENIES a deployment missing the required label", s == 403 and "require-team" in denied.get("message", ""), denied)
s, allowed = call(st, "POST", K + "/apis/apps/v1/namespaces/default/deployments",
                   {"metadata": {"name": "haslabel"}, "spec": {"replicas": 1, "template": {"metadata": {"labels": {"app": "haslabel", "team": "x"}}, "spec": {"containers": [{"name": "c", "image": "x:1"}]}}}})
check("Policy Controller ALLOWS a deployment carrying the required label", s == 200, allowed)
check("delete constraint", call(st, "DELETE", K + "/apis/constraints.gatekeeper.sh/v1beta1/k8srequiredlabels/require-team")[0] == 200)
s, allowed2 = call(st, "POST", K + "/apis/apps/v1/namespaces/default/deployments",
                    {"metadata": {"name": "nolabel2"}, "spec": {"replicas": 1, "template": {"metadata": {"labels": {"app": "nolabel2"}}, "spec": {"containers": [{"name": "c", "image": "x:1"}]}}}})
check("after deleting the constraint, the same object is allowed again", s == 200, allowed2)

check("delete deployment removes its pods too", call(st, "DELETE", K + "/apis/apps/v1/namespaces/default/deployments/web")[0] == 200)
s, pods3 = call(st, "GET", K + "/api/v1/namespaces/default/pods")
check("no leftover pods for a deleted deployment", not any(p["metadata"]["ownerReferences"][0]["name"] == "web" for p in pods3["items"]))

s, deps_allns = call(st, "GET", K + "/apis/apps/v1/deployments")
check("all-namespace Deployment list works", s == 200 and isinstance(deps_allns["items"], list))

check("unknown apis group -> 404", call(st, "GET", K + "/apis/made.up.io/v1/namespaces/default/widgets")[0] == 404)
check("delete missing namespace -> 404 Status", call(st, "DELETE", K + "/api/v1/namespaces/nope")[1].get("kind") == "Status")

s, obs = call(st, "GET", K + "/observability")
check("observability rolls up real requested-vs-allocatable resources", s == 200 and obs["allocatableCpu"] == 4.0
      and obs["allocatableMemoryMi"] == 8192.0 and obs["workloads"] == 3, obs)
s, apps = call(st, "GET", K + "/applications")
check("applications groups real workloads by their app label", s == 200 and any(a["name"] == "haslabel" for a in apps["items"]), apps)

# ── GKE Hub fleet registration (core/gcp_container_core.py) ─────────────────────────────────
M = "/v1/projects/p1/locations/global/memberships"
s, mem = call(st, "POST", M, {"endpoint": {"gkeCluster": {"resourceLink": "//container.googleapis.com/projects/p1/locations/us-central1/clusters/c1"}}}, query={"membershipId": "c1-member"})
check("register cluster to the fleet", s == 200 and mem["state"]["code"] == "READY", mem)
check("registering the same cluster twice -> 409", call(st, "POST", M, {"endpoint": {"gkeCluster": {"resourceLink": "//container.googleapis.com/projects/p1/locations/us-central1/clusters/c1"}}}, query={"membershipId": "c1-member-2"})[0] == 409)
check("registering a non-existent cluster -> 400", call(st, "POST", M, {"endpoint": {"gkeCluster": {"resourceLink": "//container.googleapis.com/projects/p1/locations/us-central1/clusters/nope"}}}, query={"membershipId": "m2"})[0] == 400)
s, mems = call(st, "GET", M)
check("list memberships", s == 200 and len(mems["resources"]) == 1)
check("membership_for_cluster finds it", gk.membership_for_cluster(st, "projects/p1/locations/us-central1/clusters/c1") is not None)
check("unregister (delete membership)", call(st, "DELETE", M + "/c1-member")[0] == 200)
check("membership_for_cluster is now None", gk.membership_for_cluster(st, "projects/p1/locations/us-central1/clusters/c1") is None)

print(f"\n{PASS}/{PASS + FAIL} checks passed")
sys.exit(1 if FAIL else 0)
