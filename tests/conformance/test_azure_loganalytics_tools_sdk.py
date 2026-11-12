"""REAL azure-mgmt-loganalytics (linked_storage_accounts, saved_searches) + azure-mgmt-storage against the Azure wire, endpoint changed only:
linked storage accounts are created/read/listed/deleted through the SDK with the service's validation, and a Computer group (a saved search with
category 'Computer Groups') made through the Vyomi computerGroups view is visible to the SDK as a real saved search and usable in KQL.
Run: PYTHONPATH=. <venv>/bin/python tests/conformance/test_azure_loganalytics_tools_sdk.py   (or pytest)"""
import time
import uuid

import requests
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.mgmt.loganalytics import LogAnalyticsManagementClient
from azure.mgmt.loganalytics.models import LinkedStorageAccountsResource
from azure.mgmt.storage import StorageManagementClient

from tests.conformance import _azure_http

SUB = "00000000-0000-0000-0000-cloudlearn01"
BASE, ROUTER = _azure_http.start()
SFX = uuid.uuid4().hex[:6]
RG = f"rg-lt-{SFX}"


class _Cred:
    def get_token(self, *a, **k):
        return AccessToken("t", int(time.time()) + 3600)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def test_linked_storage_and_computer_groups_sdk():
    requests.put(f"{BASE}/subscriptions/{SUB}/resourcegroups/{RG}", json={"location": "eastus"}, params={"api-version": "2021-04-01"}, timeout=30)
    law = LogAnalyticsManagementClient(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())
    st = StorageManagementClient(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())
    ws = law.workspaces.begin_create_or_update(RG, "lt-law", {"location": "eastus"}).result()
    a1 = st.storage_accounts.begin_create(RG, "ltsdk1" + SFX, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}).result()
    aw = st.storage_accounts.begin_create(RG, "ltsdkw" + SFX, {"location": "westus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}).result()

    try:
        law.linked_storage_accounts.create_or_update(RG, "lt-law", "CustomLogs", LinkedStorageAccountsResource(storage_account_ids=[aw.id]))
        ok("SDK: cross-region account rejected", False)
    except HttpResponseError as e:
        ok("SDK: cross-region account rejected", "region" in str(e).lower(), e)
    r = law.linked_storage_accounts.create_or_update(RG, "lt-law", "CustomLogs", LinkedStorageAccountsResource(storage_account_ids=[a1.id]))
    ok("SDK: link created", r.name == "CustomLogs" and r.storage_account_ids == [a1.id], r)
    ok("SDK: get + list_by_workspace", law.linked_storage_accounts.get(RG, "lt-law", "CustomLogs").data_source_type == "CustomLogs"
       and [x.name for x in law.linked_storage_accounts.list_by_workspace(RG, "lt-law")] == ["CustomLogs"])
    law.linked_storage_accounts.delete(RG, "lt-law", "CustomLogs")
    ok("SDK: deleted", list(law.linked_storage_accounts.list_by_workspace(RG, "lt-law")) == [])

    for host in ("db1", "db2", "app1"):
        requests.post(f"{BASE}{ws.id}/api/logs", params={"api-version": "2022-10-01", "logType": "Nodes"}, json={"Computer": host, "Role": "db" if host.startswith("db") else "app"}, timeout=30)
    g = requests.put(f"{BASE}{ws.id}/computerGroups/Databases", params={"api-version": "2022-10-01"}, timeout=30,
                     json={"properties": {"displayName": "Databases", "query": "Nodes_CL | where Role_s == 'db' | project Computer_s"}})
    ok("computer group created", g.status_code == 200 and g.json()["properties"]["members"] == ["db1", "db2"], g.text)
    s = law.saved_searches.get(RG, "lt-law", "Databases")
    ok("SDK sees it as a saved search in category 'Computer Groups' with a function alias", s.category == "Computer Groups" and s.function_alias == "Databases", s)
    q = requests.post(f"{BASE}{ws.id}/api/query", params={"api-version": "2022-10-01"}, json={"query": "Nodes_CL | where Computer_s in (Databases) | count"}, timeout=30).json()
    ok("KQL `in (Databases)` expands to the members", q["tables"][0]["rows"] == [[2]], q)


if __name__ == "__main__":
    test_linked_storage_and_computer_groups_sdk()
    print("PASS")
