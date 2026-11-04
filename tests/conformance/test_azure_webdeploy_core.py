"""App Service Deployment Center control plane: sourcecontrols/web, deployments, publishing credentials, basic-auth policies.
Run: PYTHONPATH=. python tests/conformance/test_azure_webdeploy_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


try:
    from core.azure_arm_core import AzureArm as _LaxArm
    _LaxArm.STRICT_SUBSCRIPTION = False   # engine test: ad-hoc subscription ids
except Exception:
    pass


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    Q = {"api-version": "2023-12-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/wd-rg"
    W = f"{RG}/providers/Microsoft.Web"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", f"{W}/serverfarms/p1", Q, {"location": "eastus", "sku": {"name": "B1"}})
    r = a.handle("PUT", f"{W}/sites/app1", Q, {"location": "eastus", "kind": "app,linux", "properties": {"serverFarmId": f"{W}/serverfarms/p1"}})
    _check("site created", r["status"] in (200, 201))
    S = f"{W}/sites/app1"
    put = lambda body: a.handle("PUT", f"{S}/sourcecontrols/web", Q, body)
    _check("no source control yet -> 404", a.handle("GET", f"{S}/sourcecontrols/web", Q)["status"] == 404)
    _check("repoUrl required", put({"properties": {}})["status"] == 400)
    _check("bad repo url", put({"properties": {"repoUrl": "not a url"}})["status"] == 400)
    _check("GitHub Actions needs github.com", put({"properties": {"repoUrl": "https://gitlab.com/o/r", "isGitHubAction": True}})["status"] == 400)
    _check("GitHub Actions needs a runtime config", put({"properties": {"repoUrl": "https://github.com/o/r", "isGitHubAction": True}})["status"] == 400)
    r = put({"properties": {"repoUrl": "https://github.com/o/r", "branch": "main", "isGitHubAction": True,
                            "gitHubActionConfiguration": {"codeConfiguration": {"runtimeStack": "python", "runtimeVersion": "3.11"}}}})
    y = r["body"]["properties"]["gitHubActionConfiguration"]["workflowYaml"]
    _check("GH Actions stored with generated workflow", r["status"] == 201 and "azure/webapps-deploy@v3" in y and "python-version: '3.11'" in y and "- main" in y)
    _check("scmType = GitHubAction", a.handle("GET", f"{S}/config/web", Q)["body"]["properties"]["scmType"] == "GitHubAction")
    _check("sync refused for GH Actions", a.handle("POST", f"{S}/sync", Q)["status"] == 409)
    r = put({"properties": {"repoUrl": "https://example.com/team/app.git", "branch": "release", "isManualIntegration": False}})
    _check("external git stored, scmType ExternalGit", r["status"] == 200 and a.handle("GET", f"{S}/config/web", Q)["body"]["properties"]["scmType"] == "ExternalGit")
    deps = a.handle("GET", f"{S}/deployments", Q)["body"]["value"]
    _check("continuous integration recorded a deployment attempt", len(deps) == 1)
    _check("attempt is honestly Failed with an explanation", deps[0]["properties"]["status"] == 3 and "failed:" in deps[0]["properties"]["logs"][0]["message"])
    r = a.handle("POST", f"{S}/sync", Q)
    _check("manual sync appends a record", r["status"] == 200 and len(a.handle("GET", f"{S}/deployments", Q)["body"]["value"]) == 2)
    did = deps[0]["name"]
    _check("deployment log readable", len(a.handle("GET", f"{S}/deployments/{did}/log", Q)["body"]["value"]) == 1)
    _check("deployment deletable", a.handle("DELETE", f"{S}/deployments/{did}", Q)["status"] == 200)
    c1 = a.handle("POST", f"{S}/config/publishingcredentials/list", Q)["body"]["properties"]
    _check("publishing user is $site", c1["publishingUserName"] == "$app1" and c1["scmUri"].startswith("https://$app1:"))
    a.handle("POST", f"{S}/newpassword", Q)
    c2 = a.handle("POST", f"{S}/config/publishingcredentials/list", Q)["body"]["properties"]
    _check("password rotates", c1["publishingPassword"] != c2["publishingPassword"])
    _check("policy default allow", a.handle("GET", f"{S}/basicPublishingCredentialsPolicies/ftp", Q)["body"]["properties"]["allow"] is True)
    _check("policy needs a boolean", a.handle("PUT", f"{S}/basicPublishingCredentialsPolicies/ftp", Q, {"properties": {"allow": "yes"}})["status"] == 400)
    a.handle("PUT", f"{S}/basicPublishingCredentialsPolicies/scm", Q, {"properties": {"allow": False}})
    _check("scm basic-auth switch reflected in siteConfig", a.handle("GET", f"{S}/config/web", Q)["body"]["properties"]["scmBasicAuthEnabled"] is False)
    _check("delete source control", a.handle("DELETE", f"{S}/sourcecontrols/web", Q)["status"] == 200
           and a.handle("GET", f"{S}/config/web", Q)["body"]["properties"]["scmType"] == "None")
    _check("function app shares the Deployment Center API", a.handle("PUT", f"{W}/sites/fn1", Q, {"location": "eastus", "kind": "functionapp,linux", "properties": {"serverFarmId": f"{W}/serverfarms/p1"}})["status"] in (200, 201)
           and a.handle("PUT", f"{W}/sites/fn1/sourcecontrols/web", Q, {"properties": {"repoUrl": "https://example.com/a/b", "isManualIntegration": True}})["status"] == 201)
    print("PASS test_azure_webdeploy_core")


if __name__ == "__main__":
    run()
