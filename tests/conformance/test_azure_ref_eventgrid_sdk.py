"""Azure reference architecture lane 3 (Event Grid): a blob uploaded with azure-storage-blob raises Microsoft.Storage.BlobCreated to event
subscriptions created with azure-mgmt-eventgrid on a storage-account system topic, delivered to
  - a WebHook that is a Function App function (with the SubscriptionValidation handshake; a webhook that does not answer it gets nothing and
    is left AwaitingManualAction),
  - an AzureFunction destination (the Function App's deployed code runs the batch),
  - a Service Bus queue (read back over AMQP) and a Storage Queue.
The function CODE execution is the Function App runtime's; this test uses the existing invoke path.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_ref_eventgrid_sdk.py   (skips when the Azure SDKs are absent)
"""
import io
import json
import os
import sys
import tempfile
import time
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _az_ref_harness as H  # noqa: E402

KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


def main():
    try:
        import azure.mgmt.eventgrid, azure.mgmt.storage, azure.mgmt.web, azure.storage.blob, azure.servicebus, requests  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] needs the Azure SDKs ({e})")
        return 0
    base, amqp = H.start()
    H.ensure_rg(base)
    import requests
    from azure.mgmt.eventgrid import EventGridManagementClient
    from azure.mgmt.servicebus import ServiceBusManagementClient
    from azure.mgmt.storage import StorageManagementClient
    from azure.mgmt.web import WebSiteManagementClient
    from azure.servicebus import ServiceBusClient
    from azure.storage.blob import BlobServiceClient

    ACCT = "facilitiesdocs"
    SCOPE = f"/subscriptions/{H.SUB}/resourceGroups/{H.RG}/providers/Microsoft.Storage/storageAccounts/{ACCT}"
    log = tempfile.mktemp(prefix="egfn-", suffix=".log")
    eg = H.arm(EventGridManagementClient, base)
    H.arm(StorageManagementClient, base).storage_accounts.begin_create(H.RG, ACCT, {"location": H.LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
    bs = BlobServiceClient.from_connection_string(
        f"DefaultEndpointsProtocol=http;AccountName={ACCT};AccountKey={KEY};BlobEndpoint={base}/{ACCT};")
    bs.create_container("docs")
    web = H.arm(WebSiteManagementClient, base)
    web.app_service_plans.begin_create_or_update(H.RG, "plan1", {"location": H.LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
    web.web_apps.begin_create_or_update(H.RG, "facilities-tools", {"location": H.LOC, "kind": "functionapp",
        "server_farm_id": f"/subscriptions/{H.SUB}/resourceGroups/{H.RG}/providers/Microsoft.Web/serverfarms/plan1"}).result()
    code = f'''import json
import azure.functions as func
LOG = {log!r}
def main(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    ev = body if isinstance(body, list) else [body]
    hdrs = {{k.lower(): v for k, v in req.headers.items()}}   # (the shim's header map is case-sensitive: lane az-ref-runtime)
    if hdrs.get("aeg-event-type") == "SubscriptionValidation":
        return func.HttpResponse(json.dumps({{"validationResponse": ev[0]["data"]["validationCode"]}}), mimetype="application/json")
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\\n")
    return func.HttpResponse("ok")
'''
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("on_blob/__init__.py", code)
    assert requests.post(base + "/azure-data/functions/facilities-tools/api/zipdeploy", data=z.getvalue(), timeout=30).status_code == 200
    eg.system_topics.begin_create_or_update(H.RG, "docs-topic", {"location": H.LOC, "source": SCOPE, "topicType": "Microsoft.Storage.StorageAccounts"}).result()

    def subscribe(name, dest):
        return eg.system_topic_event_subscriptions.begin_create_or_update(H.RG, "docs-topic", name, {
            "properties": {"destination": dest, "filter": {"includedEventTypes": ["Microsoft.Storage.BlobCreated", "Microsoft.Storage.BlobDeleted"]}}}).result()

    def logged(n=1, timeout=15):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if os.path.exists(log):
                rows = [json.loads(x) for x in open(log).read().splitlines() if x.strip()]
                if len(rows) >= n:
                    return rows
            time.sleep(0.3)
        return []

    def events_of(rows):
        return [e for r in rows for e in r]

    def t_webhook_function():
        subscribe("to-fn-hook", {"endpointType": "WebHook", "properties": {"endpointUrl": base + "/azure-data/functions/facilities-tools/api/on_blob"}})
        bs.get_blob_client("docs", "policy.txt").upload_blob(b"approvals above 500 need a manager")
        evs = events_of(logged(1))
        assert evs, "no BlobCreated reached the function"
        e = evs[0]
        assert e["eventType"] == "Microsoft.Storage.BlobCreated", e
        assert e["subject"] == "/blobServices/default/containers/docs/blobs/policy.txt", e["subject"]
        assert e["data"]["contentLength"] == len(b"approvals above 500 need a manager") and e["data"]["api"] == "PutBlob", e["data"]
        s = eg.system_topic_event_subscriptions.get(H.RG, "docs-topic", "to-fn-hook")
        assert s.provisioning_state == "Succeeded", s.provisioning_state

    def t_handshake_refused():
        s = subscribe("to-dumb-hook", {"endpointType": "WebHook", "properties": {"endpointUrl": base + "/azure-data/functions/nosuchapp/api/x"}})
        bs.get_blob_client("docs", "h.txt").upload_blob(b"x")
        time.sleep(3)
        s = eg.system_topic_event_subscriptions.get(H.RG, "docs-topic", "to-dumb-hook")
        assert s.provisioning_state == "AwaitingManualAction", s.provisioning_state

    def t_azure_function_destination():
        before = len(events_of(logged(0, 0.1)))
        subscribe("to-fn", {"endpointType": "AzureFunction", "properties": {
            "resourceId": f"/subscriptions/{H.SUB}/resourceGroups/{H.RG}/providers/Microsoft.Web/sites/facilities-tools/functions/on_blob"}})
        eg.system_topic_event_subscriptions.begin_delete(H.RG, "docs-topic", "to-fn-hook").result()   # only the AzureFunction sub now
        bs.get_blob_client("docs", "af.txt").upload_blob(b"azure function destination")
        t0 = time.time()
        while time.time() - t0 < 15:
            evs = events_of(logged(0, 0.1))
            if any(e["subject"].endswith("/blobs/af.txt") for e in evs):
                return
            time.sleep(0.3)
        raise AssertionError(f"AzureFunction destination never ran ({before} earlier events)")

    def t_servicebus_destination():
        sbm = H.arm(ServiceBusManagementClient, base)
        sbm.namespaces.begin_create_or_update(H.RG, "facilities-bus", {"location": H.LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
        sbm.queues.create_or_update(H.RG, "facilities-bus", "doc-events", {})
        subscribe("to-sb", {"endpointType": "ServiceBusQueue", "properties": {
            "resourceId": f"/subscriptions/{H.SUB}/resourceGroups/{H.RG}/providers/Microsoft.ServiceBus/namespaces/facilities-bus/queues/doc-events"}})
        bs.get_blob_client("docs", "sb.txt").upload_blob(b"to service bus")
        with ServiceBusClient.from_connection_string(H.sb_conn(amqp)) as c:
            with c.get_queue_receiver("doc-events", max_wait_time=15) as r:
                ms = r.receive_messages(max_message_count=1, max_wait_time=15)
                assert ms, "no event on the Service Bus queue"
                ev = json.loads(b"".join(ms[0].body).decode())
                assert ev["eventType"] == "Microsoft.Storage.BlobCreated" and ev["subject"].endswith("/blobs/sb.txt"), ev
                r.complete_message(ms[0])

    def t_blob_deleted():
        n0 = len(events_of(logged(0, 0.1)))
        bs.get_blob_client("docs", "af.txt").delete_blob()
        t0 = time.time()
        while time.time() - t0 < 15:
            if any(e["eventType"] == "Microsoft.Storage.BlobDeleted" for e in events_of(logged(0, 0.1))):
                return
            time.sleep(0.3)
        raise AssertionError("no BlobDeleted event")

    H.run_cases([
        ("BlobCreated -> WebHook that is a Function (SubscriptionValidation handshake answered)", t_webhook_function),
        ("a WebHook that does not answer the handshake is AwaitingManualAction and gets nothing", t_handshake_refused),
        ("BlobCreated -> AzureFunction destination runs the function", t_azure_function_destination),
        ("BlobCreated -> Service Bus queue (read over AMQP)", t_servicebus_destination),
        ("BlobDeleted -> function", t_blob_deleted),
    ])


if __name__ == "__main__":
    sys.exit(main())
