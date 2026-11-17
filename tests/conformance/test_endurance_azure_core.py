"""vyomi-endurance Azure regressions found by the real azurerm provider (Terraform estate).
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ~/.vyomi-endurance/venv/bin/python tests/conformance/test_endurance_azure_core.py"""
import sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from providers import azure_services as az

fails = []
def check(label, ok):
    print(("PASS: " if ok else "FAIL: ") + label)
    if not ok: fails.append(label)

app = FastAPI(); az.register(app); c = TestClient(app)
S = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"

r = c.put(f"{S}/resourceGroups/endur-rg?api-version=2023-07-01", json={"location": "eastus", "tags": {"a": "b"}})
check("F400 new resource group PUT -> 201 Created (real ARM)", r.status_code == 201)
r = c.put(f"{S}/resourceGroups/endur-rg?api-version=2023-07-01", json={"location": "eastus", "tags": {"a": "b"}})
check("F400 existing resource group PUT -> 200", r.status_code == 200)

N = f"{S}/resourceGroups/endur-rg/providers/Microsoft.Network"
c.put(f"{N}/virtualNetworks/v1?api-version=2025-01-01", json={"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}}})
r = c.put(f"{N}/virtualNetworks/v1/subnets/s1?api-version=2025-01-01", json={"properties": {"addressPrefix": "10.1.1.0/24"}})
check("F401 subnet PUT is an LRO (Azure-AsyncOperation present; else the SDK waits a 10 s default)", "azure-asyncoperation" in r.headers)
op = r.headers.get("azure-asyncoperation", "").split("19104")[-1]
check("F401 the operation URL resolves", not op or c.get(op.replace("http://testserver", "")).status_code == 200)

R = f"{S}/resourceGroups/endur-rg/providers"
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
c.delete(f"{S}/resourceGroups/endur-rg?api-version=2023-07-01")
sys.exit(1 if fails else 0)
