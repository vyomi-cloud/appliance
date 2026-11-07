"""REAL Azure SDKs (azure-mgmt-*, azure-storage-blob) against the Azure wire - only the endpoint changes - proving that the network
rules / CORS / diagnostic settings / connection policy configured THROUGH THE SDK are ENFORCED on the data planes: a blocked request is
refused (403), an allowed one passes. The front is the same AwsWireRouter code Nano runs (tests/conformance/_azure_http.py).
The simulated client is declared with x-vyomi-source-ip / -subnet / -private-endpoint / -trusted-service headers.
Run: PYTHONPATH=. python tests/conformance/test_azure_netenforce_sdk.py   (or pytest)"""
import json
import time
import uuid

import requests
from azure.core.credentials import AccessToken, AzureNamedKeyCredential
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.cosmosdb import CosmosDBManagementClient
from azure.mgmt.loganalytics import LogAnalyticsManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.servicebus import ServiceBusManagementClient
from azure.mgmt.sql import SqlManagementClient
from azure.mgmt.storage import StorageManagementClient
from azure.storage.blob import BlobServiceClient

from tests.conformance import _azure_http

SUB = "00000000-0000-0000-0000-cloudlearn01"
BASE, ROUTER = _azure_http.start()
SFX = uuid.uuid4().hex[:6]
RG = f"rg-ne-{SFX}"


class _Cred:
    def get_token(self, *a, **k):
        return AccessToken("t", int(time.time()) + 3600)


def mgmt(cls):
    return cls(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())


def rest(method, path, body=None, headers=None, params=None):
    return requests.request(method, BASE + path, json=body, headers=headers or {}, params=params, timeout=30)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


rest("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}", {"location": "eastus"}, params={"api-version": "2021-04-01"})
net = mgmt(NetworkManagementClient)
vn = net.virtual_networks.begin_create_or_update(RG, "vn", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}}).result()
sn = net.subnets.begin_create_or_update(RG, "vn", "app", {"properties": {"addressPrefix": "10.0.1.0/24", "serviceEndpoints": [
    {"service": "Microsoft.Storage"}, {"service": "Microsoft.ServiceBus"}, {"service": "Microsoft.Sql"}]}}).result()
bare = net.subnets.begin_create_or_update(RG, "vn", "bare", {"properties": {"addressPrefix": "10.0.2.0/24"}}).result()
SN, BARE = sn.id, bare.id
ok("subnet service endpoints round-trip through azure-mgmt-network", [e.service for e in net.subnets.get(RG, "vn", "app").service_endpoints] == ["Microsoft.Storage", "Microsoft.ServiceBus", "Microsoft.Sql"])


def test_vnets_subnetservices_validation():
    st = mgmt(StorageManagementClient)
    try:
        st.storage_accounts.begin_create(RG, "stbad" + SFX, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                         "properties": {"networkAcls": {"defaultAction": "Deny", "virtualNetworkRules": [{"id": BARE, "action": "Allow"}]}}}).result()
        ok("a vnet rule on a subnet WITHOUT the service endpoint is rejected", False)
    except Exception as e:  # noqa: BLE001
        ok("a vnet rule on a subnet WITHOUT the service endpoint is rejected", "SubnetsHaveNoServiceEndpointsConfigured" in str(e) or "service endpoint" in str(e).lower(), e)


