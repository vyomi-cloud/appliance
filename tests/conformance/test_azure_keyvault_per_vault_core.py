"""Azure Key Vault data plane is scoped PER VAULT (not per space): a secret belongs to the vault
it was written to, a missing/deleted vault is 404 VaultNotFound, and deleting a vault or its
resource group removes its secrets and certificates.

Run: PYTHONPATH=. python3 tests/conformance/test_azure_keyvault_per_vault_core.py
"""
from __future__ import annotations

import json

try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore

SUB, RG, AV = DEFAULT_SUBSCRIPTION, "kvrg", "2023-07-01"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    arm = AzureArm()
    router = AwsWireRouter(stores={"az_arm": arm})

    def vault(name):
        return arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/{name}",
                          {"api-version": AV}, {"location": "eastus"})

    def kv(method, path, body=None, headers=None):
        b = json.dumps(body).encode() if body is not None else b""
        return router.handle(method, path, {"api-version": "7.4"}, headers or {}, b)

    def P(v, rest):
        return f"/azure-data/keyvault/{v}{rest}"

    # the offline appliance routes `/azure-data/keyvault/{vault}/...` through wire_ingress; the Nano router takes
    # root paths + the console's x-vyomi-vault header. Same scoping core, both entry points are asserted.
    from core import wire_ingress

    def kv_path(method, path, body=None):
        b = json.dumps(body).encode() if body is not None else b""
        return wire_ingress._dispatch_azure("azure_keyvault", router, method, path, {"api-version": "7.4"}, {}, b)

    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})
    vault("va"); vault("vb")

    _check("set in va", kv_path("PUT", P("va", "/secrets/s1"), {"value": "A"})["status"] == 200)
    _check("va returns its secret", json.loads(kv_path("GET", P("va", "/secrets/s1"))["body"])["value"] == "A")
    _check("vb does NOT see va's secret", kv_path("GET", P("vb", "/secrets/s1"))["status"] == 404)
    _check("vb list is empty", json.loads(kv_path("GET", P("vb", "/secrets"))["body"])["value"] == [])
    kv_path("PUT", P("vb", "/secrets/s1"), {"value": "B"})
    _check("same name, own value in vb", json.loads(kv_path("GET", P("vb", "/secrets/s1"))["body"])["value"] == "B")
    _check("va unchanged", json.loads(kv_path("GET", P("va", "/secrets/s1"))["body"])["value"] == "A")
    _check("console header selects the vault",
           json.loads(kv("GET", "/secrets/s1", headers={"x-vyomi-vault": "vb"})["body"])["value"] == "B")

    r = kv_path("GET", P("neverexisted", "/secrets/s1"))
    _check("unknown vault -> 404 VaultNotFound",
           r["status"] == 404 and json.loads(r["body"])["error"]["code"] == "VaultNotFound")

    _check("no vault in the request keeps the legacy shared namespace working",
           kv("PUT", "/secrets/legacy", {"value": "L"})["status"] == 200
           and kv("GET", "/secrets/legacy")["status"] == 200)

    # certificates are per vault too
    cr = kv_path("POST", P("va", "/certificates/c1/create"), {"policy": {"issuer": {"name": "Self"}, "x509_props": {"subject": "CN=a"}}})
    _check("cert create in va", cr["status"] in (200, 202))
    _check("cert not visible in vb", kv_path("GET", P("vb", "/certificates/c1"))["status"] == 404)

    # deleting a vault removes ITS data only
    arm.handle("DELETE", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/va", {"api-version": AV}, None)
    _check("deleted vault -> 404 VaultNotFound", kv_path("GET", P("va", "/secrets/s1"))["status"] == 404)
    vault("va")
    _check("recreated vault starts empty", kv_path("GET", P("va", "/secrets/s1"))["status"] == 404)
    _check("other vault untouched", json.loads(kv_path("GET", P("vb", "/secrets/s1"))["body"])["value"] == "B")

    # resource-group delete removes every vault's secrets
    arm.handle("DELETE", f"/subscriptions/{SUB}/resourceGroups/{RG}", {"api-version": "2021-04-01"}, None)
    _check("RG delete: vb gone", kv_path("GET", P("vb", "/secrets/s1"))["status"] == 404)
    vault("vb")
    _check("RG delete destroyed the secret", kv_path("GET", P("vb", "/secrets/s1"))["status"] == 404)
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
