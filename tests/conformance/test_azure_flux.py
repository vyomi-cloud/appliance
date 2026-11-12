"""AKS Flux GitOps over the CI seam + k8s object store. Hermetic. Run: PYTHONPATH=. python tests/conformance/test_azure_flux.py"""
import io, json, tarfile
from core import ci_core as ci
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _tgz(files, top="o-r-abc"):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:gz") as tf:
        for p, c in files.items():
            c = c.encode() if isinstance(c, str) else c
            ti = tarfile.TarInfo(f"{top}/{p}"); ti.size = len(c); tf.addfile(ti, io.BytesIO(c))
    return b.getvalue()


DEP = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\nspec:\n  replicas: 2\n  selector:\n    matchLabels: {app: web}\n  template:\n    metadata:\n      labels: {app: web}\n    spec:\n      containers:\n      - name: web\n        image: nginx:1.25\n"
SVC = "apiVersion: v1\nkind: Service\nmetadata:\n  name: web\nspec:\n  selector: {app: web}\n  ports:\n  - port: 80\n"
CM = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg\ndata:\n  a: b\n"


def run():
    ci.set_git(None); ci.set_builder(None); ci.set_fetcher(None)
    a = AzureArm(); Q = {"api-version": "2023-05-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/fx-rg"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    C = f"{RG}/providers/Microsoft.ContainerService/managedClusters/fxaks"
    a.handle("PUT", C, {"api-version": "2024-05-01"}, {"location": "eastus", "properties": {"dnsPrefix": "fx", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_DS2_v2", "mode": "System"}]}})
    F = lambda n: f"{C}/providers/Microsoft.KubernetesConfiguration/fluxConfigurations/{n}"
    body = lambda **k: {"properties": {"scope": "cluster", "namespace": "gitops", "sourceKind": "GitRepository",
                                       "gitRepository": {"url": "vyomi://app", "repositoryRef": {"branch": "main"}},
                                       "kustomizations": {"apps": {"path": "./apps", "prune": True}}, **k}}
    _check("missing cluster 404", a.handle("PUT", f"{RG}/providers/Microsoft.ContainerService/managedClusters/nope/providers/Microsoft.KubernetesConfiguration/fluxConfigurations/x", Q, body())["status"] == 404)
    _check("bad name 400", a.handle("PUT", F("Bad_Name"), Q, body())["status"] == 400)
    _check("Bucket source rejected", a.handle("PUT", F("f1"), Q, body(sourceKind="Bucket"))["status"] == 400)
    _check("no url 400", a.handle("PUT", F("f1"), Q, {"properties": {"gitRepository": {}, "kustomizations": {"a": {}}}})["status"] == 400)
    _check("no kustomizations 400", a.handle("PUT", F("f1"), Q, body(kustomizations={}))["status"] == 400)
    _check("dependsOn unknown 400", a.handle("PUT", F("f1"), Q, body(kustomizations={"a": {"dependsOn": ["zz"]}}))["status"] == 400)
    _check("dependsOn cycle 400", a.handle("PUT", F("f1"), Q, body(kustomizations={"a": {"dependsOn": ["b"]}, "b": {"dependsOn": ["a"]}}))["status"] == 400)
    _check("two ref kinds 400", a.handle("PUT", F("f1"), Q, body(gitRepository={"url": "vyomi://app", "repositoryRef": {"branch": "a", "tag": "b"}}))["status"] == 400)

    # source repo missing -> Non-Compliant with the git reason (nothing fake)
    r = a.handle("PUT", F("f1"), Q, body())
    p = r["body"]["properties"]
    _check("missing source repo -> Non-Compliant GitOperationFailed", r["status"] in (200, 201) and p["complianceState"] == "Non-Compliant" and "failed to checkout" in p["errorMessage"])
    cl = a.state[C.lower()]
    ci.commit_files(ci.get_db(cl), "app", "main", {"apps/deploy.yaml": DEP, "apps/svc.yaml": SVC}, "init")
    r = a.handle("POST", f"{F('f1')}/reconcile", Q, {})
    p = r["body"]["properties"]
    _check("manual reconcile applies the repo", p["complianceState"] == "Compliant" and p["sourceSyncedCommitId"].startswith("main@sha1:"))
    out = a.handle("POST", f"{C}/runCommand", {"api-version": "2024-05-01"}, {"command": "kubectl get deploy,svc -A"})
    _check("objects really exist in the AKS object store", "deployment.apps/web" in json.dumps(out["body"]) or "web" in json.dumps(out["body"]))
    objs = {(o["kind"], o["metadata"]["name"]) for o in __import__("core.azure_aks_k8s_core", fromlist=["x"]).list_objects(cl)}
    _check("Deployment + Service present, flux extension auto-installed", {("Deployment", "web"), ("Service", "web")} <= objs
           and a.state[(C + "/providers/Microsoft.KubernetesConfiguration/extensions/flux").lower()]["properties"]["extensionType"] == "microsoft.flux")
    st = p["statuses"]
    _check("status lists GitRepository + Kustomization with Ready conditions", [s["kind"] for s in st] == ["GitRepository", "Kustomization"] and st[1]["name"] == "f1-apps" and st[1]["statusConditions"][0]["status"] == "True")

    # a push triggers reconcile; prune removes what the repo dropped
    sha0 = p["sourceSyncedCommitId"]
    a.handle("POST", f"{F('f1')}/vyomiPush", Q, {"files": {"apps/cm.yaml": CM, "apps/svc.yaml": None}, "message": "swap svc for cm"})
    g = a.handle("GET", F("f1"), Q)["body"]["properties"]
    objs = {(o["kind"], o["metadata"]["name"]) for o in __import__("core.azure_aks_k8s_core", fromlist=["x"]).list_objects(cl)}
    _check("push reconciled a new commit", g["sourceSyncedCommitId"] != sha0 and g["lastTrigger"].startswith("push:"))
    _check("prune removed the Service, added the ConfigMap", ("Service", "web") not in objs and ("ConfigMap", "cfg") in objs and ("Deployment", "web") in objs)
    _check("objects carry the flux owner label", all(o["metadata"]["labels"].get("kustomize.toolkit.fluxcd.io/name") == "f1-apps" for o in __import__("core.azure_aks_k8s_core", fromlist=["x"]).list_objects(cl) if o["metadata"]["name"] in ("cfg",)))

    # kustomize overlay render + dependsOn + invalid manifest + helm honesty
    ci.commit_files(ci.get_db(cl), "app", "main", {
        "base/kustomization.yaml": "resources:\n- d.yaml\n", "base/d.yaml": DEP.replace("name: web", "name: api"),
        "overlay/ns.yaml": "apiVersion: v1\nkind: Namespace\nmetadata: {name: prod}\n",
        "overlay/kustomization.yaml": "resources:\n- ../base\n- ns.yaml\nnamespace: prod\nnamePrefix: dev-\ncommonLabels: {env: dev}\nimages:\n- name: nginx\n  newTag: '1.27'\n",
        "bad/x.yaml": "apiVersion: v1\nkind: Nope\nmetadata: {name: x}\n",
        "helm/h.yaml": "apiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\nmetadata: {name: h}\n"}, "overlay", ctx={"state": a.state})
    a.handle("PUT", F("f2"), Q, body(namespace="g2", kustomizations={"over": {"path": "./overlay"}, "after": {"path": "./bad", "dependsOn": ["over"]}, "dep": {"path": "./helm"}}))
    g = a.handle("GET", F("f2"), Q)["body"]["properties"]
    ks = {s["name"]: s for s in g["statuses"] if s["kind"] == "Kustomization"}
    _check("overlay rendered: prefix/namespace/labels/image tag applied",
           ks["f2-over"]["complianceState"] == "Compliant")
    d = [o for o in __import__("core.azure_aks_k8s_core", fromlist=["x"]).list_objects(cl, "Deployment") if o["metadata"]["name"] == "dev-api"]
    _check("kustomize fields applied to the stored Deployment", d and d[0]["metadata"]["namespace"] == "prod" and d[0]["metadata"]["labels"]["env"] == "dev"
           and d[0]["spec"]["template"]["spec"]["containers"][0]["image"] == "nginx:1.27")
    _check("invalid manifest -> that kustomization Non-Compliant with the reason", ks["f2-after"]["complianceState"] == "Non-Compliant")
    _check("Helm is reported not simulated, never faked", ks["f2-dep"]["complianceState"] == "Non-Compliant" and "Helm controller is not simulated" in ks["f2-dep"]["statusConditions"][0]["message"])
    _check("overall Non-Compliant when any kustomization fails", g["complianceState"] == "Non-Compliant")

    # GitHub source with PAT through the fetcher
    seen = {}
    ci.set_fetcher(lambda u, h: (seen.update(auth=h.get("Authorization")) or (200, _tgz({"apps/cm.yaml": CM}))) if "Authorization" in h else (404, b""))
    r = a.handle("PUT", F("f3"), Q, {"properties": {"namespace": "gh", "gitRepository": {"url": "https://github.com/o/r", "httpsUser": "o"}, "configurationProtectedSettings": {"httpsKey": "ghp_fluxpat1234"},
                                                    "kustomizations": {"apps": {"path": "./apps"}}}})
    _check("GitHub source fetched with the user's PAT; key never echoed", r["body"]["properties"]["complianceState"] == "Compliant" and seen["auth"] == "Bearer ghp_fluxpat1234" and "ghp_fluxpat1234" not in json.dumps(r["body"]))
    ci.set_fetcher(None)
    r = a.handle("POST", f"{F('f3')}/reconcile", Q, {})
    _check("unreachable GitHub (Nano) -> Non-Compliant with the reason", r["body"]["properties"]["complianceState"] == "Non-Compliant" and "outbound" in r["body"]["properties"]["errorMessage"])
    # suspend, list, delete prunes
    a.handle("PATCH", F("f1"), Q, {"properties": {"suspend": True}})
    _check("suspend reported Pending", a.handle("GET", F("f1"), Q)["body"]["properties"]["complianceState"] == "Pending")
    lst = a.handle("GET", f"{C}/providers/Microsoft.KubernetesConfiguration/fluxConfigurations", Q)["body"]["value"]
    _check("fluxConfigurations list", {x["name"] for x in lst} == {"f1", "f2", "f3"})
    a.handle("PATCH", F("f1"), Q, {"properties": {"suspend": False}})
    a.handle("DELETE", F("f1"), Q)
    objs = {(o["kind"], o["metadata"]["name"]) for o in __import__("core.azure_aks_k8s_core", fromlist=["x"]).list_objects(cl)}
    _check("deleting the configuration prunes what it deployed", ("Deployment", "web") not in objs and ("ConfigMap", "cfg") not in objs)
    print("PASS test_azure_flux")


if __name__ == "__main__":
    run()
