"""Azure Key Vault access enforcement (azure.keyvaults.access_configuration /
azure.keyvaults.access_policies) — the Access configuration RBAC-vs-access-policy switch and
the Access policies list now really gate the Key Vault Keys/Secrets/Certificates data planes,
evaluated against the one simulated signed-in principal every console session acts as
(core/azure_arm_core.py CALLER_PRINCIPAL_ID).

A freshly created vault self-grants that principal full access (access-policy mode: a
self-granting policy entry; RBAC mode: a Key Vault Administrator role assignment at the
vault's own scope) — the same thing `az keyvault create` already does by default — so the
console's own create-vault-then-add-a-secret path keeps working. Everything past that is a
REAL decision: narrowing or clearing the grant really narrows or blocks the data plane, and
control-plane roles (Owner, Contributor) granted elsewhere carry no Key Vault dataActions,
matching real Azure's own actions/dataActions split.

Run: PYTHONPATH=. python3 tests/conformance/test_azure_keyvault_access_core.py
"""
from __future__ import annotations

import json
import sys

try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION, CALLER_PRINCIPAL_ID
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION, CALLER_PRINCIPAL_ID  # type: ignore
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

    # ── Access policy mode (default) ────────────────────────────────────────────────────
    arm.handle("PUT", _vault_path("polkv"), {"api-version": AV}, {"location": "eastus"})
    r = kv("PUT", "/secrets/s1", "polkv", {"value": "x"})
    _check("fresh vault (policy mode): secret create self-granted", r["status"] == 200)
    r = kv("GET", "/secrets/s1", "polkv")
    _check("fresh vault (policy mode): secret get self-granted", r["status"] == 200)

    # Clearing the access policies (the console's own "Delete" on the Access policies panel)
    # really locks the data plane — real Azure's own "you can lock yourself out".
    arm.handle("PATCH", _vault_path("polkv"), {"api-version": AV}, {"properties": {"accessPolicies": []}})
    r = kv("PUT", "/secrets/s2", "polkv", {"value": "x"})
    _check("empty access policies: secret create denied", r["status"] == 403
            and json.loads(r["body"])["error"]["code"] == "Forbidden")
    r = kv("GET", "/secrets/s1", "polkv")
    _check("empty access policies: secret get denied too", r["status"] == 403)

    # A narrow grant (Get only, no Create) really narrows what's allowed.
    arm.handle("PATCH", _vault_path("polkv"), {"api-version": AV}, {"properties": {"accessPolicies": [
        {"tenantId": "00000000-0000-0000-0000-000000000000", "objectId": CALLER_PRINCIPAL_ID,
         "permissions": {"secrets": ["Get"]}}]}})
    r = kv("GET", "/secrets/s1", "polkv")
    _check("Get-only policy: secret get allowed", r["status"] == 200)
    r = kv("PUT", "/secrets/s3", "polkv", {"value": "x"})
    _check("Get-only policy: secret create still denied", r["status"] == 403)

    # Keys and certificates are gated independently from secrets.
    r = kv("POST", "/keys/k1/create", "polkv", {"kty": "RSA", "key_size": 2048})
    _check("Get-only secrets policy doesn't grant keys", r["status"] == 403)
    arm.handle("PATCH", _vault_path("polkv"), {"api-version": AV}, {"properties": {"accessPolicies": [
        {"tenantId": "00000000-0000-0000-0000-000000000000", "objectId": CALLER_PRINCIPAL_ID,
         "permissions": {"keys": ["Get", "List", "Create", "Delete"], "secrets": ["Get"]}}]}})
    r = kv("POST", "/keys/k1/create", "polkv", {"kty": "RSA", "key_size": 2048})
    _check("adding a keys grant unlocks key create", r["status"] == 200)

    # ── RBAC mode ────────────────────────────────────────────────────────────────────────
    arm.handle("PUT", _vault_path("rbackv"), {"api-version": AV},
               {"location": "eastus", "properties": {"enableRbacAuthorization": True}})
    r = kv("PUT", "/secrets/s1", "rbackv", {"value": "x"})
    _check("fresh vault (RBAC mode): secret create self-granted (Key Vault Administrator)", r["status"] == 200)
    r = kv("POST", "/keys/k1/create", "rbackv", {"kty": "RSA", "key_size": 2048})
    _check("fresh vault (RBAC mode): key create self-granted", r["status"] == 200)
    r = kv("POST", "/keys/k1/encrypt", "rbackv", {"alg": "RSA-OAEP", "value": "eA"})
    _check("fresh vault (RBAC mode): crypto 'use' self-granted", r["status"] == 200)

    # Revoke the self-granted assignment (simulates locking yourself out) — everything's
    # denied again.
    vault_rid = _vault_path("rbackv")
    for k in [k for k, v in arm.state.items()
              if isinstance(v, dict) and v.get("_type", "").lower() == "microsoft.authorization/roleassignments"
              and (v.get("properties") or {}).get("principalId") == CALLER_PRINCIPAL_ID
              and (v.get("properties") or {}).get("scope", "").lower() == vault_rid.lower()]:
        del arm.state[k]
    r = kv("PUT", "/secrets/s2", "rbackv", {"value": "x"})
    _check("revoked role assignment: secret create denied", r["status"] == 403)

    # Owner/Contributor at a broader scope does NOT rescue you — control-plane roles carry
    # no Key Vault dataActions, matching real Azure's own actions/dataActions split.
    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Authorization/roleAssignments/owner-ra",
               {"api-version": "2022-04-01"},
               {"properties": {"principalId": CALLER_PRINCIPAL_ID, "roleName": "Owner", "principalType": "User"}})
    r = kv("PUT", "/secrets/s2", "rbackv", {"value": "x"})
    _check("Owner at the resource group scope grants NO Key Vault data access", r["status"] == 403)

    # Granting a narrow data role at the RESOURCE GROUP scope (the only PUT-able scope today)
    # covers the vault inside it via the same scope-inheritance real Azure uses.
    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Authorization/roleAssignments/secrets-user-ra",
               {"api-version": "2022-04-01"},
               {"properties": {"principalId": CALLER_PRINCIPAL_ID, "roleName": "Key Vault Secrets User", "principalType": "User"}})
    r = kv("GET", "/secrets/s1", "rbackv")
    _check("Key Vault Secrets User at the RG scope: secret get allowed", r["status"] == 200)
    r = kv("PUT", "/secrets/s2", "rbackv", {"value": "x"})
    _check("Key Vault Secrets User at the RG scope: secret create still denied (read-only role)", r["status"] == 403)
    r = kv("POST", "/keys/k1/create", "rbackv", {"kty": "RSA", "key_size": 2048})
    _check("Key Vault Secrets User grants no key access", r["status"] == 403)

    # Enforcement is genuinely per-vault: rbackv's lockout never leaks onto polkv.
    r = kv("GET", "/secrets/s1", "polkv")
    _check("a second, unrelated vault is never affected by another vault's access model", r["status"] == 200)

    # ── Unaffected cases: no vault header / unknown vault ───────────────────────────────
    r = kv("PUT", "/secrets/s1", "", {"value": "x"})
    _check("no vault header: unaffected by any vault's access configuration", r["status"] == 200)
    r = kv("PUT", "/secrets/s1", "no-such-vault", {"value": "x"})
    _check("unknown vault name: unaffected (not evidence of a restriction)", r["status"] == 200)

    return 0


if __name__ == "__main__":
    sys.exit(run())
