"""Real Azure SDK (azure-mgmt-resource, azure-mgmt-loganalytics) against the ARM core served over real HTTP.
Covers resource-group moveResources and Log Analytics data export + purge.
Run: PYTHONPATH=. python tests/conformance/test_azure_sdk_rg_move_loganalytics.py   (needs azure-mgmt-resource, azure-mgmt-loganalytics)"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core.azure_blob_core import AzureBlobStore, dispatch as blob

ARM = AzureArm()
ARM.blob_store = BS = AzureBlobStore()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        body = json.loads(raw) if raw else None
        r = ARM.handle(self.command, u.path, dict(parse_qsl(u.query)), body)
        out = json.dumps(r["body"]).encode() if r.get("body") is not None else b""
        self.send_response(r["status"])
        for k, v in (r.get("headers") or {}).items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_PUT = do_POST = do_DELETE = do_PATCH = _do


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.resource.resources.models import ResourcesMoveInfo
    from azure.mgmt.loganalytics import LogAnalyticsManagementClient
    from azure.mgmt.loganalytics.models import DataExportProperties, Destination, Table, Schema, Column, DataExport, WorkspacePurgeBody, WorkspacePurgeBodyFilters

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    cred = object()
    kw = dict(base_url=url, authentication_policy=SansIOHTTPPolicy())
    rc = ResourceManagementClient(cred, SUB, **kw)
    rc.resource_groups.create_or_update("sdk-src", {"location": "eastus"})
    rc.resource_groups.create_or_update("sdk-dst", {"location": "eastus"})
    base = f"/subscriptions/{SUB}/resourceGroups/sdk-src/providers/Microsoft.Storage/storageAccounts/sdkacct"
    rc.resources.begin_create_or_update_by_id(base, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, api_version="2023-01-01").result()
    info = ResourcesMoveInfo(resources=[base], target_resource_group=f"/subscriptions/{SUB}/resourceGroups/sdk-dst")
    rc.resources.begin_validate_move_resources("sdk-src", info).result()
    _check("SDK validate_move_resources succeeds", True)
    rc.resources.begin_move_resources("sdk-src", info).result()
    names = [r.name for r in rc.resources.list_by_resource_group("sdk-dst")]
    _check("SDK move_resources: resource now listed in the target group", "sdkacct" in names)
    _check("source group no longer lists it", "sdkacct" not in [r.name for r in rc.resources.list_by_resource_group("sdk-src")])

    la = LogAnalyticsManagementClient(cred, SUB, **kw)
    rg = "sdk-dst"
    la.workspaces.begin_create_or_update(rg, "sdkws", {"location": "eastus"}).result()
    sa_id = f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/sdkacct"
    la.tables.begin_create_or_update(rg, "sdkws", "Evt_CL", Table(schema=Schema(name="Evt_CL", columns=[Column(name="TimeGenerated", type="datetime"), Column(name="who_s", type="string")]))).result()
    de = la.data_exports.create_or_update(rg, "sdkws", "sdk-export", DataExport(properties=DataExportProperties(destination=Destination(resource_id=sa_id), table_names=["Evt_CL"], enable=True)))
    _check("SDK data_exports.create_or_update", de.name == "sdk-export" and de.properties.table_names == ["Evt_CL"])
    _check("SDK data_exports.list", [d.name for d in la.data_exports.list_by_workspace(rg, "sdkws")] == ["sdk-export"])
    # ingest through the data plane of the same workspace
    ARM.handle("POST", f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.OperationalInsights/workspaces/sdkws/api/logs",
               {"logType": "Evt", "api-version": "2022-10-01"}, [{"who": "a"}, {"who": "b"}])
    _check("rows exported to blob storage", BS.container_exists("sdkacct/am-evt-cl") and len(list(BS.container_blobs("sdkacct/am-evt-cl"))) == 1)
    p = la.workspace_purge.purge(rg, "sdkws", WorkspacePurgeBody(table="Evt_CL", filters=[WorkspacePurgeBodyFilters(column="who_s", operator="==", value="a")]))
    _check("SDK workspace_purge.purge returns an operationId", p.operation_id.startswith("purge-"))
    st = la.workspace_purge.get_purge_status(rg, "sdkws", p.operation_id)
    _check("SDK get_purge_status completed", st.status == "completed")
    la.data_exports.delete(rg, "sdkws", "sdk-export")
    _check("SDK data_exports.delete", list(la.data_exports.list_by_workspace(rg, "sdkws")) == [])
    srv.shutdown()
    print("PASS")


if __name__ == "__main__":
    run()
