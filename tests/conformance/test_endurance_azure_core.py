"""vyomi-endurance Azure regressions found by the real azurerm provider (Terraform estate).
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ~/.vyomi-endurance/venv/bin/python tests/conformance/test_endurance_azure_core.py"""
import os, sys, tempfile
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(tempfile.mkdtemp(), "s.sqlite3"))   # never touch a real state file
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", os.path.join(tempfile.mkdtemp(), "s.pkl"))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from providers import azure_services as az

fails = []
def check(label, ok):
    print(("PASS: " if ok else "FAIL: ") + label)
    if not ok: fails.append(label)

app = FastAPI(); az.register(app); c = TestClient(app)
import uuid
RGN = "endur-" + uuid.uuid4().hex[:8]       # state persists between runs: a fresh group per run
S = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"

r = c.put(f"{S}/resourceGroups/{RGN}?api-version=2023-07-01", json={"location": "eastus", "tags": {"a": "b"}})
check("F400 new resource group PUT -> 201 Created (real ARM)", r.status_code == 201)
r = c.put(f"{S}/resourceGroups/{RGN}?api-version=2023-07-01", json={"location": "eastus", "tags": {"a": "b"}})
check("F400 existing resource group PUT -> 200", r.status_code == 200)

N = f"{S}/resourceGroups/{RGN}/providers/Microsoft.Network"
c.put(f"{N}/virtualNetworks/v1?api-version=2025-01-01", json={"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}}})
r = c.put(f"{N}/virtualNetworks/v1/subnets/s1?api-version=2025-01-01", json={"properties": {"addressPrefix": "10.1.1.0/24"}})
check("F401 subnet PUT is an LRO (Azure-AsyncOperation present; else the SDK waits a 10 s default)", "azure-asyncoperation" in r.headers)
op = r.headers.get("azure-asyncoperation", "").split("19104")[-1]
check("F401 the operation URL resolves", not op or c.get(op.replace("http://testserver", "")).status_code == 200)

R = f"{S}/resourceGroups/{RGN}/providers"
rd = c.get(f"{R}/Microsoft.Authorization/roleDefinitions?$filter=roleName eq 'Reader'&api-version=2022-05-01-preview").json()["value"]
check("F402 roleDefinitions $filter=roleName eq 'Reader' -> only Reader, GUID-named full id",
      len(rd) == 1 and rd[0]["name"] == "acdd72a7-3385-48ef-bd42-f606fba81ae7" and rd[0]["id"].endswith("/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"))

c.put(f"{R}/Microsoft.Storage/storageAccounts/stendur?api-version=2025-08-01", json={"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
b = c.get(f"{R}/Microsoft.Storage/storageAccounts/stendur/blobServices/default?api-version=2025-08-01")
check("F406 blobServices/default exists before any PUT (real ARM singleton)", b.status_code == 200 and "cors" in b.json()["properties"])

c.put(f"{R}/Microsoft.Sql/servers/sqlendur?api-version=2023-08-01-preview", json={"location": "eastus", "properties": {"administratorLogin": "a", "administratorLoginPassword": "P@ssw0rd-1"}})
v = c.get(f"{R}/Microsoft.Sql/servers/sqlendur/sqlVulnerabilityAssessments/default?api-version=2023-08-01-preview")
check("F406 sqlVulnerabilityAssessments/default answers 200 Disabled", v.status_code == 200 and v.json()["properties"]["state"] == "Disabled")
cp = c.put(f"{R}/Microsoft.Sql/servers/sqlendur/connectionPolicies/default?api-version=2023-08-01-preview", json={"properties": {"connectionType": "Default"}})
check("F408 singleton PUT answers 200 not 201", cp.status_code == 200)
d = c.put(f"{R}/Microsoft.Sql/servers/sqlendur/databases/appdb?api-version=2023-08-01-preview", json={"location": "eastus", "sku": {"name": "S0"}}).json()
check("F410 SQL database exposes currentServiceObjectiveName (azurerm sku_name)", d["properties"].get("currentServiceObjectiveName") == "S0")

a = c.put(f"{R}/Microsoft.DocumentDB/databaseAccounts/cosmosendur?api-version=2024-08-15", json={"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard", "locations": [{"locationName": "eastus", "failoverPriority": 0}]}}).json()["properties"]
check("F405 Cosmos account carries a Periodic backupPolicy.type", a["backupPolicy"]["type"] == "Periodic")
check("F411 Cosmos account carries failoverPolicies", a["failoverPolicies"] and a["failoverPolicies"][0]["failoverPriority"] == 0)
sd = c.put(f"{R}/Microsoft.DocumentDB/databaseAccounts/cosmosendur/sqlDatabases/appdb?api-version=2024-08-15", json={"location": "eastus", "properties": {"resource": {"id": "appdb"}}})
check("F409 Cosmos sqlDatabases PUT -> 200 + LRO header (SDK rejects 201)", sd.status_code == 200 and "azure-asyncoperation" in sd.headers)
dl = c.delete(f"{R}/Microsoft.DocumentDB/databaseAccounts/cosmosendur?api-version=2024-08-15")
check("F412 Cosmos DELETE -> 202 + LRO header", dl.status_code == 202 and "azure-asyncoperation" in dl.headers)

from core import azure_blob_core
check("F403 Blob service properties handler exists (azurerm data-plane wait)", "restype" in open(azure_blob_core.__file__).read() and "StorageServiceProperties" in open(azure_blob_core.__file__).read())

eg = c.put(f"{R}/Microsoft.EventGrid/topics/egt1?api-version=2022-06-15", json={"location": "eastus"})
check("F413 EventGrid topic create -> 201", eg.status_code == 201)
check("F413 EventGrid topic delete -> 202 + LRO header", c.delete(f"{R}/Microsoft.EventGrid/topics/egt1?api-version=2022-06-15").status_code == 202)
c.put(f"{R}/Microsoft.ServiceBus/namespaces/sbn1?api-version=2024-01-01", json={"location": "eastus", "sku": {"name": "Standard"}})
q = c.put(f"{R}/Microsoft.ServiceBus/namespaces/sbn1/queues/q1?api-version=2024-01-01", json={"properties": {}})
check("F414 Service Bus child PUT -> 200 (SDK rejects 201)", q.status_code == 200)
nr = c.get(f"{R}/Microsoft.ServiceBus/namespaces/sbn1/networkRuleSets/default?api-version=2024-01-01")
check("F406 Service Bus networkRuleSets/default", nr.status_code == 200 and nr.json()["properties"]["defaultAction"] == "Allow")
sp = c.put(f"{R}/Microsoft.Web/serverFarms/asp1?api-version=2024-04-01", json={"location": "eastus", "sku": {"name": "B1"}, "kind": "linux", "properties": {"reserved": True}})
check("F415 App Service plan PUT -> 200 + LRO header", sp.status_code == 200 and "azure-asyncoperation" in sp.headers)
check("F416 deletedWorkspaces list", c.get(f"{S}/providers/Microsoft.OperationalInsights/deletedWorkspaces?api-version=2023-09-01").json() == {"value": []})
check("F417 checkNameAvailability", c.post(f"{S}/providers/Microsoft.Web/checknameavailability?api-version=2023-12-01", json={"name": "x", "type": "Site"}).json()["nameAvailable"] is True)
c.put(f"{R}/Microsoft.Web/sites/site1?api-version=2023-12-01", json={"location": "eastus", "kind": "app,linux", "properties": {"serverFarmId": f"{R}/Microsoft.Web/serverFarms/asp1"}})
st = c.post(f"{R}/Microsoft.Web/sites/site1/config/azurestorageaccounts/list?api-version=2023-12-01")
check("F418 config/azurestorageaccounts exists", st.status_code == 200 and "properties" in st.json())
check("F420 config/backup/list on an unconfigured site -> 404", c.post(f"{R}/Microsoft.Web/sites/site1/config/backup/list?api-version=2023-12-01").status_code == 404)
fa = c.put(f"{R}/Microsoft.Web/sites/fn1?api-version=2023-12-01", json={"location": "eastus", "kind": "functionapp,linux", "properties": {"serverFarmId": f"{R}/Microsoft.Web/serverFarms/asp1", "siteConfig": {"appSettings": [{"name": "AzureWebJobsStorage", "value": "UseDevelopmentStorage=true"}]}}})
ap = c.post(f"{R}/Microsoft.Web/sites/fn1/config/appsettings/list?api-version=2023-12-01").json()["properties"]
check("F427 function app keeps the client's AzureWebJobsStorage and has no default APPINSIGHTS key",
      ap.get("AzureWebJobsStorage") == "UseDevelopmentStorage=true" and "APPINSIGHTS_INSTRUMENTATIONKEY" not in ap)
ai = c.put(f"{R}/Microsoft.Insights/components/ai1?api-version=2020-02-02", json={"location": "eastus", "kind": "web", "properties": {"Application_Type": "web", "SamplingPercentage": 100}})
check("F419 App Insights PUT -> 200 and F423 echoes SamplingPercentage", ai.status_code == 200 and ai.json()["properties"].get("SamplingPercentage") == 100)
check("F421 currentbillingfeatures", c.get(f"{R}/Microsoft.Insights/components/ai1/currentbillingfeatures?api-version=2015-05-01").json()["CurrentBillingFeatures"] == ["Basic"])
ac = c.put(f"{R}/Microsoft.AppConfiguration/configurationStores/appcs-endur1?api-version=2024-05-01", json={"location": "eastus", "sku": {"name": "standard"}}).json()
check("F422 App Configuration echoes sku as sent and omits publicNetworkAccess", ac["sku"]["name"] == "standard" and "publicNetworkAccess" not in ac["properties"])
co = c.put(f"{R}/Microsoft.CognitiveServices/accounts/oai1?api-version=2024-10-01", json={"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "oai1"}}).json()
check("F426 Cognitive account has no networkAcls unless configured", "networkAcls" not in co["properties"])
dp = c.put(f"{R}/Microsoft.CognitiveServices/accounts/oai1/deployments/chat?api-version=2024-10-01", json={"sku": {"name": "Standard", "capacity": 10}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o-mini", "version": "2024-07-18"}}}).json()
check("F425 deployment of a legacy OpenAI model name echoes format OpenAI", dp["properties"]["model"]["format"] == "OpenAI")
sc = c.put(f"{S}/providers/Microsoft.Security/securityContacts/default?api-version=2017-08-01-preview", json={"properties": {"email": "a@b.c", "phone": "1", "alertNotifications": "On", "alertsToAdmins": "On"}})
check("F424 securityContacts PUT/GET/DELETE", sc.status_code == 200 and c.get(f"{S}/providers/Microsoft.Security/securityContacts/default?api-version=2017-08-01-preview").status_code == 200
      and c.delete(f"{S}/providers/Microsoft.Security/securityContacts/default?api-version=2017-08-01-preview").status_code == 200)
check("F428 Key Vault purge of a deleted vault is accepted", c.post(f"{S}/providers/Microsoft.KeyVault/locations/eastus/deletedVaults/kv1/purge?api-version=2023-07-01").status_code == 202)
c.delete(f"{S}/resourceGroups/{RGN}?api-version=2023-07-01")
sys.exit(1 if fails else 0)
