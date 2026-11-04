"""Azure Key Vault networking enforcement (azure.keyvaults.networking) — the Networking
blade's publicNetworkAccess / networkAcls.defaultAction now really gate the Key Vault
Keys/Secrets/Certificates data planes, not just round-trip through ARM.

Key Vault's own wire carries no vault identity (real Key Vault routes by the vault's own
hostname, {vault}.vault.azure.net; Vyomi's data planes sit behind one shared relay with no
per-vault host). The console closes that gap by tagging every data-plane call with the vault
it's showing (`x-vyomi-vault`, consoles/src/azure/services/keyvaults/api.js setActiveVault);
this proves the enforcement core/azure_arm_core.py.keyvault_network_denied() does with that
signal, exercised the same way both core/aws_wire_router.py (Nano) and core/wire_ingress.py
(offline) call it — through one shared AwsWireRouter instance, same as production.

Run: PYTHONPATH=. python3 tests/conformance/test_azure_keyvault_networking_core.py
"""
from __future__ import annotations

import json
import sys

try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


SUB = DEFAULT_SUBSCRIPTION
RG = "cloudlearn-rg"
AV = "2023-07-01"


def _vault_path(name):
    return f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/{name}"


def run() -> int:
    arm = AzureArm()
    router = AwsWireRouter(stores={"az_arm": arm})

    def kv(method, path, vault, body=None):
        headers = {"x-vyomi-vault": vault} if vault else {}
        b = json.dumps(body).encode() if body is not None else b""
        return router.handle(method, path, {"api-version": "7.4"}, headers, b)

    # Open vault (default networking): keys/secrets/certs all work.
    arm.handle("PUT", _vault_path("netopenkv"), {"api-version": AV}, {"location": "eastus"})
    r = kv("PUT", "/secrets/s1", "netopenkv", {"value": "x"})
    _check("open vault: secret create allowed", r["status"] == 200)

    # publicNetworkAccess: Disabled blocks every data-plane operation on THAT vault.
    arm.handle("PUT", _vault_path("netclosedkv"), {"api-version": AV},
               {"location": "eastus", "properties": {"publicNetworkAccess": "Disabled"}})
    r = kv("PUT", "/secrets/s1", "netclosedkv", {"value": "x"})
    _check("publicNetworkAccess=Disabled blocks secret create", r["status"] == 403
            and json.loads(r["body"])["error"]["code"] == "Forbidden")
    r = kv("POST", "/keys/k1/create", "netclosedkv", {"kty": "RSA", "key_size": 2048})
    _check("publicNetworkAccess=Disabled blocks key create", r["status"] == 403)
    r = kv("POST", "/certificates/c1/create", "netclosedkv", {"policy": {"x509_certificate_properties": {"subject": "CN=x"}}})
    _check("publicNetworkAccess=Disabled blocks certificate create", r["status"] == 403)
    r = kv("GET", "/secrets", "netclosedkv")
    _check("publicNetworkAccess=Disabled blocks list too", r["status"] == 403)

    # networkAcls.defaultAction: Deny blocks too, even with publicNetworkAccess left Enabled —
    # Vyomi has no caller IP/VNet to ever match an allow-list entry, so Deny is unconditional.
    arm.handle("PUT", _vault_path("netdenykv"), {"api-version": AV}, {"location": "eastus",
               "properties": {"networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices"}}})
    r = kv("PUT", "/secrets/s1", "netdenykv", {"value": "x"})
    _check("networkAcls.defaultAction=Deny blocks secret create", r["status"] == 403)

    # It's a LIVE config read, not a one-shot snapshot: flipping it back open on the SAME
    # vault immediately un-blocks it.
    arm.handle("PATCH", _vault_path("netclosedkv"), {"api-version": AV},
               {"properties": {"publicNetworkAccess": "Enabled"}})
    r = kv("PUT", "/secrets/s1", "netclosedkv", {"value": "x"})
    _check("re-enabling publicNetworkAccess unblocks the same vault", r["status"] == 200)

    # A call naming no vault, or an unknown one, is unaffected — "can't tell" must mean
    # "not enforced", never "silently denied".
    r = kv("PUT", "/secrets/s1", "", {"value": "x"})
    _check("no vault header: unaffected by any vault's networking", r["status"] == 200)
    r = kv("PUT", "/secrets/s1", "no-such-vault", {"value": "x"})
    _check("unknown vault name: unaffected (not evidence of a restriction)", r["status"] == 200)

    # Enforcement is genuinely per-vault: netdenykv's restriction never leaks onto netopenkv,
    # which shares the SAME global keys/secrets/certs store (azure.keyvaults.access_configuration).
    r = kv("PUT", "/secrets/s1", "netopenkv", {"value": "y"})
    _check("a second, unrelated vault is never affected by another vault's networking", r["status"] == 200)

    return 0


if __name__ == "__main__":
    sys.exit(run())
