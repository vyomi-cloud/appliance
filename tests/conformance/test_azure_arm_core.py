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


def _rgpath(rg):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}"


def run() -> int:
    arm = AzureArm()

    # 1. Subscription probe
    r = arm.handle("GET", f"/subscriptions/{SUB}")
    _check("subscription 200", r["status"] == 200 and r["body"]["subscriptionId"] == SUB)
    _check("subscription carries subscriptionPolicies.quotaId (Overview's Offer/Offer ID)",
           r["body"]["subscriptionPolicies"]["quotaId"] == "PayAsYouGo_2014-09-01")

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

    # 17a0. APIM APIs: WebSocket / GraphQL / gRPC round-trip properties.apiType exactly like
    # real APIM (azure.apim.apis.createflows) — no backend-specific code, the same generic
    # nested-resource mechanism as every other apis/{id} PUT.
    for apitype, suffix in (("websocket", "ws"), ("graphql", "gql"), ("grpc", "grpcsvc")):
        a_id = apim + f"/apis/{suffix}-api"
        r = arm.handle("PUT", a_id, {"api-version": "2023-05-01-preview"},
                       {"properties": {"displayName": f"{suffix} api", "apiType": apitype,
                                        "serviceUrl": "wss://backend.example.com", "path": suffix,
                                        "protocols": ["wss"] if apitype == "websocket" else ["https"]}})
        _check(f"apim {apitype} API put 201", r["status"] == 201 and r["body"]["properties"]["apiType"] == apitype)
        r = arm.handle("GET", a_id, {"api-version": "2023-05-01-preview"})
        _check(f"apim {apitype} API GET reflects apiType", r["body"]["properties"]["apiType"] == apitype)

    # 17a. APIM API Tags (Microsoft.ApiManagement/service/tags) — generic nested ARM
    # sub-resource, the SAME mechanism as named values/backends (AzureArm._upsert): no
    # service-specific backend code, just the type/name alternation one level deeper.
    tag = apim + "/tags/env-prod"
    r = arm.handle("PUT", tag, {"api-version": "2023-05-01-preview"}, {"properties": {"displayName": "env-prod"}})
    _check("apim tag put 201", r["status"] == 201 and r["body"]["name"] == "env-prod")
    r = arm.handle("GET", apim + "/tags", {"api-version": "2023-05-01-preview"})
    _check("apim tags list has it", [t["name"] for t in r["body"]["value"]] == ["env-prod"])
    r = arm.handle("DELETE", tag, {"api-version": "2023-05-01-preview"})
    _check("apim tag delete 200", r["status"] == 200)

    # 17b. APIM Policy fragments (Microsoft.ApiManagement/service/policyFragments) — same
    # generic nested mechanism; the XML round-trips exactly as configured (never executed).
    frag = apim + "/policyFragments/rate-limit"
    r = arm.handle("PUT", frag, {"api-version": "2023-05-01-preview"},
                   {"properties": {"format": "xml",
                                    "value": "<fragment><rate-limit calls=\"10\" renewal-period=\"60\" /></fragment>",
                                    "description": "Shared rate limit"}})
    _check("apim policy fragment put 201", r["status"] == 201 and r["body"]["properties"]["description"] == "Shared rate limit")
    r = arm.handle("GET", apim + "/policyFragments", {"api-version": "2023-05-01-preview"})
    _check("apim policy fragments list has it", [f["name"] for f in r["body"]["value"]] == ["rate-limit"])
    r = arm.handle("DELETE", frag, {"api-version": "2023-05-01-preview"})
    _check("apim policy fragment delete 200", r["status"] == 200)

    # 17b2. Named values (Microsoft.ApiManagement/service/namedValues) + listValue — the real
    # action behind the grid's "Show value" icon. A plain value round-trips as stored; a Key
    # Vault reference resolves against THIS space's own Key Vault secrets store, wired the same
    # way aws_wire_router.AwsWireRouter.__init__ wires the real router (azure.apim.namedvalues.keyvaultref).
    from core.kv_store import InMemoryKvStore
    arm.kv_secrets_store = InMemoryKvStore()
    arm.kv_secrets_store.put_secret("db-password", {
        "name": "db-password", "deleted": False, "deletedDate": None,
        "current": "v1", "versions": {"v1": {"value": "s3cr3t", "attributes": {}}},
    })
    nv_plain = apim + "/namedValues/plain-value"
    r = arm.handle("PUT", nv_plain, {"api-version": "2023-05-01-preview"},
                   {"properties": {"displayName": "plain-value", "value": "hello"}})
    _check("apim named value put 201", r["status"] == 201)
    r = arm.handle("POST", nv_plain + "/listValue", {"api-version": "2023-05-01-preview"}, {})
    _check("apim named value listValue returns the plain value", r["status"] == 200 and r["body"]["value"] == "hello")

    nv_kv = apim + "/namedValues/kv-value"
    r = arm.handle("PUT", nv_kv, {"api-version": "2023-05-01-preview"},
                   {"properties": {"displayName": "kv-value", "secret": True,
                                    "keyVault": {"secretIdentifier": "https://uic-vault.vault.azure.net/secrets/db-password"}}})
    _check("apim named value (Key Vault) put 201", r["status"] == 201)
    r = arm.handle("POST", nv_kv + "/listValue", {"api-version": "2023-05-01-preview"}, {})
    _check("apim named value listValue resolves a real Key Vault secret",
           r["status"] == 200 and r["body"]["value"] == "s3cr3t")

    nv_missing = apim + "/namedValues/missing-kv-value"
    arm.handle("PUT", nv_missing, {"api-version": "2023-05-01-preview"},
               {"properties": {"displayName": "missing-kv-value", "secret": True,
                                "keyVault": {"secretIdentifier": "https://uic-vault.vault.azure.net/secrets/does-not-exist"}}})
    r = arm.handle("POST", nv_missing + "/listValue", {"api-version": "2023-05-01-preview"}, {})
    _check("apim named value listValue 400s on an unresolved Key Vault reference", r["status"] == 400)

    # 17c. Scale out and up / Pricing tier (post-creation): sku.capacity and sku.name PATCH
    # generically (any catalog resource type), reflected back on GET — real for APIM's
    # Overview "Tier" field and every other blade that reads a.sku. The service was created
    # Developer (catalog default) — move off it first, since Developer's unit count is fixed.
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Standard"}})
    _check("apim tier patch off Developer", r["status"] == 200 and r["body"]["sku"]["name"] == "Standard")
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"capacity": 3}})
    _check("apim scale-out patch", r["status"] == 200 and r["body"]["sku"]["capacity"] == 3)
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Premium"}})
    _check("apim pricing tier patch keeps capacity",
           r["body"]["sku"]["name"] == "Premium" and r["body"]["sku"]["capacity"] == 3)

    # 17c2. Consumption has no scale units and Developer is capped at exactly 1 — ENFORCED
    # (azure.apim.scaletier), not just round-tripped.
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Consumption", "capacity": 3}})
    _check("apim Consumption tier rejects a nonzero capacity", r["status"] == 400)
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Consumption", "capacity": 0}})
    _check("apim Consumption tier accepts capacity 0", r["status"] == 200)
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Developer", "capacity": 2}})
    _check("apim Developer tier rejects more than 1 unit", r["status"] == 400)
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Developer", "capacity": 1}})
    _check("apim Developer tier accepts exactly 1 unit", r["status"] == 200)
    # Tier-only PATCH is validated against the EXISTING (now stale) capacity too.
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Consumption"}})
    _check("apim tier-only switch to Consumption rejected while capacity is still 1 (stale)", r["status"] == 400)
    r = arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"capacity": 2}})
    _check("apim Developer tier still rejects a capacity-only PATCH to 2", r["status"] == 400)
    arm.handle("PATCH", apim, {"api-version": "2023-05-01-preview"}, {"sku": {"name": "Standard", "capacity": 2}})

    # 17d. Activity log Timespan picker: eventTimestamp ge/le $filter predicates actually
    # narrow the feed (core/azure_arm_core._filter_by_timespan + azure_monitor_core's own copy).
    feed = f"/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values"
    r = arm.handle("GET", feed, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{apim}'"})
    all_ts = [e["eventTimestamp"] for e in r["body"]["value"]]
    _check("apim activity log has entries before timespan filter", len(all_ts) >= 3)
    future = "2999-01-01T00:00:00.000000Z"
    r = arm.handle("GET", feed, {"api-version": "2015-04-01",
                                  "$filter": f"resourceUri eq '{apim}' and eventTimestamp ge '{future}'"})
    _check("timespan ge in the future excludes everything", r["body"]["value"] == [])
    past = "1999-01-01T00:00:00.000000Z"
    r = arm.handle("GET", feed, {"api-version": "2015-04-01",
                                  "$filter": f"resourceUri eq '{apim}' and eventTimestamp ge '{past}'"})
    _check("timespan ge in the past keeps everything", [e["eventTimestamp"] for e in r["body"]["value"]] == all_ts)

    # 17e. Microsoft.Authorization/roleAssignments + roleDefinitions — generic top-level
    # catalog types (subscription-wide), backing every Azure lens service's "Access control
    # (IAM)" Role assignments/Roles tabs (core/azure_arm_data.py CATALOG keys 'rbac'/'role_definition').
    ra = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments/11111111-1111-1111-1111-111111111111"
    r = arm.handle("PUT", ra, {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "user-1", "roleDefinitionId": "owner", "principalType": "User"}})
    _check("role assignment put 201", r["status"] == 201 and r["body"]["properties"]["principalId"] == "user-1")
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("role assignments list has it", any(a["name"] == "11111111-1111-1111-1111-111111111111" for a in r["body"]["value"]))
    rd = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/owner"
    arm.handle("PUT", rd, {"api-version": "2022-04-01"}, {"properties": {"roleName": "Owner", "type": "BuiltInRole"}})
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions", {"api-version": "2022-04-01"})
    _check("role definitions list has it", any(d["name"] == "owner" for d in r["body"]["value"]))

    # 17f. checkAccess at the SUBSCRIPTION's own scope (rg=None) — the subscription blade's
    # Access control (IAM) > Check access / My access, same decision algorithm as the
    # resource-group-scoped case at #29 below (azure.subscriptions.access_control_iam).
    subpath = f"/subscriptions/{SUB}"
    subra = f"{subpath}/providers/Microsoft.Authorization/roleAssignments/sub-ra-1"
    r = arm.handle("PUT", subra, {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "carol", "roleName": "Reader"}})
    _check("subscription-scoped role assignment put 201 scoped to the subscription itself",
           r["status"] == 201 and r["body"]["properties"]["scope"] == subpath)

    def _sub_decision(principal, action):
        resp = arm.handle("POST", f"{subpath}/providers/Microsoft.Authorization/checkAccess",
                          {"api-version": "2022-04-01"}, {"principalId": principal, "action": action})
        return resp["body"]["value"][0]["accessDecision"]

    _check("checkAccess at subscription scope: Reader can read",
           _sub_decision("carol", "Microsoft.Storage/storageAccounts/read") == "Allowed")
    _check("checkAccess at subscription scope: Reader cannot write",
           _sub_decision("carol", "Microsoft.Storage/storageAccounts/write") == "NotAllowed")
    r = arm.handle("DELETE", subra, {"api-version": "2022-04-01"})
    _check("subscription-scoped role assignment delete 200", r["status"] == 200)
    _check("checkAccess at subscription scope reflects the deleted assignment immediately",
           _sub_decision("carol", "Microsoft.Storage/storageAccounts/read") == "NotAllowed")

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
           ev["status"] == 200 and ops[0] == "Create lock" and "Microsoft.KeyVault/vaults/write" in ops)
    ev2 = arm.handle("GET", events_path, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{kv2}'"})
    ops2 = [e["operationName"]["value"] for e in ev2["body"]["value"]]
    _check("activity log is scoped per vault (no cross-resource leakage)", "Create lock" not in ops2)

    # the timespan picker (eventTimestamp ge) is ENFORCED: a future lower bound excludes
    # every event the two writes above just produced, a past one keeps them all.
    ev_future = arm.handle("GET", events_path, {"api-version": "2015-04-01",
                           "$filter": f"resourceUri eq '{kv}' and eventTimestamp ge '2999-01-01T00:00:00Z'"})
    _check("timespan filter excludes events before the lower bound", ev_future["body"]["value"] == [])
    ev_past = arm.handle("GET", events_path, {"api-version": "2015-04-01",
                         "$filter": f"resourceUri eq '{kv}' and eventTimestamp ge '2000-01-01T00:00:00Z'"})
    _check("timespan filter keeps events after the lower bound", len(ev_past["body"]["value"]) == len(ev["body"]["value"]))

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

    # 26. Microsoft.Resources/deployments: a bounded but REAL template evaluator — every
    # resource in properties.template.resources is actually PUT through this ARM dispatcher
    # (literal [parameters('x')]/[variables('y')] substitution only), not just stored inert.
    # Enough to back a real "Deployments" history list + "View template" honestly. PUT is an
    # LRO like any other top-level type.
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

    tpl_dep = _p(RG, "Microsoft.Resources", "deployments", "uic-tpl-deployment")
    template = {"parameters": {"saName": {"defaultValue": "uictplsa"}}, "variables": {"loc": "eastus"},
               "resources": [{"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-01-01",
                              "name": "[parameters('saName')]", "location": "[variables('loc')]"}]}
    r = arm.handle("PUT", tpl_dep, {"api-version": "2021-04-01"}, {"properties": {"mode": "Incremental", "template": template}})
    _check("deployment with a template put 200", r["status"] == 200)
    _check("deployment template evaluation actually provisions the listed resource",
           r["body"]["properties"]["provisioningState"] == "Succeeded"
           and r["body"]["properties"]["outputResources"][0]["resourceName"] == "uictplsa")
    sa_from_tpl = _p(RG, "Microsoft.Storage", "storageAccounts", "uictplsa")
    r = arm.handle("GET", sa_from_tpl, {"api-version": "2023-01-01"})
    _check("the deployment's template resource is a real resource, GET-able on its own",
           r["status"] == 200 and r["body"]["location"] == "eastus")

    bad_tpl_dep = _p(RG, "Microsoft.Resources", "deployments", "uic-bad-tpl-deployment")
    bad_template = {"resources": [{"type": "Microsoft.NotReal/widgets", "apiVersion": "2021-01-01", "name": "w1"}]}
    r = arm.handle("PUT", bad_tpl_dep, {"api-version": "2021-04-01"}, {"properties": {"mode": "Incremental", "template": bad_template}})
    _check("a template resource of an unsimulated type honestly fails the deployment",
           r["body"]["properties"]["provisioningState"] == "Failed" and r["body"]["properties"]["error"]["details"])

    cancel_url = tpl_dep + "/cancel"
    r = arm.handle("POST", cancel_url, {"api-version": "2021-04-01"}, {})
    _check("Cancel on an already-completed deployment is an honest 409 (every deployment here completes synchronously)",
           r["status"] == 409 and r["body"]["error"]["code"] == "DeploymentNotCancellable")
    redeploy_url = tpl_dep + "/redeploy"
    r = arm.handle("POST", redeploy_url, {"api-version": "2021-04-01"}, {})
    _check("Redeploy re-runs the stored template for real", r["status"] == 200 and r["body"]["properties"]["provisioningState"] == "Succeeded")
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

    # azure.acr.iam: Microsoft.Authorization/roleAssignments read scoped to the registry
    # itself (the console's Access control (IAM) > Role assignments tab) — same generic
    # extension-resource engine the NSG/Cosmos/VM blades use.
    ra_acr = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments/ra-acr-scoped"
    r = arm.handle("PUT", ra_acr, {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "acr-owner", "roleName": "Owner", "scope": acr}})
    _check("role assignment scoped to the registry itself created", r["status"] == 201)
    r = arm.handle("GET", acr + "/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("registry-scoped IAM list includes the registry-scoped assignment", any(x["name"] == "ra-acr-scoped" for x in r["body"]["value"]))
    r = arm.handle("GET", acr2 + "/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("a sibling registry's IAM list excludes the other registry's assignment", all(x["name"] != "ra-acr-scoped" for x in r["body"]["value"]))

    # azure.acr.monitoring: Microsoft.Insights/diagnosticSettings, a real ARM extension
    # resource scoped to this registry (the console's Diagnostic settings panel) — same
    # generic engine the Key Vault/NSG lenses use.
    diag_acr = acr + "/providers/Microsoft.Insights/diagnosticSettings/toLogAnalytics"
    r = arm.handle("PUT", diag_acr, {"api-version": "2021-05-01-preview"},
                   {"properties": {"workspaceId": "/subscriptions/x/resourcegroups/y/providers/microsoft.operationalinsights/workspaces/uicws",
                                    "logs": [{"categoryGroup": "allLogs", "enabled": True}]}})
    _check("registry diagnostic setting put 201", r["status"] == 201 and r["body"]["name"] == "toLogAnalytics")
    r = arm.handle("GET", acr + "/providers/Microsoft.Insights/diagnosticSettings", {"api-version": "2021-05-01-preview"})
    _check("registry diagnostic settings list has item", [x["name"] for x in r["body"]["value"]] == ["toLogAnalytics"])
    r = arm.handle("GET", acr2 + "/providers/Microsoft.Insights/diagnosticSettings", {"api-version": "2021-05-01-preview"})
    _check("a sibling registry's diagnostic settings stay empty", r["body"]["value"] == [])

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

    # 22b. A vnet created with its subnet defined INLINE (properties.subnets) — the much more
    # common real-Azure pattern (`az network vnet create --subnet-prefix`, ARM templates) than
    # the dedicated subnets/{name} PUT above — must land in the SAME shared subnet collection:
    # individually gettable and listable, same as a dedicated-PUT subnet (azure.nsgs.effective_rules
    # and the "Subnets" association tab both read this collection, not the vnet's own body).
    vnet3 = _p(RG, "Microsoft.Network", "virtualNetworks", "vnet3")
    r = arm.handle("PUT", vnet3, {"api-version": "2023-11-01"}, {"location": "eastus", "properties": {
        "subnets": [{"name": "inline", "properties": {"addressPrefix": "10.0.2.0/24", "networkSecurityGroup": {"id": nsg3}}}]}})
    _check("vnet put with an inline subnet", r["status"] in (200, 201))
    inline_subnet = vnet3 + "/subnets/inline"
    r = arm.handle("GET", inline_subnet, {"api-version": "2023-11-01"})
    _check("inline subnet individually gettable via the dedicated subresource path",
           r["status"] == 200 and r["body"]["properties"]["addressPrefix"] == "10.0.2.0/24")
    r = arm.handle("GET", vnet3 + "/subnets", {"api-version": "2023-11-01"})
    _check("inline subnet appears in the subnets collection list",
           r["status"] == 200 and [x["name"] for x in r["body"]["value"]] == ["inline"]
           and r["body"]["value"][0]["properties"]["networkSecurityGroup"]["id"].lower() == nsg3.lower())

    # 22c. azure.nsgs.iam: Microsoft.Authorization/roleAssignments + checkAccess, both
    # resource-scoped to the NSG itself (not just the resource-group/subscription scope
    # section 29 below already covers) — the console's NSG "Access control (IAM) >
    # Role assignments / Check access" tabs.
    ra_nsg = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments/ra-nsg3"
    r = arm.handle("PUT", ra_nsg, {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "nsg-owner", "roleName": "Owner", "scope": nsg3}})
    _check("role assignment scoped to the NSG itself created", r["status"] == 201)
    r = arm.handle("GET", nsg3 + "/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("NSG-scoped IAM list includes the NSG-scoped assignment", any(x["name"] == "ra-nsg3" for x in r["body"]["value"]))
    r = arm.handle("GET", nsg2 + "/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("a sibling NSG's IAM list excludes the other NSG's assignment", all(x["name"] != "ra-nsg3" for x in r["body"]["value"]))
    r = arm.handle("POST", nsg3 + "/providers/Microsoft.Authorization/checkAccess", {"api-version": "2022-04-01"},
                   {"principalId": "nsg-owner", "action": "Microsoft.Network/networkSecurityGroups/write"})
    _check("checkAccess resource-scoped to the NSG: Owner can write",
           r["body"]["value"][0]["accessDecision"] == "Allowed")
    r = arm.handle("POST", nsg2 + "/providers/Microsoft.Authorization/checkAccess", {"api-version": "2022-04-01"},
                   {"principalId": "nsg-owner", "action": "Microsoft.Network/networkSecurityGroups/write"})
    _check("checkAccess resource-scoped: no access on a sibling NSG the assignment doesn't cover",
           r["body"]["value"][0]["accessDecision"] == "NotAllowed")

    # 23. Microsoft.DocumentDB/databaseAccounts listKeys / listReadOnlyKeys /
    # listConnectionStrings / regenerateKey — the real Cosmos shape (not the generic
    # storage-style {"keys": [...]}), and a round-trip for the account itself.
    cosmos = _p(RG, "Microsoft.DocumentDB", "databaseAccounts", "uiccosmos")
    r = arm.handle("PUT", cosmos, {"api-version": "2024-05-15"}, {"location": "eastus"})
    _check("cosmos account put 200 (LRO)", r["status"] == 200 and r["body"]["name"] == "uiccosmos")
    _check("cosmos account kind default", r["body"]["kind"] == "GlobalDocumentDB")
    r = arm.handle("POST", cosmos + "/listKeys", {"api-version": "2024-05-15"})
    _check("cosmos listKeys shape", r["status"] == 200
           and all(k in r["body"] for k in ("primaryMasterKey", "secondaryMasterKey", "primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")))
    pk1 = r["body"]["primaryMasterKey"]
    r2 = arm.handle("POST", cosmos + "/listKeys", {"api-version": "2024-05-15"})
    _check("cosmos listKeys is stable across calls", r2["body"]["primaryMasterKey"] == pk1)
    r = arm.handle("POST", cosmos + "/listReadOnlyKeys", {"api-version": "2024-05-15"})
    _check("cosmos listReadOnlyKeys shape", r["status"] == 200 and set(r["body"]) == {"primaryReadonlyMasterKey", "secondaryReadonlyMasterKey"})
    r = arm.handle("POST", cosmos + "/listConnectionStrings", {"api-version": "2024-05-15"})
    _check("cosmos listConnectionStrings has 4 entries", r["status"] == 200 and len(r["body"]["connectionStrings"]) == 4)
    _check("cosmos connection string embeds the primary key", pk1 in r["body"]["connectionStrings"][0]["connectionString"])
    r = arm.handle("POST", cosmos + "/regenerateKey", {"api-version": "2024-05-15"}, {"keyKind": "primary"})
    _check("cosmos regenerateKey succeeds", r["status"] == 200 and r["body"]["status"] == "Succeeded")
    r = arm.handle("POST", cosmos + "/listKeys", {"api-version": "2024-05-15"})
    _check("cosmos regenerateKey rotated only the primary key", r["body"]["primaryMasterKey"] != pk1
           and r["body"]["secondaryMasterKey"] == r2["body"]["secondaryMasterKey"])
    # 22b. A network interface's ipConfigurations[].subnet.id — the same mechanic the console's
    # vnet "Connected devices" list filters on (any NIC whose ipConfigurations[] points at one
    # of this vnet's subnets shows up there, a subscription-wide scan same as the NSG association
    # tabs above).
    nic2 = _p(RG, "Microsoft.Network", "networkInterfaces", "nic2")
    r = arm.handle("PUT", nic2, {"api-version": "2023-11-01"},
                   {"location": "eastus", "properties": {"ipConfigurations": [{"name": "ipconfig1", "properties": {"subnet": {"id": subnet}}}]}})
    _check("network interface put with subnet association 200", r["status"] == 200)
    r = arm.handle("GET", nic_collection, {"api-version": "2023-11-01"})
    nic2_rec = next(x for x in r["body"]["value"] if x["name"] == "nic2")
    _check("network interface carries its subnet association (Connected devices wiring)",
           nic2_rec["properties"]["ipConfigurations"][0]["properties"]["subnet"]["id"].lower() == subnet.lower())

    # 23. Virtual network peerings — another nested, same-namespace child resource
    # (Microsoft.Network/virtualNetworks/{vnet}/virtualNetworkPeerings/{peering}), the real
    # ARM shape `az network vnet peering create` uses. The portal's "Add" blade provisions a
    # peering object on BOTH vnets it connects, so this proves isolation + a full round trip.
    vnet2 = _p(RG, "Microsoft.Network", "virtualNetworks", "vnet2")
    arm.handle("PUT", vnet2, {"api-version": "2023-11-01"}, {"location": "eastus"})
    peer_out = vnet + "/virtualNetworkPeerings/vnet1-to-vnet2"
    r = arm.handle("PUT", peer_out, {"api-version": "2023-11-01"},
                   {"properties": {"remoteVirtualNetwork": {"id": vnet2}, "peeringState": "Connected",
                                    "peeringSyncLevel": "FullyInSync", "allowForwardedTraffic": False,
                                    "allowGatewayTransit": False, "useRemoteGateways": False}})
    _check("peering put 201", r["status"] == 201 and r["body"]["name"] == "vnet1-to-vnet2")
    _check("peering id canonical", r["body"]["id"].lower() == peer_out.lower())
    _check("peering properties", r["body"]["properties"]["remoteVirtualNetwork"]["id"].lower() == vnet2.lower()
           and r["body"]["properties"]["peeringState"] == "Connected")
    peer_in = vnet2 + "/virtualNetworkPeerings/vnet2-to-vnet1"
    arm.handle("PUT", peer_in, {"api-version": "2023-11-01"},
               {"properties": {"remoteVirtualNetwork": {"id": vnet}, "peeringState": "Connected",
                                "peeringSyncLevel": "FullyInSync", "allowForwardedTraffic": False,
                                "allowGatewayTransit": False, "useRemoteGateways": False}})
    r = arm.handle("GET", vnet + "/virtualNetworkPeerings", {"api-version": "2023-11-01"})
    _check("peerings list scoped to its own vnet", r["status"] == 200 and [x["name"] for x in r["body"]["value"]] == ["vnet1-to-vnet2"])
    r = arm.handle("GET", vnet2 + "/virtualNetworkPeerings", {"api-version": "2023-11-01"})
    _check("peerings isolated per vnet", [x["name"] for x in r["body"]["value"]] == ["vnet2-to-vnet1"])
    r = arm.handle("DELETE", peer_out, {"api-version": "2023-11-01"})
    _check("peering delete 200", r["status"] == 200)
    r = arm.handle("GET", vnet + "/virtualNetworkPeerings", {"api-version": "2023-11-01"})
    _check("deleted peering gone from the list", r["body"]["value"] == [])
    r = arm.handle("GET", vnet2 + "/virtualNetworkPeerings", {"api-version": "2023-11-01"})
    _check("the other vnet's peering survives an unrelated delete", [x["name"] for x in r["body"]["value"]] == ["vnet2-to-vnet1"])
    # deleting a vnet cascades to its (same-namespace, nested) subnets and peerings
    arm.handle("DELETE", vnet2, {"api-version": "2023-11-01"})
    r = arm.handle("GET", vnet2 + "/virtualNetworkPeerings", {"api-version": "2023-11-01"})
    _check("peerings cascade-deleted with their vnet", r["body"]["value"] == [])
    # 23. Subscription-scope: rename, tags-at-scope, resource-provider unregister, locks
    # scoped directly to the subscription itself, and the subscription-wide resources list —
    # the Subscriptions service's Overview / Tags / Resource providers / Resource locks / Resources panels.
    r = arm.handle("POST", f"/subscriptions/{SUB}/providers/Microsoft.Subscription/rename", {"api-version": "2021-10-01"}, {"subscriptionName": "CloudLearn Prod"})
    _check("subscription rename 200", r["status"] == 200 and r["body"]["displayName"] == "CloudLearn Prod")
    r = arm.handle("GET", f"/subscriptions/{SUB}")
    _check("renamed subscription persists on GET", r["body"]["displayName"] == "CloudLearn Prod")
    r = arm.handle("POST", f"/subscriptions/{SUB}/providers/Microsoft.Subscription/rename", {"api-version": "2021-10-01"}, {})
    _check("rename without a name 400s", r["status"] == 400)

    tagspath = f"/subscriptions/{SUB}/providers/Microsoft.Resources/tags/default"
    r = arm.handle("GET", tagspath, {"api-version": "2021-04-01"})
    _check("subscription tags starts empty", r["status"] == 200 and r["body"]["properties"]["tags"] == {})
    r = arm.handle("PATCH", tagspath, {"api-version": "2021-04-01"}, {"properties": {"tags": {"env": "prod"}}})
    _check("subscription tags PATCH 200", r["status"] == 200 and r["body"]["properties"]["tags"] == {"env": "prod"})
    r = arm.handle("PATCH", tagspath, {"api-version": "2021-04-01"}, {"properties": {"tags": {"team": "platform"}}})
    _check("subscription tags PATCH merges", r["body"]["properties"]["tags"] == {"env": "prod", "team": "platform"})
    r = arm.handle("PUT", tagspath, {"api-version": "2021-04-01"}, {"properties": {"tags": {"only": "this"}}})
    _check("subscription tags PUT replaces", r["body"]["properties"]["tags"] == {"only": "this"})
    r = arm.handle("GET", f"/subscriptions/{SUB}")
    _check("subscription GET reflects its tags", r["body"]["tags"] == {"only": "this"})

    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Storage")
    _check("provider registered by default", r["body"]["registrationState"] == "Registered")
    r = arm.handle("POST", f"/subscriptions/{SUB}/providers/Microsoft.Storage/unregister")
    _check("provider unregister 200", r["status"] == 200 and r["body"]["registrationState"] == "NotRegistered")
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Storage")
    _check("unregistered provider state persists on GET", r["body"]["registrationState"] == "NotRegistered")
    r = arm.handle("POST", f"/subscriptions/{SUB}/providers/Microsoft.Storage/register")
    _check("provider re-register 200", r["body"]["registrationState"] == "Registered")

    sublock = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/locks/sublock"
    r = arm.handle("PUT", sublock, {"api-version": "2016-09-01"}, {"properties": {"level": "CanNotDelete"}})
    _check("subscription-scoped lock put 201", r["status"] == 201 and r["body"]["name"] == "sublock")
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/locks", {"api-version": "2016-09-01"})
    _check("subscription-scoped locks list has it", [x["name"] for x in r["body"]["value"]] == ["sublock"])
    r = arm.handle("DELETE", sublock, {"api-version": "2016-09-01"})
    _check("subscription-scoped lock delete 200", r["status"] == 200)

    deployment = f"/subscriptions/{SUB}/providers/Microsoft.Resources/deployments/subdeploy1"
    r = arm.handle("PUT", deployment, {"api-version": "2021-04-01"}, {"properties": {"mode": "Incremental", "template": {}}})
    _check("subscription-scoped deployment put 200 (LRO)", r["status"] == 200 and r["body"]["name"] == "subdeploy1")
    r = arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Resources/deployments", {"api-version": "2021-04-01"})
    _check("subscription-scoped deployments list has it", "subdeploy1" in [x["name"] for x in r["body"]["value"]])

    rg2 = "subscope-rg"
    storage2 = _p(rg2, "Microsoft.Storage", "storageAccounts", "subscopesa")
    arm.handle("PUT", storage2, {"api-version": "2023-01-01"}, {"location": "eastus"})
    r = arm.handle("GET", f"/subscriptions/{SUB}/resources", {"api-version": "2021-04-01"})
    _check("subscription-wide resources list spans every resource group",
           "subscopesa" in [x["name"] for x in r["body"]["value"]])
    _check("subscription-wide resources list excludes resource groups themselves",
           not any(x["type"].lower() == "microsoft.resources/resourcegroups" for x in r["body"]["value"]))

    # 27. Microsoft.Insights/diagnosticSettings — a resource-scoped extension resource (the
    # same re-entrant-"providers" shape as locks, generic over any resource type) that routes
    # a resource's logs/metrics to a destination; wired by AzureArm._diagnostic_settings.
    diagkv = _p(RG, "Microsoft.KeyVault", "vaults", "uicdiagkv")
    arm.handle("PUT", diagkv, {"api-version": "2023-07-01"}, {"location": "eastus"})
    diag = diagkv + "/providers/Microsoft.Insights/diagnosticSettings/toLogAnalytics"
    r = arm.handle("GET", diagkv + "/providers/Microsoft.Insights/diagnosticSettings", {"api-version": "2021-05-01-preview"})
    _check("diagnostic settings empty before create", r["status"] == 200 and r["body"]["value"] == [])
    r = arm.handle("PUT", diag, {"api-version": "2021-05-01-preview"}, {"properties": {
        "workspaceId": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/uicdiagws",
        "logs": [{"categoryGroup": "audit", "enabled": True}], "metrics": [{"category": "AllMetrics", "enabled": False}]}})
    _check("diagnostic setting put 201", r["status"] == 201 and r["body"]["name"] == "toLogAnalytics")
    _check("diagnostic setting id canonical", r["body"]["id"].lower() == diag.lower())
    r = arm.handle("PUT", diag, {"api-version": "2021-05-01-preview"}, {"properties": {
        "workspaceId": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/uicdiagws",
        "logs": [], "metrics": [{"category": "AllMetrics", "enabled": False}]}})
    _check("diagnostic setting needs at least one enabled category", r["status"] == 400)
    r = arm.handle("PUT", diagkv + "/providers/Microsoft.Insights/diagnosticSettings/nodest",
                   {"api-version": "2021-05-01-preview"}, {"properties": {"logs": [{"category": "AuditEvent", "enabled": True}]}})
    _check("diagnostic setting needs a destination", r["status"] == 400)
    r = arm.handle("GET", diagkv + "/providers/Microsoft.Insights/diagnosticSettings", {"api-version": "2021-05-01-preview"})
    _check("diagnostic settings list has item", [x["name"] for x in r["body"]["value"]] == ["toLogAnalytics"])
    diagkv2 = _p(RG, "Microsoft.KeyVault", "vaults", "uicotherdiagkv")
    arm.handle("PUT", diagkv2, {"api-version": "2023-07-01"}, {"location": "eastus"})
    r = arm.handle("GET", diagkv2 + "/providers/Microsoft.Insights/diagnosticSettings", {"api-version": "2021-05-01-preview"})
    _check("diagnostic settings scoped per resource", r["body"]["value"] == [])
    r = arm.handle("DELETE", diag, {"api-version": "2021-05-01-preview"})
    _check("diagnostic setting delete 200", r["status"] == 200)
    r = arm.handle("GET", diag, {"api-version": "2021-05-01-preview"})
    _check("diagnostic setting gone after delete", r["status"] == 404)
    # deleting the scoped resource cascades to its diagnostic settings
    arm.handle("PUT", diag, {"api-version": "2021-05-01-preview"}, {"properties": {
        "storageAccountId": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/uicdiagsa",
        "logs": [{"categoryGroup": "audit", "enabled": True}]}})
    arm.handle("DELETE", diagkv, {"api-version": "2023-07-01"})
    r = arm.handle("GET", diagkv + "/providers/Microsoft.Insights/diagnosticSettings", {"api-version": "2021-05-01-preview"})
    _check("diagnostic settings cascade-deleted with resource", r["body"]["value"] == [])

    # 28. Microsoft.Insights/dataCollectionEndpoints + privateLinkScopes — plain RG-scoped
    # catalog CRUD through the monitor engine (same _BY_TYPE-free path as actionGroups etc.).
    dce = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Insights/dataCollectionEndpoints/uicdce"
    r = arm.handle("PUT", dce, {"api-version": "2023-03-11"}, {"location": "eastus", "properties": {}})
    _check("DCE put 201 with generated ingestion endpoints", r["status"] == 201
           and r["body"]["properties"]["logsIngestion"]["endpoint"].startswith("https://uicdce-"))
    endpoint1 = r["body"]["properties"]["logsIngestion"]["endpoint"]
    r = arm.handle("PATCH", dce, {"api-version": "2023-03-11"}, {"properties": {"description": "prod"}})
    _check("DCE update keeps the same generated endpoints", r["body"]["properties"]["logsIngestion"]["endpoint"] == endpoint1
           and r["body"]["properties"]["description"] == "prod")

    pls = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Insights/privateLinkScopes/uicpls"
    r = arm.handle("PUT", pls, {"api-version": "2021-07-01-preview"}, {"location": "global", "properties": {}})
    _check("private link scope put 201, defaults to Open access", r["status"] == 201
           and r["body"]["properties"]["accessModeSettings"]["queryAccessMode"] == "Open")
    r = arm.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Insights/privateLinkScopes", {"api-version": "2021-07-01-preview"})
    _check("private link scopes list has it", "uicpls" in [x["name"] for x in r["body"]["value"]])

    # 29. Microsoft.Authorization/locks ENFORCEMENT — scoped to Microsoft.ServiceBus only
    # (every other resource type keeps locks config_only: stored, not enforced — see
    # core/capabilities/azure/*.json). A CanNotDelete lock blocks DELETE; a ReadOnly lock
    # blocks DELETE and PUT/PATCH; removing the lock restores normal behaviour.
    sbns = _p(RG, "Microsoft.ServiceBus", "namespaces", "uic-locked-sbns")
    arm.handle("PUT", sbns, {"api-version": "2022-10-01-preview"}, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}})
    sblock = sbns + "/providers/Microsoft.Authorization/locks/dont-delete-sbns"
    r = arm.handle("PUT", sblock, {"api-version": "2020-05-01"}, {"properties": {"level": "CanNotDelete"}})
    _check("servicebus namespace lock put 201", r["status"] == 201)
    r = arm.handle("PATCH", sbns, {"api-version": "2022-10-01-preview"}, {"tags": {"env": "prod"}})
    _check("CanNotDelete lock still allows PATCH", r["status"] == 200 and r["body"]["tags"]["env"] == "prod")
    r = arm.handle("DELETE", sbns, {"api-version": "2022-10-01-preview"})
    _check("CanNotDelete lock blocks DELETE (409 ScopeLocked)", r["status"] == 409 and r["body"]["error"]["code"] == "ScopeLocked")
    r = arm.handle("GET", sbns, {"api-version": "2022-10-01-preview"})
    _check("namespace survives the blocked delete", r["status"] == 200)

    r = arm.handle("PUT", sblock, {"api-version": "2020-05-01"}, {"properties": {"level": "ReadOnly"}})
    _check("lock level changed to ReadOnly", r["status"] == 200 and r["body"]["properties"]["level"] == "ReadOnly")
    r = arm.handle("PATCH", sbns, {"api-version": "2022-10-01-preview"}, {"tags": {"env": "blocked"}})
    _check("ReadOnly lock blocks PATCH (409 ScopeLocked)", r["status"] == 409 and r["body"]["error"]["code"] == "ScopeLocked")
    r = arm.handle("GET", sbns, {"api-version": "2022-10-01-preview"})
    _check("tags unchanged by the blocked PATCH", r["body"]["tags"]["env"] == "prod")

    r = arm.handle("DELETE", sblock, {"api-version": "2020-05-01"})
    _check("lock delete 200", r["status"] == 200)
    r = arm.handle("DELETE", sbns, {"api-version": "2022-10-01-preview"})
    _check("delete succeeds once the lock is removed", r["status"] == 200)
    r = arm.handle("GET", sbns, {"api-version": "2022-10-01-preview"})
    _check("namespace gone after unlocked delete", r["status"] == 404)

    # (a lock on a KeyVault vault — a different resource type — stays config_only, not
    # enforced: proven above at "locks cascade-deleted with resource", where DELETE
    # succeeded on `kv` despite its ReadOnly lock.)

    # Microsoft.DocumentDB/databaseAccounts: azure.cosmos.default_consistency /
    # backup_restore / replicate_data_globally are ENFORCED at the ARM contract level.
    cosmos_path = _p(RG, "Microsoft.DocumentDB", "databaseAccounts", "cosmosarmtest")
    r = arm.handle("PUT", cosmos_path, {"api-version": "2024-05-15"}, {
        "location": "eastus", "kind": "GlobalDocumentDB",
        "properties": {
            "databaseAccountOfferType": "Standard",
            "consistencyPolicy": {"defaultConsistencyLevel": "Session"},
            "locations": [{"locationName": "eastus", "failoverPriority": 0, "isZoneRedundant": False}],
            "backupPolicy": {"type": "Periodic", "periodicModeProperties": {
                "backupIntervalInMinutes": 240, "backupRetentionIntervalInHours": 8, "backupStorageRedundancy": "Geo"}},
        },
    })
    _check("cosmos account create 200 (LRO)", r["status"] == 200 and "Azure-AsyncOperation" in r["headers"])

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"},
                   {"properties": {"consistencyPolicy": {"defaultConsistencyLevel": "BoundedStaleness"}}})
    _check("BoundedStaleness without staleness fields rejected", r["status"] == 400)

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"}, {"properties": {
        "consistencyPolicy": {"defaultConsistencyLevel": "BoundedStaleness", "maxStalenessPrefix": 5, "maxIntervalInSeconds": 300}}})
    _check("BoundedStaleness out-of-range prefix rejected", r["status"] == 400)

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"}, {"properties": {
        "consistencyPolicy": {"defaultConsistencyLevel": "BoundedStaleness", "maxStalenessPrefix": 100000, "maxIntervalInSeconds": 300}}})
    _check("BoundedStaleness with valid fields accepted", r["status"] == 200)
    _check("BoundedStaleness round-trips",
           r["body"]["properties"]["consistencyPolicy"]["maxStalenessPrefix"] == 100000)

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"},
                   {"properties": {"backupPolicy": {"type": "Continuous", "continuousModeProperties": {"tier": "Continuous30Days"}}}})
    _check("Periodic -> Continuous backup migration accepted", r["status"] == 200)

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"},
                   {"properties": {"backupPolicy": {"type": "Periodic"}}})
    _check("Continuous -> Periodic backup migration rejected", r["status"] == 400)

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"},
                   {"properties": {"locations": [
                       {"locationName": "eastus", "failoverPriority": 0},
                       {"locationName": "westus", "failoverPriority": 2},
                   ]}})
    _check("locations with a failoverPriority gap rejected", r["status"] == 400)

    r = arm.handle("PATCH", cosmos_path, {"api-version": "2024-05-15"},
                   {"properties": {"locations": [
                       {"locationName": "eastus", "failoverPriority": 0, "isZoneRedundant": False},
                       {"locationName": "westus", "failoverPriority": 1, "isZoneRedundant": False},
                   ]}})
    _check("adding a second region accepted", r["status"] == 200)

    r = arm.handle("POST", cosmos_path + "/failoverPriorityChange", {"api-version": "2024-05-15"},
                   {"failoverPolicies": [{"locationName": "eastus", "failoverPriority": 1},
                                        {"locationName": "westus", "failoverPriority": 0}]})
    _check("manual failover accepted", r["status"] == 202)
    r = arm.handle("GET", cosmos_path, {"api-version": "2024-05-15"})
    _check("failover promotes westus to priority 0",
           next(l["failoverPriority"] for l in r["body"]["properties"]["locations"] if l["locationName"] == "westus") == 0)
    _check("failover demotes eastus", r["body"]["location"] == "westus")

    r = arm.handle("POST", cosmos_path + "/failoverPriorityChange", {"api-version": "2024-05-15"},
                   {"failoverPolicies": [{"locationName": "eastus", "failoverPriority": 0}]})
    _check("failover missing a configured region rejected", r["status"] == 400)

    # azure.cosmos.iam: Microsoft.Authorization/roleAssignments read scoped to the account
    # (plus its subscription/resource-group ancestors — real Azure's inherited access).
    ra_path = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments"
    r = arm.handle("PUT", ra_path + "/ra-cosmos-scoped", {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "11111111-1111-1111-1111-111111111111",
                                   "roleDefinitionId": "owner", "scope": cosmos_path}})
    _check("role assignment scoped to the cosmos account created", r["status"] == 201)
    r = arm.handle("PUT", ra_path + "/ra-sub-scoped", {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "22222222-2222-2222-2222-222222222222",
                                   "roleDefinitionId": "reader", "scope": f"/subscriptions/{SUB}"}})
    _check("role assignment scoped to the subscription created", r["status"] == 201)
    other_rid = _p(RG, "Microsoft.Storage", "storageAccounts", "unrelatedforiam")
    arm.handle("PUT", other_rid, {"api-version": AV}, {"location": "eastus"})
    r = arm.handle("PUT", ra_path + "/ra-other-scoped", {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "33333333-3333-3333-3333-333333333333",
                                   "roleDefinitionId": "contributor", "scope": other_rid}})
    _check("role assignment scoped to an unrelated resource created", r["status"] == 201)

    r = arm.handle("GET", cosmos_path + "/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    names = {x["name"] for x in r["body"]["value"]}
    _check("account-scoped IAM list includes the account-scoped assignment", "ra-cosmos-scoped" in names)
    _check("account-scoped IAM list includes the inherited subscription-scoped assignment", "ra-sub-scoped" in names)
    _check("account-scoped IAM list excludes an unrelated resource's assignment", "ra-other-scoped" not in names)
    # 28. A resource group's own Activity log (queried with the RG's own resourceUri, like
    # the resource group blade does) aggregates every resource's lifecycle event inside it —
    # not just the group's own create/update/delete — because every generic-catalog mutation
    # now also lands a resourceGroupName-tagged eventtypes row (azure.resourcegroups.activity_log).
    rg3 = "activity-rg"
    arm.handle("PUT", _rgpath(rg3), {"api-version": "2021-04-01"}, {})
    sa3 = _p(rg3, "Microsoft.Storage", "storageAccounts", "activitysa")
    arm.handle("PUT", sa3, {"api-version": "2023-01-01"}, {"location": "eastus"})
    arm.handle("DELETE", sa3, {"api-version": "2023-01-01"})
    rg_events_url = f"/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values"
    r = arm.handle("GET", rg_events_url, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{_rgpath(rg3)}'"})
    rg_ops = [e["operationName"]["value"] for e in r["body"]["value"]]
    _check("resource group activity log includes the RG's own create",
           "Microsoft.Resources/resourceGroups/write" in rg_ops)
    _check("resource group activity log aggregates a resource's create inside it",
           "Microsoft.Storage/storageAccounts/write" in rg_ops)
    _check("resource group activity log aggregates a resource's delete inside it",
           "Microsoft.Storage/storageAccounts/delete" in rg_ops)
    rg4 = "activity-rg-2"
    arm.handle("PUT", _rgpath(rg4), {"api-version": "2021-04-01"}, {})
    r = arm.handle("GET", rg_events_url, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{_rgpath(rg4)}'"})
    rg4_ops = [e["operationName"]["value"] for e in r["body"]["value"]]
    _check("activity log aggregation is scoped per resource group (no cross-group leakage)",
           "Microsoft.Storage/storageAccounts/write" not in rg4_ops)
    r = arm.handle("GET", f"/subscriptions/{SUB}/resources", {"api-version": "2021-04-01"})
    _check("activity log eventtypes rows never leak into the generic resources list",
           not any(x.get("type", "").lower() == "microsoft.insights/eventtypes" for x in r["body"]["value"]))

    # 29. Access control (IAM): role assignments are real ARM resources scoped to the resource
    # group they were PUT under (not a flat subscription-wide catalog), the Roles tab lists the
    # built-in roles (never provisioned as catalog records) alongside any custom ones, and
    # checkAccess evaluates a genuine decision (wildcard + scope-inheritance + notActions +
    # explicit-deny) over exactly those assignments (azure.resourcegroups.access_control_iam).
    iamrg1, iamrg2 = "iam-rg-1", "iam-rg-2"
    arm.handle("PUT", _rgpath(iamrg1), {"api-version": "2021-04-01"}, {})
    arm.handle("PUT", _rgpath(iamrg2), {"api-version": "2021-04-01"}, {})
    roledefs_url = lambda rg: f"{_rgpath(rg)}/providers/Microsoft.Authorization/roleDefinitions"
    r = arm.handle("GET", roledefs_url(iamrg1), {"api-version": "2022-04-01"})
    roledef_names = {x["name"] for x in r["body"]["value"]}
    _check("Roles tab lists the built-in roles with no custom roles ever created",
           {"Owner", "Contributor", "Reader"} <= roledef_names)
    ra1 = f"{_rgpath(iamrg1)}/providers/Microsoft.Authorization/roleAssignments/ra1"
    r = arm.handle("PUT", ra1, {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "alice", "roleName": "Reader"}})
    _check("role assignment put 201 scoped to the resource group it was created under",
           r["status"] == 201 and r["body"]["properties"]["scope"] == _rgpath(iamrg1))
    ra2 = f"{_rgpath(iamrg1)}/providers/Microsoft.Authorization/roleAssignments/ra2"
    arm.handle("PUT", ra2, {"api-version": "2022-04-01"},
               {"properties": {"principalId": "bob", "roleName": "Contributor"}})
    r = arm.handle("GET", f"{_rgpath(iamrg1)}/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("role assignments list scoped to the group that owns them", {x["name"] for x in r["body"]["value"]} == {"ra1", "ra2"})
    r = arm.handle("GET", f"{_rgpath(iamrg2)}/providers/Microsoft.Authorization/roleAssignments", {"api-version": "2022-04-01"})
    _check("a sibling resource group's role assignments never leak in", r["body"]["value"] == [])

    def _decision(rg, principal, action):
        resp = arm.handle("POST", f"{_rgpath(rg)}/providers/Microsoft.Authorization/checkAccess",
                          {"api-version": "2022-04-01"}, {"principalId": principal, "action": action})
        return resp["body"]["value"][0]["accessDecision"]

    _check("checkAccess: Reader can read in its own resource group",
           _decision(iamrg1, "alice", "Microsoft.Storage/storageAccounts/read") == "Allowed")
    _check("checkAccess: Reader cannot write",
           _decision(iamrg1, "alice", "Microsoft.Storage/storageAccounts/write") == "NotAllowed")
    _check("checkAccess: Contributor can write",
           _decision(iamrg1, "bob", "Microsoft.Storage/storageAccounts/write") == "Allowed")
    _check("checkAccess: scope isolation — Reader has no access in a sibling resource group",
           _decision(iamrg2, "alice", "Microsoft.Storage/storageAccounts/read") == "NotAllowed")
    r = arm.handle("DELETE", ra1, {"api-version": "2022-04-01"})
    _check("role assignment delete 200", r["status"] == 200)
    _check("checkAccess reflects the deleted assignment immediately",
           _decision(iamrg1, "alice", "Microsoft.Storage/storageAccounts/read") == "NotAllowed")

    print("\nRESULT: PASS — Azure ARM core conforms (native ARM wire + LRO + catalog CRUD) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
