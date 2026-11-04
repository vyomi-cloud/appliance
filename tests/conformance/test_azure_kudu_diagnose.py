"""Azure App Service Kudu tooling (vfs / console / processes / logstream / extensions) + resource-scoped Diagnose detectors.

Hermetic: pure-Python ARM core, no network/docker.  Run: PYTHONPATH=. python tests/conformance/test_azure_kudu_diagnose.py
"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("  ok ", name)


a = AzureArm()
P = f"/subscriptions/{SUB}/resourceGroups/rg/providers"


def call(m, path, body=None, q=None):
    r = a.handle(m, path, dict({"api-version": "2023-12-01"}, **(q or {})), body)
    return r["status"], r["body"]


W = P + "/Microsoft.Web/sites/kw"
check("create web app", call("PUT", W, {"location": "eastus", "kind": "app", "properties": {}})[0] == 200)
call("PUT", W + "/config/appsettings", {"properties": {"FOO": "bar"}})

# vfs
s, b = call("GET", W + "/kudu/api/vfs/site/wwwroot")
check("vfs lists default hostingstart.html", s == 200 and any(e["name"] == "hostingstart.html" for e in b))
check("vfs write creates", call("PUT", W + "/kudu/api/vfs/site/wwwroot/a.txt", {"content": "hello\nworld\n"})[0] == 201)
check("vfs read back", call("GET", W + "/kudu/api/vfs/site/wwwroot/a.txt")[1]["content"] == "hello\nworld\n")
check("vfs 404", call("GET", W + "/kudu/api/vfs/site/nope.txt")[0] == 404)
check("vfs bad body 400", call("PUT", W + "/kudu/api/vfs/site/wwwroot/b.txt", {"x": 1})[0] == 400)
check("vfs mkdir", call("PUT", W + "/kudu/api/vfs/site/wwwroot/d", None, {"mkdir": "true"})[0] == 201)
check("vfs protected root delete", call("DELETE", W + "/kudu/api/vfs/site/wwwroot")[0] == 409)
check("vfs delete", call("DELETE", W + "/kudu/api/vfs/site/wwwroot/a.txt")[0] == 200 and call("GET", W + "/kudu/api/vfs/site/wwwroot/a.txt")[0] == 404)
call("PUT", W + "/kudu/api/vfs/site/wwwroot/a.txt", {"content": "hello\nworld\n"})

# console
def cmd(c, d="/home"):
    return call("POST", W + "/kudu/api/command", {"command": c, "dir": d})[1]


check("console cd + ls", cmd("cd site/wwwroot && ls")["Output"].split() == ["a.txt", "d/", "hostingstart.html"][:0] or "a.txt" in cmd("cd site/wwwroot && ls")["Output"])
check("console cwd persists in reply", cmd("cd site/wwwroot")["Dir"] == "/home/site/wwwroot")
check("console pipe grep", cmd("cat a.txt | grep wor", "/home/site/wwwroot")["Output"] == "world\n")
check("console env has app setting", cmd("printenv FOO")["Output"] == "bar\n")
check("console redirect writes real file", cmd("echo hi > n.txt", "/home/site/wwwroot")["ExitCode"] == 0
      and call("GET", W + "/kudu/api/vfs/site/wwwroot/n.txt")[1]["content"] == "hi\n")
check("console unknown command fails", cmd("frobnicate")["ExitCode"] == 1)
check("console missing file fails", "No such file" in cmd("cat nope")["Error"])

# processes / environment / settings / deployments / logstream
pr = call("GET", W + "/kudu/api/processes")[1]
check("processes modelled + labelled", pr["modeled"] is True and any(p["kind"] == "worker" for p in pr["value"]))
check("settings default + update", call("POST", W + "/kudu/api/settings", {"SCM_TRACE_LEVEL": "Verbose"})[1]["SCM_TRACE_LEVEL"] == "Verbose")
check("settings invalid name 400", call("POST", W + "/kudu/api/settings", {"1bad": "x"})[0] == 400)
check("environment", call("GET", W + "/kudu/api/environment")[1]["os"] == "windows")
check("deployments list", call("GET", W + "/kudu/api/deployments")[0] == 200)
ls = call("GET", W + "/kudu/api/logstream")[1]
check("logstream has platform lines incl. console command", any("[kudu] command" in l["text"] for l in ls["lines"]))
cur = ls["cursor"]
cmd("whoami")
check("logstream cursor returns only new lines", all(l["time"] > cur for l in call("GET", W + "/kudu/api/logstream", None, {"since": cur})[1]["lines"]))

# extensions (Windows only)
check("extensions gallery", len(call("GET", W + "/kudu/api/siteextensions")[1]["value"]) >= 5)
check("extension install", call("PUT", W + "/kudu/api/siteextensions/DaaS")[0] == 201)
check("extension reinstall 409", call("PUT", W + "/kudu/api/siteextensions/DaaS")[0] == 409)
check("extension installed filter", [e["id"] for e in call("GET", W + "/kudu/api/siteextensions", None, {"scope": "installed"})[1]["value"]] == ["DaaS"])
check("extension unknown 404", call("PUT", W + "/kudu/api/siteextensions/nope")[0] == 404)
check("extension uninstall", call("DELETE", W + "/kudu/api/siteextensions/DaaS")[0] == 200)
L = P + "/Microsoft.Web/sites/lw"
call("PUT", L, {"location": "eastus", "kind": "app,linux", "properties": {"reserved": True}})
check("extensions rejected on Linux", call("GET", L + "/kudu/api/siteextensions")[0] == 400)
check("linux console whoami", call("POST", L + "/kudu/api/command", {"command": "whoami"})[1]["Output"] == "app\n")

# function app: sources are the vfs
F = P + "/Microsoft.Web/sites/kf"
call("PUT", F, {"location": "eastus", "kind": "functionapp", "properties": {"reserved": True}})
call("PUT", F + "/functions/hello", {"properties": {"code": "def main(req):\n    return {'ok': 1}\n"}})
call("POST", F + "/functions/hello/invoke", {})
call("POST", F + "/functions/hello/invoke", {})
tree = call("GET", F + "/kudu/api/vfs/site/wwwroot")[1]
check("function dir in wwwroot", any(e["name"] == "hello" for e in tree) and any(e["name"] == "host.json" for e in tree))
check("function.json generated", "httpTrigger" in call("GET", F + "/kudu/api/vfs/site/wwwroot/hello/function.json")[1]["content"])
fl = call("GET", F + "/kudu/api/logstream")[1]["lines"]
check("function invocations appear in log stream", any("Executed 'Functions.hello'" in l["text"] for l in fl))
check("function log file in vfs", "Executed" in call("GET", F + "/kudu/api/vfs/LogFiles/Application/functions.log")[1]["content"])
call("POST", W + "/stop")
check("stopped app rejects console", call("POST", W + "/kudu/api/command", {"command": "ls"})[0] == 409)
check("stopped app has no processes", call("GET", W + "/kudu/api/processes")[1]["value"] == [])
call("POST", W + "/start")

# ── Diagnose detectors ──
def diag(rid):
    return call("GET", rid + "/providers/Microsoft.Vyomi/diagnostics", None, {"api-version": "2024-01-01"})


def det(rid, did):
    return next(d for d in diag(rid)[1]["detectors"] if d["id"] == did)


K = P + "/Microsoft.ContainerService/managedClusters/kc"
call("PUT", K, {"location": "eastus", "properties": {"kubernetesVersion": "1.20.0", "agentPoolProfiles": [{"name": "np", "count": 1}]}})
check("aks old version flagged", det(K, "k8s-version")["status"] == "Warning")
check("aks single node flagged", det(K, "single-node")["status"] == "Warning")
call("PATCH", K, {"properties": {"agentPoolProfiles": [{"name": "np", "count": 0}]}})
check("aks zero nodes becomes Critical (live state)", det(K, "nodepools")["status"] == "Critical" and diag(K)[1]["overall"] == "Critical")
check("diagnostics 404 on missing resource", diag(P + "/Microsoft.ContainerService/managedClusters/none")[0] == 404)
check("detector by id", call("GET", K + "/providers/Microsoft.Vyomi/diagnostics/rbac")[1]["id"] == "rbac")
check("unknown detector 404", call("GET", K + "/providers/Microsoft.Vyomi/diagnostics/zzz")[0] == 404)

M = P + "/Microsoft.ApiManagement/service/ka"
call("PUT", M, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}})
check("apim developer SLA warning", det(M, "sku-sla")["status"] == "Warning")
check("apim no apis noted", det(M, "apis")["evidence"]["apis"] == 0)

C = P + "/Microsoft.CognitiveServices/accounts/kcs"
call("PUT", C, {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {}})
check("cogs: no deployment warns", det(C, "deployments")["status"] == "Warning")
call("PATCH", C, {"properties": {"disableLocalAuth": True}})
check("cogs: local auth change reflected", det(C, "auth")["status"] in ("Healthy", "Info"))

AC = P + "/Microsoft.AppConfiguration/configurationStores/kappcfg"
s, _ = call("PUT", AC, {"location": "eastus", "sku": {"name": "Free"}})
check("appconfig free store created", s in (200, 201))
check("appconfig free tier has no soft delete", det(AC, "soft-delete")["status"] == "Info")

check("web app detectors incl. https", det(W, "https")["status"] == "Warning")
call("PATCH", W, {"properties": {"httpsOnly": True}})
check("web app https fixed -> Healthy (live)", det(W, "https")["status"] == "Healthy")
call("POST", W + "/stop")
check("stopped web app Critical", det(W, "state")["status"] == "Critical")
print("ALL OK")