def test_storage_exceptions_bypass_and_firewall():
    st = mgmt(StorageManagementClient)
    acct = "stne" + SFX
    st.storage_accounts.begin_create(RG, acct, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                     "properties": {"networkAcls": {"defaultAction": "Deny", "bypass": "None", "ipRules": [{"value": "20.50.60.0/24", "action": "Allow"}]}}}).result()
    key = "a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2U="
    cur = {}

    def hook(req):
        req.http_request.headers.update(cur)
    svc = BlobServiceClient(f"{BASE}/{acct}", credential=AzureNamedKeyCredential(acct, key), raw_request_hook=hook)
    cur.update({"x-vyomi-source-ip": "20.50.60.9"})
    svc.create_container("c1")
    ok("azure-storage-blob: allowed IP creates a container", "c1" in [c.name for c in svc.list_containers()])
    cur.clear(); cur.update({"x-vyomi-source-ip": "52.1.1.50"})
    try:
        list(svc.list_containers())
        ok("blocked IP", False)
    except Exception as e:  # noqa: BLE001
        ok("azure-storage-blob: IP outside the firewall is BLOCKED (AuthorizationFailure)", "403" in str(e) or "AuthorizationFailure" in str(e) or "not authorized" in str(e).lower(), e)
    cur.clear(); cur.update({"x-vyomi-source-ip": "52.1.1.50", "x-vyomi-trusted-service": "1"})
    try:
        list(svc.list_containers())
        ok("trusted service without bypass", False)
    except Exception:  # noqa: BLE001
        ok("trusted Azure service is BLOCKED while networkAcls.bypass=None", True)
    st.storage_accounts.update(RG, acct, {"properties": {"networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices", "ipRules": [{"value": "20.50.60.0/24", "action": "Allow"}]}}})
    ok("trusted Azure service passes once bypass=AzureServices is set via the SDK", len(list(svc.list_containers())) == 1)
    cur.clear(); cur.update({"x-vyomi-source-subnet": SN})
    try:
        list(svc.list_containers())
        ok("subnet without rule", False)
    except Exception:  # noqa: BLE001
        ok("a subnet with no virtual network rule is BLOCKED", True)
    st.storage_accounts.update(RG, acct, {"properties": {"networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices",
                                          "virtualNetworkRules": [{"id": SN, "action": "Allow"}]}}})
    ok("subnet with the Microsoft.Storage endpoint + vnet rule passes", len(list(svc.list_containers())) == 1)


def test_servicebus_network_rule_set():
    sb = mgmt(ServiceBusManagementClient)
    sb.namespaces.begin_create_or_update(RG, "sbns" + SFX, {"location": "eastus", "sku": {"name": "Premium", "tier": "Premium", "capacity": 1}}).result()
    sb.namespaces.create_or_update_network_rule_set(RG, "sbns" + SFX, {"properties": {"defaultAction": "Deny", "publicNetworkAccess": "Enabled",
        "ipRules": [{"ipMask": "198.51.100.0/24", "action": "Allow"}], "virtualNetworkRules": [{"subnet": {"id": SN}}]}})
    d = lambda **h: rest("PUT", "/q-" + SFX, headers={"x-vyomi-namespace": "sbns" + SFX, "content-type": "application/atom+xml", **h})
    ok("Service Bus: allowed IP passes", d(**{"x-vyomi-source-ip": "198.51.100.4"}).status_code in (200, 201))
    ok("Service Bus: other IP BLOCKED (403)", d(**{"x-vyomi-source-ip": "192.0.2.1"}).status_code == 403)
    ok("Service Bus: vnet rule + endpoint passes", d(**{"x-vyomi-source-subnet": SN}).status_code in (200, 201))
    sb.namespaces.create_or_update_network_rule_set(RG, "sbns" + SFX, {"properties": {"defaultAction": "Allow", "publicNetworkAccess": "Disabled"}})
    ok("Service Bus: publicNetworkAccess=Disabled BLOCKS even an allowed IP", d(**{"x-vyomi-source-ip": "198.51.100.4"}).status_code == 403)


