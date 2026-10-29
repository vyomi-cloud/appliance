"""Azure control/data-plane ops through the official azure-core / azure-storage-blob SDKs.

Only the endpoint is changed. Covers list_resource_groups, list_containers,
put_role_definition, put_role_assignment, delete_role_assignment and the
Key Vault get_key / delete_key data plane.
Run: VYOMI_BASE_URL=http://localhost:9000 python3 tests/conformance/test_azure_sdk_python_ops.py
"""
import json
import os
import sys
import uuid

from azure.core import PipelineClient
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.pipeline.policies import HeadersPolicy, RetryPolicy
from azure.core.rest import HttpRequest
from azure.storage.blob import BlobServiceClient

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
SUB = os.environ.get("SUB", "00000000-0000-0000-0000-cloudlearn01")
failed = 0


def check(name, ok, detail=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    failed += 0 if ok else 1


client = PipelineClient(BASE, policies=[HeadersPolicy(), RetryPolicy(retry_total=0)])


def call(method, path, body=None):
    req = HttpRequest(method, BASE + path, json=body)
    resp = client.send_request(req)
    text = resp.read() if hasattr(resp, "read") else b""
    try:
        return resp.status_code, json.loads(text or b"{}")
    except ValueError:
        return resp.status_code, {}


def main():
    sc, d = call("GET", f"/subscriptions/{SUB}/resourcegroups?api-version=2021-04-01")
    check("list_resource_groups returns value[]", sc == 200 and isinstance(d.get("value"), list) and d["value"], sc)

    # list_containers via the official blob SDK
    acct = "stpyops" + uuid.uuid4().hex[:6]
    key = "a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2U="
    svc = BlobServiceClient(f"{BASE}/azure-data/blob/{acct}/",
                            credential=AzureNamedKeyCredential(acct, key))
    try:
        svc.create_container("pyc1")
        names = [c.name for c in svc.list_containers()]
        check("list_containers sees created container", "pyc1" in names, names)
        svc.delete_container("pyc1")
    except Exception as e:  # noqa: BLE001
        check("list_containers via azure-storage-blob", False, e)

    scope = f"/subscriptions/{SUB}"
    rd, ra = str(uuid.uuid4()), str(uuid.uuid4())
    auth = f"{scope}/providers/Microsoft.Authorization"
    sc, d = call("PUT", f"{auth}/roleDefinitions/{rd}?api-version=2022-04-01", {"properties": {
        "roleName": "pyops-" + rd[:6], "type": "CustomRole",
        "permissions": [{"actions": ["*/read"]}], "assignableScopes": [scope]}})
    check("put_role_definition", sc in (200, 201) and d.get("name") == rd, (sc, d))
    sc, d = call("PUT", f"{auth}/roleAssignments/{ra}?api-version=2022-04-01", {"properties": {
        "roleDefinitionId": f"{auth}/roleDefinitions/{rd}", "principalId": str(uuid.uuid4())}})
    check("put_role_assignment", sc in (200, 201) and d.get("name") == ra, (sc, d))
    sc, _ = call("DELETE", f"{auth}/roleAssignments/{ra}?api-version=2022-04-01")
    check("delete_role_assignment", sc in (200, 204), sc)

    kv = f"/azure-data/keyvault/kvpy{uuid.uuid4().hex[:5]}/keys"
    sc, d = call("POST", f"{kv}/pykey/create?api-version=7.4", {"kty": "RSA"})
    check("create_key", sc == 200 and d.get("key", {}).get("kty") == "RSA", (sc, d))
    sc, d = call("GET", f"{kv}/pykey?api-version=7.4")
    check("get_key returns JWK with kid", sc == 200 and "/keys/pykey/" in d.get("key", {}).get("kid", ""), (sc, d))
    sc, d = call("DELETE", f"{kv}/pykey?api-version=7.4")
    check("delete_key returns recoveryId", sc == 200 and "pykey" in d.get("recoveryId", ""), (sc, d))

    sys.exit(1 if failed else 0)


main()
