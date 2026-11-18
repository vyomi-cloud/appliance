"""Microsoft.AppConfiguration/checkNameAvailability through the ARM route must reach the AppConfiguration core
(a taken name -> nameAvailable false), not the generic "always available" shortcut.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 tests/conformance/test_azure_appconfig_name_check_route.py"""
import sys
from fastapi.testclient import TestClient
import server

c = TestClient(server.app)
SUB = "00000000-0000-0000-0000-cloudlearn01"
V = "api-version=2023-03-01"
fails = []
def check(label, ok):
    print(("PASS: " if ok else "FAIL: ") + label)
    if not ok: fails.append(label)

c.put(f"/subscriptions/{SUB}/resourcegroups/ncrg?api-version=2021-04-01", json={"location": "eastus"})
c.put(f"/subscriptions/{SUB}/resourceGroups/ncrg/providers/Microsoft.AppConfiguration/configurationStores/ncstore1?{V}",
      json={"location": "eastus", "sku": {"name": "standard"}})
u = f"/subscriptions/{SUB}/providers/Microsoft.AppConfiguration/checkNameAvailability?{V}"
t = {"type": "Microsoft.AppConfiguration/configurationStores"}
check("taken name -> nameAvailable false", c.post(u, json={"name": "ncstore1", **t}).json().get("nameAvailable") is False)
check("free name -> nameAvailable true", c.post(u, json={"name": "ncfree-9", **t}).json().get("nameAvailable") is True)
check("too-short name -> reason Invalid", c.post(u, json={"name": "a", **t}).json().get("reason") == "Invalid")
sys.exit(1 if fails else 0)
