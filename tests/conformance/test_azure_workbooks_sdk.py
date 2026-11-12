"""REAL azure-mgmt-applicationinsights (Workbooks CRUD) + azure-mgmt-loganalytics against the Azure wire, endpoint changed only: a workbook is
created through the SDK, then rendered (Vyomi action POST .../workbooks/{n}/render -- the portal renders client-side in real Azure) and its KQL
query item returns the table computed from rows ingested through the Log Analytics HTTP Data Collector API.
Needs `pip install azure-mgmt-applicationinsights` (scratch venv). Run: PYTHONPATH=. python tests/conformance/test_azure_workbooks_sdk.py"""
import json
import time
import uuid

import requests
from azure.core.credentials import AccessToken
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
from azure.mgmt.applicationinsights import models as am
from azure.mgmt.loganalytics import LogAnalyticsManagementClient

from tests.conformance import _azure_http

SUB = "00000000-0000-0000-0000-cloudlearn01"
BASE, ROUTER = _azure_http.start()
SFX = uuid.uuid4().hex[:6]
RG = f"rg-wb-{SFX}"


class _Cred:
    def get_token(self, *a, **k):
        return AccessToken("t", int(time.time()) + 3600)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def test_workbook_sdk_render():
    requests.put(f"{BASE}/subscriptions/{SUB}/resourcegroups/{RG}", json={"location": "eastus"}, params={"api-version": "2021-04-01"}, timeout=30)
    law = LogAnalyticsManagementClient(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())
    ws = law.workspaces.begin_create_or_update(RG, "wb-law", {"location": "eastus"}).result()
    for row in ({"Region": "west", "Amount": 10}, {"Region": "east", "Amount": 5}, {"Region": "west", "Amount": 7}):
        r = requests.post(f"{BASE}{ws.id}/api/logs", params={"api-version": "2022-10-01", "logType": "Sales"}, timeout=30, json=row)
        ok("data collector ingest", r.status_code in (200, 202), r.text)
    doc = {"version": "Notebook/1.0", "items": [
        {"type": 1, "name": "t", "content": {"json": "# Sales"}},
        {"type": 3, "name": "q", "content": {"queryType": 0, "visualization": "piechart", "crossComponentResources": [ws.id],
                                              "query": "Sales_CL | summarize total = sum(Amount_d) by Region_s | order by total desc"}}]}
    ai = ApplicationInsightsManagementClient(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())
    wid = str(uuid.uuid4())
    wb = ai.workbooks.create_or_update(RG, wid, am.Workbook(location="eastus", kind="shared", display_name="Sales", category="workbook",
                                                              serialized_data=json.dumps(doc), source_id=ws.id))
    ok("SDK created workbook", wb.display_name == "Sales" and wb.name == wid, wb)
    ok("SDK get / list", ai.workbooks.get(RG, wid).serialized_data == json.dumps(doc) and any(w.name == wid for w in ai.workbooks.list_by_resource_group(RG, "shared")))
    rr = requests.post(f"{BASE}{wb.id}/render", params={"api-version": "2022-04-01"}, json={}, timeout=30)
    ok("render 200", rr.status_code == 200, rr.text)
    q = [i for i in rr.json()["items"] if i["type"] == "query"][0]
    ok("query item rendered as a table", q["status"] == "ok" and q["visualization"] == "piechart" and q["rows"] == [["west", 17], ["east", 5]], q)
    ai.workbooks.delete(RG, wid)
    ok("workbook deleted", requests.post(f"{BASE}{wb.id}/render", params={"api-version": "2022-04-01"}, json={}, timeout=30).status_code == 404)


if __name__ == "__main__":
    test_workbook_sdk_render()
    print("PASS")
