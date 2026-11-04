"""Microsoft Defender for Cloud — Microsoft.Security over the shared ARM engine
(core/azure_security_core.py via core/azure_arm_core.AzureArm).

Proves, over the native ARM wire:
  - pricings: the 13 Defender plans start Free; PUT Standard/Free toggles (enablementTime set);
    invalid tiers / unknown plans rejected;
  - the native rule engine — every rule both ways (Unhealthy on the bad config, Healthy once
    fixed): storage public blob access + secure transfer, NSG SSH/RDP from the internet (with
    priority order: a higher-priority Deny wins; child securityRules resources and inline rules),
    SQL public network access + TDE, Key Vault soft delete + purge protection, VM encryption at
    host, App Service / Function app HTTPS-only, ACR network access, APIM virtual network;
  - Kubernetes recommendations come from the cluster's Kubescape result, only while the
    Containers plan is Standard; one per Kubescape control (id kept in additionalData), with
    subAssessments per failed Kubernetes object (kind/namespace/name + fix paths);
  - resource-scoped assessments (.../{resource}/providers/Microsoft.Security/assessments);
  - secure score + controls follow Azure's formula and move when a recommendation is fixed;
  - assessment status-change dates are tracked; alerts are an honest 501;
  - Defender bookkeeping never appears in resource listings, and the state stays JSON-safe.

The Kubescape result is injected with a test scanner that parses the RECORDED CLI report
(tests/conformance/fixtures/kubescape/cli-results.json — produced by the real Kubescape CLI over
objects.yaml); test_kubescape_core.py proves that report == a live CLI scan of the same objects.

Run:  PYTHONPATH=. python3 tests/conformance/test_azure_security_core.py
"""
import json
from pathlib import Path

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
from core import kubescape_core as ks

