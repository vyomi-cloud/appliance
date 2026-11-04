"""AZ-02..05 config extensions: AKS KEDA / authorized IPs / extensions, Cosmos CORS + dedicated gateway + CMK,
Service Bus CMK + network rule sets, App Configuration CMK, subnet service endpoints / delegations.
Run: PYTHONPATH=. python tests/conformance/test_azure_cfgext_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


RG = f"/subscriptions/{SUB}/resourceGroups/cx-rg"
Q = {"api-version": "2024-05-01"}


def run():
    a = AzureArm()
    put = lambda path, body, q=Q: a.handle("PUT", path, q, body)
    get = lambda path, q=Q: a.handle("GET", path, q)
    code = lambda r: (r["body"].get("error") or {}).get("code")
    put(RG, {"location": "eastus"}, {"api-version": "2021-04-01"})

    # ── AKS: KEDA, authorized IP ranges, extensions
    c = f"{RG}/providers/Microsoft.ContainerService/managedClusters/k1"
    r = put(c, {"location": "eastus", "properties": {"kubernetesVersion": "1.22.4", "dnsPrefix": "k1", "workloadAutoScalerProfile": {"keda": {"enabled": True}}}})
    _check("KEDA rejected on k8s 1.22", r["status"] == 400 and code(r) == "FeatureNotSupportedForKubernetesVersion")
    r = put(c, {"location": "eastus", "properties": {"kubernetesVersion": "1.29.2", "dnsPrefix": "k1", "workloadAutoScalerProfile": {"keda": {"enabled": True}}}})
    _check("KEDA enabled on 1.29", r["status"] in (200, 201) and r["body"]["properties"]["workloadAutoScalerProfile"]["keda"]["enabled"] is True)
    r = put(c, {"location": "eastus", "properties": {"apiServerAccessProfile": {"authorizedIPRanges": ["10.0.0.0/8", "nope"]}}})
    _check("bad authorized range rejected", r["status"] == 400)
    r = put(c, {"location": "eastus", "properties": {"apiServerAccessProfile": {"enablePrivateCluster": True, "authorizedIPRanges": ["10.0.0.0/8"]}}})
    _check("authorized ranges + private cluster rejected", r["status"] == 400)
    r = put(c, {"location": "eastus", "properties": {"apiServerAccessProfile": {"authorizedIPRanges": ["203.0.113.0/24"]}}})
    _check("authorized ranges accepted", r["status"] in (200, 201))

    X = c + "/providers/Microsoft.KubernetesConfiguration/extensions"
    EQ = {"api-version": "2023-05-01"}
    r = put(X + "/dapr", {"properties": {"extensionType": "Microsoft.Bogus"}}, EQ)
    _check("unknown extension type", r["status"] == 400 and code(r) == "ExtensionTypeNotFound")
    r = put(X + "/dapr", {"properties": {"extensionType": "microsoft.dapr", "version": "1.12.0", "autoUpgradeMinorVersion": True}}, EQ)
    _check("version + autoUpgrade rejected", r["status"] == 400)
    r = put(X + "/dapr", {"properties": {"extensionType": "microsoft.dapr", "autoUpgradeMinorVersion": True}}, EQ)
    _check("extension installed", r["status"] in (200, 201) and r["body"]["properties"]["provisioningState"] == "Succeeded" and r["body"]["properties"]["installedVersion"])
    r = put(X + "/dapr2", {"properties": {"extensionType": "microsoft.dapr"}}, EQ)
    _check("second dapr instance rejected", r["status"] == 409)
    r = put(f"{RG}/providers/Microsoft.ContainerService/managedClusters/none/providers/Microsoft.KubernetesConfiguration/extensions/dapr", {"properties": {"extensionType": "microsoft.dapr"}}, EQ)
    _check("extension on missing cluster 404", r["status"] == 404)
    _check("extension listed", len(get(X, EQ)["body"]["value"]) == 1)
    a.handle("DELETE", c, Q)
    _check("extensions cascade with cluster", get(X + "/dapr", EQ)["status"] == 404)

    # ── Key Vault for CMKs
    kv = f"{RG}/providers/Microsoft.KeyVault/vaults/cxvault"
    put(kv, {"location": "eastus", "properties": {"tenantId": "00000000-0000-0000-0000-000000000000", "sku": {"family": "A", "name": "standard"}}}, {"api-version": "2023-07-01"})
    KEY = "https://cxvault.vault.azure.net/keys/k1"

    # ── Cosmos
    ca = f"{RG}/providers/Microsoft.DocumentDB/databaseAccounts/cxcosmos"
    CQ = {"api-version": "2024-05-15"}
    base = {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard", "locations": [{"locationName": "East US", "failoverPriority": 0}]}}
    _check("cosmos created", put(ca, base, CQ)["status"] in (200, 201, 202))
    def with_props(extra, **top):
        b = {**base, **top}; b["properties"] = {**base["properties"], **extra}; return b
    r = put(ca, with_props({"cors": [{"allowedOrigins": "ftp://x"}]}), CQ)
    _check("cors bad origin", r["status"] == 400)
    r = put(ca, with_props({"cors": [{"allowedOrigins": "https://a.example.com,https://*.example.org", "maxAgeInSeconds": -1}]}), CQ)
    _check("cors bad max age", r["status"] == 400)
    r = put(ca, with_props({"cors": [{"allowedOrigins": "https://a.example.com,https://*.example.org", "allowedMethods": "GET,POST", "maxAgeInSeconds": 300}]}), CQ)
    _check("cors stored", r["status"] in (200, 201, 202) and get(ca, CQ)["body"]["properties"]["cors"][0]["maxAgeInSeconds"] == 300)
    r = put(ca, with_props({"cors": [{"allowedOrigins": "*"}] * 11}), CQ)
    _check("cors max 10 rules", r["status"] == 400)
    r = put(ca, with_props({"keyVaultKeyUri": "https://nonesuch.vault.azure.net/keys/k1", "defaultIdentity": "SystemAssignedIdentity"}, identity={"type": "SystemAssigned"}), CQ)
    _check("cosmos CMK vault must exist", r["status"] == 400 and code(r) == "KeyVaultNotFound")
    r = put(ca, with_props({"keyVaultKeyUri": KEY}), CQ)
    _check("cosmos CMK needs identity", r["status"] == 400)
    r = put(ca, with_props({"keyVaultKeyUri": KEY, "defaultIdentity": "SystemAssignedIdentity", "cors": []}, identity={"type": "SystemAssigned"}), CQ)
    _check("cosmos CMK accepted", r["status"] in (200, 201, 202))
    G = ca + "/services/SqlDedicatedGateway"
    r = put(G, {"properties": {"serviceType": "SqlDedicatedGateway", "instanceSize": "Cosmos.D2s", "instanceCount": 1}}, CQ)
    _check("gateway size validated", r["status"] == 400)
    r = put(G, {"properties": {"serviceType": "SqlDedicatedGateway", "instanceSize": "Cosmos.D4s", "instanceCount": 9}}, CQ)
    _check("gateway count validated", r["status"] == 400)
    r = put(G, {"properties": {"serviceType": "SqlDedicatedGateway", "instanceSize": "Cosmos.D4s", "instanceCount": 2}}, CQ)
    _check("gateway provisioned", r["status"] in (200, 201, 202) and len(r["body"]["properties"]["locations"]) == 2 and r["body"]["properties"]["sqlDedicatedGatewayEndpoint"].endswith("cosmos.azure.com/"))

    # ── Service Bus
    sb = f"{RG}/providers/Microsoft.ServiceBus/namespaces/cxsb"
    SQ = {"api-version": "2022-10-01-preview"}
    _check("sb standard", put(sb, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}}, SQ)["status"] in (200, 201))
    enc = {"keySource": "Microsoft.KeyVault", "keyVaultProperties": [{"keyName": "k1", "keyVaultUri": "https://cxvault.vault.azure.net"}]}
    r = put(sb, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}, "identity": {"type": "SystemAssigned"}, "properties": {"encryption": enc}}, SQ)
    _check("sb CMK needs Premium", r["status"] == 400)
    _check("sb premium", put(sb, {"location": "eastus", "sku": {"name": "Premium", "tier": "Premium", "capacity": 1}}, SQ)["status"] in (200, 201))
    r = put(sb, {"location": "eastus", "sku": {"name": "Premium", "tier": "Premium", "capacity": 1}, "properties": {"encryption": enc}}, SQ)
    _check("sb CMK needs identity", r["status"] == 400)
    r = put(sb, {"location": "eastus", "sku": {"name": "Premium", "tier": "Premium", "capacity": 1}, "identity": {"type": "SystemAssigned"}, "properties": {"encryption": enc}}, SQ)
    _check("sb CMK accepted", r["status"] in (200, 201))
    NR = sb + "/networkRuleSets/default"
    r = put(NR, {"properties": {"defaultAction": "Deny", "ipRules": [{"ipMask": "bad", "action": "Allow"}]}}, SQ)
    _check("sb bad ip rule", r["status"] == 400)
    vn = f"{RG}/providers/Microsoft.Network/virtualNetworks/cxv"
    put(vn, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16"]}, "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.5.0.0/24"}}]}}, {"api-version": "2023-11-01"})
    r = put(NR, {"properties": {"defaultAction": "Deny", "virtualNetworkRules": [{"subnet": {"id": vn + "/subnets/s1"}}]}}, SQ)
    _check("sb subnet needs service endpoint", r["status"] == 400 and code(r) == "SubnetMissingServiceEndpoint")
    r = put(vn, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16"]}, "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.5.0.0/24", "serviceEndpoints": [{"service": "Microsoft.ServiceBus"}]}}]}}, {"api-version": "2023-11-01"})
    _check("service endpoint accepted", r["status"] in (200, 201))
    r = put(NR, {"properties": {"defaultAction": "Deny", "ipRules": [{"ipMask": "203.0.113.0/24", "action": "Allow"}], "virtualNetworkRules": [{"subnet": {"id": vn + "/subnets/s1"}}]}}, SQ)
    _check("sb rule set stored", r["status"] in (200, 201) and r["body"]["properties"]["defaultAction"] == "Deny")
    # standard namespace has no network rule sets
    sb2 = f"{RG}/providers/Microsoft.ServiceBus/namespaces/cxsb2"
    put(sb2, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}}, SQ)
    _check("sb rule set needs Premium", put(sb2 + "/networkRuleSets/default", {"properties": {"defaultAction": "Deny"}}, SQ)["status"] == 400)

    # ── Service Bus system events need Premium
    EV = {"api-version": "2022-06-15"}
    evb = {"properties": {"destination": {"endpointType": "WebHook", "properties": {"endpointUrl": "https://example.com/h"}}, "filter": {"includedEventTypes": ["Microsoft.ServiceBus.ActiveMessagesAvailableWithNoListeners"]}}}
    _check("sb events need Premium", put(sb2 + "/providers/Microsoft.EventGrid/eventSubscriptions/e1", evb, EV)["status"] == 400)
    _check("sb events on Premium", put(sb + "/providers/Microsoft.EventGrid/eventSubscriptions/e1", evb, EV)["status"] in (200, 201))
    bad_t = {"properties": {**evb["properties"], "filter": {"includedEventTypes": ["Microsoft.Storage.BlobCreated"]}}}
    _check("sb events validate type", put(sb + "/providers/Microsoft.EventGrid/eventSubscriptions/e2", bad_t, EV)["status"] == 400)

    # ── subnet service endpoints / delegations
    VQ = {"api-version": "2023-11-01"}
    bad = lambda sp: put(vn, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16"]}, "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.5.0.0/24", **sp}}]}}, VQ)
    _check("bad service endpoint", bad({"serviceEndpoints": [{"service": "Microsoft.Nope"}]})["status"] == 400)
    _check("bad delegation", bad({"delegations": [{"name": "d", "properties": {"serviceName": "Microsoft.Nope/x"}}]})["status"] == 400)
    _check("good delegation", bad({"delegations": [{"name": "d", "properties": {"serviceName": "Microsoft.Web/serverFarms"}}]})["status"] in (200, 201))

    # ── App Configuration
    ac = f"{RG}/providers/Microsoft.AppConfiguration/configurationStores/cxappcfg1"
    AQ = {"api-version": "2023-03-01"}
    _check("appcfg free", put(ac, {"location": "eastus", "sku": {"name": "free"}}, AQ)["status"] in (200, 201))
    ek = {"keyVaultProperties": {"keyIdentifier": KEY, "identityClientId": "11111111-1111-1111-1111-111111111111"}}
    r = put(ac, {"location": "eastus", "sku": {"name": "free"}, "identity": {"type": "SystemAssigned"}, "properties": {"encryption": ek}}, AQ)
    _check("appcfg CMK needs Standard", r["status"] == 400)
    r = put(ac, {"location": "eastus", "sku": {"name": "standard"}, "properties": {"encryption": ek}}, AQ)
    _check("appcfg CMK needs identity", r["status"] == 400)
    r = put(ac, {"location": "eastus", "sku": {"name": "standard"}, "identity": {"type": "SystemAssigned"}, "properties": {"encryption": {"keyVaultProperties": {"keyIdentifier": "https://x.vault.azure.net/keys/k"}}}}, AQ)
    _check("appcfg CMK vault must exist", r["status"] == 400)
    r = put(ac, {"location": "eastus", "sku": {"name": "standard"}, "identity": {"type": "SystemAssigned"}, "properties": {"encryption": ek}}, AQ)
    _check("appcfg CMK accepted", r["status"] in (200, 201))
    # ── API Management: restrict an API to a self-hosted gateway
    ap = f"{RG}/providers/Microsoft.ApiManagement/service/cxapim"
    AQ2 = {"api-version": "2022-08-01"}
    put(ap, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.co", "publisherName": "x"}}, AQ2)
    put(ap + "/apis/echo", {"properties": {"displayName": "Echo", "path": "echo", "protocols": ["https"], "serviceUrl": "https://example.com"}}, AQ2)
    _check("gateway link needs gateway", put(ap + "/gateways/gw1/apis/echo", {}, AQ2)["status"] == 404)
    put(ap + "/gateways/gw1", {"properties": {"locationData": {"name": "dc1"}}}, AQ2)
    _check("gateway link needs api", put(ap + "/gateways/gw1/apis/nope", {}, AQ2)["status"] == 404)
    _check("gateway link created", put(ap + "/gateways/gw1/apis/echo", {}, AQ2)["status"] in (200, 201))
    _check("gateway apis listed", len(get(ap + "/gateways/gw1/apis", AQ2)["body"]["value"]) == 1)
    # ── Storage trusted-services exceptions (networkAcls.bypass)
    sa = f"{RG}/providers/Microsoft.Storage/storageAccounts/cxsa{1}"
    SAQ = {"api-version": "2023-01-01"}
    sbody = lambda byp: {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "properties": {"networkAcls": {"defaultAction": "Deny", "bypass": byp}}}
    _check("bypass token validated", put(sa, sbody("Everything"), SAQ)["status"] == 400)
    _check("bypass None cannot combine", put(sa, sbody("None,Logging"), SAQ)["status"] == 400)
    _check("bypass stored", put(sa, sbody("AzureServices, Logging"), SAQ)["status"] in (200, 201) and "Logging" in get(sa, SAQ)["body"]["properties"]["networkAcls"]["bypass"])

    # ── SQL Data Discovery & Classification labels
    SQ2 = {"api-version": "2020-11-01-preview"}
    sqs = f"{RG}/providers/Microsoft.Sql/servers/cxsql"
    put(sqs, {"location": "eastus", "properties": {"administratorLogin": "u", "administratorLoginPassword": "Pass1234!x"}}, SQ2)
    lab = sqs + "/databases/d1/schemas/dbo/tables/Customer/columns/Email/sensitivityLabels/current"
    _check("label needs database", put(lab, {"properties": {"labelName": "Confidential"}}, SQ2)["status"] == 404)
    put(sqs + "/databases/d1", {"location": "eastus"}, SQ2)
    _check("label rank validated", put(lab, {"properties": {"labelName": "Confidential", "rank": "Huge"}}, SQ2)["status"] == 400)
    _check("label needs name or type", put(lab, {"properties": {"rank": "High"}}, SQ2)["status"] == 400)
    r = put(lab, {"properties": {"labelName": "Confidential", "informationType": "Contact Info", "rank": "Medium"}}, SQ2)
    _check("label stored", r["status"] in (200, 201) and get(lab, SQ2)["body"]["properties"]["rank"] == "Medium")

    # ── API Management soft-delete + restore
    DS = f"/subscriptions/{SUB}/providers/Microsoft.ApiManagement"
    _check("apim delete", a.handle("DELETE", ap, AQ2)["status"] in (200, 202, 204))
    lst = get(DS + "/deletedservices", AQ2)["body"]["value"]
    _check("soft-deleted service listed", len(lst) == 1 and lst[0]["name"] == "cxapim" and lst[0]["properties"]["scheduledPurgeDate"])
    r = put(ap, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.co", "publisherName": "x"}}, AQ2)
    _check("name reuse while soft-deleted conflicts", r["status"] == 409 and code(r) == "ServiceAlreadyExistsInSoftDeletedState")
    r = put(ap, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.co", "publisherName": "x", "restore": True}}, AQ2)
    _check("restore brings the service back", r["status"] in (200, 201) and get(ap, AQ2)["status"] == 200)
    _check("restore brings its APIs back", get(ap + "/apis/echo", AQ2)["status"] == 200)
    _check("restore clears the soft-deleted record", get(DS + "/deletedservices", AQ2)["body"]["value"] == [])
    a.handle("DELETE", ap, AQ2)
    _check("purge soft-deleted", a.handle("DELETE", DS + "/locations/eastus/deletedservices/cxapim", AQ2)["status"] == 200 and get(DS + "/deletedservices", AQ2)["body"]["value"] == [])
    _check("restore without soft-delete record 404", put(ap, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.co", "publisherName": "x", "restore": True}}, AQ2)["status"] == 404)
    print("test_azure_cfgext_core: PASS")


if __name__ == "__main__":
    run()
