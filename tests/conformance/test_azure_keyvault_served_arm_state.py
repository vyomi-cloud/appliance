"""Per-vault Key Vault finds a vault that exists only in the SERVED ARM state (providers/azure_services._state), which is
where the appliance keeps vaults created over ARM. Before the fix the offline data plane looked only at the core ARM object and
answered 404 VaultNotFound for a real vault. Offline-only (wire_ingress + providers are not vendored into Nano).
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python tests/conformance/test_azure_keyvault_served_arm_state.py (python >= 3.10)"""
import json
from core.azure_arm_core import AzureArm
from core.aws_wire_router import AwsWireRouter
from core import wire_ingress
from providers import azure_services as prov


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


SUB = "00000000-0000-0000-0000-cloudlearn01"
vid = lambda n: f"/subscriptions/{SUB}/resourceGroups/g/providers/Microsoft.KeyVault/vaults/{n}"
r = AwsWireRouter(stores={"az_arm": AzureArm()})            # the core ARM object knows NO vaults
prov._state[vid("served").lower()] = {"id": vid("served"), "name": "served", "_type": "Microsoft.KeyVault/vaults",
                                      "location": "eastus", "properties": {}}
call = lambda m, p, b=None: wire_ingress._dispatch_azure("azure_keyvault", r, m, p, {"api-version": "7.4"}, {},
                                                         json.dumps(b).encode() if b is not None else b"")
try:
    _check("put secret into a vault that exists only in the served ARM state",
           call("PUT", "/azure-data/keyvault/served/secrets/s1", {"value": "A"})["status"] == 200)
    _check("get it back", call("GET", "/azure-data/keyvault/served/secrets/s1")["status"] == 200)
    _check("a vault that exists nowhere is 404", call("GET", "/azure-data/keyvault/nope/secrets/s1")["status"] == 404)
    del prov._state[vid("served").lower()]
    _check("after the vault is deleted the secret is 404", call("GET", "/azure-data/keyvault/served/secrets/s1")["status"] == 404)
finally:
    prov._state.pop(vid("served").lower(), None)
print("PASS")
