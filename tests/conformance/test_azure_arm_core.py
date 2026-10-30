"""Azure ARM control-plane conformance — the acceptance gate for the WASM port.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler, azure_services.handle_arm)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE Azure Resource Manager wire semantics: real ARM paths
(/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.X/{type}/{name}
?api-version=), PUT→201/200 with the resource view (id/name/type/location/
properties.provisioningState=Succeeded), long-running-operation headers
(Azure-AsyncOperation + Location → /api/azure/operations/{id} → Succeeded),
collection GET → {"value":[...]} scoped by subscription + resource group, item
GET/DELETE, provider registration probes, resource-group list/item, POST action
verbs (listKeys / VM start/powerOff metadata-only). The catalog is the appliance's
real RESOURCE_CATALOG dumped verbatim (core/azure_arm_data.py); the CRUD is the
real handler logic, not a stub. No network, no fastapi/azure-sdk.

Run on host:    python3 tests/conformance/test_azure_arm_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import json

try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


SUB = DEFAULT_SUBSCRIPTION
RG = "cloudlearn-rg"
AV = "2023-01-01"


def _p(rg, ns, typ, name):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{ns}/{typ}/{name}"


def run() -> int:
    arm = AzureArm()

    # 1. Subscription probe
    r = arm.handle("GET", f"/subscriptions/{SUB}")
    _check("subscription 200", r["status"] == 200 and r["body"]["subscriptionId"] == SUB)

    # 2. Provider registration probes (ARM clients call these before CRUD)
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Storage")
    _check("provider registered", r["status"] == 200 and r["body"]["registrationState"] == "Registered")
    _check("provider has resourceTypes", any(t["resourceType"] == "storageAccounts" for t in r["body"]["resourceTypes"]))
    r = arm.handle("POST", f"/subscriptions/{SUB}/providers/Microsoft.Storage/register")
    _check("provider register POST", r["status"] == 200)
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers")
    _check("providers list", r["status"] == 200 and len(r["body"]["value"]) >= 5)

    # 3. Resource group create + list + get
    r = arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}", {"api-version": AV},
                   {"location": "eastus", "tags": {"env": "dev"}})
    _check("rg put 200", r["status"] == 200 and r["body"]["name"] == RG)
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourcegroups")
    _check("rg list contains default", any(g["name"] == RG for g in r["body"]["value"]))

    # 4. PUT a storage account (top-level type → LRO headers; status forced to 200,
    #    matching the appliance: "201 breaks armstorage" — 200 is the create/update intersection)
    path = _p(RG, "Microsoft.Storage", "storageAccounts", "vyomidata")
    r = arm.handle("PUT", path, {"api-version": AV},
                   {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2",
                    "properties": {}})
    _check("storage put 200 (LRO)", r["status"] == 200)
    _check("storage id canonical", r["body"]["id"].lower() == path.lower())
    _check("storage name", r["body"]["name"] == "vyomidata")
    _check("storage type", r["body"]["type"] == "Microsoft.Storage/storageAccounts")
    _check("storage provisioningState", r["body"]["properties"]["provisioningState"] == "Succeeded")
    _check("storage LRO async header",
           "/api/azure/operations/" in (r["headers"].get("Azure-AsyncOperation") or ""))
    _check("storage no private keys leaked", not any(k.startswith("_") for k in r["body"]))

    # 5. LRO poll → Succeeded
    op_url = r["headers"]["Azure-AsyncOperation"]
    op_path = op_url.split("?", 1)[0]
    r = arm.handle("GET", op_path)
    _check("operation Succeeded", r["status"] == 200 and r["body"]["status"] == "Succeeded")

    # 6. Idempotent PUT → 200 (already exists)
    r = arm.handle("PUT", path, {"api-version": AV}, {"location": "eastus", "properties": {}})
    _check("storage re-put 200", r["status"] == 200)

    # 7. Item GET
    r = arm.handle("GET", path, {"api-version": AV})
    _check("storage get 200", r["status"] == 200 and r["body"]["name"] == "vyomidata")

    # 8. Collection GET (scoped by RG) → {"value":[...]}
    coll = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts"
    r = arm.handle("GET", coll, {"api-version": AV})
    _check("storage collection value list", isinstance(r["body"]["value"], list))
    _check("storage collection has item", any(x["name"] == "vyomidata" for x in r["body"]["value"]))

    # 9. RG scoping: a second account in a different RG is NOT listed under the first
    arm.handle("PUT", _p("other-rg", "Microsoft.Storage", "storageAccounts", "elsewhere"),
               {"api-version": AV}, {"location": "eastus", "properties": {}})
    r = arm.handle("GET", coll, {"api-version": AV})
    _check("collection rg-scoped", all(x["name"] != "elsewhere" for x in r["body"]["value"]))

    # 10. POST action verb: listKeys → keys
    r = arm.handle("POST", path + "/listKeys", {"api-version": AV})
    _check("listKeys returns keys", r["status"] == 200 and len(r["body"]["keys"]) >= 1)

    # 11. Unsupported type → ResourceTypeNotSupported
    r = arm.handle("PUT", _p(RG, "Microsoft.Nope", "widgets", "x"), {"api-version": AV}, {})
    _check("unsupported type 404", r["status"] == 404 and r["body"]["error"]["code"] == "ResourceTypeNotSupported")

    # 12. Missing item GET → ResourceNotFound
    r = arm.handle("GET", _p(RG, "Microsoft.Storage", "storageAccounts", "ghost"), {"api-version": AV})
    _check("missing get 404", r["status"] == 404 and r["body"]["error"]["code"] == "ResourceNotFound")

    # 13. DELETE then GET → gone
    r = arm.handle("DELETE", path, {"api-version": AV})
    _check("storage delete 200", r["status"] == 200)
    r = arm.handle("GET", path, {"api-version": AV})
    _check("storage gone after delete", r["status"] == 404)

    # 14. VM lifecycle — create then start/powerOff (metadata-only, no LXD)
    vm = _p(RG, "Microsoft.Compute", "virtualMachines", "appvm")
    r = arm.handle("PUT", vm, {"api-version": AV},
                   {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})
    _check("vm created", r["status"] == 200 and r["body"]["name"] == "appvm")
    r = arm.handle("POST", vm + "/start", {"api-version": AV})
    _check("vm start succeeded", r["status"] == 200 and r["body"]["status"] == "Succeeded")
    _check("vm start metadata-only", r["body"]["containerStatus"] == "running")
    r = arm.handle("POST", vm + "/powerOff", {"api-version": AV})
    _check("vm powerOff stopped", r["body"]["containerStatus"] == "stopped")
    r = arm.handle("GET", vm, {"api-version": AV})
    _check("vm power state persisted", r["body"]["properties"]["powerState"] == "PowerState/stopped")
    # action on a non-VM type is rejected
    r = arm.handle("POST", _p(RG, "Microsoft.Storage", "storageAccounts", "vyomidata") + "/start",
                   {"api-version": AV})
    _check("start rejected on non-vm", r["status"] == 400)

    # 15. Non-ARM path → 404
    r = arm.handle("GET", "/not/an/arm/path")
    _check("non-arm 404", r["status"] == 404)

    # 16. PATCH merges (tags) without wiping properties
    r = arm.handle("PATCH", vm, {"api-version": AV}, {"tags": {"team": "platform"}})
    _check("patch 200", r["status"] == 200 and r["body"]["tags"]["team"] == "platform")
    _check("patch preserves properties",
           r["body"]["properties"]["hardwareProfile"]["vmSize"] == "Standard_B1s")

    # 17. APIM ships a default global policy: GET .../policies/policy is 200 (not 404)
    apim = _p(RG, "Microsoft.ApiManagement", "service", "apim-pol")
    pol = apim + "/policies/policy"
    r = arm.handle("GET", pol, {"api-version": "2023-05-01-preview"})
    _check("apim policy 404 before the service exists", r["status"] == 404)
    arm.handle("PUT", apim, {"api-version": "2023-05-01-preview"}, {"location": "eastus"})
    r = arm.handle("GET", pol, {"api-version": "2023-05-01-preview"})
    _check("apim default global policy 200", r["status"] == 200
           and "<policies>" in r["body"]["properties"]["value"])
    arm.handle("PUT", pol, {"api-version": "2023-05-01-preview"},
               {"properties": {"format": "xml", "value": "<policies><inbound /></policies>"}})
    r = arm.handle("GET", pol, {"api-version": "2023-05-01-preview"})
    _check("apim saved policy persists", r["body"]["properties"]["value"] == "<policies><inbound /></policies>")

    # 18. Generic top-level "identity" block merges like tags/sku (any catalog resource type).
    topic = _p(RG, "Microsoft.EventGrid", "topics", "eg-identity")
    r = arm.handle("PUT", topic, {"api-version": "2024-06-01-preview"}, {"location": "eastus",
                   "identity": {"type": "SystemAssigned"}})
    _check("identity stored on create", r["body"]["identity"]["type"] == "SystemAssigned")
    r = arm.handle("PATCH", topic, {"api-version": "2024-06-01-preview"}, {"identity": {"principalId": "p1"}})
    _check("identity merges without wiping type",
           r["body"]["identity"]["type"] == "SystemAssigned" and r["body"]["identity"]["principalId"] == "p1")

    # 19. Microsoft.Authorization/locks — a resource-scoped extension resource (any
    # resource type can carry one; the vault is just the first UI to surface it).
    kv = _p(RG, "Microsoft.KeyVault", "vaults", "uickv")
    arm.handle("PUT", kv, {"api-version": "2023-07-01"}, {"location": "eastus"})
    lock = kv + "/providers/Microsoft.Authorization/locks/dont-delete-me"
    r = arm.handle("GET", kv + "/providers/Microsoft.Authorization/locks", {"api-version": "2020-05-01"})
    _check("locks empty before create", r["status"] == 200 and r["body"]["value"] == [])
    r = arm.handle("PUT", lock, {"api-version": "2020-05-01"},
                   {"properties": {"level": "CanNotDelete", "notes": "protected"}})
    _check("lock put 201", r["status"] == 201 and r["body"]["name"] == "dont-delete-me")
    _check("lock id canonical", r["body"]["id"].lower() == lock.lower())
    _check("lock level", r["body"]["properties"]["level"] == "CanNotDelete")
    r = arm.handle("GET", lock, {"api-version": "2020-05-01"})
    _check("lock get 200", r["status"] == 200 and r["body"]["properties"]["notes"] == "protected")
    r = arm.handle("GET", kv + "/providers/Microsoft.Authorization/locks", {"api-version": "2020-05-01"})
    _check("locks list has item", any(x["name"] == "dont-delete-me" for x in r["body"]["value"]))
    # a lock on one vault doesn't leak into another vault's scope
    kv2 = _p(RG, "Microsoft.KeyVault", "vaults", "otherkv")
    arm.handle("PUT", kv2, {"api-version": "2023-07-01"}, {"location": "eastus"})
    r = arm.handle("GET", kv2 + "/providers/Microsoft.Authorization/locks", {"api-version": "2020-05-01"})
    _check("locks scoped per resource", r["body"]["value"] == [])

    # 20. Activity log (Microsoft.Insights/eventtypes/management/values) — vault create and
    # lock writes land on the unified subscription-scoped feed, filtered by resourceUri.
    events_path = f"/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values"
    ev = arm.handle("GET", events_path, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{kv}'"})
    ops = [e["operationName"]["value"] for e in ev["body"]["value"]]
    _check("activity log records the vault create + the lock create, newest first",
           ev["status"] == 200 and ops[0] == "Create lock" and "Create" in ops)
    ev2 = arm.handle("GET", events_path, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{kv2}'"})
    ops2 = [e["operationName"]["value"] for e in ev2["body"]["value"]]
    _check("activity log is scoped per vault (no cross-resource leakage)", "Create lock" not in ops2)

    r = arm.handle("DELETE", lock, {"api-version": "2020-05-01"})
    _check("lock delete 200", r["status"] == 200)
    r = arm.handle("GET", lock, {"api-version": "2020-05-01"})
    _check("lock gone after delete", r["status"] == 404)
    # deleting the resource cascades to its locks
    arm.handle("PUT", lock, {"api-version": "2020-05-01"}, {"properties": {"level": "ReadOnly"}})
    arm.handle("DELETE", kv, {"api-version": "2023-07-01"})
    r = arm.handle("GET", kv + "/providers/Microsoft.Authorization/locks", {"api-version": "2020-05-01"})
    _check("locks cascade-deleted with resource", r["body"]["value"] == [])

    print("\nRESULT: PASS — Azure ARM core conforms (native ARM wire + LRO + catalog CRUD) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
