"""Azure storage account network rules: ARM validation + Blob data-plane enforcement."""
try:
    from core import azure_blob_core as az, azure_storage_net as net
except ImportError:  # pragma: no cover
    import azure_blob_core as az, azure_storage_net as net  # type: ignore

ACCT = "netacct"
RID = f"/subscriptions/s/resourcegroups/r/providers/microsoft.storage/storageaccounts/{ACCT}"
SUB = "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/virtualNetworks/v1/subnets/default"


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print(f"  ok  {n}")


def run() -> int:
    st = az.AzureBlobStore()
    st.create_container("data")
    vnet = {"id": SUB.rsplit("/subnets", 1)[0], "name": "v1", "_type": "Microsoft.Network/virtualNetworks",
            "properties": {"subnets": [{"name": "default"}]}}
    state = {"vnetkey": vnet}
    # validation
    _check("bad cidr rejected", net.validate_network_properties({"networkAcls": {"ipRules": [{"value": "nope"}]}})[1] == "InvalidNetworkAclsIpRule")
    _check("private range rejected", net.validate_network_properties({"networkAcls": {"ipRules": [{"value": "10.1.0.0/24"}]}}) is not None)
    _check("/31 rejected", net.validate_network_properties({"networkAcls": {"ipRules": [{"value": "8.8.8.0/31"}]}}) is not None)
    _check("public cidr ok", net.validate_network_properties({"networkAcls": {"defaultAction": "Deny", "ipRules": [{"value": "8.8.8.0/24"}]}}, state) is None)
    _check("bad defaultAction", net.validate_network_properties({"networkAcls": {"defaultAction": "x"}}) is not None)
    _check("missing subnet rejected", net.validate_network_properties({"networkAcls": {"virtualNetworkRules": [{"id": SUB.replace("default", "nope")}]}}, state) is not None)
    _check("existing subnet ok", net.validate_network_properties({"networkAcls": {"virtualNetworkRules": [{"id": SUB}]}}, state) is None)
    _check("bad custom domain", net.validate_network_properties({"customDomain": {"name": "x"}}) is not None)
    _check("bad routing", net.validate_network_properties({"routingPreference": {"routingChoice": "Z"}}) is not None)

    def get(headers=None):
        return az.dispatch(st, "GET", f"/{ACCT}/data", {"restype": "container", "comp": "list"}, headers or {}, b"", account=ACCT, arm_state=state)
    props = {"networkAcls": {"defaultAction": "Deny", "bypass": "None", "ipRules": [], "virtualNetworkRules": []}}
    state[RID] = {"properties": props}
    _check("deny blocks default caller", get().status == 403)
    props["networkAcls"]["ipRules"] = [{"value": "127.0.0.1"}]
    _check("ip rule admits caller", get().status != 403)
    props["networkAcls"]["ipRules"] = [{"value": "8.8.8.0/24"}]
    _check("other ip rule still denies", get().status == 403)
    _check("client ip header in cidr admitted", get({"x-vyomi-client-ip": "8.8.8.9"}).status != 403)
    props["networkAcls"]["virtualNetworkRules"] = [{"id": SUB}]
    _check("subnet rule admits", get({"x-vyomi-source-subnet": SUB}).status != 403)
    props["networkAcls"]["resourceAccessRules"] = [{"resourceId": "/subscriptions/s/x", "tenantId": "t"}]
    _check("resource instance admits", get({"x-vyomi-resource-id": "/subscriptions/s/x"}).status != 403)
    _check("azure service bypass off", get({"x-vyomi-azure-service": "1"}).status == 403)
    props["networkAcls"]["bypass"] = "AzureServices"
    _check("azure service bypass on", get({"x-vyomi-azure-service": "1"}).status != 403)
    props["networkAcls"]["defaultAction"] = "Allow"
    _check("allow admits all", get().status != 403)
    _check("keyPolicy range", net.validate_network_properties({"keyPolicy": {"keyExpirationPeriodInDays": 0}}) is not None)
    _check("keyPolicy ok", net.validate_network_properties({"keyPolicy": {"keyExpirationPeriodInDays": 90}}) is None)
    return 0


def run_keys() -> None:
    try:
        from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUBS
    except ImportError:  # pragma: no cover
        from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUBS  # type: ignore
    arm = AzureArm()
    q = {"api-version": "2023-05-01"}
    arm.handle("PUT", f"/subscriptions/{SUBS}/resourceGroups/r1", q, {"location": "eastus"})
    base = f"/subscriptions/{SUBS}/resourceGroups/r1/providers/Microsoft.Storage/storageAccounts/keyacct"
    r = arm.handle("PUT", base, q, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    _check("create account", r["status"] in (200, 201))

    def keys(act, body=None):
        o = arm.handle("POST", f"{base}/{act}", q, body)
        return o["status"], o["body"]
    st, k1 = keys("listKeys")
    _check("listKeys returns two distinct keys", st == 200 and len(k1["keys"]) == 2 and k1["keys"][0]["value"] != k1["keys"][1]["value"])
    st, k1b = keys("listKeys")
    _check("keys are stable between calls", k1b == k1)
    st, k2 = keys("regenerateKey", {"keyName": "key1"})
    _check("regenerateKey rotates key1 only", k2["keys"][0]["value"] != k1["keys"][0]["value"] and k2["keys"][1]["value"] == k1["keys"][1]["value"])
    st, _ = keys("regenerateKey", {"keyName": "key9"})
    _check("regenerateKey rejects unknown key", st == 400)
    g = arm.handle("GET", base, q)["body"]
    _check("keyCreationTime recorded on rotation", "key1" in (g["properties"].get("keyCreationTime") or {}))
    r = arm.handle("PATCH", base, q, {"properties": {"keyPolicy": {"keyExpirationPeriodInDays": 0}}})
    _check("keyPolicy 0 days rejected over ARM", r["status"] == 400)
    r = arm.handle("PATCH", base, q, {"properties": {"keyPolicy": {"keyExpirationPeriodInDays": 90}}})
    _check("keyPolicy stored", r["status"] == 200 and r["body"]["properties"]["keyPolicy"]["keyExpirationPeriodInDays"] == 90)


if __name__ == "__main__":
    run()
    run_keys()
    print("OK")
