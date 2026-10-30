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

    # 21. Resource groups are their own real resource, not just names inferred from their
    # contents: an explicitly-created, EMPTY group persists its own location/tags and shows
    # up in the list even with nothing inside it.
    empty_rg = "uic-empty-rg"
    r = arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{empty_rg}", {"api-version": AV},
                   {"location": "westus", "tags": {"team": "platform"}})
    _check("empty rg put 200", r["status"] == 200 and r["body"]["location"] == "westus" and r["body"]["tags"]["team"] == "platform")
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{empty_rg}", {"api-version": AV})
    _check("empty rg get persists tags/location", r["status"] == 200 and r["body"]["tags"] == {"team": "platform"} and r["body"]["location"] == "westus")
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourcegroups")
    _check("rg list contains the empty group", any(g["name"] == empty_rg for g in r["body"]["value"]))

    # 22. PATCH merges resource-group tags; PUT replaces them (same contract as every other
    # catalog resource — see _upsert).
    r = arm.handle("PATCH", f"/subscriptions/{SUB}/resourceGroups/{empty_rg}", {"api-version": AV}, {"tags": {"env": "dev"}})
    _check("rg patch merges tags", r["status"] == 200 and r["body"]["tags"] == {"team": "platform", "env": "dev"})
    r = arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{empty_rg}", {"api-version": AV}, {"location": "westus", "tags": {"env": "prod"}})
    _check("rg put replaces tags", r["status"] == 200 and r["body"]["tags"] == {"env": "prod"})

    # 23. GET .../resourceGroups/{rg}/resources — every resource in the group, any type at
    # once (the real "list resources" API the RG Overview/Resources tab and the delete
    # confirmation's dependent-resources table both call).
    cascade_rg = "uic-cascade-rg"
    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{cascade_rg}", {"api-version": AV}, {"location": "eastus"})
    arm.handle("PUT", _p(cascade_rg, "Microsoft.Storage", "storageAccounts", "uiccascadesa"), {"api-version": AV}, {"location": "eastus"})
    arm.handle("PUT", _p(cascade_rg, "Microsoft.KeyVault", "vaults", "uiccascadekv"), {"api-version": AV}, {"location": "eastus"})
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{cascade_rg}/resources", {"api-version": AV})
    names_in_group = {x["name"] for x in r["body"]["value"]}
    _check("resources-in-group lists every type, excludes the group itself",
           r["status"] == 200 and names_in_group == {"uiccascadesa", "uiccascadekv"})

    # 24. Deleting a resource group cascades to everything inside it (real ARM behaviour).
    r = arm.handle("DELETE", f"/subscriptions/{SUB}/resourceGroups/{cascade_rg}", {"api-version": AV})
    _check("rg delete 200", r["status"] == 200)
    r = arm.handle("GET", _p(cascade_rg, "Microsoft.Storage", "storageAccounts", "uiccascadesa"), {"api-version": AV})
    _check("cascade-deleted storage account is gone", r["status"] == 404)
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{cascade_rg}", {"api-version": AV})
    _check("deleted resource group itself is gone (no implicit resources left)", r["status"] == 404)
    r = arm.handle("DELETE", f"/subscriptions/{SUB}/resourceGroups/uic-never-existed", {"api-version": AV})
    _check("deleting a never-created resource group 404s", r["status"] == 404)

    # 25. Microsoft.Authorization/locks scoped directly to a resource group (not one of its
    # resources) — e.g. "don't delete this whole resource group".
    rg_lock_rg = "uic-locked-rg"
    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{rg_lock_rg}", {"api-version": AV}, {"location": "eastus"})
    rg_lock = f"/subscriptions/{SUB}/resourceGroups/{rg_lock_rg}/providers/Microsoft.Authorization/locks/protect-rg"
    r = arm.handle("PUT", rg_lock, {"api-version": "2020-05-01"}, {"properties": {"level": "CanNotDelete"}})
    _check("rg-scoped lock put 201", r["status"] == 201 and r["body"]["properties"]["level"] == "CanNotDelete")
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{rg_lock_rg}/providers/Microsoft.Authorization/locks", {"api-version": "2020-05-01"})
    _check("rg-scoped locks list has item", any(x["name"] == "protect-rg" for x in r["body"]["value"]))
    r = arm.handle("DELETE", rg_lock, {"api-version": "2020-05-01"})
    _check("rg-scoped lock delete 200", r["status"] == 200)

    # a lock scoped to the resource group itself (no _sub/_rg bookkeeping fields of its own —
    # see azure_locks_core.upsert) must still cascade away when the GROUP is deleted.
    rg_lock2 = f"/subscriptions/{SUB}/resourceGroups/{rg_lock_rg}/providers/Microsoft.Authorization/locks/protect-rg-2"
    arm.handle("PUT", rg_lock2, {"api-version": "2020-05-01"}, {"properties": {"level": "CanNotDelete"}})
    arm.handle("DELETE", f"/subscriptions/{SUB}/resourceGroups/{rg_lock_rg}", {"api-version": AV})
    r = arm.handle("GET", rg_lock2, {"api-version": "2020-05-01"})
    _check("resource-group-scoped lock cascades away when the group itself is deleted", r["status"] == 404)

    # 26. Microsoft.Resources/deployments: a generic catalog resource (no template evaluation,
    # see azure_arm_data.py) — enough to back a real "Deployments" history list + "View
    # template" honestly. PUT is an LRO like any other top-level type.
    dep = _p(RG, "Microsoft.Resources", "deployments", "uic-deployment")
    r = arm.handle("PUT", dep, {"api-version": "2021-04-01"},
                   {"properties": {"mode": "Incremental", "template": {"resources": []}, "timestamp": "2026-01-01T00:00:00Z"}})
    _check("deployment put 200 (LRO)", r["status"] == 200 and r["body"]["properties"]["provisioningState"] == "Succeeded")
    _check("deployment stores the template verbatim", r["body"]["properties"]["template"] == {"resources": []})
    r = arm.handle("GET", _p(RG, "Microsoft.Resources", "deployments", "uic-deployment"), {"api-version": "2021-04-01"})
    _check("deployment get 200", r["status"] == 200 and r["body"]["name"] == "uic-deployment")
    coll = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Resources/deployments"
    r = arm.handle("GET", coll, {"api-version": "2021-04-01"})
    _check("deployment collection lists it", any(x["name"] == "uic-deployment" for x in r["body"]["value"]))
    r = arm.handle("DELETE", dep, {"api-version": "2021-04-01"})
    _check("deployment delete 200", r["status"] == 200)
    # 21. Microsoft.ContainerRegistry/registries — generic catalog CRUD + the admin-credentials
    # POST actions (az acr credential show / renew) + nested child resources (webhooks).
    AV_ACR = "2023-07-01"
    acr = _p(RG, "Microsoft.ContainerRegistry", "registries", "uicacr")
    r = arm.handle("PUT", acr, {"api-version": AV_ACR}, {"location": "eastus", "sku": {"name": "Standard"}})
    _check("registry put 200 (LRO)", r["status"] == 200 and r["body"]["name"] == "uicacr")
    _check("registry admin user off by default", r["body"]["properties"]["adminUserEnabled"] is False)
    r = arm.handle("POST", acr + "/listCredentials", {"api-version": AV_ACR})
    _check("listCredentials before admin user enabled -> 400", r["status"] == 400
           and r["body"]["error"]["code"] == "AdminUserCredentialsNotEnabled")
    arm.handle("PATCH", acr, {"api-version": AV_ACR}, {"properties": {"adminUserEnabled": True}})
    r = arm.handle("POST", acr + "/listCredentials", {"api-version": AV_ACR})
    _check("listCredentials returns username + two passwords", r["status"] == 200 and r["body"]["username"] == "uicacr"
           and {p["name"] for p in r["body"]["passwords"]} == {"password", "password2"})
    pw1 = next(p["value"] for p in r["body"]["passwords"] if p["name"] == "password")
    r = arm.handle("POST", acr + "/regenerateCredential", {"api-version": AV_ACR}, {"name": "password"})
    pw1b = next(p["value"] for p in r["body"]["passwords"] if p["name"] == "password")
    pw2 = next(p["value"] for p in r["body"]["passwords"] if p["name"] == "password2")
    _check("regenerateCredential rotates only the named password", r["status"] == 200 and pw1b != pw1)
    r2 = arm.handle("POST", acr + "/listCredentials", {"api-version": AV_ACR})
    _check("the other password is untouched", next(p["value"] for p in r2["body"]["passwords"] if p["name"] == "password2") == pw2)
    _check("credentials never leak through GET", "password" not in json.dumps(arm.handle("GET", acr, {"api-version": AV_ACR})["body"]))

    # Nested child resource (registries/{name}/webhooks/{name}) needs no catalog entry of its
    # own — generic alternation — but its collection list MUST be scoped to this parent only.
    acr2 = _p(RG, "Microsoft.ContainerRegistry", "registries", "uicacr2")
    arm.handle("PUT", acr2, {"api-version": AV_ACR}, {"location": "eastus"})
    arm.handle("PUT", acr + "/webhooks/wh1", {"api-version": AV_ACR}, {"location": "eastus", "properties": {"scope": "*", "serviceUri": "https://example.com"}})
    arm.handle("PUT", acr2 + "/webhooks/wh2", {"api-version": AV_ACR}, {"location": "eastus", "properties": {"scope": "*"}})
    r = arm.handle("GET", acr + "/webhooks", {"api-version": AV_ACR})
    _check("nested child list is scoped to its own parent registry",
           [w["name"] for w in r["body"]["value"]] == ["wh1"])
    r = arm.handle("GET", acr2 + "/webhooks", {"api-version": AV_ACR})
    _check("sibling registry's webhooks don't leak in", [w["name"] for w in r["body"]["value"]] == ["wh2"])
    r = arm.handle("DELETE", acr, {"api-version": AV_ACR})
    _check("registry delete 200", r["status"] == 200)
    # 21. Network security groups + security rules — a nested, same-namespace child
    # resource (Microsoft.Network/networkSecurityGroups/{nsg}/securityRules/{rule}), the
    # real ARM shape every azure-mgmt-network client/CLI uses (NOT an extension resource
    # like locks — it stays inside the SAME provider namespace, alternating type/name).
    nsg1 = _p(RG, "Microsoft.Network", "networkSecurityGroups", "nsg1")
    nsg2 = _p(RG, "Microsoft.Network", "networkSecurityGroups", "nsg2")
    arm.handle("PUT", nsg1, {"api-version": "2023-11-01"}, {"location": "eastus"})
    arm.handle("PUT", nsg2, {"api-version": "2023-11-01"}, {"location": "eastus"})
    rule = nsg1 + "/securityRules/allow-ssh"
    r = arm.handle("PUT", rule, {"api-version": "2023-11-01"},
                   {"properties": {"priority": 100, "direction": "Inbound", "access": "Allow",
                                    "protocol": "Tcp", "sourceAddressPrefix": "*", "sourcePortRange": "*",
                                    "destinationAddressPrefix": "*", "destinationPortRange": "22"}})
    _check("security rule put 201", r["status"] == 201 and r["body"]["name"] == "allow-ssh")
    _check("security rule id canonical", r["body"]["id"].lower() == rule.lower())
    _check("security rule properties", r["body"]["properties"]["destinationPortRange"] == "22")
    r = arm.handle("GET", rule, {"api-version": "2023-11-01"})
    _check("security rule get 200", r["status"] == 200 and r["body"]["properties"]["priority"] == 100)
    arm.handle("PUT", nsg1 + "/securityRules/deny-all", {"api-version": "2023-11-01"},
               {"properties": {"priority": 4096, "direction": "Inbound", "access": "Deny", "protocol": "*",
                                "sourceAddressPrefix": "*", "sourcePortRange": "*",
                                "destinationAddressPrefix": "*", "destinationPortRange": "*"}})
    arm.handle("PUT", nsg2 + "/securityRules/other-nsg-rule", {"api-version": "2023-11-01"},
               {"properties": {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "*",
                                "sourceAddressPrefix": "*", "sourcePortRange": "*",
                                "destinationAddressPrefix": "*", "destinationPortRange": "*"}})
    r = arm.handle("GET", nsg1 + "/securityRules", {"api-version": "2023-11-01"})
    names1 = sorted(x["name"] for x in r["body"]["value"])
    _check("security rules list scoped to its own NSG (not leaked from another NSG)",
           r["status"] == 200 and names1 == ["allow-ssh", "deny-all"])
    r = arm.handle("GET", nsg2 + "/securityRules", {"api-version": "2023-11-01"})
    _check("security rules list isolated per NSG", [x["name"] for x in r["body"]["value"]] == ["other-nsg-rule"])
    r = arm.handle("DELETE", nsg1 + "/securityRules/deny-all", {"api-version": "2023-11-01"})
    _check("security rule delete 200", r["status"] == 200)
    r = arm.handle("GET", nsg1 + "/securityRules", {"api-version": "2023-11-01"})
    _check("deleted rule gone from the list", [x["name"] for x in r["body"]["value"]] == ["allow-ssh"])
    # deleting the NSG cascades to its (same-namespace, nested) security rules
    arm.handle("DELETE", nsg1, {"api-version": "2023-11-01"})
    r = arm.handle("GET", nsg1 + "/securityRules", {"api-version": "2023-11-01"})
    _check("security rules cascade-deleted with their NSG", r["body"]["value"] == [])
    r = arm.handle("GET", nsg2 + "/securityRules", {"api-version": "2023-11-01"})
    _check("sibling NSG's rules survive an unrelated NSG delete", [x["name"] for x in r["body"]["value"]] == ["other-nsg-rule"])

    # 22. NSG associations — a network interface and a (nested) subnet pointing at an NSG via
    # properties.networkSecurityGroup.id, the real ARM shape the console's "Network interfaces"
    # / "Subnets" association tabs read back (Microsoft.Network/networkInterfaces is a plain
    # catalog type; a vnet's subnets are nested same-namespace children, same mechanic as #21).
    nsg3 = _p(RG, "Microsoft.Network", "networkSecurityGroups", "nsg3")
    arm.handle("PUT", nsg3, {"api-version": "2023-11-01"}, {"location": "eastus"})
    nic = _p(RG, "Microsoft.Network", "networkInterfaces", "nic1")
    r = arm.handle("PUT", nic, {"api-version": "2023-11-01"},
                   {"location": "eastus", "properties": {"networkSecurityGroup": {"id": nsg3}}})
    _check("network interface put 200 (LRO, top-level type)", r["status"] == 200 and r["body"]["name"] == "nic1")
    _check("network interface has a private IP from its catalog defaults", r["body"]["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"])
    nic_collection = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network/networkInterfaces"
    r = arm.handle("GET", nic_collection, {"api-version": "2023-11-01"})
    _check("network interfaces list", r["status"] == 200 and [x["name"] for x in r["body"]["value"]] == ["nic1"])
    nic_rec = r["body"]["value"][0]
    _check("network interface carries its NSG association", nic_rec["properties"]["networkSecurityGroup"]["id"].lower() == nsg3.lower())

    vnet = _p(RG, "Microsoft.Network", "virtualNetworks", "vnet1")
    arm.handle("PUT", vnet, {"api-version": "2023-11-01"}, {"location": "eastus"})
    subnet = vnet + "/subnets/default"
    r = arm.handle("PUT", subnet, {"api-version": "2023-11-01"},
                   {"properties": {"addressPrefix": "10.0.1.0/24", "networkSecurityGroup": {"id": nsg3}}})
    _check("subnet put 201", r["status"] == 201 and r["body"]["name"] == "default")
    r = arm.handle("GET", vnet + "/subnets", {"api-version": "2023-11-01"})
    _check("subnets list scoped to its own vnet", r["status"] == 200 and [x["name"] for x in r["body"]["value"]] == ["default"])
    subnet_rec = r["body"]["value"][0]
    _check("subnet carries its NSG association and address prefix",
           subnet_rec["properties"]["networkSecurityGroup"]["id"].lower() == nsg3.lower() and subnet_rec["properties"]["addressPrefix"] == "10.0.1.0/24")

    print("\nRESULT: PASS — Azure ARM core conforms (native ARM wire + LRO + catalog CRUD) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
