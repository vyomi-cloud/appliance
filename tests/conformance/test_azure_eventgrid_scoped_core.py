try:
    import core.azure_arm_core as _lax_arm; _lax_arm.AzureArm.STRICT_SUBSCRIPTION = False  # engine test: ad-hoc subscription ids
except ImportError:
    pass
"""Event Grid subscriptions scoped to a resource / resource group; real ResourceWriteSuccess events from ARM writes."""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    av = {"api-version": "2022-06-15"}
    a.handle("PUT", f"/subscriptions/{S}/resourceGroups/r", {"api-version": "2021-04-01"}, {"location": "eastus"})
    rg = f"/subscriptions/{S}/resourceGroups/r"
    sa = f"{rg}/providers/Microsoft.Storage/storageAccounts/sa1"
    a.handle("PUT", sa, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    dest = {"endpointType": "WebHook", "properties": {"endpointUrl": "http://localhost:9/x"}}
    _check("destination required", a.handle("PUT", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/bad", av, {"properties": {}})["status"] == 400)
    _check("invalid event type rejected", a.handle("PUT", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/bad", av,
           {"properties": {"destination": dest, "filter": {"includedEventTypes": ["Microsoft.KeyVault.SecretExpired"]}}})["status"] == 400)
    r = a.handle("PUT", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/blobs", av,
                 {"properties": {"destination": dest, "filter": {"includedEventTypes": ["Microsoft.Storage.BlobCreated"], "subjectBeginsWith": "/x"}}})
    _check("storage-scoped subscription created", r["status"] == 201)
    _check("listed at that scope only", len(a.handle("GET", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions", av)["body"]["value"]) == 1
           and len(a.handle("GET", f"{rg}/providers/Microsoft.EventGrid/eventSubscriptions", av)["body"]["value"]) == 0)
    o = a.handle("POST", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/simulateEvent", av, {"eventType": "Microsoft.Storage.BlobDeleted", "subject": "/x/y"})
    _check("non-matching event type not matched", o["body"]["deliveries"] == [])
    o = a.handle("POST", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/simulateEvent", av, {"eventType": "Microsoft.Storage.BlobCreated", "subject": "/x/y"})
    _check("matching event matched + honestly dropped (unreachable webhook)", o["body"]["deliveries"][0]["result"] == "dropped")
    st = a.handle("GET", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/blobs/deliveryStatus", av)["body"]
    _check("delivery counters real", st["matched"] == 1 and st["failed"] == 1)
    a.handle("PUT", f"{rg}/providers/Microsoft.EventGrid/eventSubscriptions/rgw", av,
             {"properties": {"destination": dest, "filter": {"includedEventTypes": ["Microsoft.Resources.ResourceWriteSuccess"]}}})
    a.handle("PUT", f"{rg}/providers/Microsoft.Network/virtualNetworks/v1", {"api-version": "2023-11-01"}, {"location": "eastus"})
    st = a.handle("GET", f"{rg}/providers/Microsoft.EventGrid/eventSubscriptions/rgw/deliveryStatus", av)["body"]
    _check("a real ARM write raises ResourceWriteSuccess on the resource group", st["matched"] >= 1)
    _check("delete", a.handle("DELETE", f"{sa}/providers/Microsoft.EventGrid/eventSubscriptions/blobs", av)["status"] == 200)
    print("PASS test_azure_eventgrid_scoped_core")


if __name__ == "__main__":
    run()
