"""Azure Key Vault KEYS are scoped per vault (like secrets/certs): the same key name in two vaults
is two keys, soft-delete/purge are per vault, deleting a vault drops its keys, and customer-managed-key
envelopes resolve the key in the vault their key URI names.

Run: PYTHONPATH=. python3 tests/conformance/test_azure_keyvault_keys_per_vault_core.py
"""
from __future__ import annotations

import json

try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
    from core.aws_wire_router import AwsWireRouter
    from core import azure_cmk_core as cmk
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore
    import azure_cmk_core as cmk  # type: ignore

SUB, RG = DEFAULT_SUBSCRIPTION, "kvkrg"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    arm = AzureArm()
    router = AwsWireRouter(stores={"az_arm": arm})
    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})
    for v in ("va", "vb"):
        arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/{v}",
                   {"api-version": "2023-07-01"}, {"location": "eastus"})

    def kv(vault, method, path, body=None):
        b = json.dumps(body).encode() if body is not None else b""
        r = router.handle(method, path, {"api-version": "7.4"}, {"x-vyomi-vault": vault}, b)
        return r["status"], (json.loads(r["body"]) if r["body"] else {})

    st, a = kv("va", "POST", "/keys/k1/create", {"kty": "RSA", "key_size": 2048})
    _check("create k1 in va", st == 200)
    _check("vb does NOT see va's key", kv("vb", "GET", "/keys/k1")[0] == 404)
    _check("vb key list is empty", kv("vb", "GET", "/keys")[1]["value"] == [])
    st, b = kv("vb", "POST", "/keys/k1/create", {"kty": "RSA", "key_size": 2048})
    _check("same name creates a separate key in vb", st == 200 and a["key"]["kid"] != b["key"]["kid"]
           and a["key"]["n"] != b["key"]["n"])
    _check("va lists exactly its own key", len(kv("va", "GET", "/keys")[1]["value"]) == 1)

    # soft delete is per vault
    _check("delete k1 in va", kv("va", "DELETE", "/keys/k1")[0] == 200)
    _check("vb's k1 survives va's delete", kv("vb", "GET", "/keys/k1")[0] == 200)
    _check("va's deleted list has k1", len(kv("va", "GET", "/deletedkeys")[1]["value"]) == 1)
    _check("vb's deleted list is empty", kv("vb", "GET", "/deletedkeys")[1]["value"] == [])
    _check("recover in va", kv("va", "POST", "/deletedkeys/k1/recover")[0] == 200)

    # customer-managed key: the envelope resolves the key in the vault its URI names
    store = router.az_kvkeys
    env = cmk.seal(store, "https://vb.vault.azure.net/keys/k1", b"secret")
    _check("envelope records its vault", env.get("keyVault") == "vb")
    _check("unseal resolves vb's key", cmk.unseal(store, env) == b"secret")
    kv("vb", "DELETE", "/keys/k1")
    try:
        cmk.unseal(store, env)
        _check("unseal fails once vb's key is deleted (va's k1 must not stand in)", False)
    except cmk.CmkError:
        _check("unseal fails once vb's key is deleted (va's k1 must not stand in)", True)
    _check("usable() checks the named vault", cmk.usable(store, "https://va.vault.azure.net/keys/k1")[0]
           and not cmk.usable(store, "https://vb.vault.azure.net/keys/k1")[0])

    # deleting a vault drops its keys
    arm.handle("DELETE", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/va",
               {"api-version": "2023-07-01"}, None)
    from core import azure_keyvault_keys_core as kvk
    _check("vault delete purges its keys", list(kvk.scoped(store, "va").keys) == [])
    return 0


if __name__ == "__main__":
    run()
    print("OK")
