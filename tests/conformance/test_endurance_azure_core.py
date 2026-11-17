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
c.delete(f"{S}/resourceGroups/endur-rg?api-version=2023-07-01")
sys.exit(1 if fails else 0)