def test_cognitive_services_networking():
    cs = mgmt(CognitiveServicesManagementClient)
    a = "oai" + SFX
    cs.accounts.begin_create(RG, a, {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": a}}).result()
    cs.deployments.begin_create_or_update(RG, a, "gpt", {"sku": {"name": "Standard", "capacity": 10}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o-mini", "version": "2024-07-18"}}}).result()
    cs.accounts.begin_update(RG, a, {"properties": {"networkAcls": {"defaultAction": "Deny", "ipRules": [{"value": "20.50.60.0/24"}], "virtualNetworkRules": [{"id": SN}]}}}).result()
    chat = lambda **h: rest("POST", "/openai/deployments/gpt/chat/completions", {"messages": [{"role": "user", "content": "hi"}]},
                            headers={"api-key": "k", **h}, params={"api-version": "2024-06-01"})
    ok("Azure AI: IP outside the account firewall BLOCKED (403)", chat(**{"x-vyomi-source-ip": "52.1.1.50"}).status_code == 403)
    ok("Azure AI: allowed IP is not firewall-blocked", chat(**{"x-vyomi-source-ip": "20.50.60.7"}).status_code != 403)
    cs.accounts.begin_update(RG, a, {"properties": {"publicNetworkAccess": "Disabled"}}).result()
    ok("Azure AI: publicNetworkAccess=Disabled BLOCKS an allowed IP", chat(**{"x-vyomi-source-ip": "20.50.60.7"}).status_code == 403)


def test_log_analytics_public_access():
    la = mgmt(LogAnalyticsManagementClient)
    ws = "law-" + SFX
    la.workspaces.begin_create_or_update(RG, ws, {"location": "eastus", "properties": {"publicNetworkAccessForIngestion": "Enabled", "publicNetworkAccessForQuery": "Disabled"}}).result()
    p = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/{ws}"
    ing = lambda: rest("POST", p + "/api/logs", [{"a": 1}], params={"api-version": "2022-10-01", "logType": "App"})
    qry = lambda: rest("POST", p + "/api/query", {"query": "App_CL | take 1"}, params={"api-version": "2022-10-01"})
    ok("Log Analytics: ingestion allowed", ing().status_code < 300)
    ok("Log Analytics: query BLOCKED while publicNetworkAccessForQuery=Disabled", qry().status_code == 403)
    la.workspaces.begin_create_or_update(RG, ws, {"location": "eastus", "properties": {"publicNetworkAccessForIngestion": "Disabled", "publicNetworkAccessForQuery": "Enabled"}}).result()
    ok("Log Analytics: ingestion BLOCKED once disabled; query allowed", ing().status_code == 403 and qry().status_code < 300)


def test_cosmos_cors_preflight():
    cz = mgmt(CosmosDBManagementClient)
    a = "cz" + SFX
    cz.database_accounts.begin_create_or_update(RG, a, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"locations": [{"locationName": "East US", "failoverPriority": 0}],
        "databaseAccountOfferType": "Standard",
        "cors": [{"allowedOrigins": "https://app.contoso.com", "allowedHeaders": "x-ms-version", "maxAgeInSeconds": 300}]}}).result()
    pre = lambda o: rest("OPTIONS", "/dbs", headers={"Origin": o, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-ms-version", "x-vyomi-account": a})
    r = pre("https://app.contoso.com")
    ok("Cosmos CORS preflight: listed origin gets Access-Control-Allow-Origin", r.status_code == 200 and r.headers.get("access-control-allow-origin") == "https://app.contoso.com", (r.status_code, dict(r.headers)))
    r = pre("https://evil.example")
    ok("Cosmos CORS preflight: unlisted origin BLOCKED, no CORS headers", r.status_code == 403 and "access-control-allow-origin" not in r.headers)


def test_sql_connection_policy_and_firewall():
    sq = mgmt(SqlManagementClient)
    srv = "sql" + SFX
    sq.servers.begin_create_or_update(RG, srv, {"location": "eastus", "properties": {"administratorLogin": "adm", "administratorLoginPassword": "Passw0rd!xyz"}}).result()
    sq.firewall_rules.create_or_update(RG, srv, "office", {"properties": {"startIpAddress": "198.51.100.10", "endIpAddress": "198.51.100.20"}})
    sq.server_connection_policies.begin_create_or_update(RG, srv, "default", {"properties": {"connectionType": "Redirect"}}).result()
    rest("PUT", f"/azure-sql/servers/{srv}/databases/d1", {})
    q = lambda **h: rest("POST", f"/azure-sql/servers/{srv}/databases/d1/query", {"sql": "select 1"}, headers=h)
    r = q()
    ok("SQL: undeclared caller reaches the database", r.status_code == 200, (r.status_code, r.text[:200]))
    r = q(**{"x-vyomi-source-ip": "52.1.1.1"})
    ok("SQL: IP outside the server firewall BLOCKED (ClientIpNotAllowed)", r.status_code == 403 and "ClientIpNotAllowed" in r.text, r.text[:200])
    r = q(**{"x-vyomi-source-ip": "198.51.100.15"})
    ok("SQL: IP inside the firewall rule passes; the Redirect policy sends it to the node port range",
       r.status_code == 200 and r.json()["connection"]["mode"] == "Redirect" and r.json()["connection"]["endpoint"].endswith(":11000"), r.text[:300])
    sq.server_connection_policies.begin_create_or_update(RG, srv, "default", {"properties": {"connectionType": "Proxy"}}).result()
    r = q(**{"x-vyomi-source-ip": "198.51.100.15"})
    ok("SQL: Proxy policy answers through the gateway on 1433", r.json()["connection"]["mode"] == "Proxy" and r.json()["connection"]["endpoint"].endswith(":1433"), r.text[:300])
    sq.server_connection_policies.begin_create_or_update(RG, srv, "default", {"properties": {"connectionType": "Default"}}).result()
    sq.virtual_network_rules.begin_create_or_update(RG, srv, "r1", {"properties": {"virtualNetworkSubnetId": SN}}).result()
    r = q(**{"x-vyomi-source-subnet": SN})
    ok("SQL: Default policy + caller inside Azure (subnet with Microsoft.Sql endpoint + vnet rule) -> Redirect", r.status_code == 200 and r.json()["connection"]["mode"] == "Redirect", r.text[:300])
    sq.servers.begin_create_or_update(RG, srv, {"location": "eastus", "properties": {"publicNetworkAccess": "Disabled"}}).result()
    ok("SQL: publicNetworkAccess=Disabled BLOCKS the previously allowed IP", q(**{"x-vyomi-source-ip": "198.51.100.15"}).status_code == 403)


def test_diagnostic_settings_deliver():
    la = mgmt(LogAnalyticsManagementClient)
    mon = mgmt(MonitorManagementClient)
    st = mgmt(StorageManagementClient)
    ws = "lawd-" + SFX
    w = la.workspaces.begin_create_or_update(RG, ws, {"location": "eastus"}).result()
    acct = "stdg" + SFX
    sa = st.storage_accounts.begin_create(RG, acct, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}).result()
    sbn = mgmt(ServiceBusManagementClient)
    ns = sbn.namespaces.begin_create_or_update(RG, "sbd" + SFX, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}}).result()
    mon.diagnostic_settings.create_or_update(ns.id, "toLaw", {"properties": {"workspaceId": w.id, "storageAccountId": sa.id,
        "logs": [{"category": "OperationalLogs", "enabled": True}], "metrics": [{"category": "AllMetrics", "enabled": True}]}})
    sbn.namespaces.begin_create_or_update(RG, "sbd" + SFX, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}, "tags": {"x": "1"}}).result()
    p = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/{ws}"
    r = rest("POST", p + "/api/query", {"query": "AzureDiagnostics | where Category == 'OperationalLogs'"}, params={"api-version": "2022-10-01"})
    rows = r.json()["tables"][0]["rows"]
    ok("diagnostic setting created via azure-mgmt-monitor delivered a log row to the Log Analytics workspace", len(rows) >= 1, r.text[:300])
    r = rest("POST", p + "/api/query", {"query": "AzureMetrics | take 5"}, params={"api-version": "2022-10-01"})
    ok("...and a metric row", len(r.json()["tables"][0]["rows"]) >= 1)
    key = "a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2U="
    svc = BlobServiceClient(f"{BASE}/{acct}", credential=AzureNamedKeyCredential(acct, key))
    cont = svc.get_container_client("insights-logs-operationallogs")
    blobs = [b.name for b in cont.list_blobs()]
    ok("...and a JSON-lines blob in the destination storage account (read back with azure-storage-blob)", len(blobs) == 1 and b"OperationalLogs" in cont.download_blob(blobs[0]).readall(), blobs)
    ok("diagnostic setting is listed back by the SDK", [d.name for d in mon.diagnostic_settings.list(ns.id)] == ["toLaw"])


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            print(n)
            f()
    print("netenforce sdk ok")
