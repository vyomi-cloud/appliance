"""AKS automated deployments (GitHub Actions workflow + real build/push/deploy) and App Service workflow commit.
Hermetic. Run: PYTHONPATH=. python tests/conformance/test_azure_autodeploy.py"""
import base64, io, json, sys, tarfile
sys.path.insert(0, "tests/conformance")
from core import ci_core as ci, azure_flux_core as fx, azure_aks_k8s_core as k8s
from core.azure_acr_core import AcrRegistryStore
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from test_ci_core import docker_stub, _tgz


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


DEP = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\nspec:\n  replicas: 1\n  selector:\n    matchLabels: {app: web}\n  template:\n    metadata:\n      labels: {app: web}\n    spec:\n      containers:\n      - name: web\n        image: contoso/web\n"


def run():
    ci.set_git(None); ci.set_builder(None); ci.set_fetcher(None); ci.set_http(None)
    a = AzureArm(); Q = {"api-version": "2024-05-01"}
    a.acr_store = AcrRegistryStore(); fx.ACR_STORE = a.acr_store
    RG = f"/subscriptions/{SUB}/resourceGroups/ad-rg"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    C = f"{RG}/providers/Microsoft.ContainerService/managedClusters/adaks"
    R = f"{RG}/providers/Microsoft.ContainerRegistry/registries/adacr"
    a.handle("PUT", C, Q, {"location": "eastus", "properties": {"dnsPrefix": "ad", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_DS2_v2", "mode": "System"}]}})
    a.handle("PUT", R, {"api-version": "2023-07-01"}, {"location": "eastus", "sku": {"name": "Standard"}})
    AD = lambda n: f"{C}/vyomiAutomatedDeployments/{n}"
    body = lambda **k: {"properties": {"repoUrl": "vyomi://shop", "branch": "main", "acrId": R, "imageName": "contoso/web", "namespace": "shop", **k}}
    _check("unknown cluster 404", a.handle("PUT", f"{RG}/providers/Microsoft.ContainerService/managedClusters/zz/vyomiAutomatedDeployments/x", Q, body())["status"] == 404)
    _check("bad repo url 400", a.handle("PUT", AD("d1"), Q, body(repoUrl="https://gitlab.com/o/r"))["status"] == 400)
    _check("unknown ACR 400", a.handle("PUT", AD("d1"), Q, body(acrId=R + "x"))["status"] == 400)
    _check("bad image 400", a.handle("PUT", AD("d1"), Q, body(imageName="Bad Image"))["status"] == 400)
    _check("Helm refused honestly", a.handle("PUT", AD("d1"), Q, body(deploymentType="Helm"))["status"] == 400)
    cl = a.state[C.lower()]
    db = ci.get_db(cl)
    ci.set_builder(ci.BuildKitBuilder(docker_stub))
    ci.create_repo(db, "shop")
    ci.commit_files(db, "shop", "main", {"Dockerfile": "FROM alpine:3\n", "manifests/dep.yaml": DEP}, "app")
    # namespace missing on the cluster -> the first run (triggered by the workflow commit push) fails with the reason
    r = a.handle("PUT", AD("d1"), Q, body())
    p = r["body"]["properties"]
    _check("workflow YAML generated for the pipeline (build -> ACR -> k8s-deploy)", "az acr build" in p["workflowYaml"] and "azure/k8s-deploy@v5" in p["workflowYaml"] and "adacr" in p["workflowYaml"])
    _check("workflow committed into the repo (vyomi:// = a push)", ".github/workflows/d1.yml" in ci.tree(db, "shop") and p["workflowCommit"]["path"] == ".github/workflows/d1.yml")
    _check("run failed honestly: namespace does not exist", p["runs"][0]["status"] == "Failed" and "namespace" in p["runs"][0]["error"])
    a.handle("POST", f"{C}/runCommand", Q, {"command": "kubectl create namespace shop"})
    r = a.handle("POST", f"{AD('d1')}/run", Q, {})
    run1 = r["body"]["properties"]["runs"][0]
    _check("manual run Succeeded", r["status"] == 200 and run1["status"] == "Succeeded", )
    _check("image PUSHED to the simulated ACR repository store", "contoso/web" in a.acr_store.repos and run1["image"].split(":")[-1] in a.acr_store.repos["contoso/web"]["tags"])
    dep = [o for o in k8s.list_objects(cl, "Deployment") if o["metadata"]["name"] == "web"]
    _check("Deployment applied to the AKS object store with the ACR image", dep and dep[0]["metadata"]["namespace"] == "shop"
           and dep[0]["spec"]["template"]["spec"]["containers"][0]["image"] == run1["image"] and run1["image"].startswith("adacr.azurecr.io/contoso/web:"))
    n0 = len(a.handle("GET", AD("d1"), Q)["body"]["properties"]["runs"])
    a.handle("POST", f"{AD('d1')}/vyomiPush", Q, {"files": {"manifests/dep.yaml": DEP.replace("replicas: 1", "replicas: 3")}, "message": "scale"})
    g = a.handle("GET", AD("d1"), Q)["body"]["properties"]
    dep = [o for o in k8s.list_objects(cl, "Deployment") if o["metadata"]["name"] == "web"][0]
    _check("a push triggers a new workflow run that redeploys", len(g["runs"]) == n0 + 1 and g["runs"][0]["status"] == "Succeeded" and dep["spec"]["replicas"] == 3)
    ci.set_builder(None)
    r = a.handle("POST", f"{AD('d1')}/run", Q, {})
    _check("no container builder (Nano) -> Failed with reason, deployment untouched", r["body"]["properties"]["runs"][0]["status"] == "Failed" and "No container builder" in r["body"]["properties"]["runs"][0]["error"])

    # GitHub repo: commit the workflow with the user's PAT through the Contents API
    calls = []
    def http(method, url, h, b):
        calls.append((method, url, h.get("Authorization"), b))
        if method == "GET":
            return (404, b"{}")
        return 201, json.dumps({"commit": {"sha": "abc"}, "content": {"html_url": "https://github.com/o/r/blob/main/x"}}).encode()
    ci.set_http(http)
    r = a.handle("PUT", AD("d2"), Q, body(repoUrl="https://github.com/o/r", vyomiAccessToken="ghp_adpat123456"))
    p = r["body"]["properties"]
    put = [c for c in calls if c[0] == "PUT"][0]
    _check("workflow committed to GitHub via Contents API with the PAT", "/repos/o/r/contents/.github/workflows/d2.yml" in put[1] and put[2] == "Bearer ghp_adpat123456"
           and base64.b64decode(json.loads(put[3])["content"]).decode() == p["workflowYaml"] and p["workflowCommit"]["commit"] == "abc")
    _check("PAT never echoed", "ghp_adpat123456" not in json.dumps(r["body"]))
    ci.set_http(None)
    r = a.handle("PUT", AD("d3"), Q, body(repoUrl="https://github.com/o/r2"))
    _check("no PAT / no HTTP -> workflow generated, not committed, reason given", "outbound" in r["body"]["properties"]["workflowCommitError"])

    # App Service GitHub Actions wizard: workflow commit
    W = f"{RG}/providers/Microsoft.Web"; S = f"{W}/sites/ghapp"; QW = {"api-version": "2023-12-01"}
    a.handle("PUT", f"{W}/serverfarms/p1", QW, {"location": "eastus", "sku": {"name": "B1"}})
    a.handle("PUT", S, QW, {"location": "eastus", "kind": "app,linux", "properties": {"serverFarmId": f"{W}/serverfarms/p1"}})
    src = {"repoUrl": "https://github.com/o/app", "branch": "main", "isGitHubAction": True,
           "gitHubActionConfiguration": {"codeConfiguration": {"runtimeStack": "python", "runtimeVersion": "3.11"}, "isLinux": True}}
    r = a.handle("PUT", f"{S}/sourcecontrols/web", QW, {"properties": src})
    g = r["body"]["properties"]["gitHubActionConfiguration"]
    _check("no PAT: workflow generated, honest not-committed reason", "setup-python" in g["workflowYaml"] and "not committed" in g["workflowCommitError"])
    calls.clear(); ci.set_http(http)
    r = a.handle("PUT", f"{S}/sourcecontrols/web", QW, {"properties": {**src, "vyomiAccessToken": "ghp_wizardpat99"}})
    g = r["body"]["properties"]["gitHubActionConfiguration"]
    put = [c for c in calls if c[0] == "PUT"][0]
    _check("with PAT the workflow file is committed to the connected repo", r["status"] in (200, 201) and "/repos/o/app/contents/.github/workflows/main_ghapp.yml" in put[1] and g["workflowCommit"]["commit"] == "abc")
    ci.set_http(lambda m, u, h, b: (403, b'{"message":"Resource not accessible"}'))
    r = a.handle("PUT", f"{S}/sourcecontrols/web", QW, {"properties": src})
    _check("GitHub refusal surfaces as an error, not a fake success", r["status"] == 403 and "could not be committed" in json.dumps(r["body"]))
    ci.set_http(None); ci.set_builder(None)
    print("PASS test_azure_autodeploy")


if __name__ == "__main__":
    run()