FIX = Path(__file__).resolve().parent / "fixtures" / "kubescape"
SUB = DEFAULT_SUBSCRIPTION
RG = "sec-rg"
SEC = f"/subscriptions/{SUB}/providers/Microsoft.Security"
Q = {"api-version": "2021-06-01"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


class RecordedReportScanner:
    """Test double: 'scans' by parsing the recorded real-CLI report (synchronous)."""
    engine = "kubescape-cli v4.0.16 (recorded)"

    def __init__(self):
        self.calls = 0

    def request(self, rec, rid, reason=""):
        self.calls += 1
        rep = json.loads((FIX / "cli-results.json").read_text())
        ks.store_result(rec, "succeeded", engine=self.engine, parsed=ks.parse_report(rep, self.engine))


def _rid(t, name, rg=RG):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{t}/{name}"


def run() -> int:
    arm = AzureArm()
    arm.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})
    put = lambda rid, body, av="2023-01-01": arm.handle("PUT", rid, {"api-version": av}, {"location": "eastus", **body})

    def assessments(scope=""):
        r = arm.handle("GET", (scope or f"/subscriptions/{SUB}") + "/providers/Microsoft.Security/assessments", Q)
        assert r["status"] == 200, r
        return r["body"]

    def status_of(rid, title):
        for v in assessments()["value"]:
            if v["properties"]["resourceDetails"]["Id"].lower() == rid.lower() and v["properties"]["displayName"].startswith(title):
                return v["properties"]["status"]["code"]
        return None

    # ── pricings ───────────────────────────────────────────────────────────────────────
    r = arm.handle("GET", SEC + "/pricings", {"api-version": "2024-01-01"})
    plans = {p["name"]: p["properties"]["pricingTier"] for p in r["body"]["value"]}
    _check("13 Defender plans, all Free on a new subscription", len(plans) == 13 and set(plans.values()) == {"Free"} and "Containers" in plans)
    r = arm.handle("PUT", SEC + "/pricings/containers", {"api-version": "2024-01-01"}, {"properties": {"pricingTier": "Standard"}})
    _check("PUT pricings/Containers Standard (case-insensitive name)", r["status"] == 200 and r["body"]["name"] == "Containers"
           and r["body"]["properties"]["pricingTier"] == "Standard" and r["body"]["properties"]["enablementTime"])
    r = arm.handle("GET", SEC + "/pricings/Containers", {"api-version": "2024-01-01"})
    _check("GET reads the plan back", r["body"]["properties"]["pricingTier"] == "Standard")
    _check("invalid tier rejected", arm.handle("PUT", SEC + "/pricings/Containers", {}, {"properties": {"pricingTier": "Gold"}})["status"] == 400)
    _check("unknown plan -> 404", arm.handle("GET", SEC + "/pricings/Nope", {})["status"] == 404)
    arm.handle("PUT", SEC + "/pricings/Containers", {}, {"properties": {"pricingTier": "Free"}})

    # ── rule engine ────────────────────────────────────────────────────────────────────
    st = _rid("Microsoft.Storage/storageAccounts", "secst1")
    put(st, {"properties": {"allowBlobPublicAccess": True, "supportsHttpsTrafficOnly": False}})
    _check("storage: public blob access -> Unhealthy", status_of(st, "Storage account public access should be disallowed") == "Unhealthy")
    _check("storage: secure transfer off -> Unhealthy", status_of(st, "Secure transfer to storage accounts") == "Unhealthy")
    arm.handle("PATCH", st, {"api-version": "2023-01-01"}, {"properties": {"allowBlobPublicAccess": False, "supportsHttpsTrafficOnly": True}})
    _check("storage: fixed -> both Healthy", status_of(st, "Storage account public access") == "Healthy"
           and status_of(st, "Secure transfer to storage accounts") == "Healthy")

    nsg = _rid("Microsoft.Network/networkSecurityGroups", "secnsg")
    put(nsg, {}, "2023-11-01")
    _check("NSG with only default rules -> Healthy", status_of(nsg, "Management ports should not be open") == "Healthy")
    ssh = nsg + "/securityRules/allow-ssh"
    rule = {"properties": {"direction": "Inbound", "access": "Allow", "protocol": "Tcp", "priority": 300,
                           "sourceAddressPrefix": "*", "sourcePortRange": "*", "destinationAddressPrefix": "*", "destinationPortRange": "22"}}
    arm.handle("PUT", ssh, {"api-version": "2023-11-01"}, rule)
    _check("NSG child rule 0.0.0.0/0 (*) -> 22 Allow -> Unhealthy", status_of(nsg, "Management ports should not be open") == "Unhealthy")
    v = next(v for v in assessments()["value"] if v["properties"]["resourceDetails"]["Id"].lower() == nsg.lower())
    _check("NSG assessment explains which rule exposes which port", "port 22" in v["properties"]["status"]["description"]
           and "allow-ssh" in v["properties"]["status"]["description"])
    deny = dict(rule["properties"], access="Deny", priority=200)
    arm.handle("PUT", nsg + "/securityRules/deny-ssh", {"api-version": "2023-11-01"}, {"properties": deny})
    _check("a higher-priority Deny wins -> Healthy", status_of(nsg, "Management ports should not be open") == "Healthy")
    arm.handle("DELETE", nsg + "/securityRules/deny-ssh", {"api-version": "2023-11-01"})
    arm.handle("PUT", ssh, {"api-version": "2023-11-01"}, {"properties": dict(rule["properties"], sourceAddressPrefix="10.1.0.0/16")})
    _check("restricting the source fixes it -> Healthy", status_of(nsg, "Management ports should not be open") == "Healthy")
    nsg2 = _rid("Microsoft.Network/networkSecurityGroups", "secnsg2")
    put(nsg2, {"properties": {"securityRules": [{"name": "rdp", "properties": {"direction": "Inbound", "access": "Allow", "protocol": "*",
                                                 "priority": 100, "sourceAddressPrefix": "Internet", "destinationPortRanges": ["3000-4000"]}}]}}, "2023-11-01")
    _check("inline rule Internet -> 3000-4000 covers RDP 3389 -> Unhealthy", status_of(nsg2, "Management ports should not be open") == "Unhealthy")

    sql = _rid("Microsoft.Sql/servers", "secsql")
    put(sql, {"properties": {"administratorLogin": "a"}}, "2023-05-01-preview")
    _check("SQL server public network access (default Enabled) -> Unhealthy", status_of(sql, "Public network access on Azure SQL") == "Unhealthy")
    arm.handle("PATCH", sql, {"api-version": "2023-05-01-preview"}, {"properties": {"publicNetworkAccess": "Disabled"}})
    _check("SQL publicNetworkAccess Disabled -> Healthy", status_of(sql, "Public network access on Azure SQL") == "Healthy")
    db = sql + "/databases/appdb"
    arm.handle("PUT", db, {"api-version": "2023-05-01-preview"}, {"location": "eastus", "properties": {"transparentDataEncryption": {"state": "Disabled"}}})
    _check("SQL database TDE off -> Unhealthy", status_of(db, "Transparent Data Encryption") == "Unhealthy")
    arm.handle("PATCH", db, {"api-version": "2023-05-01-preview"}, {"properties": {"transparentDataEncryption": {"state": "Enabled"}}})
    _check("SQL database TDE on -> Healthy", status_of(db, "Transparent Data Encryption") == "Healthy")

    kv = _rid("Microsoft.KeyVault/vaults", "seckv")
    put(kv, {"properties": {"enableSoftDelete": False}}, "2023-07-01")
    _check("Key Vault soft delete off -> Unhealthy", status_of(kv, "Key vaults should have soft delete") == "Unhealthy")
    _check("Key Vault purge protection off (catalog default) -> Unhealthy", status_of(kv, "Key vaults should have deletion protection") == "Unhealthy")
    arm.handle("PATCH", kv, {"api-version": "2023-07-01"}, {"properties": {"enableSoftDelete": True, "enablePurgeProtection": True}})
    _check("Key Vault fixed -> both Healthy", status_of(kv, "Key vaults should have soft delete") == "Healthy"
           and status_of(kv, "Key vaults should have deletion protection") == "Healthy")

    vm = _rid("Microsoft.Compute/virtualMachines", "secvm")
    put(vm, {}, "2023-09-01")
    _check("VM without encryption at host -> Unhealthy", status_of(vm, "Virtual machines should encrypt") == "Unhealthy")
    arm.handle("PATCH", vm, {"api-version": "2023-09-01"}, {"properties": {"securityProfile": {"encryptionAtHost": True}}})
    _check("VM encryptionAtHost -> Healthy", status_of(vm, "Virtual machines should encrypt") == "Healthy")

    acr = _rid("Microsoft.ContainerRegistry/registries", "secacr")
    put(acr, {"sku": {"name": "Premium"}}, "2023-07-01")
    _check("ACR public network access -> Unhealthy", status_of(acr, "Container registries should not allow unrestricted") == "Unhealthy")
    arm.handle("PATCH", acr, {"api-version": "2023-07-01"}, {"properties": {"publicNetworkAccess": "Disabled"}})
    _check("ACR public access disabled -> Healthy", status_of(acr, "Container registries should not allow unrestricted") == "Healthy")

    apim = _rid("Microsoft.ApiManagement/service", "secapim")
    put(apim, {"sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}}, "2023-05-01-preview")
    _check("APIM without a virtual network -> Unhealthy", status_of(apim, "API Management services should use a virtual network") == "Unhealthy")
    arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"properties": {"virtualNetworkType": "External"}})
    _check("APIM External VNet -> Healthy", status_of(apim, "API Management services should use a virtual network") == "Healthy")

    web = _rid("Microsoft.Web/sites", "secweb")
    r = arm.handle("PUT", web, {"api-version": "2023-12-01"}, {"location": "eastus", "kind": "app", "properties": {"httpsOnly": False}})
    fn = _rid("Microsoft.Web/sites", "secfunc")
    arm.handle("PUT", fn, {"api-version": "2023-12-01"}, {"location": "eastus", "kind": "functionapp", "properties": {"httpsOnly": False}})
    _check("web app not HTTPS-only -> Unhealthy (App Service rule)", status_of(web, "App Service apps should only be accessible over HTTPS") == "Unhealthy"
           and status_of(web, "Function apps should") is None)
    _check("function app not HTTPS-only -> Unhealthy (Function app rule)", status_of(fn, "Function apps should only be accessible over HTTPS") == "Unhealthy")
    arm.handle("PATCH", fn, {"api-version": "2023-12-01"}, {"properties": {"httpsOnly": True}})
    _check("function app HTTPS-only -> Healthy", status_of(fn, "Function apps should only be accessible over HTTPS") == "Healthy")

    # ── Kubernetes (Kubescape) ─────────────────────────────────────────────────────────
    scanner = RecordedReportScanner()
    ks.set_scanner(scanner)
    aks = _rid("Microsoft.ContainerService/managedClusters", "secaks")
    put(aks, {}, "2024-09-02-preview")
    y = (FIX / "objects.yaml").read_text()
    r = arm.handle("POST", aks + "/runCommand", {"api-version": "2024-09-02-preview"}, {"command": "kubectl apply -f - <<EOF\n" + y + "EOF"})
    _check("objects applied via runCommand", r["body"]["exitCode"] == 0)
    _check("Containers plan OFF: no scan requested, no Kubernetes recommendations",
           scanner.calls == 0 and not [v for v in assessments()["value"] if "kubescapeControlId" in v["properties"]["additionalData"]])
    body = assessments()
    sc = next(s for s in body["vyomiKubernetesScanners"] if s["clusterId"].lower() == aks.lower())
    _check("the scanner state says the plan is off", sc["status"] == "plan-off")
    arm.handle("PUT", SEC + "/pricings/Containers", {}, {"properties": {"pricingTier": "Standard"}})
    body = assessments()
    k8s_items = [v for v in body["value"] if "kubescapeControlId" in v["properties"]["additionalData"]]
    _check("Containers plan ON: the first read scans the stale cluster", scanner.calls == 1 and len(k8s_items) == 61)
    priv = next(v for v in k8s_items if v["properties"]["additionalData"]["kubescapeControlId"] == "C-0057")
    _check("C-0057 -> 'Privileged containers should be avoided (C-0057)', Unhealthy, High, on the cluster",
           priv["properties"]["displayName"] == "Privileged containers should be avoided (C-0057)"
           and priv["properties"]["status"]["code"] == "Unhealthy" and priv["properties"]["metadata"]["severity"] == "High"
           and priv["properties"]["resourceDetails"]["Id"].lower() == aks.lower())
    _check("assessment metadata carries Kubescape's remediation + frameworks",
           "privileged" in priv["properties"]["metadata"]["remediationDescription"].lower() and priv["properties"]["metadata"]["frameworks"])
    na = [v for v in k8s_items if v["properties"]["status"]["code"] == "NotApplicable"]
    _check("controls with no matching objects are NotApplicable (not Healthy)", len(na) > 0)
    subs = arm.handle("GET", priv["id"] + "/subAssessments", {"api-version": "2019-01-01-preview"})["body"]["value"]
    _check("subAssessment per failed Kubernetes object: Deployment shop/priv-app with fix paths",
           [s["properties"]["id"] for s in subs] == ["Deployment/shop/priv-app"]
           and subs[0]["properties"]["additionalData"]["fixPaths"] is not None and subs[0]["properties"]["status"]["code"] == "Unhealthy")
    one = arm.handle("GET", subs[0]["id"], {"api-version": "2019-01-01-preview"})
    _check("GET one subAssessment", one["status"] == 200 and one["body"]["name"] == subs[0]["name"])
    allsubs = arm.handle("GET", SEC + "/subAssessments", {"api-version": "2019-01-01-preview"})["body"]["value"]
    _check("subscription-wide subAssessments list", len(allsubs) >= 40)
    scoped = assessments(aks)
    _check("resource-scoped assessments = only this cluster's", scoped["value"] and all(
        v["properties"]["resourceDetails"]["Id"].lower() == aks.lower() for v in scoped["value"]))
    one = arm.handle("GET", priv["id"], Q)
    _check("GET one assessment by its id", one["status"] == 200 and one["body"]["name"] == priv["name"])
    _check("unknown resource scope -> 404", arm.handle("GET", _rid("Microsoft.Storage/storageAccounts", "ghost") + "/providers/Microsoft.Security/assessments", Q)["status"] == 404)
    rg_scoped = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Security/assessments", Q)["body"]["value"]
    _check("resource-group-scoped list", rg_scoped and all(f"/resourcegroups/{RG}/" in v["id"].lower() for v in rg_scoped))
    meta = arm.handle("GET", SEC + "/assessmentMetadata", Q)["body"]["value"]
    _check("assessmentMetadata lists native rules + Kubescape controls", len(meta) == 12 + 61)
    r = arm.handle("POST", aks + "/runCommand", {"api-version": "2024-09-02-preview"}, {"command": "kubectl delete deploy priv-app -n shop"})
    _check("an object change rescans the cluster (plan on)", scanner.calls == 2)

    # ── secure score ───────────────────────────────────────────────────────────────────
    ss = arm.handle("GET", SEC + "/secureScores", {"api-version": "2020-01-01"})["body"]["value"][0]["properties"]["score"]
    ctrls = arm.handle("GET", SEC + "/secureScores/ascScore/secureScoreControls", {"api-version": "2020-01-01", "$expand": "definition"})["body"]["value"]
    inplay = [c for c in ctrls if c["properties"]["healthyResourceCount"] + c["properties"]["unhealthyResourceCount"] > 0]
    _check("secure score = sum(control current) / sum(control max) over controls in play",
           abs(ss["current"] - round(sum(c["properties"]["score"]["current"] for c in inplay), 2)) < 0.011
           and ss["max"] == sum(c["properties"]["score"]["max"] for c in inplay))
    for c in inplay:
        p = c["properties"]
        exp = round(p["score"]["max"] * p["healthyResourceCount"] / (p["healthyResourceCount"] + p["unhealthyResourceCount"]), 2)
        assert abs(p["score"]["current"] - exp) < 0.011, c
    _check("each control: current = max x healthy / (healthy + unhealthy)", True)
    _check("$expand=definition returns the control definition", all("definition" in c["properties"] for c in ctrls))
    smp = next(c for c in ctrls if c["properties"]["displayName"] == "Secure management ports")
    before = ss["current"]
    arm.handle("PUT", ssh, {"api-version": "2023-11-01"}, rule)       # re-open SSH to the internet
    ss2 = arm.handle("GET", SEC + "/secureScores/ascScore", {"api-version": "2020-01-01"})["body"]["properties"]["score"]
    _check("opening SSH to the internet lowers the secure score", ss2["current"] < before)
    v = next(v for v in assessments()["value"] if v["properties"]["resourceDetails"]["Id"].lower() == nsg.lower())
    _check("status change date tracked across Healthy -> Unhealthy",
           v["properties"]["status"]["statusChangeDate"] >= v["properties"]["status"]["firstEvaluationDate"])
    _check("definitions endpoint", len(arm.handle("GET", SEC + "/secureScoreControlDefinitions", {})["body"]["value"]) == 7)

    # ── honesty + hygiene ──────────────────────────────────────────────────────────────
    r = arm.handle("GET", SEC + "/alerts", {"api-version": "2022-01-01"})
    _check("alerts are an honest 501 NotImplemented", r["status"] == 501 and r["body"]["error"]["code"] == "NotImplemented")
    res = arm.handle("GET", f"/subscriptions/{SUB}/resources", {})["body"]["value"]
    _check("Defender bookkeeping never shows up in resource listings", not any("microsoft.security" in x["id"].lower() for x in res))
    _check("ARM state stays JSON-safe", json.loads(json.dumps(arm.state)) == arm.state)
    ks.set_scanner(ks.WasmScanner())
    print("\nRESULT: PASS — Microsoft Defender for Cloud (Microsoft.Security) conforms on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
