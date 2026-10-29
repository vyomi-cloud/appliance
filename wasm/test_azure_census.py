"""Nano Azure census must count ARM resources (feeds cost_savings resource_count + azure savings).
Regression: the census read a non-existent `_state` attribute of AzureArm, so it always counted 0."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wasm.core as wasm_core
sys.modules["core"] = wasm_core          # in the browser `core` IS wasm/core
from wasm.backends.store import Backends
from wasm.providers import registry as R

b = Backends()
base = "/subscriptions/s/resourceGroups/rg1/providers/"
for t, n, body in [("Microsoft.Storage/storageAccounts", "a1", {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}),
                   ("Microsoft.KeyVault/vaults", "k1", {"location": "eastus", "properties": {}})]:
    assert R.dispatch(b, "azure", "_arm", "PUT", params={"path": base + t + "/" + n, "query": {"api-version": "2023-01-01"}, "body": body})["ok"]
c = R._census_dispatch(b, "azure")
ok = c["resources"] == 2 and c["by_service"].get("microsoft.storage/storageaccounts") == 1
print(("[PASS]" if ok else "[FAIL]"), "azure census counts ARM resources", c["by_service"])
sys.exit(0 if ok else 1)
