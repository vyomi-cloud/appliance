"""CMK key lookup: Storage / Cosmos / Service Bus / App Config customer-managed keys are cross-checked against the Key Vault keys store.
Run: PYTHONPATH=. python tests/conformance/test_azure_cmk_keylookup.py"""
try:
    from core import azure_cfgext_core as cfg, azure_keyvault_keys_core as kvk
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
    from core.kms_keystore import InMemoryKeyStore
except ImportError:  # pragma: no cover
    import azure_cfgext_core as cfg, azure_keyvault_keys_core as kvk  # type: ignore
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    store = InMemoryKeyStore()
    cfg.bind_key_store(store)
    a = AzureArm()
    RG = f"/subscriptions/{SUB}/resourceGroups/k-rg"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", RG + "/providers/Microsoft.KeyVault/vaults/kv1", {"api-version": "2023-07-01"}, {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}})
    cos = RG + "/providers/Microsoft.DocumentDB/databaseAccounts/c1"
    body = lambda: {"location": "eastus", "identity": {"type": "SystemAssigned"}, "properties": {"keyVaultKeyUri": "https://kv1.vault.azure.net/keys/mykey", "defaultIdentity": "SystemAssignedIdentity"}}
    r = a.handle("PUT", cos, {"api-version": "2024-05-15"}, body())
    _check("missing key rejected (Cosmos)", r["status"] == 400 and r["body"]["error"]["code"] == "KeyVaultKeyNotFound")
    import json
    kv = kvk.dispatch(store, "POST", "/keys/mykey/create", {}, {}, json.dumps({"kty": "RSA"}).encode())
    _check("key created", kv.status in (200, 201))
    r = a.handle("PUT", cos, {"api-version": "2024-05-15"}, body())
    _check("existing key accepted (Cosmos)", r["status"] in (200, 201))
    st = RG + "/providers/Microsoft.Storage/storageAccounts/sa1"
    sb = lambda k: {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "properties": {"encryption": {"keySource": "Microsoft.Keyvault", "keyvaultproperties": {"keyvaulturi": "https://kv1.vault.azure.net", "keyname": k}}}}
    r = a.handle("PUT", st, {"api-version": "2023-01-01"}, sb("nokey"))
    _check("missing key rejected (Storage)", r["status"] == 400 and "nokey" in r["body"]["error"]["message"])
    r = a.handle("PUT", st, {"api-version": "2023-01-01"}, sb("mykey"))
    _check("existing key accepted (Storage)", r["status"] in (200, 201))
    cfg.set_key_lookup(None)
    r = a.handle("PUT", RG + "/providers/Microsoft.DocumentDB/databaseAccounts/c2", {"api-version": "2024-05-15"}, body())
    _check("no lookup injected -> not cross-checked", r["status"] in (200, 201))
    print("cmk key lookup: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
