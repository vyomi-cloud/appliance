"""Customer-managed keys, end to end with REAL SDKs over HTTP: azure-cosmos and azure-appconfiguration read/write data in
accounts whose data is envelope-encrypted with a Key Vault key; disabling the key makes the SDK calls fail (403) and data stays
ciphertext at rest; re-enabling restores access.  Key Vault operations use the simulator's Key Vault keys wire.
Run: PYTHONPATH=. python tests/conformance/test_azure_cmk_sdk.py"""
import json

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import HttpResponseError
from azure.cosmos import CosmosClient

from core import azure_keyvault_keys_core as kvk
from core.azure_arm_core import DEFAULT_SUBSCRIPTION as S
from tests.conformance._az_http_bridge import start, header_transport


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    router, srv, base = start()
    arm, kv = router.az_arm, router.az_kvkeys
    kvk.dispatch(kv, "POST", "/keys/cmk1/create", {}, {}, json.dumps({"kty": "RSA"}).encode())
    setkey = lambda en: kvk.dispatch(kv, "PATCH", "/keys/cmk1", {}, {}, json.dumps({"attributes": {"enabled": en}}).encode())
    RG = f"/subscriptions/{S}/resourceGroups/k-rg"
    arm.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    arm.handle("PUT", RG + "/providers/Microsoft.KeyVault/vaults/kv1", {"api-version": "2023-07-01"},
               {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}})
    KEY = "https://kv1.vault.azure.net/keys/cmk1"
    ident = {"type": "SystemAssigned"}
    arm.handle("PUT", RG + "/providers/Microsoft.DocumentDB/databaseAccounts/cos", {"api-version": "2024-05-15"},
               {"location": "eastus", "identity": ident, "properties": {"keyVaultKeyUri": KEY, "defaultIdentity": "SystemAssignedIdentity"}})
    arm.handle("PUT", RG + "/providers/Microsoft.AppConfiguration/configurationStores/cfg1", {"api-version": "2024-05-01"},
               {"location": "eastus", "sku": {"name": "Standard"}, "identity": ident,
                "properties": {"encryption": {"keyVaultProperties": {"keyIdentifier": KEY}}}})

    cl = CosmosClient(base, credential="a2V5", transport=header_transport({"x-vyomi-account": "cos"}), enable_endpoint_discovery=False)
    c = cl.create_database("d").create_container("c", partition_key={"paths": ["/pk"], "kind": "Hash"})
    c.upsert_item({"id": "1", "pk": "a", "secret": "TOP-SECRET-VALUE"})
    _check("cosmos SDK write/read through the CMK account", c.read_item("1", "a")["secret"] == "TOP-SECRET-VALUE")
    _check("cosmos at rest: only the CMK envelope, no plaintext", list(router.az_cosmos.docs) == ["$cmk"] and "TOP-SECRET" not in json.dumps(router.az_cosmos.docs))
    setkey(False)
    try:
        c.read_item("1", "a")
        raise AssertionError("expected failure")
    except HttpResponseError as e:
        _check("cosmos SDK read fails with 403 when the key is disabled", e.status_code == 403)
    setkey(True)
    _check("cosmos SDK read works again after re-enable", c.read_item("1", "a")["secret"] == "TOP-SECRET-VALUE")

    conn = f"Endpoint={base}/azure-data/appconfig/cfg1;Id=cred;Secret=c2VjcmV0"
    ac = AzureAppConfigurationClient.from_connection_string(conn)
    ac.set_configuration_setting(ConfigurationSetting(key="db", value="PRIVATE-CONN-STRING"))
    _check("appconfig SDK set/get through the CMK store", ac.get_configuration_setting("db").value == "PRIVATE-CONN-STRING")
    st = arm.state[(RG + "/providers/Microsoft.AppConfiguration/configurationStores/cfg1").lower()]
    _check("appconfig at rest: ciphertext envelope only", "_kv" not in st and "PRIVATE-CONN-STRING" not in json.dumps(st, default=str))
    setkey(False)
    try:
        ac.get_configuration_setting("db")
        raise AssertionError("expected failure")
    except HttpResponseError as e:
        _check("appconfig SDK read fails with 403 when the key is disabled", e.status_code == 403)
    setkey(True)
    _check("appconfig SDK read works again after re-enable", ac.get_configuration_setting("db").value == "PRIVATE-CONN-STRING")
    srv.shutdown()
    print("PASS test_azure_cmk_sdk")


if __name__ == "__main__":
    run()
